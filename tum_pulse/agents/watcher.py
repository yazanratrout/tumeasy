"""WatcherAgent: scrapes TUMonline (via NAT REST API) and Moodle for deadlines."""

import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from tum_pulse.memory.database import SQLiteMemory

TUM_API_BASE = "https://api.srv.nat.tum.de"


class WatcherAgent:
    """Monitors TUMonline and Moodle for upcoming deadlines and saves them to SQLite."""

    def __init__(self) -> None:
        """Initialise with the shared SQLite memory layer."""
        self.db = SQLiteMemory()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_current_semester_key(self) -> str | None:
        """Return the semester_key for the currently active semester.

        Returns:
            Semester key string (e.g. '2026s') or None if the API is unreachable.
        """
        resp = requests.get(
            f"{TUM_API_BASE}/api/v1/semesters",
            params={"limit": 200},
            timeout=10,
        )
        resp.raise_for_status()
        semesters = resp.json()
        current = next((s for s in semesters if s.get("is_current")), None)
        return current["semester_key"] if current else None

    # ------------------------------------------------------------------
    # Scrapers
    # ------------------------------------------------------------------

    def scrape_tumonline(self) -> list[dict]:
        """Return deadline data from the TUM NAT public REST API.

        Fetches two data sources:
        1. Exam-period registration deadlines for the current semester
           (``/api/v1/semesters/examperiods``).
        2. Per-exam registration close dates whose deadline falls within the
           next 60 days (``/api/v1/exam/date``).

        Falls back to mock data if the API is unreachable or returns an error.

        Returns:
            List of deadline dicts with keys: title, course, deadline_date, source.
        """
        try:
            print(f"[WatcherAgent] Using REAL TUMonline API ({TUM_API_BASE})")

            semester_key = self._get_current_semester_key()
            if not semester_key:
                raise ValueError("Could not determine current semester")
            print(f"[WatcherAgent] Current semester: {semester_key}")

            deadlines: list[dict] = []
            now = datetime.now(tz=timezone.utc)
            cutoff = now + timedelta(days=60)

            # --- 1. Exam-period registration deadlines ---
            time.sleep(0.5)
            ep_resp = requests.get(
                f"{TUM_API_BASE}/api/v1/semesters/examperiods",
                timeout=10,
            )
            ep_resp.raise_for_status()
            for ep in ep_resp.json():
                if ep.get("semester_key") != semester_key:
                    continue
                reg_end_raw = ep.get("examperiod_registration_end", "")
                if not reg_end_raw:
                    continue
                try:
                    reg_end = datetime.fromisoformat(reg_end_raw)
                    if reg_end.tzinfo is None:
                        reg_end = reg_end.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                if reg_end < now:
                    continue
                tag = ep.get("examperiod_tag", "")
                title_en = ep.get("examperiod_title_en", f"{tag} exam period")
                semester_tag = ep.get("semester", {}).get("semester_tag", semester_key)
                deadlines.append({
                    "title": f"Exam Registration Deadline: {title_en}",
                    "course": f"All courses — {semester_tag}",
                    "deadline_date": reg_end.strftime("%Y-%m-%d"),
                    "source": "tumonline",
                })
                print(f"[WatcherAgent]   Exam period: {title_en} → {reg_end.strftime('%Y-%m-%d')}")

            # --- 2. Per-exam registration close dates (next 60 days) ---
            time.sleep(0.5)
            exam_resp = requests.get(
                f"{TUM_API_BASE}/api/v1/exam/date",
                params={"semester_key": semester_key, "limit": 100},
                timeout=10,
            )
            exam_resp.raise_for_status()
            exam_data = exam_resp.json()
            hits = exam_data.get("hits", []) if isinstance(exam_data, dict) else exam_data

            for exam in hits:
                reg_end_raw = exam.get("register_end", "")
                if not reg_end_raw:
                    continue
                try:
                    reg_end = datetime.fromisoformat(reg_end_raw)
                    if reg_end.tzinfo is None:
                        reg_end = reg_end.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                if reg_end < now or reg_end > cutoff:
                    continue

                course_name = exam.get("course_name_en") or exam.get("course_name", "Unknown")
                course_code = exam.get("course_code", "")
                exam_start_raw = exam.get("exam_start", "")
                exam_date = ""
                if exam_start_raw:
                    try:
                        exam_date = f" (exam {datetime.fromisoformat(exam_start_raw).strftime('%Y-%m-%d')})"
                    except ValueError:
                        pass

                deadlines.append({
                    "title": f"Exam Registration Closes: {course_name}{exam_date}",
                    "course": f"{course_name} [{course_code}]",
                    "deadline_date": reg_end.strftime("%Y-%m-%d"),
                    "source": "tumonline",
                })
                print(f"[WatcherAgent]   Exam reg: {course_name} → {reg_end.strftime('%Y-%m-%d')}")

            print(f"[WatcherAgent] TUMonline: fetched {len(deadlines)} deadline(s)")
            return deadlines

        except Exception as exc:
            print(f"[WatcherAgent] TUMonline API failed ({exc}) — Using MOCK data")
            return self._mock_tumonline()

    def scrape_moodle(self) -> list[dict]:
        """Return deadline data scraped from Moodle via Playwright SSO login.

        Instantiates MoodleScraper, logs in, and fetches calendar deadlines.
        Falls back to mock data if the scraper raises an exception.

        Returns:
            List of deadline dicts with keys: title, course, deadline_date, source.
        """
        try:
            from tum_pulse.tools.moodle_scraper import MoodleScraper
            scraper = MoodleScraper()
            deadlines = scraper.get_deadlines_from_calendar()
            print(f"[WatcherAgent] Moodle: fetched {len(deadlines)} deadline(s)")
            return deadlines
        except Exception as exc:
            print(f"[WatcherAgent] Moodle scrape failed ({exc}) — Using MOCK data")
            return self._mock_moodle()

    # ------------------------------------------------------------------
    # Mock fallbacks (kept so the app works without credentials)
    # ------------------------------------------------------------------

    def _mock_tumonline(self) -> list[dict]:
        """Return hardcoded mock TUMonline deadlines."""
        today = datetime.now()
        return [
            {
                "title": "Exam Registration: Analysis 2",
                "course": "Analysis 2",
                "deadline_date": (today + timedelta(days=3)).strftime("%Y-%m-%d"),
                "source": "tumonline",
            },
            {
                "title": "Homework Sheet 5 Submission",
                "course": "Algorithms and Data Structures",
                "deadline_date": (today + timedelta(days=5)).strftime("%Y-%m-%d"),
                "source": "tumonline",
            },
            {
                "title": "Lab Report 2",
                "course": "Practical Course: Machine Learning",
                "deadline_date": (today + timedelta(days=10)).strftime("%Y-%m-%d"),
                "source": "tumonline",
            },
        ]

    def _mock_moodle(self) -> list[dict]:
        """Return hardcoded mock Moodle deadlines."""
        today = datetime.now()
        return [
            {
                "title": "Quiz: Probability Theory Chapter 3",
                "course": "Introduction to Probability",
                "deadline_date": (today + timedelta(days=2)).strftime("%Y-%m-%d"),
                "source": "moodle",
            },
            {
                "title": "Project Milestone 1",
                "course": "Software Engineering",
                "deadline_date": (today + timedelta(days=7)).strftime("%Y-%m-%d"),
                "source": "moodle",
            },
        ]

    # ------------------------------------------------------------------
    # Main entry points
    # ------------------------------------------------------------------

    def run(self) -> str:
        """Scrape all sources, persist to DB, return human-readable summary.

        Returns:
            A formatted string listing all newly saved deadlines.
        """
        all_deadlines: list[dict] = []

        try:
            tumonline_deadlines = self.scrape_tumonline()
            all_deadlines.extend(tumonline_deadlines)
        except Exception as exc:
            print(f"[WatcherAgent] TUMonline scrape error: {exc}")

        try:
            moodle_deadlines = self.scrape_moodle()
            all_deadlines.extend(moodle_deadlines)
        except Exception as exc:
            print(f"[WatcherAgent] Moodle scrape error: {exc}")

        for dl in all_deadlines:
            self.db.save_deadline(
                title=dl["title"],
                course=dl["course"],
                deadline_date=dl["deadline_date"],
                source=dl["source"],
            )

        if not all_deadlines:
            return "No deadlines found from any source."

        lines = [f"Found {len(all_deadlines)} deadline(s):\n"]
        for dl in sorted(all_deadlines, key=lambda x: x["deadline_date"]):
            lines.append(f"  • [{dl['deadline_date']}] {dl['title']} ({dl['course']})")
        return "\n".join(lines)

    def get_this_week(self) -> str:
        """Return a formatted list of deadlines in the next 7 days.

        Returns:
            Human-readable string of upcoming deadlines.
        """
        deadlines = self.db.get_upcoming_deadlines(days=7)
        if not deadlines:
            return "No deadlines in the next 7 days. "

        lines = ["**Upcoming deadlines (next 7 days):**\n"]
        for dl in deadlines:
            lines.append(f"  • [{dl['deadline_date']}] {dl['title']} — {dl['course']}")
        return "\n".join(lines)


if __name__ == "__main__":
    agent = WatcherAgent()

    print("=" * 60)
    print("TEST: scrape_tumonline() — real TUM NAT API")
    print("=" * 60)
    try:
        tum_deadlines = agent.scrape_tumonline()
        print(f"\nReturned {len(tum_deadlines)} deadline(s):")
        for d in tum_deadlines:
            print(f"  [{d['deadline_date']}] {d['title']}")
    except Exception as e:
        print(f"Error: {e}")

    print()
    print("=" * 60)
    print("TEST: scrape_moodle() — Playwright SSO")
    print("=" * 60)
    try:
        moodle_deadlines = agent.scrape_moodle()
        print(f"\nReturned {len(moodle_deadlines)} deadline(s):")
        for d in moodle_deadlines:
            print(f"  [{d['deadline_date']}] {d['title']}")
    except Exception as e:
        print(f"Error: {e}")

    print()
    print("=" * 60)
    print("TEST: full run() + this week")
    print("=" * 60)
    print(agent.run())
    print()
    print(agent.get_this_week())
