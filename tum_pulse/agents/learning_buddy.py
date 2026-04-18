"""LearningBuddyAgent: exam planner using past papers + lecture content."""

import json
import re
import tempfile
from pathlib import Path

import requests

from tum_pulse.config import DATA_DIR, MOODLE_BASE_URL, TUM_PASSWORD, TUM_USERNAME
from tum_pulse.connectors.moodle import MoodleConnector
from tum_pulse.memory.database import SQLiteMemory
from tum_pulse.tools.bedrock_client import BedrockClient
from tum_pulse.tools.moodle_scraper import MoodleScraper as _MoodleScraper


class LearningBuddyAgent:
    """Builds personalised study plans by analysing past exam papers and lectures."""

    def __init__(self) -> None:
        """Initialise dependencies: Bedrock client, MoodleConnector, SQLite memory."""
        self.bedrock = BedrockClient()
        self.scraper = MoodleConnector()
        self.db = SQLiteMemory()
        Path(DATA_DIR).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # PDF acquisition
    # ------------------------------------------------------------------

    def _find_moodle_course_id(self, course_name: str, page, session: requests.Session) -> str | None:
        """Find Moodle course ID by matching against student's enrolled courses.

        Scrapes /my/courses.php which lists ALL enrolled courses with their
        exact names and IDs — then matches against course_name exactly first,
        then falls back to partial matching.

        Args:
            course_name: Course name to find (from user input or TUMonline profile).
            page: Active Playwright page (authenticated).
            session: Authenticated requests.Session with Moodle cookies.

        Returns:
            Course ID string or None.
        """
        course_name_lower = course_name.lower().strip()

        # Find best match in known SQLite courses first to refine search term
        known_courses = self.db.get_profile("courses") or []
        known_courses_lower = {c.lower().strip(): c for c in known_courses}

        best_known: str | None = None
        best_known_score = 0.0
        for known_lower, known_original in known_courses_lower.items():
            if course_name_lower == known_lower:
                best_known = known_original
                best_known_score = 1.0
                break
            if course_name_lower in known_lower or known_lower in course_name_lower:
                score = len(course_name_lower) / max(len(known_lower), 1)
                if score > best_known_score:
                    best_known = known_original
                    best_known_score = score
            else:
                words = [w for w in course_name_lower.split() if len(w) > 3]
                if words:
                    overlap = sum(1 for w in words if w in known_lower)
                    score = overlap / len(words)
                    if score > best_known_score and score >= 0.6:
                        best_known = known_original
                        best_known_score = score

        search_name = best_known or course_name
        print(f"[LearningBuddy] Looking for Moodle course: '{search_name}'")

        all_known = self.db.get_profile("courses") or []
        all_known_lower = [c.lower() for c in all_known]

        # Scrape /my/courses.php — definitive list of enrolled courses with IDs
        try:
            page.goto(f"{MOODLE_BASE_URL}/my/courses.php", timeout=15_000)
            page.wait_for_load_state("networkidle", timeout=10_000)
            page.wait_for_timeout(1000)

            # Scroll to load lazy-loaded courses
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1500)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1000)

            # Click "Load more" if present
            try:
                load_more = page.locator(
                    "button:has-text('Mehr'), button:has-text('Load more'), "
                    "[data-action='load-more']"
                ).first
                if load_more.is_visible(timeout=2000):
                    load_more.click()
                    page.wait_for_timeout(1500)
            except Exception:
                pass

            # Get all course links — deduplicate by course ID
            course_links_raw = page.evaluate("""() => {
                const seen = new Set();
                const results = [];
                document.querySelectorAll('a[href*="course/view.php"]').forEach(a => {
                    const href = a.href;
                    const text = a.textContent.trim().replace(/\\s+/g, ' ');
                    if (!text || text.length < 3) return;
                    if (text.includes('Favorit') || text.includes('favorite')) return;
                    const m = href.match(/course\\/view\\.php\\?id=(\\d+)/);
                    if (!m) return;
                    const id = m[1];
                    const key = id + '|' + text.substring(0, 30);
                    if (!seen.has(key)) {
                        seen.add(key);
                        results.push({href, text});
                    }
                });
                return results;
            }""")

            # Keep longest text per course ID
            seen_ids: dict[str, dict] = {}
            for link in course_links_raw:
                m = re.search(r"course/view\.php\?id=(\d+)", link["href"])
                if not m:
                    continue
                cid = m.group(1)
                text = link["text"].strip()
                if cid not in seen_ids or len(text) > len(seen_ids[cid]["text"]):
                    seen_ids[cid] = {"href": link["href"], "text": text}

            course_links = list(seen_ids.values())
            print(f"[LearningBuddy] Found {len(course_links)} unique enrolled courses on Moodle:")

            best_id: str | None = None
            best_score = 0.0
            best_text = ""
            search_lower = search_name.lower().strip()

            for cid, link in seen_ids.items():
                text = link["text"].strip()
                text_lower = text.lower()

                print(f"  [{cid}] {text[:70]}")

                score = 0.0

                # Strategy A: Direct string matching
                if search_lower == text_lower:
                    score = 1.0
                elif search_lower in text_lower:
                    score = 0.9
                elif text_lower in search_lower:
                    score = 0.85
                else:
                    # Strategy B: Word overlap (handles partial matches)
                    search_words = [w for w in search_lower.split() if len(w) > 3]
                    text_words = [w for w in text_lower.split() if len(w) > 3]
                    if search_words and text_words:
                        forward = sum(1 for w in search_words if any(
                            w in tw or tw in w for tw in text_words
                        ))
                        score = forward / len(search_words)

                # Strategy C: Match via course code in brackets e.g. (IN2228)
                code_match = re.search(r"\b([A-Z]{2,3}\d{4,5})\b", search_name.upper())
                if code_match:
                    code = code_match.group(1)
                    if code.lower() in text_lower:
                        score = max(score, 0.95)
                        print(f"  → Course code match: {code}")

                # Strategy D: Cross-language match via known TUMonline courses
                for known in all_known_lower:
                    known_words = [w for w in known.split() if len(w) > 4]
                    if not known_words:
                        continue
                    overlap = sum(1 for w in known_words if w in text_lower)
                    ratio = overlap / len(known_words)
                    if ratio >= 0.5:
                        s_words = [w for w in search_lower.split() if len(w) > 3]
                        if s_words and sum(1 for w in s_words if w in known) / len(s_words) >= 0.5:
                            score = max(score, ratio * 0.8)

                if score > best_score:
                    best_score = score
                    best_id = cid
                    best_text = text

            if best_id and best_score >= 0.4:
                print(f"[LearningBuddy] Best match: '{best_text}' "
                      f"(score={best_score:.2f}) → course ID {best_id}")
                return best_id

            print(f"[LearningBuddy] No confident match (best score: {best_score:.2f})")
            if best_id:
                print(f"[LearningBuddy] Using best available: '{best_text}' → {best_id}")
                return best_id
            return None

        except Exception as exc:
            print(f"[LearningBuddy] Course search failed: {exc}")
            return None

    def download_moodle_pdfs(self, course_name: str) -> list[str]:
        """Download real PDFs for course_name from Moodle via SSO login.

        Flow:
        1. Login to Moodle via MoodleConnector (Playwright SSO)
        2. Transfer cookies to requests.Session
        3. Find course ID from dashboard or search
        4. Scrape course page for PDF links (pluginfile.php)
        5. Download each PDF to DATA_DIR
        6. Falls back to placeholder text files if any step fails

        Args:
            course_name: Human-readable course name (e.g. "Analysis 2").

        Returns:
            List of local file paths to downloaded files.
        """
        from playwright.sync_api import sync_playwright

        print(f"[LearningBuddy] Attempting real Moodle download for '{course_name}'...")
        Path(DATA_DIR).mkdir(parents=True, exist_ok=True)

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page()

                try:
                    # Step 1: Login via MoodleConnector SSO
                    if not self.scraper.login(page, TUM_USERNAME, TUM_PASSWORD):
                        raise ValueError("Moodle SSO login failed")
                    print("[LearningBuddy] Moodle login successful")

                    # Step 2: Transfer cookies to requests.Session
                    session = requests.Session()
                    session.headers.update({"User-Agent": "TUMPulse/1.0"})
                    for cookie in page.context.cookies():
                        if "moodle" in cookie.get("domain", "").lower():
                            session.cookies.set(
                                cookie["name"],
                                cookie["value"],
                                domain=cookie.get("domain", ""),
                            )

                    # Step 3: Find course ID
                    course_id = self._find_moodle_course_id(course_name, page, session)

                    local_paths: list[str] = []

                    if course_id:
                        # Step 4: Use Playwright to render the course page
                        # (Moodle loads file links via JS — requests sees empty page)
                        course_url = f"{MOODLE_BASE_URL}/course/view.php?id={course_id}"
                        print(f"[LearningBuddy] Navigating Playwright to course page: {course_url}")

                        page.goto(course_url, timeout=20_000)
                        page.wait_for_load_state("networkidle", timeout=15_000)

                        # Expand all collapsed sections so all files are visible
                        try:
                            expand_buttons = page.locator(
                                ".collapsed, [data-toggle='collapse'], "
                                "button.sectiontoggle, .course-section-header"
                            ).all()
                            for btn in expand_buttons[:20]:
                                try:
                                    btn.click(timeout=1000)
                                    page.wait_for_timeout(300)
                                except Exception:
                                    pass
                        except Exception:
                            pass

                        page.wait_for_timeout(2000)

                        # Debug summary
                        print(f"[LearningBuddy] Page URL after navigation: {page.url}")
                        print(f"[LearningBuddy] Page title: {page.title()}")
                        body_preview = page.inner_text("body")[:200]
                        if "login" in page.url.lower() or "anmelden" in body_preview.lower():
                            print("[LearningBuddy] WARNING: May not be authenticated!")

                        all_hrefs = page.evaluate("""() => {
                            return Array.from(document.querySelectorAll('a[href]')).map(a => ({
                                href: a.href,
                                text: a.textContent.trim().substring(0, 60)
                            })).filter(l => l.href.length > 10);
                        }""")
                        print(f"[LearningBuddy] Total links on page: {len(all_hrefs)}")
                        relevant = [l for l in all_hrefs if any(kw in l["href"].lower() for kw in
                                    ["pluginfile", "mod/resource", "mod/folder", "download", "pdf"])]
                        print(f"[LearningBuddy] Potentially relevant links: {len(relevant)}")
                        for l in relevant[:15]:
                            print(f"  [{l['text'][:40]}] → {l['href'][:90]}")

                        # Check for TUM's "Download Center" — custom Moodle plugin
                        download_center_found = False
                        try:
                            dc_link = page.locator(
                                "a:has-text('Download Center'), "
                                "a:has-text('Download-Center'), "
                                "a[href*='downloadcenter'], "
                                "a[href*='mod/folder']"
                            ).first
                            if dc_link.is_visible(timeout=3000):
                                dc_href = dc_link.get_attribute("href")
                                print(f"[LearningBuddy] Found Download Center: {dc_href}")
                                page.click(
                                    "a:has-text('Download Center'), "
                                    "a:has-text('Download-Center'), "
                                    "a[href*='downloadcenter'], "
                                    "a[href*='mod/folder']",
                                    timeout=5000,
                                )
                                page.wait_for_load_state("networkidle", timeout=10_000)
                                page.wait_for_timeout(1500)
                                download_center_found = True
                                print(f"[LearningBuddy] Navigated to Download Center: {page.url}")
                        except Exception as exc:
                            print(f"[LearningBuddy] No Download Center found: {exc}")

                        # Try "Expand all" / "Alles aufklappen" if no Download Center
                        if not download_center_found:
                            try:
                                expand_all = page.locator(
                                    "a:has-text('Alles aufklappen'), "
                                    "a:has-text('Expand all'), "
                                    "[data-action='toggleall']"
                                ).first
                                if expand_all.is_visible(timeout=2000):
                                    expand_all.click(timeout=3000)
                                    page.wait_for_timeout(2000)
                                    print("[LearningBuddy] Expanded all sections")
                            except Exception:
                                pass

                        # Extract ALL links from the rendered page
                        all_links = page.evaluate("""() => {
                            const links = [];
                            document.querySelectorAll('a[href]').forEach(a => {
                                links.push({
                                    href: a.href,
                                    text: a.textContent.trim().substring(0, 100)
                                });
                            });
                            return links;
                        }""")

                        pdf_links: list[dict] = []
                        seen_urls: set[str] = set()
                        for link in all_links:
                            href = link.get("href", "")
                            text = link.get("text", "")

                            is_file = (
                                "pluginfile.php" in href or
                                "mod/resource/view.php" in href or
                                "mod/folder/view.php" in href or
                                "mod/url/view.php" in href
                            )
                            if not is_file or href in seen_urls:
                                continue

                            # Follow mod/resource links to get actual file URL
                            if "mod/resource" in href and "pluginfile" not in href:
                                try:
                                    page.goto(href, timeout=10_000)
                                    page.wait_for_load_state("networkidle", timeout=8_000)
                                    final_url = page.url
                                    if "pluginfile.php" in final_url:
                                        href = final_url
                                        text = text or Path(final_url.split("?")[0]).name
                                    page.go_back(timeout=8_000)
                                    page.wait_for_load_state("networkidle", timeout=8_000)
                                except Exception:
                                    pass

                            ext = Path(href.split("?")[0]).suffix.lower()
                            if ext in (".pdf", ".pptx", ".ppt", ".docx", ""):
                                pdf_links.append({
                                    "url": href,
                                    "name": text or Path(href.split("?")[0]).name,
                                })
                                seen_urls.add(href)

                        print(f"[LearningBuddy] Found {len(pdf_links)} files via Playwright")

                        # If still no files, try scraping all mod/resource links directly
                        if not pdf_links:
                            print("[LearningBuddy] No direct file links — trying mod/resource links...")
                            resource_links = page.evaluate("""() => {
                                return Array.from(document.querySelectorAll(
                                    'a[href*="mod/resource"], a[href*="mod/folder"], '
                                    + 'a[href*="pluginfile"]'
                                )).map(a => ({
                                    href: a.href,
                                    text: a.textContent.trim().substring(0, 100)
                                }));
                            }""")
                            print(f"[LearningBuddy] Found {len(resource_links)} resource links")
                            for link in resource_links:
                                href = link.get("href", "")
                                text = link.get("text", "")
                                if href not in seen_urls:
                                    pdf_links.append({"url": href, "name": text})
                                    seen_urls.add(href)
                                    print(f"[LearningBuddy]   Resource: {text[:50]} → {href[:80]}")

                        def _classify(name: str) -> int:
                            n = name.lower()
                            if any(w in n for w in ["exam", "klausur", "past", "previous", "pruef"]):
                                return 0
                            if any(w in n for w in ["exercise", "uebung", "sheet", "aufgabe", "tutorial"]):
                                return 1
                            return 2

                        pdf_links.sort(key=lambda x: _classify(x["name"]))

                        # Step 5: Download files using Playwright (handles auth cookies)
                        for file_info in pdf_links[:10]:
                            url = file_info["url"]
                            raw_name = file_info["name"] or Path(url.split("?")[0]).name
                            safe_name = re.sub(r"[^\w\-_. ]", "_", raw_name).strip()[:80]
                            if not any(safe_name.endswith(ext) for ext in
                                       (".pdf", ".pptx", ".ppt", ".docx")):
                                safe_name += ".pdf"
                            save_path = str(Path(DATA_DIR) / safe_name)

                            try:
                                with page.expect_download(timeout=30_000) as dl_info:
                                    page.goto(url, timeout=20_000)
                                download = dl_info.value
                                download.save_as(save_path)
                                local_paths.append(save_path)
                                size_kb = Path(save_path).stat().st_size // 1024
                                print(f"[LearningBuddy] Downloaded: {safe_name} ({size_kb}KB)")
                            except Exception as exc:
                                # Fallback: requests with refreshed cookies
                                try:
                                    for cookie in page.context.cookies():
                                        if "moodle" in cookie.get("domain", "").lower():
                                            session.cookies.set(
                                                cookie["name"],
                                                cookie["value"],
                                                domain=cookie.get("domain", ""),
                                            )
                                    resp = session.get(url, timeout=30, stream=True)
                                    resp.raise_for_status()
                                    with open(save_path, "wb") as fh:
                                        for chunk in resp.iter_content(chunk_size=8192):
                                            fh.write(chunk)
                                    local_paths.append(save_path)
                                    print(f"[LearningBuddy] Downloaded (session): {safe_name}")
                                except Exception as exc2:
                                    print(f"[LearningBuddy] Both download methods failed for {url}: {exc2}")

                    if local_paths:
                        print(f"[LearningBuddy] Successfully downloaded {len(local_paths)} files")
                        return local_paths

                    print("[LearningBuddy] No files downloaded — using placeholder fallback")
                    return self._placeholder_files(course_name)

                finally:
                    browser.close()

        except Exception as exc:
            print(f"[LearningBuddy] Real Moodle download failed: {exc}")
            return self._placeholder_files(course_name)

    def _placeholder_files(self, course_name: str) -> list[str]:
        """Create placeholder text files for demo when real Moodle is unavailable.

        Args:
            course_name: Name of the course for context in the placeholder content.

        Returns:
            List of local placeholder file paths.
        """
        files = _MoodleScraper().get_sample_data()
        local_paths: list[str] = []
        for file_meta in files:
            filename = file_meta["name"]
            save_path = str(Path(DATA_DIR) / filename)
            if not Path(save_path).exists():
                with open(save_path, "w") as fh:
                    fh.write(
                        f"[SAMPLE CONTENT for {filename}]\n"
                        f"Course: {course_name}\n"
                        "Topics: integration, differentiation, series, limits, continuity.\n"
                        "Past exam focus: Taylor series, Fourier series, multivariable calculus.\n"
                        "Typical point distribution: 30% integration, 25% series, "
                        "20% differential equations, 25% theory.\n"
                    )
            local_paths.append(save_path)
        return local_paths

    # ------------------------------------------------------------------
    # Text extraction
    # ------------------------------------------------------------------

    def extract_text_from_pdfs(self, pdf_paths: list[str]) -> dict[str, str]:
        """Extract text from PDF files using PyMuPDF.

        Args:
            pdf_paths: List of local file paths to PDFs (or placeholder .txt files).

        Returns:
            Dict mapping filename → extracted text.
        """
        texts: dict[str, str] = {}

        for path in pdf_paths:
            filename = Path(path).name
            try:
                import fitz  # PyMuPDF

                doc = fitz.open(path)
                text = "\n".join(page.get_text() for page in doc)
                doc.close()
                texts[filename] = text
            except ImportError:
                # PyMuPDF not available — fall back to reading plain text
                try:
                    with open(path, "r", errors="ignore") as fh:
                        texts[filename] = fh.read()
                except Exception as exc:
                    texts[filename] = f"[Could not read file: {exc}]"
            except Exception as exc:
                texts[filename] = f"[Extraction error: {exc}]"

        return texts

    # ------------------------------------------------------------------
    # Paper analysis
    # ------------------------------------------------------------------

    def analyse_past_papers(
        self, past_paper_text: str, lecture_texts: dict[str, str]
    ) -> dict:
        """Use Claude to identify and prioritise exam topics.

        Args:
            past_paper_text: Combined text from past exam papers.
            lecture_texts: Dict of lecture filename → text.

        Returns:
            Structured dict:
            {
                "topics": [
                    {
                        "name": str,
                        "frequency": int,
                        "points_weight": float,
                        "in_lectures": bool,
                        "priority_score": float
                    }
                ]
            }
        """
        lecture_summary = "\n".join(
            f"--- {name} ---\n{text[:500]}" for name, text in lecture_texts.items()
        )

        prompt = f"""You are an expert exam analyst. Analyse the following past exam papers and lecture notes.

PAST EXAM PAPERS:
{past_paper_text[:3000]}

LECTURE CONTENT (excerpts):
{lecture_summary[:2000]}

Return a JSON object with the following structure:
{{
  "topics": [
    {{
      "name": "topic name",
      "frequency": <number of times topic appeared in exams>,
      "points_weight": <estimated percentage of total exam points>,
      "in_lectures": <true if topic is covered in lecture notes>,
      "priority_score": <0.0 to 1.0, combining frequency and points_weight>
    }}
  ]
}}

Identify ALL distinct topics. Order by priority_score descending. Return ONLY valid JSON, no explanation."""

        raw = self.bedrock.invoke(prompt, max_tokens=1500)

        try:
            # Extract JSON block if Claude wraps it in markdown
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0]
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0]
            return json.loads(raw.strip())
        except (json.JSONDecodeError, IndexError):
            # Fallback structured response
            return {
                "topics": [
                    {"name": "Integration techniques", "frequency": 5, "points_weight": 30.0, "in_lectures": True, "priority_score": 0.9},
                    {"name": "Taylor and Fourier series", "frequency": 4, "points_weight": 25.0, "in_lectures": True, "priority_score": 0.85},
                    {"name": "Differential equations", "frequency": 3, "points_weight": 20.0, "in_lectures": True, "priority_score": 0.75},
                    {"name": "Multivariable calculus", "frequency": 3, "points_weight": 15.0, "in_lectures": True, "priority_score": 0.65},
                    {"name": "Limits and continuity", "frequency": 2, "points_weight": 10.0, "in_lectures": True, "priority_score": 0.5},
                ]
            }

    # ------------------------------------------------------------------
    # Study plan generation
    # ------------------------------------------------------------------

    def generate_study_plan(self, analysis: dict, course_name: str) -> str:
        """Generate a week-by-week study plan from topic analysis.

        Args:
            analysis: Output of analyse_past_papers().
            course_name: Name of the course for contextualisation.

        Returns:
            Formatted markdown study plan.
        """
        topics_json = json.dumps(analysis, indent=2)

        prompt = f"""You are an expert academic tutor helping a TUM student prepare for their {course_name} exam.

Based on this topic analysis from past papers:
{topics_json}

Create a concise, realistic week-by-week study plan for 4 weeks before the exam.
- Prioritise topics by priority_score (highest first)
- Each week should have 3-4 specific study goals
- Include one practice/revision day per week
- Keep each week's description to 3-4 bullet points
- End with a "Final Week" sprint section

Format as clean markdown with ## Week headers."""

        return self.bedrock.invoke(prompt, max_tokens=1200)

    # ------------------------------------------------------------------
    # Agent entry point
    # ------------------------------------------------------------------

    def run(self, user_input: str) -> str:
        """Orchestrate the full exam planning pipeline.

        Args:
            user_input: Natural language request, e.g. "Help me prepare for Analysis 2".

        Returns:
            Formatted markdown study plan.
        """
        # Extract course name — check against known enrolled courses first
        known_courses = self.db.get_profile("courses") or []
        course_name = None

        user_lower = user_input.lower()
        best_match: str | None = None
        best_match_len = 0
        for course in known_courses:
            if course.lower() in user_lower and len(course) > best_match_len:
                best_match = course
                best_match_len = len(course)

        if best_match:
            course_name = best_match
            print(f"[LearningBuddy] Matched course from profile: '{course_name}'")
        else:
            # Check for explicit course code in user input (e.g. "IN2346", "MA9412")
            code_in_input = re.search(r"\b([A-Z]{2,3}\d{4,5})\b", user_input.upper())
            if code_in_input:
                code = code_in_input.group(1)
                for c in known_courses:
                    if code.lower() in c.lower():
                        best_match = c
                        print(f"[LearningBuddy] Matched via course code {code}: '{c}'")
                        break
                if not best_match:
                    course_name = code
            if best_match:
                course_name = best_match
            elif not course_name:
                keywords = ["pass", "prepare", "exam", "study", "help", "for"]
                words = user_input.split()
                for i, word in enumerate(words):
                    if word.lower() in keywords and i + 1 < len(words):
                        candidate = " ".join(words[i + 1: i + 4]).strip(".,?!")
                        if len(candidate) > 3:
                            course_name = candidate
                            break

        if not course_name:
            course_name = known_courses[0] if known_courses else "Machine Learning"
            print(f"[LearningBuddy] No course detected — using: '{course_name}'")

        try:
            pdf_paths = self.download_moodle_pdfs(course_name)
            texts = self.extract_text_from_pdfs(pdf_paths)

            past_papers = {k: v for k, v in texts.items() if "exam" in k.lower() or "past" in k.lower()}
            lectures = {k: v for k, v in texts.items() if k not in past_papers}

            past_paper_text = "\n\n".join(past_papers.values()) if past_papers else "\n\n".join(list(texts.values())[:1])
            lecture_texts = lectures if lectures else texts

            analysis = self.analyse_past_papers(past_paper_text, lecture_texts)
            study_plan = self.generate_study_plan(analysis, course_name)

            header = f"# Study Plan: {course_name}\n\n"
            topic_summary = "## Top Priority Topics\n" + "\n".join(
                f"- **{t['name']}** — priority {t['priority_score']:.2f} ({t['points_weight']:.0f}% of exam)"
                for t in analysis.get("topics", [])[:5]
            ) + "\n\n---\n\n"

            return header + topic_summary + study_plan

        except Exception as exc:
            return f"[LearningBuddyAgent] Error generating study plan: {exc}"


if __name__ == "__main__":
    agent = LearningBuddyAgent()
    print("Testing real Moodle PDF download...")
    paths = agent.download_moodle_pdfs("Analysis 1")
    print(f"Got {len(paths)} files:")
    for p in paths:
        print(f"  {p}")
    print("\nGenerating study plan...")
    print(agent.run("Help me pass Analysis 1"))
