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
    page_title="TUM Easy",
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
[data-testid="stHeader"] {{ background: {TUM_BG}; }}

/* ── Tab bar ── */
.stTabs [data-baseweb="tab-list"] {{
    background: #fff;
    border-radius: 12px 12px 0 0;
    padding: 4px 8px 0;
    gap: 4px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    display: flex;
    width: 100%;
    justify-content: space-between;
    align-items: stretch;
}}
.stTabs [data-baseweb="tab"] {{
    border-radius: 8px 8px 0 0;
    padding: 10px 20px;
    font-weight: 600;
    color: #555;
    border-bottom: 3px solid transparent;
    flex: 1;
    text-align: center;
    min-width: 0;
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
    padding-bottom: 25px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}}

/* ── Chat input (fixed at bottom) ── */
[data-testid="stChatInputContainer"] {{
    position: fixed !important;
    bottom: 0 !important;
    left: 0 !important;
    right: 0 !important;
    width: 100% !important;
    padding: 16px !important;
    background: {TUM_BG} !important;
    box-shadow: 0 -2px 8px rgba(0,0,0,0.1) !important;
    z-index: 1000 !important;
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

/* ── Pin chat input to bottom ── */
[data-testid="stChatInput"] {{
    position: sticky;
    bottom: 0;
    background: {TUM_BG};
    padding: 12px 0 4px 0;
    z-index: 100;
    border-top: 1px solid rgba(0,101,189,0.10);
}}

/* ── Make chat messages area scrollable above input ── */
[data-testid="stChatMessageContainer"] {{
    padding-bottom: 80px;
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
    "watcher_message": "No sync has run yet.",
    "watcher_running": False,
    "watcher_data_mode": "unknown",
    "electives_mode": "unknown",
    "zhs_slots": [],
    "zhs_search_done": False,
    "zhs_reg_result": None,
    "chat_deadlines": [],
    "chat_electives": [],
    "chat_learning_buddy": [],
    "chat_zhs": [],
    "active_chat": "deadlines",
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
            <div class="login-title">TUM Easy</div>
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
        TUM Easy stores credentials only on your machine when you choose to remember them.
        </p>
        """, unsafe_allow_html=True)

    st.stop()

# ===========================================================================
# MAIN APP (only reached when logged_in = True)
# ===========================================================================

from tum_pulse.agents.orchestrator import run as orchestrator_run  # noqa: E402
from tum_pulse.agents.watcher import WatcherAgent                   # noqa: E402
from tum_pulse.memory.database import SQLiteMemory                  # noqa: E402

_COURSE_PLACEHOLDER = [
    "Introduction to Programming",
    "Linear Algebra",
    "Analysis",
    "Algorithms and Data Structures",
]

_db = SQLiteMemory()


def _derive_deadlines_mode(status: dict[str, str], has_cached: bool) -> str:
    values = {v for v in status.values() if v}
    if "live" in values:
        return "live"
    if has_cached:
        return "cached"
    if "mock" in values:
        return "demo"
    if values and values <= {"skipped", "not run"}:
        return "waiting"
    return "unknown"


def _derive_electives_mode(count: int) -> str:
    return "live" if count > 15 else "demo"


def _mode_badge(mode: str) -> str:
    mapping = {
        "live": "🟢 Live",
        "cached": "🔵 Cached",
        "demo": "🟠 Demo",
        "waiting": "⚪ Waiting",
        "unknown": "⚫ Unknown",
    }
    return mapping.get(mode, mode.title())


def _safe_grade_rows(
    saved_courses: list | None,
    saved_grades: dict | None,
    selected_courses: list | None = None,
) -> list[dict[str, object]]:
    """Build rows for the course data editor (2 columns: checkbox + name)."""
    grades = saved_grades if isinstance(saved_grades, dict) else {}
    courses = saved_courses if isinstance(saved_courses, list) else []
    selected = {
        str(c).strip() for c in (selected_courses or []) if str(c).strip()
    }

    ordered_courses: list[str] = []
    seen: set[str] = set()
    for course in [*courses, *grades.keys()]:
        name = str(course).strip()
        if name and name not in seen:
            ordered_courses.append(name)
            seen.add(name)

    rows = [
        {
            "Use for Recommendations": course in selected,
            "Course": course,
        }
        for course in ordered_courses
    ]

    if not rows:
        rows.append({"Use for Recommendations": False, "Course": ""})

    return rows


def _save_profile_form(student_name: str, course_rows: list[dict]) -> tuple[bool, str]:
    """Persist courses and selected-for-recommendations list to SQLite."""
    cleaned_courses: list[str] = []
    selected_courses: list[str] = []

    for row in course_rows:
        course = str(row.get("Course", "")).strip()
        use = bool(row.get("Use for Recommendations", False))
        if not course:
            continue
        if course not in cleaned_courses:
            cleaned_courses.append(course)
        if use and course not in selected_courses:
            selected_courses.append(course)

    if student_name.strip():
        _db.save_profile("name", student_name.strip())
    _db.save_profile("courses", cleaned_courses)
    _db.save_profile("selected_recommendation_courses", selected_courses)
    # Keep existing grades untouched — we no longer edit them here
    return True, "Profile saved."


def _background_scrape() -> None:
    st.session_state.watcher_running = True
    try:
        # 1. Sync deadlines from TUMonline, Moodle, Confluence
        agent = WatcherAgent()
        summary = agent.run()
        st.session_state.watcher_status = agent.status
        st.session_state.last_refreshed = datetime.now().strftime("%H:%M:%S")
        st.session_state.watcher_message = summary
        _db.save_last_fetched(datetime.now().isoformat())
    except Exception as exc:
        st.session_state.watcher_message = f"Background sync failed: {exc}"
    finally:
        has_cached = bool(_db.get_upcoming_deadlines(days=120))
        st.session_state.watcher_data_mode = _derive_deadlines_mode(
            st.session_state.watcher_status, has_cached
        )
        st.session_state.watcher_running = False

    try:
        # 2. Auto-fetch electives in the same background thread
        from tum_pulse.agents.advisor import get_electives
        _fresh = get_electives(_db, force_refresh=False)  # use cache if < 24h old
        _db.save_profile("electives_count", len(_fresh))
        st.session_state.electives_mode = _derive_electives_mode(len(_fresh))
    except Exception:
        pass  # electives failure is non-critical


if "startup_done" not in st.session_state:
    st.session_state.startup_done = True
    threading.Thread(target=_background_scrape, daemon=True).start()

st.session_state.electives_mode = _derive_electives_mode(_db.get_profile("electives_count") or 0)
if st.session_state.watcher_data_mode == "unknown":
    st.session_state.watcher_data_mode = _derive_deadlines_mode(
        st.session_state.watcher_status,
        bool(_db.get_upcoming_deadlines(days=120)),
    )

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
        <div style='font-size:1.2rem;font-weight:700;letter-spacing:1px'>TUM EASY</div>
        <div style='font-size:0.8rem;opacity:0.75;margin-top:2px'>Campus Co-Pilot</div>
    </div>
    """, unsafe_allow_html=True)

    _name_saved = _db.get_profile("name") or ""
    student_name = st.text_input("Your Name", value=_name_saved, placeholder="Max Mustermann")

    st.markdown(f"<div style='opacity:0.7;font-size:0.78rem;margin-top:-8px;margin-bottom:12px'>Logged in as <b>{st.session_state.tum_username}</b></div>", unsafe_allow_html=True)

    _saved_courses = _db.get_profile("courses") or []
    _saved_grades = _db.get_profile("grades") or {}
    _selected_recommendation_courses = _db.get_profile("selected_recommendation_courses") or []

    _saved_grades_rows = _safe_grade_rows(
        _saved_courses,
        _saved_grades,
        _selected_recommendation_courses,
    )

    st.divider()

    st.markdown("""
    <style>
    [data-testid="stExpander"] details summary {
        background-color: #0d47a1 !important;
        color: white !important;
        padding: 10px 16px !important;
        border-radius: 4px !important;
        font-weight: 500 !important;
        cursor: pointer !important;
        border: none !important;
    }
    [data-testid="stExpander"] details summary:hover {
        background-color: #1565c0 !important;
        color: white !important;
    }
    [data-testid="stExpander"] details summary:active {
        background-color: #0d47a1 !important;
        color: white !important;
    }
    </style>
    """, unsafe_allow_html=True)

    with st.expander("👤 Profile", expanded=True):
        st.caption("Check specific courses to guide elective recommendations.")
        grades_df = pd.DataFrame(_saved_grades_rows)
        edited_grades = st.data_editor(
            grades_df,
            use_container_width=True,
            num_rows="dynamic",
            hide_index=True,
            column_config={
                "Use for Recommendations": st.column_config.CheckboxColumn(
                    "✓",
                    help="Check to include this course in elective recommendations.",
                    default=False,
                    width="small",
                ),
                "Course": st.column_config.TextColumn(
                    "Course",
                    width="large",
                ),
            },
            column_order=["Use for Recommendations", "Course"],
        )
        _selected_count = int(
            edited_grades["Use for Recommendations"].fillna(False).astype(bool).sum()
        ) if "Use for Recommendations" in edited_grades else 0
        if _selected_count:
            st.caption(f"{_selected_count} course(s) selected for recommendations.")
        else:
            st.caption("No selection — all courses used for recommendations.")

        if st.button("💾 Save Profile", use_container_width=True):
            ok, msg = _save_profile_form(student_name, edited_grades.to_dict("records"))
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

        profile_mode = "live" if (_saved_courses or _saved_grades) else "demo"
        st.caption(f"Profile status: {_mode_badge(profile_mode)}")
        if not (_saved_courses or _saved_grades):
            st.caption("No synced profile found yet. Add courses manually or run a live refresh.")

    st.divider()

    st.markdown("**🔔 Upcoming (next 2 days)**")
    _imminent = SQLiteMemory().get_upcoming_deadlines(days=2)
    if _imminent:
        for _dl in _imminent:
            st.warning(f"**{_dl['title'][:40]}**  \n{_dl['deadline_date']}")
    else:
        st.caption("No urgent deadlines cached right now.")

    st.divider()

    if st.session_state.watcher_status:
        st.markdown("**Per-source status**")
        _icons = {"live": "🟢", "mock": "🟠", "skipped": "⚫", "not run": "⚪"}
        for src, state in st.session_state.watcher_status.items():
            st.caption(f"{_icons.get(state,'⚫')} {src.title()}: {state.title()}")
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
            <h2 style='margin:0;color:{TUM_DARK_BLUE}'>TUM Easy</h2>
            <p style='margin:0;color:#666;font-size:0.9rem'>Ask me about deadlines, electives, ZHS or exam prep</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    # Quick prompts - click to switch between separate chat tabs
    qcols = st.columns(4)
    quick_prompts = [
        ("📅", "Deadlines this week", "deadlines"),
        ("📚", "Recommend electives", "electives"),
        ("🧠", "Learning Buddy", "learning_buddy"),
        ("🏃", "Book ZHS", "zhs"),
    ]
    for col, (icon, label, chat_key) in zip(qcols, quick_prompts):
        with col:
            st.markdown('<div class="quick-btn">', unsafe_allow_html=True)
            if st.button(f"{icon} {label}", use_container_width=True):
                st.session_state.active_chat = chat_key
            st.markdown('</div>', unsafe_allow_html=True)

    st.divider()

    # Get the active chat (default to deadlines)
    active_chat = st.session_state.get("active_chat", "deadlines")
    chat_messages = st.session_state[f"chat_{active_chat}"]

    # Display messages for the active chat
    for msg in chat_messages:
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

    # --- Handle input for active chat ---
    if active_chat == "deadlines":
        typed = st.chat_input(f"How can I help you manage your deadlines?")
    elif active_chat == "electives":
        typed = st.chat_input(f"How can I help you choose your electives?")
    elif active_chat == "learning_buddy":
        typed = st.chat_input(f"How can I help you personalise a study plan")
    elif active_chat == "zhs":
        typed = st.chat_input(f"How can I help you search or book ZHS sport courses?")
    if typed:
        # Add user message to active chat
        chat_messages.append({"role": "user", "content": typed})
        with st.chat_message("user"):
            st.markdown(typed)

        # Get response from orchestrator
        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                response, agent_called = orchestrator_run(
                    typed,
                    thread_id=student_name or st.session_state.tum_username or "default",
                )
            st.markdown(response)
            st.session_state.last_agent = agent_called

            # Context-aware feedback badges shown after each relevant response
            if agent_called in ("elective_advice", "exam_plan", "deadlines"):
                _fb_db = SQLiteMemory()
                _fb_grades = _fb_db.get_profile("grades") or {}
                _weak = [
                    c for c, g in _fb_grades.items()
                    if isinstance(g, (int, float)) and g > 2.3
                ]
                _urgent = _fb_db.get_upcoming_deadlines(days=3)

                if agent_called in ("elective_advice", "exam_plan"):
                    if _weak:
                        st.info(
                            f"📉 Weak subjects considered: "
                            f"{', '.join(_weak[:3])}"
                        )
                    if _urgent:
                        st.warning(
                            "⚠️ Upcoming deadlines detected — "
                            "recommendations adapted for time pressure"
                        )

                if agent_called == "elective_advice":
                    st.success("🎯 Personalised using your grades and course history")
                elif agent_called == "exam_plan":
                    st.success(
                        "🧠 Study plan adapted to your weak subjects "
                        "and available time"
                    )
                elif agent_called == "deadlines":
                    st.success(
                        "📅 Aggregated live from TUMonline, Moodle "
                        "and Confluence"
                    )

        # Add assistant message to active chat
        chat_messages.append({"role": "assistant", "content": response})
        st.rerun()

# ===========================================================================
# TAB 2 — Deadlines
# ===========================================================================

with tab_deadlines:
    st.markdown(f"<h2 style='color:{TUM_DARK_BLUE};margin-bottom:4px'>📅 Upcoming Deadlines</h2>", unsafe_allow_html=True)
    st.caption("TUM Easy shows whether each source is live, cached, or demo so you know how trustworthy the data is.")

    if st.session_state.watcher_running:
        st.info("⏳ Syncing data from TUM systems in the background…")
    elif st.session_state.watcher_status:
        _BADGE = {
            "live": "🟢 live", "mock": "🟠 demo",
            "skipped": "⚫ skipped", "not run": "⚪ not run",
        }
        parts = [
            f"**{src.title()}** — {_BADGE.get(state, state)}"
            for src, state in st.session_state.watcher_status.items()
        ]
        st.caption("   ·   ".join(parts))
        if st.session_state.last_refreshed:
            st.caption(f"Last synced at {st.session_state.last_refreshed}")
    else:
        st.caption("⏳ Syncing in background on first load…")

    st.divider()

    db = SQLiteMemory()
    deadlines = db.get_upcoming_deadlines(days=120)

    if not deadlines:
        st.info("No cached deadlines yet. Use **🔄 Refresh** to try a live sync.")
        st.warning("Showing demo preview data so the page is not empty.")
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

    # City filter
    ZHS_CITIES = [
        "München", "Garching", "Weihenstephan", "Straubing",
        "Heilbronn", "Starnberg", "Singapur", "Freising",
    ]
    selected_cities = st.multiselect(
        "Filter by city (leave empty for all)",
        options=ZHS_CITIES,
        default=[],
        placeholder="Select one or more cities…",
    )

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

        all_slots = result.get("slots", [])

        # Apply city filter if any cities selected
        if selected_cities:
            city_lower = [c.lower() for c in selected_cities]
            all_slots = [
                s for s in all_slots
                if any(city in (s.location or "").lower() for city in city_lower)
            ]

        st.session_state.zhs_search_done = True
        st.session_state.zhs_slots = all_slots
        st.session_state.zhs_last_query = sport_query
        st.session_state.zhs_reg_result = None
        st.session_state.zhs_selected_cities = selected_cities

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
            city_note = f" in {', '.join(st.session_state.get('zhs_selected_cities', []))}" if st.session_state.get('zhs_selected_cities') else ""
            st.markdown(f"<h3 style='color:{TUM_DARK_BLUE}'>Found {len(slots)} slot(s) for '{query}'{city_note}</h3>", unsafe_allow_html=True)

            for i, slot in enumerate(slots):
                spots_color = (
                    "#1a7f37" if slot.spots_left > 5 else
                    "#d97706" if slot.spots_left > 0 else
                    "#cf222e"
                )
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
        1. TUM Easy logs into <code>kurse.zhs-muenchen.de</code> with your TUM SSO credentials<br>
        2. Searches available sport courses matching your query<br>
        3. Click <b>Buchen</b> to register — confirmation sent to your TUM email
    </div>
    """, unsafe_allow_html=True)

# ===========================================================================
# TAB 4 — About
# ===========================================================================

with tab_about:
    st.markdown(f"<h2 style='color:{TUM_DARK_BLUE}'>About TUM Easy 🎓</h2>", unsafe_allow_html=True)

    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown(f"""
        <div class='tum-card'>
            <b style='color:{TUM_DARK_BLUE};font-size:1.05rem'>What is TUM Easy?</b><br><br>
            TUM Easy is your AI-powered Campus Co-Pilot for TUM. It connects your
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
