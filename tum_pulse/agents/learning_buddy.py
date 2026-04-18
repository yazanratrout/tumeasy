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
        """Search Moodle for a course matching course_name and return its ID.

        Tries:
        1. My courses dashboard: /my/ — scrape enrolled course links
        2. Moodle search: /course/search.php?search={course_name}

        Args:
            course_name: Human-readable course name to search for.
            page: Active Playwright page (authenticated).
            session: Authenticated requests.Session with Moodle cookies.

        Returns:
            Course ID string or None.
        """
        from bs4 import BeautifulSoup

        course_name_lower = course_name.lower()

        # Strategy 1: scrape /my/ dashboard for enrolled course links
        try:
            resp = session.get(
                f"{MOODLE_BASE_URL}/my/",
                timeout=15,
                allow_redirects=True,
            )
            soup = BeautifulSoup(resp.text, "lxml")

            for link in soup.find_all("a", href=True):
                href = link.get("href", "")
                text = link.get_text(strip=True).lower()
                m = re.search(r"course/view\.php\?id=(\d+)", href)
                if m and any(
                    word in text
                    for word in course_name_lower.split()
                    if len(word) > 3
                ):
                    course_id = m.group(1)
                    print(f"[LearningBuddy] Found course ID {course_id} for '{course_name}'")
                    return course_id
        except Exception as exc:
            print(f"[LearningBuddy] Dashboard scrape failed: {exc}")

        # Strategy 2: Moodle course search
        try:
            search_term = course_name.replace(" ", "+")
            resp = session.get(
                f"{MOODLE_BASE_URL}/course/search.php?search={search_term}",
                timeout=15,
            )
            soup = BeautifulSoup(resp.text, "lxml")
            for link in soup.find_all("a", href=True):
                href = link.get("href", "")
                text = link.get_text(strip=True).lower()
                m = re.search(r"course/view\.php\?id=(\d+)", href)
                if m and any(
                    word in text
                    for word in course_name_lower.split()
                    if len(word) > 3
                ):
                    course_id = m.group(1)
                    print(f"[LearningBuddy] Found course ID {course_id} via search")
                    return course_id
        except Exception as exc:
            print(f"[LearningBuddy] Course search failed: {exc}")

        print(f"[LearningBuddy] Could not find Moodle course ID for '{course_name}'")
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
                                "mod/resource" in href or
                                "mod/folder" in href
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
        # Extract course name from input (simple heuristic)
        course_name = "Analysis 2"  # default
        keywords = ["for", "pass", "prepare", "exam", "study"]
        words = user_input.split()
        for i, word in enumerate(words):
            if word.lower() in keywords and i + 1 < len(words):
                candidate = " ".join(words[i + 1 : i + 3]).strip(".,?!")
                if len(candidate) > 3:
                    course_name = candidate
                    break

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
    paths = agent.download_moodle_pdfs("Machine Learning")
    print(f"Got {len(paths)} files:")
    for p in paths:
        print(f"  {p}")
    print("\nGenerating study plan...")
    print(agent.run("Help me pass Machine Learning"))
