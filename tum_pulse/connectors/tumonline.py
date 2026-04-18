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
