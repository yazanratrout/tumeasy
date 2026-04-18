"""WatcherAgent — scrapes TUMonline, Moodle, and Confluence for deadlines.

Scraper hierarchy per source:
  TUMonline  → NAT REST API (public, no auth) → TUMonlineConnector (Playwright/Shibboleth) → mock
  Moodle     → MoodleConnector (Shibboleth + AJAX API) → MoodleScraper (Playwright) → mock
  Confluence → atlassian-python-api → skipped (not a hard error)
"""

import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from tum_pulse.config import (
    CONFLUENCE_PAT,
    CONFLUENCE_PASSWORD,
    CONFLUENCE_SPACE,
    CONFLUENCE_URL,
    CONFLUENCE_USERNAME,
    DB_PATH,
    TUM_PASSWORD,
    TUM_USERNAME,
)
from tum_pulse.memory.database import SQLiteMemory

TUM_API_BASE = "https://api.srv.nat.tum.de"

_GENERIC_WORDS = {
    "introduction", "advanced", "applied", "practical", "principles",
    "fundamentals", "basics", "overview", "seminar", "lecture",
    "course", "study", "studies", "special", "topics", "selected",
}


# ---------------------------------------------------------------------------
# Module-level mock functions (importable by main.py for preview)
# ---------------------------------------------------------------------------

def _mock_tumonline() -> list[dict]:
    """Return hardcoded mock TUMonline deadlines (never saved to DB)."""
    today = datetime.now()
    return [
        {"title": "Exam Registration: Analysis 2", "course": "Analysis 2",
         "deadline_date": (today + timedelta(days=3)).strftime("%Y-%m-%d"), "source": "mock"},
        {"title": "Homework Sheet 5 Submission", "course": "Algorithms and Data Structures",
         "deadline_date": (today + timedelta(days=5)).strftime("%Y-%m-%d"), "source": "mock"},
        {"title": "Lab Report 2", "course": "Practical Course: Machine Learning",
         "deadline_date": (today + timedelta(days=10)).strftime("%Y-%m-%d"), "source": "mock"},
    ]


def _mock_moodle() -> list[dict]:
    """Return hardcoded mock Moodle deadlines (never saved to DB)."""
    today = datetime.now()
    return [
        {"title": "Quiz: Probability Theory Chapter 3", "course": "Introduction to Probability",
         "deadline_date": (today + timedelta(days=2)).strftime("%Y-%m-%d"), "source": "mock"},
        {"title": "Project Milestone 1", "course": "Software Engineering",
         "deadline_date": (today + timedelta(days=7)).strftime("%Y-%m-%d"), "source": "mock"},
    ]


# ---------------------------------------------------------------------------
# WatcherAgent
# ---------------------------------------------------------------------------

