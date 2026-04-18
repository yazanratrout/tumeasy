"""Smart LearningBuddy: cache-based course selection, PDF extraction, interactive study help."""

import json
import re
import tempfile
from pathlib import Path

from tum_pulse.config import DATA_DIR
from tum_pulse.connectors.cache import CacheManager
from tum_pulse.memory.database import SQLiteMemory
from tum_pulse.tools.bedrock_client import BedrockClient, HAIKU, SONNET
from tum_pulse.tools.llm_cache import LLMCache
from tum_pulse.tools.moodle_scraper import MoodleScraper


def _extract_text_from_file(file_path: str) -> str:
    """Extract text from a PDF or text file using PyMuPDF with plain-text fallback."""
    try:
        import fitz
        doc = fitz.open(file_path)
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        return text
    except ImportError:
        pass
    except Exception as exc:
        print(f"[SmartLearningBuddy] PyMuPDF failed for {file_path}: {exc}")

    try:
        with open(file_path, "r", errors="ignore") as fh:
            return fh.read()
    except Exception as exc:
        return f"[Could not read file: {exc}]"


class SmartLearningBuddy:
    """Study buddy using cached courses/materials for instant selection, then PDF extraction."""

    def __init__(self):
        self.cache = CacheManager()
        self.db = SQLiteMemory()
        self.bedrock = BedrockClient()
        self.llm_cache = LLMCache()
        self.scraper = MoodleScraper()
        Path(DATA_DIR).mkdir(parents=True, exist_ok=True)

    # ─────────────────────────────────────────────────────────────────────
    # Step 1: Course selection (fast, cache-first)
    # ─────────────────────────────────────────────────────────────────────

    def _select_course(self, user_input: str) -> dict | None:
        """Select course from cached current semester courses.

        Returns: {"id": course_id, "name": course_name, "materials": [...]} or None.
        """
        current_courses = self.cache.get_moodle_current_courses()
        user_lower = user_input.lower()
        # Strip course codes from user input for cleaner word matching
        user_words = [w for w in re.sub(r'\b[A-Z]{2,3}\d{4,5}\b', '', user_lower).split() if len(w) > 3]

        def _score(name: str) -> float:
            n = re.sub(r'\(.*?\)', '', name).lower().strip()  # strip "(IN2346)" suffix
            if n in user_lower:
                return 1.0
            words = [w for w in n.split() if len(w) > 3]
            if not words or not user_words:
                return 0.0
            # How many course-name words appear in the user message
            forward = sum(1 for w in words if any(w in uw or uw in w for uw in user_words))
            return forward / len(words)

        def _best_from(course_dict: dict) -> tuple:
            """Returns (best_id, best_name, best_materials, best_score)."""
            best_id, best_name, best_mats, best_sc = None, None, [], 0.0

            # Course code exact match wins outright
            code_match = re.search(r'\b([A-Z]{2,3}\d{4,5})\b', user_input.upper())
            if code_match:
                code = code_match.group(1).lower()
                for cid, info in course_dict.items():
                    if code in info["name"].lower():
                        return cid, info["name"], info.get("materials", []), 1.0

            for cid, info in course_dict.items():
                sc = _score(info["name"])
                if sc > best_sc:
                    best_sc, best_id, best_name, best_mats = sc, cid, info["name"], info.get("materials", [])
            return best_id, best_name, best_mats, best_sc

        # ── Search Moodle cache first ──
        if current_courses:
            bid, bname, bmats, bsc = _best_from(current_courses)
            if bsc >= 0.4:
                print(f"[SmartLearningBuddy] Cache match: '{bname}' (score={bsc:.2f})")
                return {"id": bid, "name": bname, "materials": bmats}

        # ── Fallback: profile courses (word-overlap, same logic) ──
        profile_courses = self.db.get_profile("courses") or []
        if profile_courses:
            profile_dict = {str(i): {"name": c, "materials": []} for i, c in enumerate(profile_courses)}
            bid, bname, bmats, bsc = _best_from(profile_dict)
            if bsc >= 0.4:
                print(f"[SmartLearningBuddy] Profile match: '{bname}' (score={bsc:.2f})")
                return {"id": None, "name": bname, "materials": []}

        # ── Last resort: ask Claude ──
        all_courses = (
            [info["name"] for info in current_courses.values()]
            if current_courses else profile_courses
        )
        if all_courses:
            try:
                prompt = (
                    f'User message: "{user_input}"\n\n'
                    f'Courses:\n' + "\n".join(f"- {n}" for n in all_courses)
                    + "\n\nWhich course is the user asking about? Return ONLY the exact course name or NONE.\nCourse:"
                )
                result = self.bedrock.invoke(prompt, max_tokens=40, model=HAIKU).strip().strip('"').strip("'")
                if result and result != "NONE":
                    for cid, info in (current_courses or {}).items():
                        if result.lower() in info["name"].lower() or info["name"].lower() in result.lower():
                            return {"id": cid, "name": info["name"], "materials": info.get("materials", [])}
                    for c in profile_courses:
                        if result.lower() in c.lower() or c.lower() in result.lower():
                            return {"id": None, "name": c, "materials": []}
            except Exception as e:
                print(f"[SmartLearningBuddy] Claude course selection failed: {e}")

        return None

    # ─────────────────────────────────────────────────────────────────────
    # Step 2: Document selection (smart filtering)
    # ─────────────────────────────────────────────────────────────────────

    def _select_documents(self, materials: list[dict], user_input: str, mode: str) -> list[dict]:
        """Filter materials by what the user needs.

        For study plans: prioritise past exams → exercises → lectures.
        For summaries: prioritise lectures → exercises.
        """
        if not materials:
            return []

        user_lower = user_input.lower()

        def _classify(name: str) -> int:
            n = name.lower()
            if any(w in n for w in ["exam", "klausur", "past", "previous", "pruef", "test"]):
                return 0  # past paper — highest priority for study plans
            if any(w in n for w in ["exercise", "uebung", "sheet", "aufgabe", "tutorial", "hw", "homework"]):
                return 1
            return 2  # lecture / other

        if mode == "study_plan":
            # Sort: exams first, then exercises, then lectures — take up to 5
            sorted_mats = sorted(materials, key=lambda m: _classify(m.get("name", "")))
            return sorted_mats[:5]
        elif mode == "summarize":
            # Prefer lecture materials
            lectures = [m for m in materials if _classify(m.get("name", "")) == 2]
            if lectures:
                return lectures[:3]
            return materials[:3]
        else:
            # Specific document reference: "first lecture", "week 3"
            match = re.search(r'\b(first|second|third|week\s+\d+|lecture\s+\d+|sheet\s+\d+)\b', user_lower)
            if match:
                return materials[:1]
            return materials[:3]

    # ─────────────────────────────────────────────────────────────────────
    # Step 3: PDF text extraction
    # ─────────────────────────────────────────────────────────────────────

    def _authenticate_scraper(self) -> bool:
        """Ensure MoodleScraper has an authenticated session."""
        if getattr(self.scraper, "_logged_in", False):
            return True
        print("[SmartLearningBuddy] Authenticating Moodle session...")
        return self.scraper.login()

    def _extract_pdf_text(self, doc_info: dict) -> str | None:
        """Download PDF from Moodle URL with authenticated session and extract text."""
        url = doc_info.get("url", "")
        if not url:
            return None

        try:
            suffix = Path(url.split("?")[0]).suffix or ".pdf"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp_path = tmp.name

            # Try unauthenticated first (may work for public/cached files)
            result = self.scraper.download_pdf(url, tmp_path)
            if not result or not Path(tmp_path).exists() or Path(tmp_path).stat().st_size < 100:
                # Authenticate and retry
                if self._authenticate_scraper():
                    result = self.scraper.download_pdf(url, tmp_path)

            if result and Path(tmp_path).exists() and Path(tmp_path).stat().st_size > 100:
                text = _extract_text_from_file(tmp_path)
                try:
                    Path(tmp_path).unlink()
                except Exception:
                    pass
                return text if text.strip() else None
        except Exception as e:
            print(f"[SmartLearningBuddy] PDF extraction failed for {url}: {e}")

        return None

    def _download_course_pdfs_playwright(self, course_name: str) -> list[tuple[str, str]]:
        """Fallback: use LearningBuddyAgent's full Playwright SSO flow to get real PDFs.

        Returns empty list if only placeholder/sample content is available so the
        caller can fall back to generating a response from Claude's course knowledge.
        """
        try:
            from tum_pulse.agents.learning_buddy import LearningBuddyAgent
            agent = LearningBuddyAgent()
            pdf_paths = agent.download_moodle_pdfs(course_name)
            texts_dict = agent.extract_text_from_pdfs(pdf_paths)
            # Filter out placeholder/sample files — they belong to a different course
            real = [
                (name, text)
                for name, text in texts_dict.items()
                if text.strip() and not text.strip().startswith("[SAMPLE CONTENT")
            ]
            if not real:
                print("[SmartLearningBuddy] Only placeholder content returned — skipping")
            return real
        except Exception as e:
            print(f"[SmartLearningBuddy] Playwright fallback failed: {e}")
            return []

    def _collect_pdf_texts(
        self, materials: list[dict], course_name: str, max_docs: int = 4
    ) -> list[tuple[str, str]]:
        """Extract text from up to max_docs materials, return [(name, text)] pairs.

        Falls back to the full Playwright download flow if direct URL downloads fail.
        """
        results = []
        for material in materials[:max_docs]:
            text = self._extract_pdf_text(material)
            if text and text.strip():
                results.append((material.get("name", "Document"), text))
                print(f"[SmartLearningBuddy] Extracted {len(text)} chars from {material.get('name', '?')}")

        if not results:
            print("[SmartLearningBuddy] Direct downloads failed — trying Playwright fallback...")
            results = self._download_course_pdfs_playwright(course_name)

        return results

    # ─────────────────────────────────────────────────────────────────────
    # Step 4a: Topic analysis (shared by both modes)
    # ─────────────────────────────────────────────────────────────────────

    def _analyse_topics(self, course_name: str, doc_pairs: list[tuple[str, str]], context: dict) -> dict:
        """Use Haiku to extract key topics and their exam weight — cached 12h."""
        combined = "\n\n".join(
            f"=== {name} ===\n{text[:4000]}" for name, text in doc_pairs
        )
        weak_subjects = context.get("weak_subjects", [])
        weak_hint = (
            f"\nSTUDENT WEAK AREAS (prioritise these): {', '.join(weak_subjects)}\n"
            if weak_subjects else ""
        )

        prompt = f"""You are an expert exam analyst for TUM course: {course_name}.
{weak_hint}
MATERIALS:
{combined[:8000]}

Identify ALL distinct exam topics. Return JSON only:
{{
  "topics": [
    {{
      "name": "topic name",
      "frequency": <times seen>,
      "points_weight": <% of exam>,
      "in_exams": <true/false>,
      "priority_score": <0.0-1.0>
    }}
  ]
}}

Order by priority_score descending. Return ONLY valid JSON."""

        cached = self.llm_cache.get(prompt, model=HAIKU)
        if cached:
            print(f"[SmartLearningBuddy] Topic analysis cache hit for {course_name}")
            try:
                return json.loads(cached)
            except Exception:
                pass

        raw = self.bedrock.invoke(prompt, max_tokens=1500, model=HAIKU)
        try:
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0]
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0]
            result = json.loads(raw.strip())
            self.llm_cache.set(prompt, json.dumps(result), ttl_seconds=43200, model=HAIKU)
            return result
        except Exception:
            return {"topics": []}

    # ─────────────────────────────────────────────────────────────────────
    # Step 4b: Study plan generation
    # ─────────────────────────────────────────────────────────────────────

    def _generate_study_plan(
        self,
        course_name: str,
        duration_days: int,
        doc_pairs: list[tuple[str, str]],
        topics: dict,
        context: dict,
    ) -> str:
        """Generate a smart, personalised study plan with topic analysis baked in."""
        weeks = max(1, duration_days // 7)
        weak_subjects = context.get("weak_subjects", [])
        weak_hint = (
            f"\nStudent struggles with: {', '.join(weak_subjects)}. Allocate extra time.\n"
            if weak_subjects else ""
        )
        topics_json = json.dumps(topics, indent=2)

        # Include sample content from each document for richness
        content_preview = "\n\n".join(
            f"[{name}]\n{text[:1500]}" for name, text in doc_pairs[:3]
        )

        prompt = f"""You are an expert TUM study coach helping a student prepare for: {course_name}
{weak_hint}
AVAILABLE TIME: {weeks} week(s) ({duration_days} days)

TOPIC ANALYSIS (from past exams + lectures):
{topics_json}

COURSE CONTENT PREVIEW:
{content_preview[:4000]}

Create a PERSONALISED, SPECIFIC study plan:
- Week-by-week breakdown with ## Week N headers
- Daily focus topics tied to real material (be specific, not generic)
- Allocate more time to high priority_score topics
- Include practice sessions and past paper review days
- End with a "## Final Week Sprint" section
- Add 💡 tips for each major topic

Format as clean markdown. Be specific: mention actual topic names from the analysis."""

        return self.bedrock.invoke(prompt, max_tokens=2000)

    # ─────────────────────────────────────────────────────────────────────
    # Step 4c: Lecture summary
    # ─────────────────────────────────────────────────────────────────────

    def _summarize_lecture(self, material_name: str, doc_pairs: list[tuple[str, str]], user_query: str) -> str:
        """Summarise lecture material with targeted explanation based on the student's question."""
        combined = "\n\n".join(f"=== {name} ===\n{text[:4000]}" for name, text in doc_pairs)

        prompt = f"""You are an expert TUM study buddy explaining complex material.

MATERIAL: {material_name}
STUDENT'S QUESTION: {user_query}

CONTENT:
{combined[:6000]}

Provide a clear, interactive summary:
1. **Key Concepts** — explained simply with examples
2. **How It Connects** — to the broader course
3. **Common Exam Mistakes** — what to watch out for
4. **Self-Test Questions** — 3-5 questions to check understanding
5. **Next Steps** — what to study next

Use markdown formatting. Be specific to the actual content above."""

        return self.bedrock.invoke(prompt, max_tokens=2000)

    # ─────────────────────────────────────────────────────────────────────
    # Main entry point
    # ─────────────────────────────────────────────────────────────────────

    def run(self, user_input: str, context: dict | None = None) -> str:
        """Smart study buddy orchestration.

        Flow:
        1. Select course from cache (instant)
        2. Select materials by type (instant)
        3. Extract PDF text
        4. Analyse topics via Claude
        5. Generate study plan OR lecture summary
        """
        ctx = context or {}

        # Step 1: Select course
        course = self._select_course(user_input)
        if not course:
            profile_courses = self.db.get_profile("courses") or []
            courses_hint = "\n".join(f"- {c}" for c in profile_courses[:10]) if profile_courses else "- (none saved)"
            return (
                "I couldn't find a matching course in your current semester cache.\n\n"
                "**Your saved courses:**\n" + courses_hint + "\n\n"
                "Try phrasing like: *\"Study plan for Analysis 2\"* or *\"Summarise ML lecture 3\"*.\n"
                "If courses aren't cached yet, run a Moodle sync first."
            )

        print(f"[SmartLearningBuddy] Course: {course['name']}")

        # Step 2: Determine mode and select materials
        user_lower = user_input.lower()
        if any(kw in user_lower for kw in ["study plan", "prepare", "plan", "revision", "exam prep"]):
            mode = "study_plan"
        elif any(kw in user_lower for kw in ["summarize", "summarise", "explain", "summary", "overview", "what is"]):
            mode = "summarize"
        else:
            mode = "study_plan"  # default to study plan for learning buddy intent

        materials = self._select_documents(course["materials"], user_input, mode)

        # Step 3: Extract PDF texts (tries direct URL, then Playwright SSO fallback)
        if materials:
            doc_pairs = self._collect_pdf_texts(materials, course["name"], max_docs=4)
        else:
            # No cached materials — go straight to Playwright
            doc_pairs = self._download_course_pdfs_playwright(course["name"])

        if not doc_pairs:
            # No PDFs extracted — still generate a useful response using topic knowledge
            print(f"[SmartLearningBuddy] No PDFs extracted, generating from course knowledge")
            if mode == "study_plan":
                duration_days = _parse_duration(user_input)
                prompt = (
                    f"Generate a {duration_days}-day study plan for TUM course: {course['name']}. "
                    "Based on typical TUM exam patterns for this course, include key topics, "
                    "week-by-week breakdown, and exam tips. Use markdown."
                )
                cached = self.llm_cache.get(prompt, model=SONNET)
                plan = cached or self.bedrock.invoke(prompt, max_tokens=2000, model=SONNET)
                if not cached:
                    self.llm_cache.set(prompt, plan, ttl_seconds=21600, model=SONNET)
                return (
                    f"## Study Plan: {course['name']}\n\n"
                    "> ⚠️ No course materials were accessible — plan generated from course knowledge.\n\n"
                    + plan
                    + "\n\n---\n💡 **Tip:** Sync your Moodle materials for a personalised plan based on your actual lecture content."
                )
            else:
                prompt = (
                    f"You are a TUM study expert. Summarise the key topics and concepts covered in "
                    f"the TUM course '{course['name']}'. Structure it as: Key Concepts, Typical Exam Topics, "
                    f"and Study Tips. Use markdown."
                )
                overview = self.bedrock.invoke(prompt, max_tokens=1500)
                return (
                    f"## {course['name']}\n\n"
                    f"> ⚠️ Moodle materials couldn't be fetched (SSO/network issue). "
                    f"Summary based on course knowledge:\n\n"
                    + overview
                    + "\n\n---\n💡 **To get a summary from your actual lecture slides**, "
                    "make sure your TUM credentials are saved and Moodle is reachable, then try again."
                )

        # Step 4: Topic analysis (only for study plans)
        topics = {"topics": []}
        if mode == "study_plan":
            print(f"[SmartLearningBuddy] Analysing topics from {len(doc_pairs)} documents...")
            topics = self._analyse_topics(course["name"], doc_pairs, ctx)

        # Step 5: Generate response
        if mode == "study_plan":
            duration_days = _parse_duration(user_input)
            print(f"[SmartLearningBuddy] Generating study plan ({duration_days} days)...")
            plan = self._generate_study_plan(course["name"], duration_days, doc_pairs, topics, ctx)

            # Build topic summary header
            top_topics = topics.get("topics", [])[:6]
            if top_topics:
                topic_lines = "\n".join(
                    f"- **{t['name']}** — {t.get('points_weight', '?')}% of exam, priority {t.get('priority_score', 0):.2f}"
                    for t in top_topics
                )
                topic_section = f"## Key Exam Topics\n{topic_lines}\n\n---\n\n"
            else:
                topic_section = ""

            follow_up = (
                "\n\n---\n**What would you like next?**\n"
                "- 💬 *\"Explain [topic name]\"* — deep dive on any topic\n"
                "- 📝 *\"Quiz me on [topic]\"* — practice questions\n"
                "- 📅 *\"What are my upcoming deadlines?\"* — check exam dates"
            )
            return f"# Study Plan: {course['name']}\n\n{topic_section}{plan}{follow_up}"

        else:
            print(f"[SmartLearningBuddy] Summarising {len(doc_pairs)} materials...")
            summary = self._summarize_lecture(
                doc_pairs[0][0] if doc_pairs else course["name"],
                doc_pairs,
                user_input,
            )
            follow_up = (
                "\n\n---\n**Keep going:**\n"
                "- 📋 *\"Make a study plan for [course]\"* — full exam prep plan\n"
                "- ❓ *\"Quiz me on this\"* — test your understanding\n"
                "- 📖 *\"Summarise [next lecture]\"* — continue through the material"
            )
            return f"## {course['name']}\n\n{summary}{follow_up}"


    def run_with_pdf(self, user_input: str, pdf_text: str, pdf_name: str, context: dict | None = None) -> str:
        """Process a user-uploaded PDF directly — no Moodle fetch needed.

        Args:
            user_input: The student's question/request.
            pdf_text: Text already extracted from the uploaded PDF.
            pdf_name: Filename of the uploaded PDF (for display).
            context: Optional student profile context.
        """
        ctx = context or {}
        user_lower = user_input.lower()

        if any(kw in user_lower for kw in ["study plan", "prepare", "plan", "revision", "exam prep"]):
            mode = "study_plan"
        else:
            mode = "summarize"

        doc_pairs = [(pdf_name, pdf_text)]

        if mode == "study_plan":
            topics = self._analyse_topics(pdf_name, doc_pairs, ctx)
            duration_days = _parse_duration(user_input)
            plan = self._generate_study_plan(pdf_name, duration_days, doc_pairs, topics, ctx)
            top_topics = topics.get("topics", [])[:6]
            topic_section = ""
            if top_topics:
                lines = "\n".join(
                    f"- **{t['name']}** — {t.get('points_weight', '?')}% of exam, priority {t.get('priority_score', 0):.2f}"
                    for t in top_topics
                )
                topic_section = f"## Key Exam Topics\n{lines}\n\n---\n\n"
            follow_up = (
                "\n\n---\n**What would you like next?**\n"
                "- 💬 *\"Explain [topic name]\"* — deep dive on any topic\n"
                "- 📝 *\"Quiz me on [topic]\"* — practice questions\n"
                "- 📅 *\"What are my upcoming deadlines?\"* — check exam dates"
            )
            return f"# Study Plan: {pdf_name}\n\n{topic_section}{plan}{follow_up}"
        else:
            summary = self._summarize_lecture(pdf_name, doc_pairs, user_input)
            follow_up = (
                "\n\n---\n**Keep going:**\n"
                "- 📋 *\"Make a study plan for this\"* — full exam prep plan\n"
                "- ❓ *\"Quiz me on this\"* — test your understanding\n"
                "- 📖 Upload the next lecture PDF to continue"
            )
            return f"## {pdf_name}\n\n{summary}{follow_up}"


def _parse_duration(user_input: str) -> int:
    """Parse study duration from natural language. Defaults to 14 days."""
    text = user_input.lower()
    m = re.search(r"(\d+|a|an)\s+(day|week|month)s?", text)
    if m:
        qty_str, unit = m.group(1), m.group(2)
        qty = 1 if qty_str in ("a", "an") else int(qty_str)
        if unit == "day":
            return max(1, qty)
        if unit == "week":
            return qty * 7
        if unit == "month":
            return qty * 30
    return 14
