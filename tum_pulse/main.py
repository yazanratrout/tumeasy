"""TUM Pulse — Streamlit chat interface entry point."""

import json
import threading

import streamlit as st

from tum_pulse.agents.orchestrator import run as orchestrator_run
from tum_pulse.agents.watcher import WatcherAgent
from tum_pulse.memory.database import SQLiteMemory

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="TUM Pulse",
    page_icon="🎓",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------

if "messages" not in st.session_state:
    st.session_state.messages = []

if "last_agent" not in st.session_state:
    st.session_state.last_agent = ""

if "toasted_alert_ids" not in st.session_state:
    st.session_state.toasted_alert_ids = set()

# ---------------------------------------------------------------------------
# Startup: refresh deadlines in background, then surface any pending alerts
# ---------------------------------------------------------------------------

def _background_scrape() -> None:
    try:
        WatcherAgent().run()
    except Exception:
        pass

if "startup_done" not in st.session_state:
    st.session_state.startup_done = True
    threading.Thread(target=_background_scrape, daemon=True).start()

_db = SQLiteMemory()
for _alert in _db.get_pending_alerts():
    if _alert["id"] not in st.session_state.toasted_alert_ids:
        st.toast(_alert["message"], icon="⚠️")
        _db.mark_alert_sent(_alert["id"])
        st.session_state.toasted_alert_ids.add(_alert["id"])

# ---------------------------------------------------------------------------
# Sidebar — student profile
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("TUM Pulse 🎓")
    st.markdown("**Your Campus Co-Pilot**")
    st.divider()

    student_name = st.text_input("Your Name", placeholder="Max Mustermann")

    default_profile = json.dumps(
        {
            "grades": {
                "Linear Algebra": 1.7,
                "Analysis": 2.3,
                "Algorithms and Data Structures": 2.0,
                "Probability Theory": 2.7,
            },
            "courses": [
                "Introduction to Programming",
                "Linear Algebra",
                "Analysis",
                "Algorithms and Data Structures",
            ],
        },
        indent=2,
    )
    profile_json = st.text_area(
        "Grades & Completed Courses (JSON)",
        value=default_profile,
        height=240,
    )

    if st.button("Save Profile", use_container_width=True):
        try:
            profile = json.loads(profile_json)
            db = SQLiteMemory()
            if "grades" in profile:
                db.save_profile("grades", profile["grades"])
            if "courses" in profile:
                db.save_profile("courses", profile["courses"])
            if student_name:
                db.save_profile("name", student_name)
            st.success("Profile saved!")
        except json.JSONDecodeError:
            st.error("Invalid JSON — please check your input.")

    st.divider()

    st.subheader("🔔 Upcoming Alerts")
    _imminent = SQLiteMemory().get_upcoming_deadlines(days=2)
    if _imminent:
        for _dl in _imminent:
            st.warning(f"**{_dl['title']}**  \n{_dl['course']} — {_dl['deadline_date']}")
    else:
        st.caption("No deadlines in the next 2 days.")

    st.divider()
    st.caption("Powered by Amazon Bedrock + LangGraph")

# ---------------------------------------------------------------------------
# Main area header
# ---------------------------------------------------------------------------

st.title("TUM Pulse 🎓")
st.caption("Ask me about deadlines, electives, ZHS registration, or exam prep.")

# ---------------------------------------------------------------------------
# Quick-start example prompts
# ---------------------------------------------------------------------------

col1, col2, col3 = st.columns(3)

with col1:
    if st.button("📅 What deadlines do I have this week?", use_container_width=True):
        st.session_state.quick_prompt = "What deadlines do I have this week?"

with col2:
    if st.button("📚 Recommend me elective courses", use_container_width=True):
        st.session_state.quick_prompt = "Recommend me elective courses"

with col3:
    if st.button("🧠 Help me pass Analysis 2", use_container_width=True):
        st.session_state.quick_prompt = "Help me pass Analysis 2"

st.divider()

# ---------------------------------------------------------------------------
# Chat history display
# ---------------------------------------------------------------------------

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ---------------------------------------------------------------------------
# Agent status indicator
# ---------------------------------------------------------------------------

_AGENT_LABELS: dict[str, str] = {
    "deadlines": "📅 Watcher Agent",
    "zhs_registration": "🏃 Executor Agent",
    "elective_advice": "📚 Advisor Agent",
    "exam_plan": "🧠 Learning Buddy",
    "general": "💬 General Assistant",
    "error": "⚠️ Error",
    "": "",
}

if st.session_state.last_agent:
    label = _AGENT_LABELS.get(st.session_state.last_agent, st.session_state.last_agent)
    st.caption(f"Last activated: **{label}**")

# ---------------------------------------------------------------------------
# Chat input — handle quick prompt or typed message
# ---------------------------------------------------------------------------

user_input: str = ""

quick = st.session_state.pop("quick_prompt", None)
if quick:
    user_input = quick

typed = st.chat_input("Ask TUM Pulse anything...")
if typed:
    user_input = typed

if user_input:
    # Show user message immediately
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # Run orchestrator
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            response, agent_called = orchestrator_run(
                user_input,
                thread_id=student_name or "default",
            )
        st.markdown(response)
        st.session_state.last_agent = agent_called

    st.session_state.messages.append({"role": "assistant", "content": response})
    st.rerun()