class WatcherAgent:
    """Monitors TUMonline, Moodle, and Confluence for upcoming deadlines."""

    def __init__(self) -> None:
        """Initialise with the shared SQLite memory layer."""
        self.db = SQLiteMemory()
        self.status: dict[str, str] = {
            "tumonline": "not run",
            "moodle":    "not run",
            "confluence": "not run",
        }
        self._last_enrolled_courses: list[str] = []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_current_semester_key(self) -> str | None:
        """Return the semester_key for the currently active semester."""
        resp = requests.get(
            f"{TUM_API_BASE}/api/v1/semesters",
            params={"limit": 200},
            timeout=10,
        )
        resp.raise_for_status()
        semesters = resp.json()
        current = next((s for s in semesters if s.get("is_current")), None)
        return current["semester_key"] if current else None

    def _get_enrolled_courses(self) -> dict:
        """Fetch enrolled courses and grades from TUMonline, cache in SQLite.

        Tries in order:
        1. TUMonlineConnector.scrape_with_courses() — real Playwright scrape
        2. SQLiteMemory cached profile (from previous successful scrape)
        3. Empty dict (no filtering applied)

        Always saves successful results to SQLite so they persist across runs.

        Returns:
            dict with "enrolled" (list), "grades" (dict), "all_courses" (list)
        """
        _empty = {"enrolled": [], "grades": {}, "all_courses": []}

        # --- 1. Live Playwright scrape via TUMonlineConnector ---
        try:
            from tum_pulse.connectors.tumonline import TUMonlineConnector
            result = TUMonlineConnector().scrape_with_courses(TUM_USERNAME, TUM_PASSWORD)
            courses_data = result.get("courses", {})

            if courses_data.get("all_courses"):
                self.db.save_profile("courses", courses_data["all_courses"])
                self.db.save_profile("enrolled", courses_data["enrolled"])
                if courses_data.get("grades"):
                    self.db.save_profile("grades", courses_data["grades"])
                    print(f"[WatcherAgent] Saved {len(courses_data['grades'])} grades to profile")
                else:
                    print("[WatcherAgent] No grades returned from TUMonline this session")
                print(f"[WatcherAgent] Fetched {len(courses_data['all_courses'])} courses from TUMonline")
                return courses_data
        except Exception as exc:
            print(f"[WatcherAgent] TUMonline course fetch failed: {exc}")

        # --- 2. Cached SQLite profile ---
        try:
            cached_courses = self.db.get_profile("courses")
            cached_grades = self.db.get_profile("grades")
            cached_enrolled = self.db.get_profile("enrolled")
            if cached_courses and isinstance(cached_courses, list):
                print(f"[WatcherAgent] Using {len(cached_courses)} cached courses from SQLite profile")
                return {
                    "enrolled": cached_enrolled or cached_courses,
                    "grades": cached_grades or {},
                    "all_courses": cached_courses,
                }
        except Exception:
            pass

        print("[WatcherAgent] No course data available — showing all deadlines unfiltered")
        return _empty

    # Words too generic to use as sole matching signal in TUM context
    _DEADLINE_STOPWORDS = frozenset({
        "which", "their", "these", "those", "about", "other", "where",
        "there", "using", "seminar", "systems", "master", "introduction",
    })

    @staticmethod
    def _course_key_words(name: str) -> list[str]:
        """Extract significant words from an enrolled course name."""
        # Strip course codes like (IN2346) but keep (Robot Operating System)
        clean = re.sub(r'\([A-Z]{1,4}\d{3,}[^)]*\)', '', name).lower()
        return [
            w for w in re.split(r'\W+', clean)
            if len(w) > 3 and w not in WatcherAgent._DEADLINE_STOPWORDS
        ]

    def _filter_by_enrollment(
        self, deadlines: list[dict], enrolled: list[str]
    ) -> list[dict]:
        """Filter deadlines to only those relevant to the student's enrolled courses.

        Uses word-overlap matching (≥2 significant words, or 1 for single-keyword
        courses like Japanisch). Course codes (IN2346) are matched exactly.
        Always passes through TUM Administration deadlines.

        Args:
            deadlines: Full list of deadline dicts.
            enrolled: Exact course name strings from the student's profile.

        Returns:
            Filtered list of relevant deadlines.
        """
        if not enrolled:
            return deadlines

        def _matches(deadline: dict) -> bool:
            title = deadline.get("title", "")
            course = deadline.get("course", "") or ""
            if course == "TUM Administration":
                return True
            if title.startswith(("Exam Registration Deadline", "Course Registration",
                                   "Re-enrollment", "Semester Contribution", "Exmatriculation")):
                return True
            text = (title + " " + course).lower()
            for enr in enrolled:
                codes = re.findall(r'[A-Z]{1,4}\d{3,}', enr)
                if codes:
                    # Course has a code — only match via that code, never by keywords alone
                    if any(c.lower() in text for c in codes):
                        return True
                    continue
                # No course code — fall back to word-overlap
                words = self._course_key_words(enr)
                if not words:
                    continue
                hits = sum(1 for w in words if w in text)
                threshold = 1 if len(words) == 1 else 2
                if hits >= threshold:
                    return True
            return False

        filtered = [dl for dl in deadlines if _matches(dl)]
        print(
            f"[WatcherAgent] Enrollment filter: "
            f"{len(deadlines)} → {len(filtered)} deadline(s)"
        )
        return filtered

    def _parse_time_range(self, user_input: str) -> tuple[int, str]:
        """Parse a natural-language time expression into (days, human_label).

        Covers English and German expressions. Falls back to 7 days.

        Examples:
            "what's due today"           →  (1,  "today")
            "deadlines this week"        →  (7,  "this week")
            "anything in the next month" →  (30, "this month")
            "next 2 weeks"               →  (14, "next 2 weeks")
            "nächste woche"              →  (14, "next two weeks")
        """
        text = user_input.lower()

        m = re.search(r"(\d+)\s*days?", text)
        if m:
            d = int(m.group(1))
            return d, f"next {d} day{'s' if d > 1 else ''}"

        m = re.search(r"(\d+)\s*weeks?", text)
        if m:
            w = int(m.group(1))
            return w * 7, f"next {w} week{'s' if w > 1 else ''}"

        m = re.search(r"(\d+)\s*months?", text)
        if m:
            mo = int(m.group(1))
            return mo * 30, f"next {mo} month{'s' if mo > 1 else ''}"

        if any(w in text for w in ("today", "heute", "today's")):
            return 1, "today"

        if any(w in text for w in ("tomorrow", "morgen")):
            return 2, "tomorrow"

        if any(w in text for w in ("this week", "diese woche", "current week")):
            return 7, "this week"

        if any(w in text for w in ("next week", "nächste woche")):
            return 14, "next two weeks"

        if any(w in text for w in (
            "this month", "diesen monat", "month", "monat",
            "coming weeks", "upcoming weeks",
        )):
            return 30, "this month"

        if any(w in text for w in ("semester", "term")):
            return 120, "this semester"

        return 7, "the next 7 days"

    # ------------------------------------------------------------------
    # Scrapers — TUMonline
    # ------------------------------------------------------------------

    def scrape_tumonline_semester_deadlines(self) -> list[dict]:
        """Fetch semester-level registration, re-enrollment and payment deadlines.

        Reads the current semester object from the NAT API which contains:
        - Course registration windows (Belegfrist)
        - Re-enrollment deadline (Rückmeldung)
        - Semester contribution payment deadline (Beitragszahlung)

        Returns:
            List of deadline dicts.
        """
        deadlines: list[dict] = []
        try:
            resp = requests.get(f"{TUM_API_BASE}/api/v1/semesters", params={"limit": 20}, timeout=10)
            resp.raise_for_status()
            semesters = resp.json()
            current = next((s for s in semesters if s.get("is_current")), None)
            if not current:
                return []

            now = datetime.now()
            semester_tag = current.get("semester_tag", "Current Semester")

            # Field name pairs: (api_field, human label, type)
            date_fields = [
                ("enrollment_start",        "enrollment_end",          "Course Registration Opens",   "tumonline"),
                ("enrollment_end",          None,                       "Course Registration Closes (Belegfrist)", "tumonline"),
                ("reenrollment_start",      "reenrollment_end",         "Re-enrollment Opens (Rückmeldung)", "tumonline"),
                ("reenrollment_end",        None,                       "Re-enrollment Deadline (Rückmeldung)", "tumonline"),
                ("contribution_deadline",   None,                       "Semester Contribution Payment (Beitrag)", "tumonline"),
                ("exmatriculation_deadline",None,                       "Exmatriculation Deadline",   "tumonline"),
            ]

            for start_field, _end_field, label, source in date_fields:
                raw = current.get(start_field) or current.get(_end_field if _end_field else "")
                if not raw:
                    continue
                try:
                    dt = datetime.fromisoformat(str(raw)[:10])
                    if dt.date() < now.date():
                        continue
                    deadlines.append({
                        "title": f"{label}: {semester_tag}",
                        "course": "TUM Administration",
                        "deadline_date": dt.strftime("%Y-%m-%d"),
                        "source": source,
                    })
                    print(f"[WatcherAgent] Semester deadline: {label} → {dt.strftime('%Y-%m-%d')}")
                except (ValueError, TypeError):
                    continue

            # Also check top-level keys that might be nested differently
            for key, val in current.items():
                if "deadline" in key.lower() or "end" in key.lower() or "frist" in key.lower():
                    if isinstance(val, str) and len(val) >= 10:
                        try:
                            dt = datetime.fromisoformat(val[:10])
                            if dt.date() < now.date():
                                continue
                            human = key.replace("_", " ").title()
                            # Skip if we already have this field
                            if any(human.lower() in d["title"].lower() for d in deadlines):
                                continue
                            if any(w in key.lower() for w in ["deadline", "end", "frist", "reenroll", "enroll", "contribution"]):
                                deadlines.append({
                                    "title": f"{human}: {semester_tag}",
                                    "course": "TUM Administration",
                                    "deadline_date": dt.strftime("%Y-%m-%d"),
                                    "source": "tumonline",
                                })
                        except (ValueError, TypeError):
                            continue

        except Exception as exc:
            print(f"[WatcherAgent] Semester deadline fetch failed: {exc}")

        return deadlines

    def scrape_tumonline(self) -> list[dict]:
        """Return deadline data from the TUM NAT public REST API (primary path).

        Fetches exam-period registration deadlines and per-exam registration
        close dates within 60 days. Falls back to mock on any error.

        Returns:
            List of deadline dicts with keys: title, course, deadline_date, source.
        """
        try:
            print(f"[WatcherAgent] Using REAL TUMonline API ({TUM_API_BASE})")

            courses_data = self._get_enrolled_courses()
            # Use current-semester enrolled only — not historical achievements
            enrolled_courses = (
                courses_data.get("enrolled") or
                courses_data.get("all_courses", [])
            )
            self._last_enrolled_courses = enrolled_courses

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

            print(f"[WatcherAgent] TUMonline NAT API: {len(deadlines)} deadline(s) before filtering")
            deadlines = self._filter_by_enrollment(deadlines, enrolled_courses)
            self.status["tumonline"] = "live" if deadlines else "mock"
            return deadlines

        except Exception as exc:
            print(f"[WatcherAgent] TUMonline NAT API failed ({exc}) — will try Playwright fallback")
            self._last_enrolled_courses = []
            self.status["tumonline"] = "mock"
            return []

    def scrape_tumonline_playwright(self) -> list[dict]:
        """Secondary TUMonline scraper: Playwright login to campus.tum.de.

        Called by run() only when the NAT REST API returns 0 results.
        Returns empty list (never mock) if login or scraping fails.
        """
        try:
            from tum_pulse.connectors.tumonline import TUMonlineConnector
            print("[WatcherAgent] Trying TUMonlineConnector (Playwright) ...")
            results = TUMonlineConnector().scrape(TUM_USERNAME, TUM_PASSWORD)
            if results:
                print(f"[WatcherAgent] TUMonlineConnector: {len(results)} deadline(s)")
                self.status["tumonline"] = "live"
                return results
            print("[WatcherAgent] TUMonlineConnector returned 0 results")
            return []
        except Exception as exc:
            print(f"[WatcherAgent] TUMonlineConnector failed: {exc}")
            return []

    # ------------------------------------------------------------------
    # Scrapers — Moodle
    # ------------------------------------------------------------------

    def scrape_moodle_ajax(self) -> list[dict]:
        """Fetch Moodle deadlines via Shibboleth SSO + AJAX calendar API (primary).

        Uses MoodleConnector which calls core_calendar_get_action_events_by_timesort.

        Returns:
            List of deadline dicts.

        Raises:
            Exception: propagated so scrape_moodle() can fall back.
        """
        from tum_pulse.connectors.moodle import MoodleConnector
        print("[WatcherAgent] Trying MoodleConnector (AJAX) ...")
        results = MoodleConnector().scrape(TUM_USERNAME, TUM_PASSWORD)
        print(f"[WatcherAgent] MoodleConnector: {len(results)} deadline(s)")
        return results

    def scrape_moodle(self) -> list[dict]:
        """Return Moodle deadlines: AJAX connector → Playwright DOM → mock.

        Returns:
            List of deadline dicts with keys: title, course, deadline_date, source.
        """
        # --- 1. AJAX API via MoodleConnector (best quality data) ---
        try:
            results = self.scrape_moodle_ajax()
            self.status["moodle"] = "live"
            return results
        except Exception as exc:
            print(f"[WatcherAgent] MoodleConnector failed ({exc}) — trying MoodleScraper ...")

        # --- 2. Playwright DOM parsing via MoodleScraper (fallback) ---
        try:
            from tum_pulse.tools.moodle_scraper import MoodleScraper
            scraper = MoodleScraper()
            deadlines = scraper.get_deadlines_from_calendar()
            # Reject sample/mock deadlines that come from the fallback path
            real = [d for d in deadlines if d.get("source") != "mock"]
            if real:
                print(f"[WatcherAgent] MoodleScraper: {len(real)} deadline(s)")
                self.status["moodle"] = "live"
                return real
            print("[WatcherAgent] MoodleScraper returned only sample data — skipping")
            self.status["moodle"] = "failed"
            return []
        except Exception as exc:
            print(f"[WatcherAgent] MoodleScraper failed: {exc}")
            self.status["moodle"] = "failed"
            return []

    # ------------------------------------------------------------------
    # Scrapers — Confluence
    # ------------------------------------------------------------------

    def scrape_confluence(self) -> list[dict]:
        """Search Confluence/Collab Wiki for deadline-related pages.

        Uses atlassian-python-api CQL search. Skipped (returns []) rather than
        raising if Confluence is unreachable or not configured.

        Returns:
            List of deadline dicts, or [] if Confluence is skipped.
        """
        try:
            from atlassian import Confluence
            from tum_pulse.connectors.tumonline import parse_date as _parse_date

            if not CONFLUENCE_PAT:
                # collab.dvb.bayern has basic auth disabled; PAT is required.
                # Generate one at: https://collab.dvb.bayern/plugins/personalaccesstokens/usertokens.action
                # Then add CONFLUENCE_PAT=<token> to your .env file.
                print("[WatcherAgent] Confluence skipped: CONFLUENCE_PAT not set (basic auth disabled on collab.dvb.bayern)")
                self.status["confluence"] = "skipped"
                return []

            confluence = Confluence(
                url=CONFLUENCE_URL,
                token=CONFLUENCE_PAT,
                timeout=20,
            )
            space_filter = f"AND space = '{CONFLUENCE_SPACE}'" if CONFLUENCE_SPACE else ""
            cql = (
                f"text ~ 'deadline OR exam OR Abgabe OR Prüfung' "
                f"{space_filter} ORDER BY lastmodified DESC"
            )
            results = confluence.cql(cql, limit=20).get("results", [])

            deadlines: list[dict] = []
            today = datetime.now()
            for result in results:
                title = result.get("title", "")
                excerpt = result.get("excerpt", "")
                url = result.get("url", "")
                self.db.save_content("confluence", url, f"{title}\n{excerpt}")
                date_str = _parse_date(excerpt) or _parse_date(title)
                if date_str:
                    try:
                        if datetime.strptime(date_str, "%Y-%m-%d") >= today:
                            deadlines.append({
                                "title": title,
                                "course": "",
                                "deadline_date": date_str,
                                "source": "confluence",
                            })
                    except ValueError:
                        pass

            self.status["confluence"] = "live"
            print(f"[WatcherAgent] Confluence: {len(deadlines)} deadline(s)")
            return deadlines

        except Exception as exc:
            print(f"[WatcherAgent] Confluence skipped: {exc}")
            self.status["confluence"] = "skipped"
            return []

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------

    def check_and_create_alerts(self) -> int:
        """Create alerts for deadlines within 2 days, skipping duplicates.

        Returns:
            Number of new alert rows created.
        """
        upcoming = self.db.get_upcoming_deadlines(days=2)
        if not upcoming:
            return 0

        with sqlite3.connect(DB_PATH) as conn:
            existing_messages = {
                row[0] for row in conn.execute("SELECT message FROM alerts").fetchall()
            }

        created = 0
        for dl in upcoming:
            try:
                delta = datetime.strptime(dl["deadline_date"], "%Y-%m-%d") - datetime.now().replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                days_away = max(delta.days, 0)
            except ValueError:
                days_away = 0

            message = f"⚠️ Deadline in {days_away} days: {dl['title']} ({dl['course']})"
            if message not in existing_messages:
                self.db.create_alert(message=message, deadline_date=dl["deadline_date"])
                existing_messages.add(message)
                created += 1

        if created:
            print(f"[WatcherAgent] Created {created} new alert(s)")
        return created

    # ------------------------------------------------------------------
    # Main entry points
    # ------------------------------------------------------------------

    def run(self) -> str:
        """Scrape all sources, persist to SQLite, return human-readable summary.

        TUMonline: NAT REST API first; falls back to Playwright connector if empty.
        Moodle: AJAX connector first; falls back to DOM scraper, then mock.
        Confluence: best-effort; silently skipped on failure.

        Returns:
            Formatted string listing all deadlines found.
        """
        all_deadlines: list[dict] = []
        self._last_enrolled_courses = []

        # TUMonline — NAT API primary, Playwright secondary
        try:
            nat_deadlines = self.scrape_tumonline()
            if nat_deadlines:
                all_deadlines.extend(nat_deadlines)
                if self._last_enrolled_courses:
                    # Save current-semester enrolled courses (not historical)
                    self.db.save_profile("enrolled", self._last_enrolled_courses)
                    # Merge into courses list without clobbering historical grades
                    existing = self.db.get_profile("courses") or []
                    merged = list(dict.fromkeys(self._last_enrolled_courses + existing))
                    self.db.save_profile("courses", merged)
            else:
                pw_deadlines = self.scrape_tumonline_playwright()
                all_deadlines.extend(pw_deadlines)
        except Exception as exc:
            print(f"[WatcherAgent] TUMonline scrape error: {exc}")

        # TUMonline — semester admin deadlines (Belegfrist, Rückmeldung, Beitrag)
        try:
            sem_deadlines = self.scrape_tumonline_semester_deadlines()
            all_deadlines.extend(sem_deadlines)
            # These are always "live" since they come from the public NAT API
            if sem_deadlines:
                self.status["tumonline"] = "live"
        except Exception as exc:
            print(f"[WatcherAgent] Semester deadline scrape error: {exc}")

        # Moodle
        try:
            moodle_deadlines = self.scrape_moodle()
            all_deadlines.extend(moodle_deadlines)
        except Exception as exc:
            print(f"[WatcherAgent] Moodle scrape error: {exc}")

        # Confluence (best-effort)
        try:
            confluence_deadlines = self.scrape_confluence()
            all_deadlines.extend(confluence_deadlines)
        except Exception as exc:
            print(f"[WatcherAgent] Confluence scrape error: {exc}")

        # Only persist LIVE deadlines — never save mock/fallback data
        # so the DB stays clean and only contains real student data.
        live_sources = {
            src for src, state in self.status.items() if state == "live"
        }
        saved = 0
        for dl in all_deadlines:
            if dl.get("source") in live_sources:
                self.db.save_deadline(
                    title=dl["title"],
                    course=dl["course"],
                    deadline_date=dl["deadline_date"],
                    source=dl["source"],
                )
                saved += 1

        print(f"[WatcherAgent] Saved {saved} live deadline(s) to DB "
              f"(skipped {len(all_deadlines) - saved} mock/fallback)")

        if not all_deadlines:
            return "No deadlines found from any source."

        lines = [f"Found {len(all_deadlines)} deadline(s):\n"]
        for dl in sorted(all_deadlines, key=lambda x: x["deadline_date"]):
            src = self.status.get(dl["source"], "")
            tag = "✅" if src == "live" else "📋"
            lines.append(f"  {tag} [{dl['deadline_date']}] {dl['title']} ({dl['course'] or dl['source']})")

        self.check_and_create_alerts()
        return "\n".join(lines)

    def get_this_week(self, user_input: str = "", context: dict | None = None) -> str:
        """Return personalized, formatted deadlines for the requested time range.

        Parses the time range from user_input (defaults to 7 days).
        Filters by enrolled courses from context or SQLite.
        Flags weak subjects with a warning marker.

        Args:
            user_input: Natural language query (used to parse time range).
            context: Optional orchestrator context with courses/grades/weak_subjects.

        Returns:
            Formatted markdown string of upcoming deadlines.
        """
        days, time_label = self._parse_time_range(user_input)

        enrolled = (
            (context or {}).get("courses")
            or self.db.get_profile("courses")
            or []
        )
        weak = (context or {}).get("weak_subjects") or []

        deadlines = self.db.get_upcoming_deadlines(days=days)
        deadlines = self._filter_by_enrollment(deadlines, enrolled)

        if not deadlines:
            msg = f"No deadlines found for **{time_label}**."
            last_fetched = self.db.get_last_fetched()
            if not last_fetched:
                msg += (
                    "\n\n> ⚠️ Data has not been synced yet. "
                    "A background sync runs automatically on login."
                )
            return msg

        lines = [f"**Deadlines for {time_label}** ({len(deadlines)} found):\n"]
        for dl in sorted(deadlines, key=lambda x: x.get("deadline_date", "")):
            date_str = dl["deadline_date"]
            try:
                delta = (
                    datetime.strptime(date_str, "%Y-%m-%d").date()
                    - datetime.now().date()
                ).days
                urgency = "🔴" if delta <= 1 else "🟡" if delta <= 3 else "📅"
            except ValueError:
                urgency = "📅"

            # Flag if this is a known weak subject
            weak_flag = ""
            if weak:
                combined = (dl["title"] + " " + dl.get("course", "")).lower()
                if any(w.lower() in combined for w in weak):
                    weak_flag = " ⚠️ *weak subject*"

            lines.append(
                f"  {urgency} **{date_str}** — {dl['title']} "
                f"({dl.get('course', dl.get('source', ''))}){weak_flag}"
            )

        return "\n".join(lines)


if __name__ == "__main__":
    agent = WatcherAgent()

    print("=" * 60)
    print("TEST: scrape_tumonline() — NAT REST API")
    print("=" * 60)
    tum = agent.scrape_tumonline()
    print(f"Returned {len(tum)} deadline(s)")
    for d in tum[:5]:
        print(f"  [{d['deadline_date']}] {d['title']}")

    print()
    print("=" * 60)
    print("TEST: scrape_moodle()")
    print("=" * 60)
    moodle = agent.scrape_moodle()
    print(f"Returned {len(moodle)} deadline(s)")

    print()
    print("=" * 60)
    print("TEST: full run()")
    print("=" * 60)
    print(agent.run())
    print("\nStatus:", agent.status)
    print()
    print(agent.get_this_week())
