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

    # -------------------------------------------------------------------------
    # Forum read / write actions
    # -------------------------------------------------------------------------

    def _ajax(self, sesskey: str, cookies: dict, methodname: str, args: dict) -> dict:
        """Generic Moodle AJAX call helper."""
        import requests as _req
        payload = json.dumps([{"index": 0, "methodname": methodname, "args": args}])
        sess = _req.Session()
        for name, val in cookies.items():
            sess.cookies.set(name, val, domain="www.moodle.tum.de")
        resp = sess.post(
            f"{_MOODLE_BASE}/lib/ajax/service.php?sesskey={sesskey}&info={methodname}",
            data=payload,
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json()
        if result and isinstance(result, list):
            if result[0].get("error"):
                raise ValueError(f"Moodle API error: {result[0].get('error')}")
            return result[0].get("data", {})
        return {}

    def _get_enrolled_course_ids(self, page, sesskey: str, cookies: dict) -> list[dict]:
        """Return list of {id, fullname} for enrolled Moodle courses."""
        data = self._ajax(sesskey, cookies, "core_enrol_get_users_courses", {
            "userid": 0,   # 0 = current user
            "returnusercount": False,
        })
        # API may return list directly or under a key
        if isinstance(data, list):
            return [{"id": c["id"], "fullname": c.get("fullname", "")} for c in data]
        return []

    def get_course_forums(self, page, course_id: int) -> list[dict]:
        """List forums for a Moodle course by ID.

        Returns list of {id, name, type, intro} dicts.
        """
        sesskey = self._extract_sesskey(page)
        cookies = {
            c["name"]: c["value"]
            for c in page.context.cookies()
            if "moodle" in c.get("domain", "")
        }
        data = self._ajax(sesskey, cookies, "mod_forum_get_forums_by_courses", {
            "courseids": [course_id],
        })
        forums = data if isinstance(data, list) else data.get("forums", [])
        return [
            {"id": f["id"], "name": f.get("name", ""), "type": f.get("type", ""), "intro": f.get("intro", "")}
            for f in forums
        ]

    def post_to_forum(self, page, forum_id: int, subject: str, message: str) -> dict:
        """Create a new discussion in a Moodle forum.

        Returns dict with success (bool) and message (str).
        """
        sesskey = self._extract_sesskey(page)
        cookies = {
            c["name"]: c["value"]
            for c in page.context.cookies()
            if "moodle" in c.get("domain", "")
        }
        try:
            data = self._ajax(sesskey, cookies, "mod_forum_add_discussion", {
                "forumid": forum_id,
                "subject": subject,
                "message": message,
                "messageformat": 1,   # 1 = HTML
                "options": [],
            })
            discussion_id = data.get("discussionid") if isinstance(data, dict) else None
            return {
                "success": True,
                "message": f"Posted to forum (discussion #{discussion_id})." if discussion_id else "Post submitted.",
                "discussionid": discussion_id,
            }
        except Exception as exc:
            return {"success": False, "message": str(exc), "discussionid": None}

    def find_and_post_forum(
        self,
        username: str,
        password: str,
        course_name: str,
        subject: str,
        message: str,
    ) -> dict:
        """Full workflow: login, find course by name, pick first forum, post message."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                if not self.login(page, username, password):
                    return {"success": False, "message": "Moodle login failed.", "course": course_name}

                sesskey = self._extract_sesskey(page)
                cookies = {
                    c["name"]: c["value"]
                    for c in page.context.cookies()
                    if "moodle" in c.get("domain", "")
                }

                # Fetch enrolled courses to match by name
                courses = self._get_enrolled_course_ids(page, sesskey, cookies)
                matched_course = next(
                    (c for c in courses if course_name.lower() in c["fullname"].lower()),
                    None,
                )

                if not matched_course:
                    return {
                        "success": False,
                        "message": f"No Moodle course found matching **{course_name}**. Enrolled courses: {[c['fullname'] for c in courses[:5]]}",
                        "course": course_name,
                    }

                forums = self.get_course_forums(page, matched_course["id"])
                if not forums:
                    return {
                        "success": False,
                        "message": f"No forums found in **{matched_course['fullname']}**.",
                        "course": matched_course["fullname"],
                    }

                # Pick the first general/news forum, or just first
                target_forum = next(
                    (f for f in forums if f["type"] in ("general", "news")),
                    forums[0],
                )

                result = self.post_to_forum(page, target_forum["id"], subject, message)
                result["course"] = matched_course["fullname"]
                result["forum"] = target_forum["name"]
                return result

            finally:
                browser.close()

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
