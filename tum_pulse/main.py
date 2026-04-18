"""TUM Pulse — Streamlit chat interface entry point."""

import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Page config — must be first Streamlit call
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="TUM Pulse",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# TUM brand CSS
# ---------------------------------------------------------------------------

TUM_BLUE       = "#0065BD"
TUM_DARK_BLUE  = "#003359"
TUM_LIGHT_BLUE = "#64A0C8"
TUM_ORANGE     = "#E37222"
TUM_BG         = "#F0F4F8"

st.markdown(f"""
<style>
/* ── Global ── */
html, body, [data-testid="stAppViewContainer"] {{
    background: {TUM_BG};
    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
}}

/* ── Sidebar ── */
[data-testid="stSidebar"] {{
    background: linear-gradient(170deg, {TUM_DARK_BLUE} 0%, {TUM_BLUE} 100%);
    border-right: none;
}}
[data-testid="stSidebar"] * {{ color: #fff !important; }}
[data-testid="stSidebar"] input,
[data-testid="stSidebar"] textarea {{ color: #111 !important; background: #fff !important; border-radius: 6px; }}
[data-testid="stSidebar"] .stButton button {{
    background: rgba(255,255,255,0.15);
    border: 1px solid rgba(255,255,255,0.35);
    color: #fff !important;
    border-radius: 8px;
    transition: background 0.2s;
}}
[data-testid="stSidebar"] .stButton button:hover {{
    background: rgba(255,255,255,0.28);
}}

/* ── Top header bar ── */
[data-testid="stHeader"] {{ background: {TUM_DARK_BLUE}; }}

/* ── Tab bar ── */
.stTabs [data-baseweb="tab-list"] {{
    background: #fff;
    border-radius: 12px 12px 0 0;
    padding: 4px 8px 0;
    gap: 4px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}}
.stTabs [data-baseweb="tab"] {{
    border-radius: 8px 8px 0 0;
    padding: 10px 20px;
    font-weight: 600;
    color: #555;
    border-bottom: 3px solid transparent;
}}
.stTabs [aria-selected="true"] {{
    color: {TUM_BLUE} !important;
    border-bottom: 3px solid {TUM_BLUE} !important;
    background: {TUM_BG} !important;
}}
.stTabs [data-baseweb="tab-panel"] {{
    background: #fff;
    border-radius: 0 0 12px 12px;
    padding: 24px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}}

/* ── Buttons ── */
.stButton > button {{
    border-radius: 8px;
    font-weight: 600;
    border: 2px solid {TUM_BLUE};
    color: {TUM_BLUE};
    background: #fff;
    transition: all 0.2s;
}}
.stButton > button:hover {{
    background: {TUM_BLUE};
    color: #fff;
}}
.stButton > button[kind="primary"] {{
    background: {TUM_BLUE};
    color: #fff;
}}

/* ── Chat bubbles ── */
[data-testid="stChatMessage"] {{
    border-radius: 12px;
    margin-bottom: 8px;
    padding: 4px 0;
}}

/* ── Metric / info cards ── */
.tum-card {{
    background: #fff;
    border-radius: 12px;
    padding: 20px 24px;
    border-left: 5px solid {TUM_BLUE};
    box-shadow: 0 2px 10px rgba(0,101,189,0.08);
    margin-bottom: 12px;
}}
.tum-card-orange {{
    border-left-color: {TUM_ORANGE};
}}

/* ── Login page ── */
.login-box {{
    max-width: 440px;
    margin: 60px auto;
    background: #fff;
    border-radius: 16px;
    padding: 48px 44px 40px;
    box-shadow: 0 8px 40px rgba(0,53,89,0.15);
    text-align: center;
}}
.login-logo {{
    font-size: 3rem;
    margin-bottom: 8px;
}}
.login-title {{
    color: {TUM_DARK_BLUE};
    font-size: 1.7rem;
    font-weight: 700;
    margin-bottom: 4px;
}}
.login-sub {{
    color: #666;
    font-size: 0.95rem;
    margin-bottom: 32px;
}}

/* ── Dataframe ── */
[data-testid="stDataFrame"] {{ border-radius: 10px; overflow: hidden; }}

/* ── Divider ── */
hr {{ border-color: rgba(0,101,189,0.12); }}

/* ── Status badges ── */
.badge-live   {{ color: #1a7f37; font-weight: 700; }}
.badge-mock   {{ color: #d97706; font-weight: 700; }}
.badge-skip   {{ color: #888;    font-weight: 700; }}

/* ── Quick prompt buttons ── */
.quick-btn button {{
    background: linear-gradient(135deg, {TUM_BLUE}18, {TUM_LIGHT_BLUE}22) !important;
    border: 1.5px solid {TUM_BLUE}44 !important;
    color: {TUM_DARK_BLUE} !important;
    font-size: 0.88rem;
    padding: 10px 8px;
}}
.quick-btn button:hover {{
    background: {TUM_BLUE} !important;
    color: #fff !important;
    border-color: {TUM_BLUE} !important;
}}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# .env helper
# ---------------------------------------------------------------------------

_ENV_PATH = Path(__file__).parent.parent / ".env"


def _update_env(updates: dict[str, str]) -> None:
    """Write or update key=value lines in the .env file."""
    lines: list[str] = []
    if _ENV_PATH.exists():
        lines = _ENV_PATH.read_text().splitlines()

    for key, value in updates.items():
        quoted = f'"{value}"'
        pattern = re.compile(rf"^{re.escape(key)}\s*=")
        replaced = False
        for i, line in enumerate(lines):
            if pattern.match(line):
                lines[i] = f"{key}={quoted}"
                replaced = True
                break
        if not replaced:
            lines.append(f"{key}={quoted}")

    _ENV_PATH.write_text("\n".join(lines) + "\n")
    # Propagate into current process immediately
    for key, value in updates.items():
        os.environ[key] = value

# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------

for _k, _v in {
    "logged_in": False,
    "tum_username": "",
    "messages": [],
    "last_agent": "",
    "toasted_alert_ids": set(),
    "watcher_status": {},
    "last_refreshed": None,
    "zhs_slots": [],
    "zhs_search_done": False,
    "zhs_reg_result": None,
}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# Auto-login if credentials already in env
from tum_pulse.config import TUM_USERNAME, TUM_PASSWORD  # noqa: E402
if TUM_USERNAME and TUM_PASSWORD and not st.session_state.logged_in:
    st.session_state.logged_in = True
    st.session_state.tum_username = TUM_USERNAME

# ===========================================================================
# LOGIN PAGE
# ===========================================================================

if not st.session_state.logged_in:
    _, _c2, _ = st.columns([1, 2, 1])
    with _c2:
        st.markdown(f"""
        <div class="login-box">
            <div class="login-logo">🎓</div>
            <div class="login-title">TUM Pulse</div>
            <div class="login-sub">Your AI Campus Co-Pilot for TU Munich</div>
        </div>
        """, unsafe_allow_html=True)

        with st.form("login_form"):
            username = st.text_input(
                "TUM Username",
                placeholder="ge12abc",
                help="Your TUM identifier (same as TUMonline / Moodle login)",
            )
            password = st.text_input(
                "TUM Password",
                type="password",
                placeholder="••••••••",
            )
            remember = st.checkbox("Save credentials to .env for future sessions", value=True)
            submitted = st.form_submit_button(
                "Sign in →",
                use_container_width=True,
                type="primary",
            )

        if submitted:
            if not username or not password:
                st.error("Please enter both username and password.")
            else:
                if remember:
                    _update_env({
                        "TUM_USERNAME": username,
                        "TUM_PASSWORD": password,
                        "ZHS_USERNAME": username,
                        "ZHS_PASSWORD": password,
                        "CONFLUENCE_USERNAME": username,
                        "CONFLUENCE_PASSWORD": password,
                    })
                else:
                    os.environ["TUM_USERNAME"] = username
                    os.environ["TUM_PASSWORD"] = password
                    os.environ["ZHS_USERNAME"] = username
                    os.environ["ZHS_PASSWORD"] = password

                st.session_state.logged_in = True
                st.session_state.tum_username = username
                st.rerun()

        st.markdown("""
        <p style='text-align:center;color:#888;font-size:0.82rem;margin-top:16px'>
        Credentials are stored only in your local <code>.env</code> file.<br>
        TUM Pulse never transmits them outside your machine.
        </p>
        """, unsafe_allow_html=True)

    st.stop()

# ===========================================================================
# MAIN APP (only reached when logged_in = True)
# ===========================================================================

from tum_pulse.agents.orchestrator import run as orchestrator_run  # noqa: E402
from tum_pulse.agents.watcher import WatcherAgent                   # noqa: E402
from tum_pulse.memory.database import SQLiteMemory                  # noqa: E402

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
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown(f"""
    <div style='text-align:center;padding:8px 0 4px'>
        <div style='font-size:2.4rem'>🎓</div>
        <div style='font-size:1.2rem;font-weight:700;letter-spacing:1px'>TUM PULSE</div>
        <div style='font-size:0.8rem;opacity:0.75;margin-top:2px'>Campus Co-Pilot</div>
    </div>
    """, unsafe_allow_html=True)

    _name_saved = _db.get_profile("name") or ""
    student_name = st.text_input("Your Name", value=_name_saved, placeholder="Max Mustermann")

    st.markdown(f"<div style='opacity:0.7;font-size:0.78rem;margin-top:-8px'>Logged in as <b>{st.session_state.tum_username}</b></div>", unsafe_allow_html=True)

    st.divider()

    _saved_courses = _db.get_profile("courses") or _DEFAULT_COURSES
    _saved_grades = _db.get_profile("grades") or {
        "Linear Algebra": 1.7,
        "Analysis": 2.3,
        "Algorithms and Data Structures": 2.0,
        "Probability Theory": 2.7,
    }
    default_profile = json.dumps({"grades": _saved_grades, "courses": _saved_courses}, indent=2)
    profile_json = st.text_area("Grades & Courses (JSON)", value=default_profile, height=180)
    st.caption("Synced automatically from TUMonline on each refresh.")

    if st.button("💾 Save Profile", use_container_width=True):
        try:
            profile = json.loads(profile_json)
            if "grades" in profile:
                _db.save_profile("grades", profile["grades"])
            if "courses" in profile:
                _db.save_profile("courses", profile["courses"])
            if student_name:
                _db.save_profile("name", student_name)
            st.success("Saved!")
        except json.JSONDecodeError:
            st.error("Invalid JSON.")

    st.divider()

    _electives_count = SQLiteMemory().get_profile("electives_count") or 0
    if _electives_count > 15:
        st.caption(f"📚 {_electives_count} real TUM electives loaded")
    else:
        st.caption("📚 Using sample elective catalogue")

    if st.button("🔄 Refresh Electives", use_container_width=True):
        from tum_pulse.agents.advisor import get_electives
        _edb = SQLiteMemory()
        _fresh = get_electives(_edb, force_refresh=True)
        _edb.save_profile("electives_count", len(_fresh))
        st.success(f"Loaded {len(_fresh)} electives!")
        st.rerun()

    st.divider()

    st.markdown("**🔔 Upcoming (next 2 days)**")
    _imminent = SQLiteMemory().get_upcoming_deadlines(days=2)
    if _imminent:
        for _dl in _imminent:
            st.warning(f"**{_dl['title'][:40]}**  \n{_dl['deadline_date']}")
    else:
        st.caption("No urgent deadlines.")

    st.divider()

    if st.session_state.watcher_status:
        st.markdown("**System Status**")
        _icons = {"live": "🟢", "mock": "🟠", "skipped": "⚫", "not run": "⚫"}
        for src, state in st.session_state.watcher_status.items():
            st.caption(f"{_icons.get(state,'⚫')} {src.title()}: {state}")
        st.divider()

    if st.button("🚪 Sign out", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.tum_username = ""
        st.rerun()

    st.caption("Powered by Amazon Bedrock · LangGraph")

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
    # Header
    st.markdown(f"""
    <div style='display:flex;align-items:center;gap:12px;margin-bottom:4px'>
        <span style='font-size:2rem'>🎓</span>
        <div>
            <h2 style='margin:0;color:{TUM_DARK_BLUE}'>TUM Pulse</h2>
            <p style='margin:0;color:#666;font-size:0.9rem'>Ask me about deadlines, electives, ZHS or exam prep</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    # Quick prompts
    qcols = st.columns(4)
    quick_prompts = [
        ("📅", "Deadlines this week", "What deadlines do I have this week?"),
        ("📚", "Recommend electives", "Recommend me elective courses"),
        ("🧠", "Help pass Analysis 2", "Help me pass Analysis 2"),
        ("🏃", "Book ZHS Badminton", "Register me for Badminton at ZHS"),
    ]
    for col, (icon, label, prompt) in zip(qcols, quick_prompts):
        with col:
            st.markdown('<div class="quick-btn">', unsafe_allow_html=True)
            if st.button(f"{icon} {label}", use_container_width=True):
                st.session_state.quick_prompt = prompt
            st.markdown('</div>', unsafe_allow_html=True)

    st.divider()

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    _AGENT_LABELS: dict[str, str] = {
        "deadlines":       "📅 Watcher Agent",
        "zhs_registration":"🏃 Executor Agent",
        "elective_advice": "📚 Advisor Agent",
        "exam_plan":       "🧠 Learning Buddy",
        "general":         "💬 General Assistant",
        "error":           "⚠️ Error",
        "":                "",
    }
    if st.session_state.last_agent:
        label = _AGENT_LABELS.get(st.session_state.last_agent, st.session_state.last_agent)
        st.caption(f"Last activated: **{label}**")

    user_input: str = ""
    quick = st.session_state.pop("quick_prompt", None)
    if quick:
        user_input = quick

    typed = st.chat_input("Ask TUM Pulse anything…")
    if typed:
        user_input = typed

    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)
        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                response, agent_called = orchestrator_run(
                    user_input,
                    thread_id=student_name or st.session_state.tum_username or "default",
                )
            st.markdown(response)
            st.session_state.last_agent = agent_called
        st.session_state.messages.append({"role": "assistant", "content": response})
        st.rerun()

