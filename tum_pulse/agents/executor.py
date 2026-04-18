"""ExecutorAgent: ZHS sport registration via the ZHSConnector."""

import os
import re
from pathlib import Path

from tum_pulse.config import DATA_DIR, ZHS_PASSWORD, ZHS_URL, ZHS_USERNAME
from tum_pulse.connectors.zhs import ZHSConnector, SportSlot

# Apply WSL2 Playwright lib path fix
_LOCAL_LIBS = os.path.expanduser("~/.local/usr/lib/x86_64-linux-gnu")
if os.path.isdir(_LOCAL_LIBS):
    os.environ["LD_LIBRARY_PATH"] = (
        _LOCAL_LIBS + ":" + os.environ.get("LD_LIBRARY_PATH", "")
    )

Path(DATA_DIR).mkdir(parents=True, exist_ok=True)


class ExecutorAgent:
    """Automates ZHS sport slot search and registration via Playwright."""

    def __init__(self) -> None:
        self.connector = ZHSConnector()
        self.username = ZHS_USERNAME
        self.password = ZHS_PASSWORD
        self.screenshot_path = str(Path(DATA_DIR) / "zhs_screenshot.png")

    def search_sports(self, query: str) -> list[SportSlot]:
        """Search ZHS for sport courses matching query. Returns list of SportSlot."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                logged_in = self.connector.login(page, self.username, self.password)
                if not logged_in:
                    print("[ExecutorAgent] ZHS login failed")
                    return []
                return self.connector.search_sports(page, query)
            except Exception as exc:
                print(f"[ExecutorAgent] Search error: {exc}")
                return []
            finally:
                browser.close()

    def register_zhs(self, sport: str, date: str = "") -> str:
        """Search for sport, optionally filter by date, register for first available slot."""
        result = self.connector.run(
            self.username,
            self.password,
            sport,
            register_first=True,
        )

        if not result["logged_in"]:
            return f"❌ ZHS login failed. Check credentials in .env (ZHS_USERNAME / ZHS_PASSWORD).\n{result['message']}"

        slots = result["slots"]
        if not slots:
            return (
                f"🔍 Logged in to ZHS successfully, but no courses found for '{sport}'.\n"
                "Try a different search term (e.g. 'Badminton', 'Yoga', 'Schwimmen')."
            )

        lines = [f"✅ Logged in to ZHS. Found {len(slots)} slot(s) for '{sport}':\n"]
        for i, slot in enumerate(slots[:5], 1):
            lines.append(
                f"  {i}. **{slot.title}**  |  {slot.day} {slot.time}  |  "
                f"{slot.location}  |  {slot.spots_left} spots left"
            )

        if result.get("registered"):
            reg = result["registered"]
            if reg["screenshot"]:
                img_path = str(Path(DATA_DIR) / "zhs_registration.png")
                with open(img_path, "wb") as f:
                    f.write(reg["screenshot"])
            status = "✅" if reg["success"] else "⚠️"
            lines.append(f"\n{status} **Registration attempt:** {reg['message']}")
        else:
            lines.append(f"\n{result['message']}")

        return "\n".join(lines)

    def run(self, task: str) -> str:
        """Parse natural-language task and dispatch to the right method."""
        task_lower = task.lower()

        if any(kw in task_lower for kw in ("zhs", "sport", "register", "register", "course", "gym", "swim")):
            # Extract sport name after "for" keyword or use full task
            sport = "sport"
            date = ""
            words = task.split()
            for i, word in enumerate(words):
                if word.lower() == "for" and i + 1 < len(words):
                    sport = " ".join(words[i + 1:]).split(" on ")[0].strip(".,")
                if word.lower() == "on" and i + 1 < len(words):
                    date = words[i + 1].strip(".,")
            return self.register_zhs(sport, date)

        return f"[ExecutorAgent] Task not recognised: '{task}'. Supported: ZHS sport registration."


if __name__ == "__main__":
    agent = ExecutorAgent()
    result = agent.run("register for Badminton at ZHS")
    print(result)
