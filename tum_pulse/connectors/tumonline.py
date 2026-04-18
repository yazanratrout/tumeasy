"""TUMonline connector — Keycloak → Shibboleth login + deadline scraping."""

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
        """Scrape the student's courses and grades from TUMonline after login.

        Navigates to the student's course/grade pages and extracts currently
        enrolled courses and completed courses with grades.

        Returns:
            dict with keys:
              "enrolled": list of str (current semester course names)
              "grades": dict of {course_name: grade_float} (completed courses)
              "all_courses": list of str (union of enrolled + completed course names)
        """
        result: dict = {"enrolled": [], "grades": {}, "all_courses": []}

        # --- Current semester courses ---
        for path in [
            "/wbStELP.cbSEL",
            "/wbKUVKU.cbSEL",
            "/wbStELPV.cbSEL",
        ]:
            try:
                page.goto(self.BASE + path, timeout=15_000)
                page.wait_for_load_state("networkidle", timeout=10_000)

                rows = page.locator("table tr, .listresult tr, .list tr").all()
                for row in rows:
                    text = row.inner_text().strip()
                    if not text or len(text) < 5:
                        continue
                    if any(t in text for t in ["VO", "UE", "SE", "PR", "MA", "IN", "EI"]):
                        cells = row.locator("td").all()
                        if len(cells) >= 2:
                            course_name = cells[1].inner_text().strip()
                            if course_name and len(course_name) > 3:
                                result["enrolled"].append(course_name)

                if result["enrolled"]:
                    print(f"[TUMonlineConnector] Found {len(result['enrolled'])} enrolled courses")
                    break
            except Exception as exc:
                print(f"[TUMonlineConnector] Could not fetch courses from {path}: {exc}")
                continue

        # --- Grades / transcript ---
        for path in [
            "/wbStuPla.cbStuProgress",
            "/wbStuPla.cbPruefungen",
            "/wbStELPV.cbSELPruefungen",
        ]:
            try:
                page.goto(self.BASE + path, timeout=15_000)
                page.wait_for_load_state("networkidle", timeout=10_000)

                rows = page.locator("table tr, .listresult tr").all()
                for row in rows:
                    cells = row.locator("td").all()
                    if len(cells) < 3:
                        continue
                    texts = [c.inner_text().strip() for c in cells]

                    course_name = ""
                    grade = None
                    for t in texts:
                        if len(t) > 5 and not t.replace(".", "").replace(",", "").isdigit():
                            course_name = t
                        try:
                            val = float(t.replace(",", "."))
                            if 1.0 <= val <= 5.0:
                                grade = val
                        except ValueError:
                            pass

                    if course_name and grade is not None:
                        result["grades"][course_name] = grade

                if result["grades"]:
                    print(f"[TUMonlineConnector] Found {len(result['grades'])} graded courses")
                    break
            except Exception as exc:
                print(f"[TUMonlineConnector] Could not fetch grades from {path}: {exc}")
                continue

        all_names = list(result["enrolled"])
        for name in result["grades"]:
            if name not in all_names:
                all_names.append(name)
        result["all_courses"] = all_names

        return result

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
    from dotenv import load_dotenv
    load_dotenv()
    username = os.getenv("TUM_USERNAME", "")
    password = os.getenv("TUM_PASSWORD", "")
    if not username or not password:
        print("Set TUM_USERNAME and TUM_PASSWORD in .env to test")
    else:
        result = TUMonlineConnector().scrape_with_courses(username, password)
        print(f"Deadlines ({len(result['deadlines'])}):")
        for dl in result["deadlines"][:5]:
            print(f"  [{dl['deadline_date']}] {dl['title']}")
        courses = result["courses"]
        print(f"\nEnrolled ({len(courses['enrolled'])}): {courses['enrolled'][:5]}")
        print(f"Grades ({len(courses['grades'])}): {dict(list(courses['grades'].items())[:5])}")
        print(f"All courses ({len(courses['all_courses'])}): {courses['all_courses'][:5]}")
