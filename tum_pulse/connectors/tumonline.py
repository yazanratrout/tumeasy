"""TUMonline connector — Keycloak → Shibboleth login + deadline scraping."""

import json
import re
from datetime import datetime
from typing import Optional

_TUMONLINE_BASE = "https://campus.tum.de/tumonline"

_GERMAN_MONTHS = {
    "januar": 1, "februar": 2, "märz": 3, "april": 4,
    "mai": 5, "juni": 6, "juli": 7, "august": 8,
    "september": 9, "oktober": 10, "november": 11, "dezember": 12,
}


def parse_date(text: str) -> Optional[str]:
    """Extract YYYY-MM-DD from German or ISO date strings."""
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", text)
    if m:
        try:
            return datetime.strptime(m.group(0), "%d.%m.%Y").strftime("%Y-%m-%d")
        except ValueError:
            pass
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return m.group(0)
    m = re.search(
        r"(\d{1,2})\.\s*(" + "|".join(_GERMAN_MONTHS) + r")(?:.*?(\d{4}))?",
        text.lower(),
    )
    if m:
        day = int(m.group(1))
        month = _GERMAN_MONTHS[m.group(2)]
        year = int(m.group(3)) if m.group(3) else datetime.now().year
        try:
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


class TUMonlineConnector:
    """Playwright-based connector for campus.tum.de (TUMonline)."""

    BASE = _TUMONLINE_BASE

    def login(self, page, username: str, password: str) -> bool:
        """Two-step TUMonline login: Keycloak username → Shibboleth password.

        Returns True when the post-login page is TUMonline.
        """
        page.goto(self.BASE + "/", timeout=30_000)
        page.wait_for_load_state("networkidle", timeout=20_000)

        # Step 1: Keycloak username-only form
        page.fill('input[name="username"]', username)
        page.click("#kc-login")
        page.wait_for_load_state("networkidle", timeout=20_000)

        # Step 2: Shibboleth password form at login.tum.de
        if "login.tum.de" in page.url:
            page.fill('input[name="j_username"]', username)
            page.fill('input[name="j_password"]', password)
            page.click('button[type="submit"], input[type="submit"]')
            page.wait_for_load_state("networkidle", timeout=20_000)

        return "campus.tum.de" in page.url

    def get_deadlines(self, page) -> list[dict]:
        """Scrape wbEeHooks.showHooks for upcoming deadline items."""
        page.goto(self.BASE + "/wbEeHooks.showHooks", timeout=20_000)
        page.wait_for_load_state("networkidle", timeout=15_000)

        deadlines: list[dict] = []
        today = datetime.now()

        for el in page.locator("li, tr, .hook-item, p").all():
            text = el.inner_text().strip()
            if not text or len(text) < 10:
                continue
            date_str = parse_date(text)
            if not date_str:
                continue
            if datetime.strptime(date_str, "%Y-%m-%d") < today:
                continue
            lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
            deadlines.append({
                "title": lines[0][:100],
                "course": lines[1][:80] if len(lines) > 1 else "",
                "deadline_date": date_str,
                "source": "tumonline",
            })

        return deadlines

    def scrape(self, username: str, password: str) -> list[dict]:
        """Full scrape: launch browser, login, scrape deadlines, close."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                if not self.login(page, username, password):
                    return []
                return self.get_deadlines(page)
            except Exception as exc:
                print(f"[TUMonlineConnector] Error: {exc}")
                return []
            finally:
                browser.close()

    def get_enrolled_courses(self, page) -> dict:
        """Fetch enrolled courses via CAMPUSonline REST API.

        Navigates to the new SPA, forces a Bearer token refresh, then calls
        /slc.tm.cp/student/myCourses for the current semester.

        Returns:
            dict with keys:
              "enrolled": list of str (current semester course names)
              "grades": dict  (empty — grades in student dossier require separate flow)
              "all_courses": list of str (same as enrolled)
        """
        result: dict = {"enrolled": [], "grades": {}, "all_courses": []}

        try:
            # Navigate to SPA to establish auth context
            page.goto(
                "https://campus.tum.de/tumonline/ee/ui/ca2/app/desktop/#/home?$ctx=lang=en",
                timeout=20_000,
            )
            page.wait_for_load_state("networkidle", timeout=15_000)
            page.wait_for_timeout(1000)

            # Force a token refresh via the SPA's own endpoint
            token_data = page.evaluate("""async () => {
                const r = await fetch('/tumonline/ee/rest/auth/token/refresh', {
                    method: 'POST',
                    headers: {Accept: 'application/json', 'Content-Type': 'application/json'},
                    body: '{}'
                });
                return r.ok ? await r.json() : {};
            }""")
            token = token_data.get("accessToken", "")
            if not token:
                print("[TUMonlineConnector] Token refresh returned no accessToken")
                return result

            token_js = json.dumps(token)  # safely quoted for JS string interpolation

            # Step 1: discover current semester ID
            meta = page.evaluate(f"""async () => {{
                const r = await fetch('/tumonline/ee/rest/slc.tm.cp/student/courses?$ctx=lang=EN', {{
                    headers: {{Accept: 'application/json', Authorization: 'Bearer ' + {token_js}}}
                }});
                return r.ok ? await r.json() : {{}};
            }}""")

            semester_id: Optional[int] = None
            for link in meta.get("links", []):
                m = re.search(r'semesterId=(\d+)', link.get("href", ""))
                if m:
                    semester_id = int(m.group(1))
                    break

            if not semester_id:
                print("[TUMonlineConnector] Could not determine semester ID from courses endpoint")
                return result

            # Step 2: fetch enrolled courses for this semester
            data = page.evaluate(f"""async () => {{
                const r = await fetch(
                    '/tumonline/ee/rest/slc.tm.cp/student/myCourses?$filter=termId-eq={semester_id}&$orderBy=title=ascnf&$skip=0&$top=50',
                    {{headers: {{Accept: 'application/json', Authorization: 'Bearer ' + {token_js}}}}}
                );
                return r.ok ? await r.json() : {{}};
            }}""")

            for reg in data.get("registrations", []):
                title = reg.get("course", {}).get("courseTitle", {}).get("value", "")
                if title:
                    result["enrolled"].append(title)

            result["all_courses"] = list(result["enrolled"])
            print(f"[TUMonlineConnector] Found {len(result['enrolled'])} enrolled courses via REST API")

            # Step 3: fetch grades from current-semester examinations
            try:
                grades_data = page.evaluate(f"""async () => {{
                    const r = await fetch(
                        '/tumonline/ee/rest/slc.tm.cp/student/myExaminations?$filter=termId-eq={semester_id}&$skip=0&$top=100',
                        {{headers: {{Accept: 'application/json', Authorization: 'Bearer ' + {token_js}}}}}
                    );
                    return r.ok ? await r.json() : {{}};
                }}""")

                for exam in grades_data.get("examinations", []):
                    grade_val = (
                        exam.get("grade", {}).get("value") or
                        exam.get("gradeValue") or
                        exam.get("grade_value")
                    )
                    course_title = (
                        exam.get("course", {}).get("courseTitle", {}).get("value") or
                        (exam.get("courseTitle") or {}).get("value") or
                        exam.get("title") or ""
                    ).strip()

                    if course_title and grade_val:
                        try:
                            grade_float = float(str(grade_val).replace(",", "."))
                            if 1.0 <= grade_float <= 5.0:
                                result["grades"][course_title] = grade_float
                        except (ValueError, TypeError):
                            pass

                print(f"[TUMonlineConnector] Found {len(result['grades'])} graded courses")
            except Exception as exc:
                print(f"[TUMonlineConnector] Grade fetch failed: {exc}")

            # Also try the full transcript endpoint (all semesters)
            try:
                transcript_data = page.evaluate(f"""async () => {{
                    const r = await fetch(
                        '/tumonline/ee/rest/slc.tm.cp/student/myExaminations?$skip=0&$top=200',
                        {{headers: {{Accept: 'application/json', Authorization: 'Bearer ' + {token_js}}}}}
                    );
                    return r.ok ? await r.json() : {{}};
                }}""")

                for exam in transcript_data.get("examinations", []):
                    grade_val = (
                        exam.get("grade", {}).get("value") or
                        exam.get("gradeValue") or
                        exam.get("grade_value")
                    )
                    course_title = (
                        exam.get("course", {}).get("courseTitle", {}).get("value") or
                        (exam.get("courseTitle") or {}).get("value") or
                        exam.get("title") or ""
                    ).strip()

                    if course_title and grade_val and course_title not in result["grades"]:
                        try:
                            grade_float = float(str(grade_val).replace(",", "."))
                            if 1.0 <= grade_float <= 5.0:
                                result["grades"][course_title] = grade_float
                                if course_title not in result["all_courses"]:
                                    result["all_courses"].append(course_title)
                        except (ValueError, TypeError):
                            pass

                print(f"[TUMonlineConnector] Total graded courses after transcript: {len(result['grades'])}")
            except Exception as exc:
                print(f"[TUMonlineConnector] Transcript fetch failed: {exc}")

        except Exception as exc:
            print(f"[TUMonlineConnector] get_enrolled_courses error: {exc}")

        return result

    def debug_grades_page(self, username: str, password: str) -> None:
        """Navigate to known TUMonline grade pages and print their URLs and HTML structure."""
        from playwright.sync_api import sync_playwright

        GRADE_URLS = [
            "/tumonline/wbStELP.cbSEL",
            "/tumonline/wbStuPla.cbStuProgress",
            "/tumonline/wbStuPla.cbPruefungen",
            "/tumonline/wbPrfList.cbShowLV",
            "/tumonline/wbPrfList.cbShowAll",
            "/tumonline/wbKUVKU.cbSEL",
            "/tumonline/wbStELPV.cbSEL",
            "/tumonline/wbStNotenDaten.cbNotenDaten",
            "/tumonline/wbStNotenSpiegel.cbNotenSpiegel",
        ]

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False)
            page = browser.new_page()
            try:
                if not self.login(page, username, password):
                    print("Login failed")
                    return

                for url in GRADE_URLS:
                    try:
                        full_url = "https://campus.tum.de" + url
                        page.goto(full_url, timeout=15_000)
                        page.wait_for_load_state("networkidle", timeout=10_000)

                        final_url = page.url
                        title = page.title()
                        body_text = page.inner_text("body")[:300].strip()
                        has_table = page.locator("table").count() > 0
                        has_grade = any(g in body_text.lower() for g in
                                        ["grade", "note", "prüfung", "ects", "bestanden"])

                        print(f"\n{'='*60}")
                        print(f"URL tried: {url}")
                        print(f"Final URL: {final_url}")
                        print(f"Title: {title}")
                        print(f"Has table: {has_table} | Has grade content: {has_grade}")
                        print(f"Body preview: {body_text[:200]}")

                        if has_grade or has_table:
                            print(">>> PROMISING PAGE - printing table structure:")
                            tables = page.locator("table").all()
                            for i, table in enumerate(tables[:2]):
                                print(f"  Table {i}: {table.inner_text()[:400]}")

                    except Exception as exc:
                        print(f"URL {url} failed: {exc}")

                print("\n\nBrowser staying open for 30s — check manually if needed")
                page.wait_for_timeout(30_000)

            finally:
                browser.close()

    def scrape_with_courses(self, username: str, password: str) -> dict:
        """Full scrape: login once, then fetch deadlines AND courses/grades.

        More efficient than separate calls since login happens only once.

        Returns:
            dict with keys:
              "deadlines": list of deadline dicts
              "courses": dict from get_enrolled_courses()
        """
        from playwright.sync_api import sync_playwright

        _empty = {"deadlines": [], "courses": {"enrolled": [], "grades": {}, "all_courses": []}}

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                if not self.login(page, username, password):
                    return _empty
                deadlines = self.get_deadlines(page)
                courses = self.get_enrolled_courses(page)
                return {"deadlines": deadlines, "courses": courses}
            except Exception as exc:
                print(f"[TUMonlineConnector] scrape_with_courses error: {exc}")
                return _empty
            finally:
                browser.close()

if __name__ == "__main__":
    import os
    import sys
    from dotenv import load_dotenv
    load_dotenv()
    username = os.getenv("TUM_USERNAME", "")
    password = os.getenv("TUM_PASSWORD", "")
    if not username or not password:
        print("Set TUM_USERNAME and TUM_PASSWORD in .env to test")
        sys.exit(1)

    if "--debug-grades" in sys.argv:
        print("=== Finding grades page ===")
        TUMonlineConnector().debug_grades_page(username, password)
    else:
        print("=== Full scrape ===")
        result = TUMonlineConnector().scrape_with_courses(username, password)
        courses = result["courses"]
        print(f"Enrolled: {courses['enrolled']}")
        print(f"Grades: {courses['grades']}")
