"""ExecutorAgent: Playwright browser automation for ZHS sport registration."""

import asyncio
import os
from pathlib import Path
from typing import Optional

from tum_pulse.config import DATA_DIR, ZHS_PASSWORD, ZHS_URL, ZHS_USERNAME


class ExecutorAgent:
    """Automates browser interactions, primarily ZHS sport slot registration."""

    def __init__(self) -> None:
        """Initialise executor with ZHS credentials from config."""
        self.zhs_url = ZHS_URL
        self.username = ZHS_USERNAME
        self.password = ZHS_PASSWORD
        self.screenshot_path = str(Path(DATA_DIR) / "zhs_screenshot.png")
        Path(DATA_DIR).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # ZHS registration
    # ------------------------------------------------------------------

    async def _register_zhs_async(self, sport: str, date: str) -> str:
        """Async Playwright implementation for ZHS registration.

        Args:
            sport: Sport name to register for (e.g. "Badminton").
            date: Desired date string (e.g. "2026-05-10").

        Returns:
            Status message.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return "[ExecutorAgent] playwright not installed. Run: pip install playwright && playwright install"

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                await page.goto(self.zhs_url, timeout=15000)

                # TODO: Login step
                # await page.click("text=Anmelden")
                # await page.fill("#username", self.username)
                # await page.fill("#password", self.password)
                # await page.click("button[type='submit']")
                # await page.wait_for_navigation()

                # TODO: Navigate to sport catalogue and search for `sport`
                # await page.goto(f"{self.zhs_url}/sportarten")
                # await page.fill("#search", sport)
                # await page.click("button[type='submit']")

                # TODO: Find slot for `date` and click register
                # slots = await page.query_selector_all(".slot-row")
                # for slot in slots:
                #     slot_date = await slot.query_selector(".slot-date")
                #     if date in await slot_date.inner_text():
                #         await slot.click("button.register")
                #         break

                await page.screenshot(path=self.screenshot_path)
                await browser.close()

                return (
                    f"Opened ZHS page for '{sport}' on {date} — "
                    f"manual registration step ready. Screenshot saved to {self.screenshot_path}"
                )

            except Exception as exc:
                await browser.close()
                return f"[ExecutorAgent] Browser error: {exc}"

    def register_zhs(self, sport: str, date: str) -> str:
        """Register for a ZHS sport slot (synchronous wrapper for Streamlit).

        Args:
            sport: Sport name to register for.
            date: Target date in any human-readable format.

        Returns:
            Status message describing the outcome.
        """
        return asyncio.run(self._register_zhs_async(sport, date))

    # ------------------------------------------------------------------
    # Generic task dispatcher
    # ------------------------------------------------------------------

    def run(self, task: str) -> str:
        """Parse a natural-language task and dispatch to the right method.

        Args:
            task: Free-text instruction, e.g. "register for Badminton on 2026-05-10".

        Returns:
            Execution result string.
        """
        task_lower = task.lower()

        if "zhs" in task_lower or "sport" in task_lower or "register" in task_lower:
            # Naive extraction: look for sport name and date
            sport = "Unknown sport"
            date = "Unknown date"

            words = task.split()
            for i, word in enumerate(words):
                if word.lower() == "for" and i + 1 < len(words):
                    sport = words[i + 1].strip(".,")
                if word.lower() == "on" and i + 1 < len(words):
                    date = words[i + 1].strip(".,")

            return self.register_zhs(sport, date)

        return f"[ExecutorAgent] Task not recognised: '{task}'. Supported: ZHS sport registration."


if __name__ == "__main__":
    agent = ExecutorAgent()
    result = agent.run("register for Badminton on 2026-05-10")
    print(result)
