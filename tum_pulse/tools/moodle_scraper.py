"""Moodle scraper: Playwright SSO login, calendar deadlines, course files, PDF download."""

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

from tum_pulse.config import DATA_DIR, MOODLE_BASE_URL, TUM_PASSWORD, TUM_USERNAME


class MoodleScraper:
    """Handles authenticated access to TUM Moodle for deadlines and file retrieval."""

    def __init__(
        self,
        base_url: str = MOODLE_BASE_URL,
        username: str = TUM_USERNAME,
        password: str = TUM_PASSWORD,
    ) -> None:
        """Store credentials and initialise a requests session.

        Args:
            base_url: Root URL of the Moodle instance.
            username: TUM / Moodle username.
            password: TUM / Moodle password.
        """
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "TUMPulse/1.0"})
        self._logged_in = False

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def login_playwright(self) -> bool:
        """Authenticate via TUM Shibboleth SSO using a headless Chromium browser.

        Navigates to Moodle, clicks the TUM SSO button, fills credentials on
        the SSO page, waits for the redirect back, then transfers cookies into
        self.session so subsequent requests calls are authenticated.

        Returns:
            True if login succeeded and we are back on Moodle, False otherwise.
        """
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
        except ImportError:
            print("[MoodleScraper] playwright not installed, falling back to requests login")
            return False

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()

                print(f"[MoodleScraper] Navigating to {self.base_url} ...")
                page.goto(self.base_url, timeout=20000)

                # Find the TUM SSO login button — Moodle shows a "TUM Login" link
                # or a standard Shibboleth "Login" button pointing to auth/shibboleth
                sso_selectors = [
                    "a[href*='shibboleth']",
                    "a:has-text('TUM')",
                    "a:has-text('Anmelden')",
                    "a:has-text('Login')",
                    "button:has-text('Login')",
                ]
                clicked = False
                for sel in sso_selectors:
                    try:
                        page.wait_for_selector(sel, timeout=3000)
                        page.click(sel)
                        clicked = True
                        print(f"[MoodleScraper] Clicked SSO button: {sel}")
                        break
                    except PWTimeout:
                        continue

                if not clicked:
                    print("[MoodleScraper] SSO button not found")
                    browser.close()
                    return False

                # Wait for redirect to SSO / login page
                page.wait_for_url("**/login**", timeout=15000)
                print(f"[MoodleScraper] On SSO page: {page.url}")

                # Fill username
                for sel in ["#username", "input[name='username']", "input[type='text']"]:
                    try:
                        page.wait_for_selector(sel, timeout=3000)
                        page.fill(sel, self.username)
                        break
                    except PWTimeout:
                        continue

                # Fill password
                for sel in ["#password", "input[name='password']", "input[type='password']"]:
                    try:
                        page.wait_for_selector(sel, timeout=3000)
                        page.fill(sel, self.password)
                        break
                    except PWTimeout:
                        continue

                # Submit
                for sel in ["button[type='submit']", "input[type='submit']", "#loginButton"]:
                    try:
                        page.wait_for_selector(sel, timeout=3000)
                        page.click(sel)
                        break
                    except PWTimeout:
                        continue

                # Wait for redirect back to Moodle
                page.wait_for_url(f"**{self.base_url.split('/')[-1]}**", timeout=20000)
                final_url = page.url
                print(f"[MoodleScraper] Redirected to: {final_url}")

                if "login" in final_url.lower() or "error" in final_url.lower():
                    print("[MoodleScraper] Still on login page — credentials may be wrong")
                    browser.close()
                    return False

                # Transfer cookies to requests.Session
                for cookie in context.cookies():
                    self.session.cookies.set(
                        cookie["name"],
                        cookie["value"],
                        domain=cookie.get("domain", ""),
                    )

                browser.close()
                self._logged_in = True
                print("[MoodleScraper] Playwright SSO login succeeded")
                return True

        except Exception as exc:
            print(f"[MoodleScraper] Playwright login error: {exc}")
            return False

    def _login_requests_fallback(self) -> bool:
        """Fallback: authenticate via plain HTTP POST to the Moodle login form.

        Does NOT handle Shibboleth/SAML redirects — only works if Moodle allows
        direct form login (i.e. non-SSO accounts).

        Returns:
            True if the response contains no login-error indicator, False otherwise.
        """
        try:
            login_url = f"{self.base_url}/login/index.php"
            resp = self.session.get(login_url, timeout=10)
            soup = BeautifulSoup(resp.text, "lxml")
            token_input = soup.find("input", {"name": "logintoken"})
            token = token_input["value"] if token_input else ""

            payload = {
                "username": self.username,
                "password": self.password,
                "logintoken": token,
            }
            resp = self.session.post(login_url, data=payload, timeout=10)
            success = "loginerrormessage" not in resp.text
            if success:
                self._logged_in = True
                print("[MoodleScraper] Requests fallback login succeeded")
            else:
                print("[MoodleScraper] Requests fallback login failed (error in response)")
            return success
        except Exception as exc:
            print(f"[MoodleScraper] Requests fallback login error: {exc}")
            return False

    def login(self) -> bool:
        """Authenticate against Moodle: try Playwright SSO first, fall back to requests.

        Returns:
            True if either method succeeds, False otherwise.
        """
        if self.login_playwright():
            return True
        print("[MoodleScraper] Playwright failed, trying requests fallback ...")
        return self._login_requests_fallback()

    # ------------------------------------------------------------------
    # Calendar deadlines
    # ------------------------------------------------------------------

    def get_deadlines_from_calendar(self) -> list[dict]:
        """Fetch upcoming assignment and quiz deadlines from the Moodle dashboard.

        Logs in if needed, then parses the timeline / upcoming-events block on
        the dashboard page (/my/).  Falls back to get_sample_data() on any error.

        Returns:
            List of dicts with keys: title, course, deadline_date, source.
        """
        if not self._logged_in:
            if not self.login():
                print("[MoodleScraper] Login failed — returning sample deadline data")
                return self._sample_deadlines()

        try:
            dashboard_url = f"{self.base_url}/my/"
            print(f"[MoodleScraper] Fetching dashboard: {dashboard_url}")
            resp = self.session.get(dashboard_url, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")

            deadlines: list[dict] = []

            # Moodle 4.x: timeline events are in .block_myoverview or
            # data-eventtype list items inside .timeline-event-list
            event_items = soup.select(
                ".timeline-event-list li, "
                ".block_myoverview .event, "
                "[data-region='event-list-item'], "
                ".calendarwrapper .event"
            )

            for item in event_items:
                title_el = item.select_one(".event-name, .name, a")
                date_el = item.select_one("time, .date, [data-eventtype]")
                course_el = item.select_one(".course-name, .coursename, .text-truncate")

                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                course = course_el.get_text(strip=True) if course_el else "Unknown course"

                # Parse date from <time datetime="..."> or text
                deadline_date = ""
                if date_el:
                    dt_attr = date_el.get("datetime", "")
                    if dt_attr:
                        try:
                            deadline_date = datetime.fromisoformat(dt_attr[:10]).strftime("%Y-%m-%d")
                        except ValueError:
                            pass
                    if not deadline_date:
                        raw = date_el.get_text(strip=True)
                        for fmt in ("%d %B %Y", "%d. %B %Y", "%Y-%m-%d"):
                            try:
                                deadline_date = datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
                                break
                            except ValueError:
                                continue

                if title and deadline_date:
                    deadlines.append({
                        "title": title,
                        "course": course,
                        "deadline_date": deadline_date,
                        "source": "moodle",
                    })

            if deadlines:
                print(f"[MoodleScraper] Parsed {len(deadlines)} deadline(s) from dashboard")
                return deadlines

            print("[MoodleScraper] No timeline events found in dashboard HTML — using sample data")
            return self._sample_deadlines()

        except Exception as exc:
            print(f"[MoodleScraper] get_deadlines_from_calendar failed: {exc}")
            return self._sample_deadlines()

    # ------------------------------------------------------------------
    # Course files
    # ------------------------------------------------------------------

    def get_course_files(self, course_id: str) -> list[dict]:
        """Return a list of file metadata dicts for *course_id*.

        Navigates to the course page and scrapes pluginfile / resource links.
        Falls back to get_sample_data() on error.

        Args:
            course_id: Moodle numeric course ID.

        Returns:
            List of dicts with keys: name, url, type.
        """
        if not self._logged_in:
            self.login()

        try:
            url = f"{self.base_url}/course/view.php?id={course_id}"
            resp = self.session.get(url, timeout=10)
            soup = BeautifulSoup(resp.text, "lxml")

            files = []
            for link in soup.select("a[href*='pluginfile.php'], a[href*='mod/resource']"):
                href = link.get("href", "")
                name = link.get_text(strip=True)
                ext = Path(href).suffix.lower()
                file_type = ext.lstrip(".") if ext else "unknown"
                if name:
                    files.append({"name": name, "url": href, "type": file_type})
            return files
        except Exception as exc:
            print(f"[MoodleScraper] get_course_files failed: {exc}")
            return []

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def _extract_text(self, file_path: str) -> str:
        """Extract text from a local PDF or text file using PyMuPDF, falling back to plain read."""
        try:
            import fitz
            doc = fitz.open(file_path)
            text = "\n".join(page.get_text() for page in doc)
            doc.close()
            return text
        except ImportError:
            pass
        except Exception as exc:
            print(f"[MoodleScraper] PyMuPDF failed for {file_path}: {exc}")
        try:
            with open(file_path, "r", errors="ignore") as fh:
                return fh.read()
        except Exception as exc:
            return f"[Could not read: {exc}]"

    def download_pdf(self, url: str, save_path: str) -> str:
        """Download a PDF from *url* and save to *save_path*.

        Args:
            url: Direct download URL for the PDF.
            save_path: Local file path to write to.

        Returns:
            The local path of the saved file, or empty string on failure.
        """
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        try:
            resp = self.session.get(url, timeout=30, stream=True)
            resp.raise_for_status()
            with open(save_path, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=8192):
                    fh.write(chunk)
            return save_path
        except Exception as exc:
            print(f"[MoodleScraper] download_pdf failed: {exc}")
            return ""

    # ------------------------------------------------------------------
    # Demo / mock data
    # ------------------------------------------------------------------

    def _sample_deadlines(self) -> list[dict]:
        """Return empty list — never show fake deadlines."""
        return []

    def get_sample_data(self) -> list[dict]:
        """Return mock course files for demo purposes when auth is unavailable."""
        return [
            {
                "name": "Analysis_2_Lecture_01.pdf",
                "url": f"{self.base_url}/sample/analysis2_l01.pdf",
                "type": "pdf",
            },
            {
                "name": "Analysis_2_Exercises_Sheet_03.pdf",
                "url": f"{self.base_url}/sample/analysis2_ex03.pdf",
                "type": "pdf",
            },
            {
                "name": "Analysis_2_Past_Exam_SS2024.pdf",
                "url": f"{self.base_url}/sample/analysis2_exam_ss2024.pdf",
                "type": "pdf",
            },
            {
                "name": "Linear_Algebra_Summary.pdf",
                "url": f"{self.base_url}/sample/linalg_summary.pdf",
                "type": "pdf",
            },
        ]


if __name__ == "__main__":
    scraper = MoodleScraper()
    print("Testing Moodle login and deadline fetch ...")
    deadlines = scraper.get_deadlines_from_calendar()
    print(f"Got {len(deadlines)} deadline(s):")
    for d in deadlines:
        print(f"  [{d['deadline_date']}] {d['title']} — {d['course']}")
