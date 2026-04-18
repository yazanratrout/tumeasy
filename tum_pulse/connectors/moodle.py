"""Moodle connector — Shibboleth SSO login + AJAX calendar API."""

import json
import re
import time
from datetime import datetime

import requests

_MOODLE_BASE = "https://www.moodle.tum.de"
_MOODLE_SSO_URL = (
    "https://www.moodle.tum.de/Shibboleth.sso/Login"
    "?providerId=https%3A%2F%2Ftumidp.lrz.de%2Fidp%2Fshibboleth"
    "&target=https%3A%2F%2Fwww.moodle.tum.de%2Fauth%2Fshibboleth%2Findex.php"
)


class MoodleConnector:
    """Playwright + requests connector for Moodle TUM."""

    def login(self, page, username: str, password: str) -> bool:
        """Login via direct Shibboleth SSO URL → login.tum.de credentials.

        Returns True when landing on moodle.tum.de after auth.
        """
        page.goto(_MOODLE_SSO_URL, timeout=30_000)
        page.wait_for_load_state("networkidle", timeout=20_000)

        if "login.tum.de" in page.url:
            page.fill('input[name="j_username"]', username)
            page.fill('input[name="j_password"]', password)
            page.click('button[type="submit"], input[type="submit"]')
            page.wait_for_load_state("networkidle", timeout=20_000)

        return "moodle.tum.de" in page.url and "login" not in page.url.lower()

    def _extract_sesskey(self, page) -> str:
        content = page.content()
        m = re.search(r"""["']sesskey["']\s*:\s*["']([^"']+)""", content)
        return m.group(1) if m else ""

    def get_calendar_events(self, page, days: int = 90) -> list[dict]:
        """Call core_calendar_get_action_events_by_timesort via Moodle AJAX API."""
        sesskey = self._extract_sesskey(page)
        if not sesskey:
            raise ValueError("Could not extract Moodle sesskey — login may have failed")

        cookies = {
            c["name"]: c["value"]
            for c in page.context.cookies()
            if "moodle" in c.get("domain", "")
        }

        sess = requests.Session()
        for name, val in cookies.items():
            sess.cookies.set(name, val, domain="www.moodle.tum.de")

        now_ts = int(time.time())
        payload = json.dumps([{
            "index": 0,
            "methodname": "core_calendar_get_action_events_by_timesort",
            "args": {
                "limitnum": 50,
                "timesortfrom": now_ts,
                "timesortto": now_ts + 60 * 60 * 24 * days,
                "limittononsuspendedevents": True,
            },
        }])
        resp = sess.post(
            f"{_MOODLE_BASE}/lib/ajax/service.php"
            f"?sesskey={sesskey}&info=core_calendar_get_action_events_by_timesort",
            data=payload,
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        events = resp.json()[0].get("data", {}).get("events", [])

        deadlines: list[dict] = []
        today = datetime.now()
        for ev in events:
            ts = ev.get("timesort") or ev.get("timestart", 0)
            if not ts:
                continue
            dt = datetime.fromtimestamp(ts)
            if dt < today:
                continue
            course_obj = ev.get("course") or {}
            deadlines.append({
                "title": ev.get("name", "Moodle Event"),
                "course": course_obj.get("fullname", "")[:80] if course_obj else "",
                "deadline_date": dt.strftime("%Y-%m-%d"),
                "source": "moodle",
            })
        return deadlines

    def scrape(self, username: str, password: str, days: int = 90) -> list[dict]:
        """Full scrape: launch browser, login, fetch calendar events, close."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                if not self.login(page, username, password):
                    raise ValueError("Moodle login failed")
                return self.get_calendar_events(page, days=days)
            except Exception as exc:
                print(f"[MoodleConnector] Error: {exc}")
                raise
            finally:
                browser.close()
