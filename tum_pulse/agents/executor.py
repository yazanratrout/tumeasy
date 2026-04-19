"""ExecutorAgent: ZHS sport registration, TUMonline course reg/dereg, Moodle forum posting."""

import os
import re
from pathlib import Path

from tum_pulse.config import (
    DATA_DIR,
    TUM_PASSWORD,
    TUM_USERNAME,
    ZHS_PASSWORD,
    ZHS_URL,
    ZHS_USERNAME,
)
from tum_pulse.connectors.zhs import ZHSConnector, SportSlot

# Apply WSL2 Playwright lib path fix
_LOCAL_LIBS = os.path.expanduser("~/.local/usr/lib/x86_64-linux-gnu")
if os.path.isdir(_LOCAL_LIBS):
    os.environ["LD_LIBRARY_PATH"] = (
        _LOCAL_LIBS + ":" + os.environ.get("LD_LIBRARY_PATH", "")
    )

Path(DATA_DIR).mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Keyword sets for intent disambiguation
# ---------------------------------------------------------------------------

_ZHS_KEYWORDS   = {"zhs", "sport", "gym", "yoga", "badminton", "tennis",
                    "swimming", "schwimmen", "fitness", "volleyball", "basketball",
                    "bouldern", "klettern", "climbing", "pilates", "aerobic"}
_REG_KEYWORDS   = {"register", "enroll", "sign up", "anmelden", "join", "book"}
_DEREG_KEYWORDS = {"deregister", "drop", "unenroll", "abmelden", "withdraw", "cancel", "leave"}
_COURSE_KEYWORDS = {"lecture", "seminar", "lab", "practical", "course", "lv", "vorlesung", "übung"}
_FORUM_KEYWORDS  = {"forum", "post", "write", "message", "discussion", "announce",
                    "studying group", "study group", "moodle forum"}


def _is_zhs_intent(text: str) -> bool:
    words = set(re.findall(r"\w+", text.lower()))
    return bool(words & _ZHS_KEYWORDS)


def _is_forum_intent(text: str) -> bool:
    return any(kw in text.lower() for kw in _FORUM_KEYWORDS)


def _is_dereg_intent(text: str) -> bool:
    return any(kw in text.lower() for kw in _DEREG_KEYWORDS)


def _is_academic_reg_intent(text: str) -> bool:
    lower = text.lower()
    has_reg = any(kw in lower for kw in _REG_KEYWORDS)
    is_zhs  = _is_zhs_intent(lower)
    return has_reg and not is_zhs


def _extract_quoted_or_after(text: str, markers: list[str]) -> str:
    """Extract quoted string or text following a marker keyword."""
    # Try quoted first
    m = re.search(r'["\']([^"\']+)["\']', text)
    if m:
        return m.group(1).strip()
    # After marker keyword
    lower = text.lower()
    for marker in markers:
        idx = lower.find(marker)
        if idx != -1:
            after = text[idx + len(marker):].strip().split("\n")[0].strip(".,!?")
            if after:
                return after
    return text.strip()


