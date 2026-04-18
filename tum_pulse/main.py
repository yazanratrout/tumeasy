"""TUM Pulse — Streamlit chat interface entry point."""

import json
import threading
from datetime import datetime
from pathlib import Path

import pandas as pd
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

st.markdown("""
<style>
[data-testid="stSidebar"] { background: linear-gradient(180deg, #0d2a6e 0%, #1a3a8f 100%); }
[data-testid="stSidebar"] * { color: white !important; }
[data-testid="stSidebar"] input { color: #111 !important; }
[data-testid="stSidebar"] textarea { color: #111 !important; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

if "messages" not in st.session_state:
    st.session_state.messages = []
if "last_agent" not in st.session_state:
    st.session_state.last_agent = ""
if "toasted_alert_ids" not in st.session_state:
    st.session_state.toasted_alert_ids = set()
if "watcher_status" not in st.session_state:
    st.session_state.watcher_status = {}
if "last_refreshed" not in st.session_state:
    st.session_state.last_refreshed = None
if "zhs_slots" not in st.session_state:
    st.session_state.zhs_slots = []
if "zhs_search_done" not in st.session_state:
    st.session_state.zhs_search_done = False
if "zhs_reg_result" not in st.session_state:
    st.session_state.zhs_reg_result = None

# ---------------------------------------------------------------------------
# Startup: seed courses + background scrape + surface pending alerts
# ---------------------------------------------------------------------------

_DEFAULT_COURSES = [
    "Introduction to Programming",
    "Linear Algebra",
    "Analysis",
    "Algorithms and Data Structures",
]

_db = SQLiteMemory()

if not _db.get_profile("courses"):
    _db.save_profile("courses", _DEFAULT_COURSES)


def _background_scrape() -> None:
    try:
        WatcherAgent().run()
    except Exception:
        pass


if "startup_done" not in st.session_state:
    st.session_state.startup_done = True
    threading.Thread(target=_background_scrape, daemon=True).start()

for _alert in _db.get_pending_alerts():
    if _alert["id"] not in st.session_state.toasted_alert_ids:
        st.toast(_alert["message"], icon="⚠️")
        _db.mark_alert_sent(_alert["id"])
        st.session_state.toasted_alert_ids.add(_alert["id"])

# ---------------------------------------------------------------------------
# Sidebar — student profile
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## 🎓 TUM Pulse")
    st.markdown("*Your Campus Co-Pilot*")
    st.divider()

    student_name = st.text_input("Your Name", placeholder="Max Mustermann")

    _saved_courses = _db.get_profile("courses") or _DEFAULT_COURSES
    default_profile = json.dumps(
        {
            "grades": {
                "Linear Algebra": 1.7,
                "Analysis": 2.3,
                "Algorithms and Data Structures": 2.0,
                "Probability Theory": 2.7,
            },
            "courses": _saved_courses,
        },
        indent=2,
    )
    profile_json = st.text_area(
        "Grades & Completed Courses (JSON)",
        value=default_profile,
        height=200,
    )
    st.caption("💡 Your enrolled courses are synced automatically from TUMonline.")

    if st.button("💾 Save Profile", use_container_width=True):
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

    if st.session_state.watcher_status:
        st.markdown("**System Status**")
        for src, state in st.session_state.watcher_status.items():
            icon = "🟢" if state == "live" else "🟠" if state == "mock" else "⚫"
            st.caption(f"{icon} {src.title()}: {state}")
        st.divider()

    st.caption("Powered by Amazon Bedrock + LangGraph")

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab_chat, tab_deadlines, tab_zhs, tab_about = st.tabs(
    ["💬 Chat", "📅 Deadlines", "🏃 ZHS Sports", "ℹ️ About"]
)

# ===========================================================================
# TAB 1 — Chat
# ===========================================================================

with tab_chat:
    st.title("TUM Pulse 🎓")
    st.caption("Ask me about deadlines, electives, ZHS registration, or exam prep.")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("📅 Deadlines this week", use_container_width=True):
            st.session_state.quick_prompt = "What deadlines do I have this week?"
    with col2:
        if st.button("📚 Recommend electives", use_container_width=True):
            st.session_state.quick_prompt = "Recommend me elective courses"
    with col3:
        if st.button("🧠 Help pass Analysis 2", use_container_width=True):
            st.session_state.quick_prompt = "Help me pass Analysis 2"
    with col4:
        if st.button("🏃 Book ZHS Badminton", use_container_width=True):
            st.session_state.quick_prompt = "Register me for Badminton at ZHS"

    st.divider()

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

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

    user_input: str = ""
    quick = st.session_state.pop("quick_prompt", None)
    if quick:
        user_input = quick

    typed = st.chat_input("Ask TUM Pulse anything...")
    if typed:
        user_input = typed

    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                response, agent_called = orchestrator_run(
                    user_input, thread_id=student_name or "default"
                )
            st.markdown(response)
            st.session_state.last_agent = agent_called
        st.session_state.messages.append({"role": "assistant", "content": response})
        st.rerun()

# ===========================================================================
# TAB 2 — Deadlines dashboard
# ===========================================================================

with tab_deadlines:
    st.header("Upcoming Deadlines")
    st.caption("Pulls live data from TUMonline, Moodle, and Confluence.")

    col_btn, col_status = st.columns([2, 5])

    with col_btn:
        refresh = st.button("🔄 Refresh from TUM systems", use_container_width=True)

    if refresh:
        with st.spinner("Logging in and scraping TUMonline, Moodle, Confluence..."):
            agent = WatcherAgent()
            agent.run()
            st.session_state.watcher_status = agent.status
            st.session_state.last_refreshed = datetime.now().strftime("%H:%M:%S")
        st.success("Done!")
        st.rerun()

    with col_status:
        if st.session_state.watcher_status:
            _BADGE = {
                "live":    ":green[● live]",
                "mock":    ":orange[● mock]",
                "skipped": ":gray[● skipped]",
                "not run": ":gray[○ not run]",
            }
            status = st.session_state.watcher_status
            badges = "  |  ".join(
                f"**{src.title()}** {_BADGE.get(state, state)}"
                for src, state in status.items()
            )
            st.markdown(badges)
            if st.session_state.last_refreshed:
                st.caption(f"Last refreshed at {st.session_state.last_refreshed}")

    st.divider()

    db = SQLiteMemory()
    deadlines = db.get_upcoming_deadlines(days=120)

    if not deadlines:
        st.info("No live deadlines stored yet. Hit **🔄 Refresh** to scrape your real TUM data.")
        st.caption("Preview (mock data — not from your account):")
        from tum_pulse.agents.watcher import _mock_tumonline, _mock_moodle
        deadlines = _mock_tumonline() + _mock_moodle()
        is_mock_preview = True
    else:
        is_mock_preview = False

    _SOURCE_ICON = {
        "tumonline": "🏛️ TUMonline",
        "moodle":    "📘 Moodle",
        "confluence": "📝 Wiki",
        "pytest":    "🧪 Test",
    }

    rows = []
    for dl in deadlines:
        try:
            dl_date = datetime.strptime(dl["deadline_date"], "%Y-%m-%d")
            days_left = (dl_date.date() - datetime.now().date()).days
        except (ValueError, TypeError):
            days_left = 999
        urgency = (
            "🔴 Today" if days_left == 0 else
            "🟠 Tomorrow" if days_left == 1 else
            f"🟡 {days_left}d" if days_left <= 7 else
            f"🟢 {days_left}d"
        )
        rows.append({
            "Date": dl.get("deadline_date", ""),
            "Due": urgency,
            "Title": dl["title"],
            "Course": dl.get("course", ""),
            "Source": _SOURCE_ICON.get(dl.get("source", ""), dl.get("source", "")),
        })

    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Date":   st.column_config.TextColumn("Date", width="small"),
                "Due":    st.column_config.TextColumn("Due in", width="small"),
                "Title":  st.column_config.TextColumn("Title", width="large"),
                "Course": st.column_config.TextColumn("Course", width="medium"),
                "Source": st.column_config.TextColumn("Source", width="small"),
            },
        )
        label = f"{len(deadlines)} deadline(s) shown"
        if is_mock_preview:
            label += " (preview only — hit Refresh to load your real data)"
        else:
            label += " — live from your TUM account ✅"
        st.caption(label)

    this_week = db.get_upcoming_deadlines(days=7) if not is_mock_preview else []
    if this_week:
        st.subheader("This Week")
        for dl in this_week:
            try:
                days_left = (
                    datetime.strptime(dl["deadline_date"], "%Y-%m-%d").date()
                    - datetime.now().date()
                ).days
            except (ValueError, TypeError):
                days_left = 999
            icon = "🔴" if days_left <= 1 else "🟠" if days_left <= 3 else "🟡"
            st.markdown(
                f"{icon} **{dl['deadline_date']}** — {dl['title']}  "
                f"<small style='color:grey'>{dl.get('course','')}</small>",
                unsafe_allow_html=True,
            )

# ===========================================================================
# TAB 3 — ZHS Sports Registration
# ===========================================================================

with tab_zhs:
    st.header("🏃 ZHS Sport Registration")
    st.caption(
        "Search for sport courses at ZHS München and register directly. "
        "Logs in with your TUM credentials via SSO."
    )

    col_search, col_btn = st.columns([4, 1])
    with col_search:
        sport_query = st.text_input(
            "Sport / Activity",
            placeholder="Badminton, Yoga, Schwimmen, Bouldern...",
            label_visibility="collapsed",
        )
    with col_btn:
        do_search = st.button("🔍 Search", use_container_width=True)

    if do_search and sport_query:
        from tum_pulse.connectors.zhs import ZHSConnector
        from tum_pulse.config import ZHS_USERNAME, ZHS_PASSWORD

        with st.spinner(f"Logging into ZHS and searching for '{sport_query}'..."):
            connector = ZHSConnector()
            result = connector.run(ZHS_USERNAME, ZHS_PASSWORD, sport_query, register_first=False)

        st.session_state.zhs_search_done = True
        st.session_state.zhs_slots = result.get("slots", [])
        st.session_state.zhs_last_query = sport_query
        st.session_state.zhs_reg_result = None

        if result["logged_in"]:
            st.success(f"✅ Logged into ZHS | {result['message']}")
        else:
            st.error(f"❌ {result['message']}")

    if st.session_state.zhs_search_done:
        slots = st.session_state.zhs_slots
        query = st.session_state.get("zhs_last_query", "")

        if not slots:
            st.info(f"No courses found for '{query}'. Try a different keyword.")
        else:
            st.subheader(f"Found {len(slots)} slot(s) for '{query}'")

            for i, slot in enumerate(slots):
                with st.container():
                    c1, c2, c3, c4, c5 = st.columns([3, 2, 2, 1, 1])
                    with c1:
                        st.markdown(f"**{slot.title}**")
                    with c2:
                        st.caption(f"📍 {slot.location or '—'}")
                    with c3:
                        st.caption(f"🕐 {slot.day} {slot.time}" if slot.day or slot.time else "")
                    with c4:
                        spots_color = "🟢" if slot.spots_left > 5 else "🟠" if slot.spots_left > 0 else "🔴"
                        st.caption(f"{spots_color} {slot.spots_left} spots")
                    with c5:
                        if st.button("Buchen", key=f"book_{i}", use_container_width=True):
                            from tum_pulse.connectors.zhs import ZHSConnector
                            from tum_pulse.config import ZHS_USERNAME, ZHS_PASSWORD
                            from playwright.sync_api import sync_playwright

                            with st.spinner(f"Registering for {slot.title}..."):
                                with sync_playwright() as pw:
                                    browser = pw.chromium.launch(headless=True)
                                    page = browser.new_page()
                                    c = ZHSConnector()
                                    c.login(page, ZHS_USERNAME, ZHS_PASSWORD)
                                    reg = c.register(page, slot)
                                    browser.close()
                                st.session_state.zhs_reg_result = reg
                            st.rerun()
                    st.divider()

        if st.session_state.zhs_reg_result:
            reg = st.session_state.zhs_reg_result
            if reg["success"]:
                st.success(f"🎉 {reg['message']}")
            else:
                st.warning(f"⚠️ {reg['message']}")
            if reg.get("screenshot"):
                st.image(reg["screenshot"], caption="ZHS page after registration attempt", use_column_width=True)

    st.divider()
    st.markdown("""
**How it works:**
1. TUM Pulse logs into `kurse.zhs-muenchen.de` using your TUM SSO credentials
2. Searches for available sport courses matching your query
3. You can book directly with one click — confirmation sent to your TUM email

> ZHS login uses the same TUM username/password as TUMonline and Moodle.
""")

# ===========================================================================
# TAB 4 — About
# ===========================================================================

with tab_about:
    st.header("About TUM Pulse 🎓")

    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("What is TUM Pulse?")
        st.markdown("""
TUM Pulse is your AI-powered Campus Co-Pilot for TU Munich. It brings together
all your academic information and automates repetitive tasks through a single
conversational interface.

**Agents:**
- 📅 **Watcher Agent** — scrapes TUMonline, Moodle & Confluence for deadlines
- 🏃 **Executor Agent** — automates ZHS sport registration via Playwright
- 📚 **Advisor Agent** — recommends electives using semantic similarity (Titan Embeddings)
- 🧠 **Learning Buddy** — creates personalised exam prep plans
- 💬 **General Assistant** — answers any TUM-related question
        """)

    with col_right:
        st.subheader("Tech Stack")
        st.markdown("""
| Layer | Technology |
|---|---|
| LLM | Amazon Bedrock (Claude Sonnet) |
| Embeddings | Amazon Titan Embed v2 |
| Orchestration | LangGraph |
| Browser automation | Playwright (sync) |
| Storage | SQLite (local) |
| UI | Streamlit |
| TUM Auth | Keycloak + Shibboleth SSO |
| Moodle API | AJAX calendar endpoint |
| ZHS | Ory Kratos + TUM SSO |
        """)

    st.divider()
    st.subheader("Data Flow")
    st.markdown("""
```
User Query
    │
    ▼
Orchestrator (LangGraph) ──► Intent Classification (Claude)
    │
    ├── deadlines ──► WatcherAgent ──► TUMonlineConnector + MoodleConnector ──► SQLite
    ├── zhs_registration ──► ExecutorAgent ──► ZHSConnector ──► kurse.zhs-muenchen.de
    ├── elective_advice ──► AdvisorAgent ──► Titan Embeddings ──► Claude
    └── exam_plan ──► LearningBuddyAgent ──► Claude
```
    """)

    st.subheader("Source status")
    status_data = {
        "TUMonline": ["campus.tum.de", "Keycloak → Shibboleth", "wbEeHooks.showHooks"],
        "Moodle": ["moodle.tum.de", "Shibboleth SSO", "AJAX calendar API"],
        "Confluence": ["collab.dvb.bayern", "Username + Password", "CQL search"],
        "ZHS": ["kurse.zhs-muenchen.de", "Ory Kratos + TUM SSO", "MeiliSearch API"],
    }
    df_about = pd.DataFrame(status_data, index=["URL", "Auth", "Data source"]).T
    df_about.index.name = "Service"
    st.dataframe(df_about, use_container_width=True)
