"""WatcherAgent: scrapes TUMonline and Moodle for deadlines."""

from datetime import datetime, timedelta
from typing import Any

from tum_pulse.memory.database import SQLiteMemory


class WatcherAgent:
    """Monitors TUMonline and Moodle for upcoming deadlines and saves them to SQLite."""

    def __init__(self) -> None:
        """Initialise with the shared SQLite memory layer."""
        self.db = SQLiteMemory()

    # ------------------------------------------------------------------
    # Scrapers (placeholders — implement with real auth later)
    # ------------------------------------------------------------------

    def scrape_tumonline(self) -> list[dict]:
        """Return deadline data scraped from TUMonline.

        Returns:
            List of deadline dicts with keys: title, course, deadline_date, source.

        TODO: Replace mock data with real Playwright automation:
              1. Launch browser with playwright.sync_api
              2. Navigate to https://campus.tum.de and log in with TUM credentials
              3. Navigate to "My Studies" > "Exams" and parse the exam registration table
              4. Navigate to "Submissions" section and parse assignment deadlines
              5. Extract dates, convert to ISO format (YYYY-MM-DD), and return
        """
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

    def scrape_moodle(self) -> list[dict]:
        """Return deadline data scraped from Moodle.

        Returns:
            List of deadline dicts with keys: title, course, deadline_date, source.

        TODO: Replace mock data with real Moodle scraping:
              1. Use MoodleScraper.login() with TUM SSO credentials
              2. Fetch the Moodle calendar API: /calendar/action_getall_events.php
              3. Filter for event types 'assign' and 'quiz'
              4. Parse deadlines and return structured dicts
        """
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
    print("--- Scraping all sources ---")
    print(agent.run())
    print("\n--- This week's deadlines ---")
    print(agent.get_this_week())