# ===========================================================================
# TAB 2 — Deadlines
# ===========================================================================

with tab_deadlines:
    st.markdown(f"<h2 style='color:{TUM_DARK_BLUE};margin-bottom:4px'>📅 Upcoming Deadlines</h2>", unsafe_allow_html=True)
    st.caption("Live data from TUMonline, Moodle, and Confluence.")

    col_btn, col_status = st.columns([2, 5])
    with col_btn:
        refresh = st.button("🔄 Refresh from TUM systems", use_container_width=True, type="primary")

    if refresh:
        with st.spinner("Logging in and scraping TUMonline, Moodle, Confluence…"):
            agent = WatcherAgent()
            agent.run()
            st.session_state.watcher_status = agent.status
            st.session_state.last_refreshed = datetime.now().strftime("%H:%M:%S")
        st.success("Refresh complete!")
        st.rerun()

    with col_status:
        if st.session_state.watcher_status:
            _BADGE = {"live": "🟢 live", "mock": "🟠 mock", "skipped": "⚫ skipped", "not run": "⚫ not run"}
            parts = [
                f"**{src.title()}** — {_BADGE.get(state, state)}"
                for src, state in st.session_state.watcher_status.items()
            ]
            st.markdown("   ·   ".join(parts))
            if st.session_state.last_refreshed:
                st.caption(f"Last refreshed at {st.session_state.last_refreshed}")

    st.divider()

    db = SQLiteMemory()
    deadlines = db.get_upcoming_deadlines(days=120)

    if not deadlines:
        st.info("No deadlines cached yet — hit **🔄 Refresh** to pull your live TUM data.")
        st.caption("Preview (mock data):")
        from tum_pulse.agents.watcher import _mock_tumonline, _mock_moodle
        deadlines = _mock_tumonline() + _mock_moodle()
        is_mock_preview = True
    else:
        is_mock_preview = False

    _SOURCE_ICON = {
        "tumonline":  "🏛️ TUMonline",
        "moodle":     "📘 Moodle",
        "confluence": "📝 Wiki",
    }

    rows = []
    for dl in deadlines:
        try:
            dl_date = datetime.strptime(dl["deadline_date"], "%Y-%m-%d")
            days_left = (dl_date.date() - datetime.now().date()).days
        except (ValueError, TypeError):
            days_left = 999
        urgency = (
            "🔴 Today"        if days_left == 0 else
            "🟠 Tomorrow"     if days_left == 1 else
            f"🟡 {days_left}d" if days_left <= 7 else
            f"🟢 {days_left}d"
        )
        rows.append({
            "Date":   dl.get("deadline_date", ""),
            "Due":    urgency,
            "Title":  dl["title"],
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
                "Date":   st.column_config.TextColumn("Date",    width="small"),
                "Due":    st.column_config.TextColumn("Due in",  width="small"),
                "Title":  st.column_config.TextColumn("Title",   width="large"),
                "Course": st.column_config.TextColumn("Course",  width="medium"),
                "Source": st.column_config.TextColumn("Source",  width="small"),
            },
        )
        caption = f"{len(deadlines)} deadline(s)"
        caption += " (preview — hit Refresh for real data)" if is_mock_preview else " from your TUM account ✅"
        st.caption(caption)

    this_week = db.get_upcoming_deadlines(days=7) if not is_mock_preview else []
    if this_week:
        st.markdown(f"<h3 style='color:{TUM_DARK_BLUE};margin-top:24px'>This Week</h3>", unsafe_allow_html=True)
        for dl in this_week:
            try:
                days_left = (datetime.strptime(dl["deadline_date"], "%Y-%m-%d").date() - datetime.now().date()).days
            except (ValueError, TypeError):
                days_left = 999
            icon = "🔴" if days_left <= 1 else "🟠" if days_left <= 3 else "🟡"
            st.markdown(
                f"<div class='tum-card{' tum-card-orange' if days_left <= 1 else ''}'>"
                f"{icon} <b>{dl['deadline_date']}</b> &nbsp;—&nbsp; {dl['title']}<br>"
                f"<span style='color:#888;font-size:0.85rem'>{dl.get('course','')}</span></div>",
                unsafe_allow_html=True,
            )

