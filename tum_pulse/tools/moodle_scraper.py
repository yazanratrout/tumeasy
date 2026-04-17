"""Moodle scraper: login, list course files, download PDFs."""

import os
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

from tum_pulse.config import DATA_DIR, MOODLE_BASE_URL, TUM_PASSWORD, TUM_USERNAME


class MoodleScraper:
    """Handles authenticated access to TUM Moodle for file retrieval."""

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

    def login(self) -> bool:
        """Authenticate against Moodle using the standard login form.

        Returns:
            True if login succeeded, False otherwise.

        TODO: Real credentials are required. TUM SSO may redirect through
              Shibboleth; handle the SAML redirect chain if needed.
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
            self._logged_in = "loginerrormessage" not in resp.text
            return self._logged_in
        except Exception as exc:
            print(f"[MoodleScraper] Login failed: {exc}")
            return False

    # ------------------------------------------------------------------
    # Course files
    # ------------------------------------------------------------------

    def get_course_files(self, course_id: str) -> list[dict]:
        """Return a list of file metadata dicts for *course_id*.

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
                files.append({"name": name, "url": href, "type": file_type})
            return files
        except Exception as exc:
            print(f"[MoodleScraper] get_course_files failed: {exc}")
            return self.get_sample_data()

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download_pdf(self, url: str, save_path: str) -> str:
        """Download a PDF from *url* and save to *save_path*.

        Args:
            url: Direct download URL for the PDF.
            save_path: Local file path to write to.

        Returns:
            The local path of the saved file.
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
    print("Sample data:", scraper.get_sample_data())