class ExecutorAgent:
    """Automates ZHS sport registration, TUMonline course enrollment, and Moodle forum posting."""

    def __init__(self) -> None:
        self.zhs      = ZHSConnector()
        self.zhs_user = ZHS_USERNAME
        self.zhs_pass = ZHS_PASSWORD
        self.tum_user = TUM_USERNAME
        self.tum_pass = TUM_PASSWORD
        self.screenshot_path = str(Path(DATA_DIR) / "zhs_screenshot.png")

    # ── ZHS sports ─────────────────────────────────────────────────────────

    def search_sports(self, query: str) -> list[SportSlot]:
        """Search ZHS for sport courses matching query."""
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                if not self.zhs.login(page, self.zhs_user, self.zhs_pass):
                    return []
                return self.zhs.search_sports(page, query)
            except Exception as exc:
                print(f"[ExecutorAgent] ZHS search error: {exc}")
                return []
            finally:
                browser.close()

    def register_zhs(self, sport: str, date: str = "") -> str:
        """Search for sport, register for first available slot."""
        result = self.zhs.run(self.zhs_user, self.zhs_pass, sport, register_first=True)

        if not result["logged_in"]:
            return f"❌ ZHS login failed. Check ZHS_USERNAME / ZHS_PASSWORD in .env.\n{result['message']}"

        slots = result["slots"]
        if not slots:
            return (
                f"🔍 Logged in to ZHS — no courses found for '{sport}'.\n"
                "Try a different keyword (e.g. 'Badminton', 'Yoga', 'Schwimmen')."
            )

        lines = [f"✅ Logged into ZHS. Found {len(slots)} slot(s) for **{sport}**:\n"]
        for i, slot in enumerate(slots[:5], 1):
            lines.append(
                f"  {i}. **{slot.title}**  |  {slot.day} {slot.time}  |  "
                f"{slot.location}  |  {slot.spots_left} spots left"
            )

        if result.get("registered"):
            reg = result["registered"]
            if reg.get("screenshot"):
                img_path = str(Path(DATA_DIR) / "zhs_registration.png")
                with open(img_path, "wb") as f:
                    f.write(reg["screenshot"])
            status = "✅" if reg["success"] else "⚠️"
            lines.append(f"\n{status} **Registration:** {reg['message']}")
        else:
            lines.append(f"\n{result['message']}")

        return "\n".join(lines)

    # ── TUMonline academic course registration ──────────────────────────────

    def register_academic_course(self, course_name: str) -> str:
        """Register for a TUMonline academic course by name."""
        from tum_pulse.connectors.tumonline import TUMonlineConnector

        if not self.tum_user or not self.tum_pass:
            return "❌ TUM credentials not found. Sign in with 'Remember credentials' enabled."

        connector = TUMonlineConnector()
        result = connector.scrape_register_course(self.tum_user, self.tum_pass, course_name)

        if result["success"]:
            return (
                f"✅ **Course registration successful!**\n\n"
                f"📚 {result['message']}\n\n"
                f"Check TUMonline → My Courses to confirm."
            )
        return (
            f"⚠️ **Course registration attempt for '{result['course']}':**\n\n"
            f"{result['message']}"
        )

    def deregister_academic_course(self, course_name: str) -> str:
        """Deregister from a TUMonline academic course by name."""
        from tum_pulse.connectors.tumonline import TUMonlineConnector

        if not self.tum_user or not self.tum_pass:
            return "❌ TUM credentials not found."

        connector = TUMonlineConnector()
        result = connector.scrape_deregister_course(self.tum_user, self.tum_pass, course_name)

        if result["success"]:
            return (
                f"✅ **Deregistration successful!**\n\n"
                f"📚 {result['message']}\n\n"
                f"Check TUMonline → My Courses to confirm."
            )
        return (
            f"⚠️ **Deregistration attempt for '{result['course']}':**\n\n"
            f"{result['message']}"
        )

    # ── Moodle forum posting ────────────────────────────────────────────────

    def post_forum(self, course_name: str, message: str, subject: str = "") -> str:
        """Post a message to the first forum of a Moodle course."""
        from tum_pulse.connectors.moodle import MoodleConnector

        if not self.tum_user or not self.tum_pass:
            return "❌ TUM credentials not found."

        if not subject:
            subject = message[:60].rstrip() + ("…" if len(message) > 60 else "")

        connector = MoodleConnector()
        result = connector.find_and_post_forum(
            self.tum_user, self.tum_pass, course_name, subject, message
        )

        if result["success"]:
            return (
                f"✅ **Forum post published!**\n\n"
                f"📘 Course: **{result.get('course', course_name)}**\n"
                f"💬 Forum: {result.get('forum', 'General')}\n"
                f"📝 Subject: {subject}\n\n"
                f"{result['message']}"
            )
        return (
            f"⚠️ **Forum post failed for '{course_name}':**\n\n"
            f"{result['message']}"
        )

    # ── Unified run() ───────────────────────────────────────────────────────

    def run(self, task: str, context: dict | None = None) -> str:
        """Parse the natural-language task and dispatch to the right method."""
        task_lower = task.lower()

        # Forum post (highest specificity first)
        if _is_forum_intent(task_lower):
            # Extract: course name and message
            course = _extract_quoted_or_after(task, ["in ", "for ", "to "])
            # Message is after "post", "write", "say"
            msg_match = re.search(r'(?:post|write|say|message)[:\s]+(.+)', task, re.IGNORECASE)
            message = msg_match.group(1).strip() if msg_match else task
            subject_match = re.search(r'(?:subject|title)[:\s]+["\']?([^"\']+)["\']?', task, re.IGNORECASE)
            subject = subject_match.group(1).strip() if subject_match else ""
            return self.post_forum(course, message, subject)

        # Academic course deregistration
        if _is_dereg_intent(task_lower):
            course = _extract_quoted_or_after(task, ["from ", "drop ", "deregister ", "abmelden ", "unenroll from "])
            return self.deregister_academic_course(course)

        # Academic course registration (must not be ZHS sport)
        if _is_academic_reg_intent(task_lower):
            course = _extract_quoted_or_after(task, ["for ", "in ", "anmelden ", "enroll in ", "register for "])
            return self.register_academic_course(course)

        # ZHS sport registration
        if _is_zhs_intent(task_lower) or any(kw in task_lower for kw in ("sport", "zhs", "register")):
            sport = "sport"
            date  = ""
            words = task.split()
            for i, word in enumerate(words):
                if word.lower() == "for" and i + 1 < len(words):
                    sport = " ".join(words[i + 1:]).split(" on ")[0].strip(".,")
                if word.lower() == "on" and i + 1 < len(words):
                    date = words[i + 1].strip(".,")
            return self.register_zhs(sport, date)

        return (
            f"[ExecutorAgent] Task not recognised: '{task}'.\n"
            "Supported actions:\n"
            "• ZHS sport booking (e.g. 'register me for yoga at ZHS')\n"
            "• TUMonline course registration (e.g. 'register for Machine Learning')\n"
            "• TUMonline course deregistration (e.g. 'drop Advanced ML')\n"
            "• Moodle forum post (e.g. 'post in forum for ML: Has anyone solved HW3?')"
        )


if __name__ == "__main__":
    agent = ExecutorAgent()
    print(agent.run("register for Badminton at ZHS"))