# ===========================================================================
# TAB 3 — ZHS Sports
# ===========================================================================

with tab_zhs:
    st.markdown(f"<h2 style='color:{TUM_DARK_BLUE};margin-bottom:4px'>🏃 ZHS Sport Registration</h2>", unsafe_allow_html=True)
    st.caption("Search and register for sport courses at ZHS München using your TUM SSO credentials.")

    col_search, col_btn = st.columns([4, 1])
    with col_search:
        sport_query = st.text_input(
            "Sport",
            placeholder="Badminton, Yoga, Schwimmen, Bouldern…",
            label_visibility="collapsed",
        )
    with col_btn:
        do_search = st.button("🔍 Search", use_container_width=True, type="primary")

    if do_search and sport_query:
        from tum_pulse.connectors.zhs import ZHSConnector
        from tum_pulse.config import ZHS_USERNAME, ZHS_PASSWORD

        with st.spinner(f"Searching ZHS for '{sport_query}'…"):
            connector = ZHSConnector()
            result = connector.run(ZHS_USERNAME, ZHS_PASSWORD, sport_query, register_first=False)

        st.session_state.zhs_search_done = True
        st.session_state.zhs_slots = result.get("slots", [])
        st.session_state.zhs_last_query = sport_query
        st.session_state.zhs_reg_result = None

        if result["logged_in"]:
            st.success(f"✅ Logged into ZHS — {result['message']}")
        else:
            st.error(f"❌ {result['message']}")

    if st.session_state.zhs_search_done:
        slots = st.session_state.zhs_slots
        query = st.session_state.get("zhs_last_query", "")

        if not slots:
            st.info(f"No courses found for '{query}'. Try a different keyword.")
        else:
            st.markdown(f"<h3 style='color:{TUM_DARK_BLUE}'>Found {len(slots)} slot(s) for '{query}'</h3>", unsafe_allow_html=True)

            for i, slot in enumerate(slots):
                spots_color = "#1a7f37" if slot.spots_left > 5 else "#d97706" if slot.spots_left > 0 else "#cf222e"
                with st.container():
                    st.markdown(f"""
                    <div class='tum-card' style='display:flex;justify-content:space-between;align-items:center'>
                        <div>
                            <b style='font-size:1rem'>{slot.title}</b><br>
                            <span style='color:#666;font-size:0.85rem'>📍 {slot.location or "—"} &nbsp;·&nbsp; 🕐 {slot.day or ""} {slot.time or ""}</span>
                        </div>
                        <div style='text-align:right'>
                            <span style='color:{spots_color};font-weight:700'>{slot.spots_left} spots</span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                    if st.button("📌 Buchen", key=f"book_{i}", use_container_width=False):
                        from tum_pulse.connectors.zhs import ZHSConnector
                        from tum_pulse.config import ZHS_USERNAME, ZHS_PASSWORD
                        from playwright.sync_api import sync_playwright

                        with st.spinner(f"Registering for {slot.title}…"):
                            with sync_playwright() as pw:
                                browser = pw.chromium.launch(headless=True)
                                page = browser.new_page()
                                _zc = ZHSConnector()
                                _zc.login(page, ZHS_USERNAME, ZHS_PASSWORD)
                                reg = _zc.register(page, slot)
                                browser.close()
                            st.session_state.zhs_reg_result = reg
                        st.rerun()

        if st.session_state.zhs_reg_result:
            reg = st.session_state.zhs_reg_result
            if reg["success"]:
                st.success(f"🎉 {reg['message']}")
            else:
                st.warning(f"⚠️ {reg['message']}")
            if reg.get("screenshot"):
                st.image(reg["screenshot"], caption="ZHS confirmation", use_column_width=True)

    st.divider()
    st.markdown(f"""
    <div class='tum-card'>
        <b style='color:{TUM_DARK_BLUE}'>How it works</b><br><br>
        1. TUM Pulse logs into <code>kurse.zhs-muenchen.de</code> with your TUM SSO credentials<br>
        2. Searches available sport courses matching your query<br>
        3. Click <b>Buchen</b> to register — confirmation sent to your TUM email
    </div>
    """, unsafe_allow_html=True)

# ===========================================================================
# TAB 4 — About
# ===========================================================================

with tab_about:
    st.markdown(f"<h2 style='color:{TUM_DARK_BLUE}'>About TUM Pulse 🎓</h2>", unsafe_allow_html=True)

    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown(f"""
        <div class='tum-card'>
            <b style='color:{TUM_DARK_BLUE};font-size:1.05rem'>What is TUM Pulse?</b><br><br>
            TUM Pulse is your AI-powered Campus Co-Pilot for TU Munich. It connects your
            academic systems and automates repetitive tasks through one conversational interface.<br><br>
            <b>Agents</b><br>
            📅 <b>Watcher</b> — scrapes TUMonline, Moodle & Confluence for deadlines<br>
            🏃 <b>Executor</b> — automates ZHS sport registration via Playwright<br>
            📚 <b>Advisor</b> — recommends electives via Titan Embeddings<br>
            🧠 <b>Learning Buddy</b> — personalised exam prep plans<br>
            💬 <b>General</b> — answers any TUM-related question
        </div>
        """, unsafe_allow_html=True)

    with col_right:
        st.markdown(f"""
        <div class='tum-card'>
            <b style='color:{TUM_DARK_BLUE};font-size:1.05rem'>Tech Stack</b><br><br>
            🤖 <b>LLM</b> — Amazon Bedrock (Claude Sonnet)<br>
            🔢 <b>Embeddings</b> — Amazon Titan Embed v2<br>
            🔗 <b>Orchestration</b> — LangGraph<br>
            🌐 <b>Browser</b> — Playwright (sync)<br>
            🗄️ <b>Storage</b> — SQLite (local)<br>
            🖥️ <b>UI</b> — Streamlit<br>
            🔐 <b>TUM Auth</b> — Keycloak + Shibboleth SSO<br>
            📘 <b>Moodle</b> — AJAX calendar API<br>
            🏃 <b>ZHS</b> — Ory Kratos + TUM SSO
        </div>
        """, unsafe_allow_html=True)

    st.divider()

    st.markdown(f"""
    <div class='tum-card'>
        <b style='color:{TUM_DARK_BLUE};font-size:1.05rem'>Data Flow</b><br><br>
        <pre style='background:#f5f7fa;border-radius:8px;padding:12px;font-size:0.82rem'>
User Query
    │
    ▼
Orchestrator (LangGraph) ──► Intent Classification (Claude)
    │
    ├── deadlines        ──► WatcherAgent  ──► TUMonline + Moodle + Confluence ──► SQLite
    ├── zhs_registration ──► ExecutorAgent ──► ZHSConnector ──► kurse.zhs-muenchen.de
    ├── elective_advice  ──► AdvisorAgent  ──► Titan Embeddings ──► Claude
    └── exam_plan        ──► LearningBuddy ──► Claude
        </pre>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"<h3 style='color:{TUM_DARK_BLUE}'>Connected Services</h3>", unsafe_allow_html=True)
    status_data = {
        "TUMonline":  ["campus.tum.de",          "Keycloak → Shibboleth SSO", "CAMPUSonline REST API"],
        "Moodle":     ["moodle.tum.de",           "Shibboleth SSO",            "AJAX calendar endpoint"],
        "Confluence": ["collab.dvb.bayern",       "Personal Access Token",     "CQL search"],
        "ZHS":        ["kurse.zhs-muenchen.de",   "Ory Kratos + TUM SSO",     "MeiliSearch API"],
    }
    df_about = pd.DataFrame(status_data, index=["URL", "Auth", "Data source"]).T
    df_about.index.name = "Service"
    st.dataframe(df_about, use_container_width=True)
