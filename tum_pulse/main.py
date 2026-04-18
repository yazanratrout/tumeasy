"""TUM Pulse — Streamlit chat interface entry point."""

import os
import re
import threading
from datetime import datetime, timedelta
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
    "active_chat": "electives",
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
        # Clear stale mock/placeholder deadlines before live sync
        _db.clear_deadlines(source="mock")
        last = _db.get_last_fetched()
        if last:
            try:
                age = datetime.now() - datetime.fromisoformat(last)
                if age > timedelta(hours=24):
                    _db.clear_deadlines()
            except ValueError:
                pass

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
        from tum_pulse.agents.advisor import get_electives
        _fresh = get_electives(_db, force_refresh=False)
        _db.save_profile("electives_count", len(_fresh))
        st.session_state.electives_mode = _derive_electives_mode(len(_fresh))
    except Exception:
        pass


if "startup_done" not in st.session_state:
    st.session_state.startup_done = True
    # Clear any stale mock deadlines that may be in DB from previous runs
    _db.clear_deadlines(source="mock")
    # Only start background scrape if we haven't fetched recently
    _last = _db.get_last_fetched()
    _should_fetch = True
    if _last:
        try:
            _age = datetime.now() - datetime.fromisoformat(_last)
            if _age < timedelta(hours=2):
                _should_fetch = False
                print(f"[Startup] Cache is fresh ({int(_age.total_seconds()/60)}m old) — skipping scrape")
        except ValueError:
            pass
    if _should_fetch:
        threading.Thread(target=_background_scrape, daemon=True).start()

# One-time cleanup of known mock deadline titles that pollute the cache
_MOCK_TITLES = {
    "Quiz: Probability Theory Chapter 3",
    "Project Milestone 1",
    "Exam Registration: Analysis 2",
    "Homework Sheet 5 Submission",
    "Lab Report 2",
}
if not st.session_state.get("mock_cleaned"):
    st.session_state.mock_cleaned = True
    import sqlite3 as _sqlite3
    try:
        with _sqlite3.connect(_db.db_path) as _conn:
            for _title in _MOCK_TITLES:
                _conn.execute(
                    "DELETE FROM deadlines WHERE title = ?", (_title,)
                )
    except Exception:
        pass

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
    # Use current-semester enrolled only for sidebar (not historical courses)
    _enrolled_current = _db.get_profile("enrolled") or _db.get_profile("courses") or []
    _all_imminent = _db.get_upcoming_deadlines(days=2)

    _SB_STOPWORDS = frozenset({
        "which","their","these","those","about","other","where","there",
        "using","seminar","systems","master","introduction",
    })

    def _sb_key_words(name: str) -> list[str]:
        import re as _re2
        clean = _re2.sub(r'\([A-Z]{1,4}\d{3,}[^)]*\)', '', name).lower()
        return [w for w in _re2.split(r'\W+', clean) if len(w) > 3 and w not in _SB_STOPWORDS]

    def _matches_enrolled(dl: dict, enrolled: list[str]) -> bool:
        import re as _re2
        if dl.get("course") == "TUM Administration":
            return True
        title = dl.get("title", "")
        if title.startswith(("Exam Registration Deadline", "Course Registration",
                              "Re-enrollment", "Semester Contribution", "Exmatriculation")):
            return True
        if not enrolled:
            return True
        text = (title + " " + (dl.get("course") or "")).lower()
        for enr in enrolled:
            codes = _re2.findall(r'[A-Z]{1,4}\d{3,}', enr)
            if any(c.lower() in text for c in codes):
                return True
            words = _sb_key_words(enr)
            if not words:
                continue
            hits = sum(1 for w in words if w in text)
            if hits >= (1 if len(words) == 1 else 2):
                return True
        return False

    _imminent = [d for d in _all_imminent if _matches_enrolled(d, _enrolled_current)]
    if _imminent:
        for _dl in _imminent:
            st.warning(f"**{_dl['title'][:45]}**  \n{_dl['deadline_date']}")
    elif _enrolled_current:
        st.caption("No urgent deadlines for your courses in the next 2 days.")
    else:
        st.caption("No urgent deadlines cached right now.")

    st.divider()

    if st.session_state.watcher_status:
        st.markdown("**Per-source status**")
        _icons = {"live": "🟢", "mock": "🟠", "failed": "🔴", "skipped": "⚫", "not run": "⚪"}
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

_AGENT_LABELS: dict[str, str] = {
    "deadlines":        "📅 Watcher Agent",
    "zhs_registration": "🏃 Executor Agent",
    "elective_advice":  "📚 Advisor Agent",
    "exam_plan":        "🧠 Learning Buddy",
    "general":          "💬 General Assistant",
    "error":            "⚠️ Error",
    "":                 "",
}

with tab_chat:
    st.markdown(f"""
    <div style='display:flex;align-items:center;gap:12px;margin-bottom:4px'>
        <span style='font-size:2rem'>🎓</span>
        <div>
            <h2 style='margin:0;color:{TUM_DARK_BLUE}'>TUM Easy — Your Campus Co-Pilot</h2>
            <p style='margin:0;color:#666;font-size:0.9rem'>Deadlines · Electives · Study Buddy · ZHS</p>
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.divider()

    # ── Top nav: which agent area ──
    qcols = st.columns(2)
    quick_prompts = [
        ("📚", "Electives", "electives"),
        ("🧠", "Study Buddy", "learning_buddy"),
    ]
    for col, (icon, label, chat_key) in zip(qcols, quick_prompts):
        with col:
            is_active = st.session_state.get("active_chat", "electives") == chat_key
            btn_style = f"background:{TUM_BLUE};color:white;border-radius:8px" if is_active else ""
            st.markdown(f'<div style="{btn_style}">', unsafe_allow_html=True)
            if st.button(f"{icon} {label}", use_container_width=True, key=f"nav_{chat_key}"):
                st.session_state.active_chat = chat_key
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

    st.divider()
    active_chat = st.session_state.get("active_chat", "electives")

    # ══════════════════════════════════════════════════════════
    # STUDY BUDDY — per-course tabs with PDF upload + exam prep
    # ══════════════════════════════════════════════════════════
    if active_chat == "learning_buddy":
        _lb_db = SQLiteMemory()
        _lb_courses = _lb_db.get_profile("courses") or []

        if not _lb_courses:
            st.info("No courses found in your profile yet. Sync TUMonline first via the sidebar.")
        else:
            def _short_label(name: str) -> str:
                s = re.sub(r'\s*\(.*?\)', '', name).strip()
                return s[:30] + "…" if len(s) > 30 else s

            # ── Course selector (selectbox — no cramped tabs) ──
            selected_course_label = st.selectbox(
                "📖 Select course",
                options=_lb_courses,
                format_func=_short_label,
                key="lb_selected_course",
                label_visibility="collapsed",
            )
            course_name = selected_course_label
            tab_i = _lb_courses.index(course_name)

            st.markdown(f"### 📖 {course_name}")
            st.divider()

            chat_key_lb = f"chat_lb_{tab_i}"
            quiz_mode_key = f"lb_quiz_mode_{tab_i}"
            if chat_key_lb not in st.session_state:
                st.session_state[chat_key_lb] = []

            # ── Action buttons ──
            act_col1, act_col2, act_col3 = st.columns(3)
            with act_col1:
                do_exam_plan = st.button("📝 Study Plan", key=f"examplan_{tab_i}", use_container_width=True)
            with act_col2:
                do_quiz = st.button("❓ Start Quiz", key=f"quiz_{tab_i}", use_container_width=True)
            with act_col3:
                do_clear = st.button("🗑 Clear Chat", key=f"clear_{tab_i}", use_container_width=True)

            if do_clear:
                st.session_state[chat_key_lb] = []
                st.session_state.pop(quiz_mode_key, None)
                st.rerun()

            # ── PDF uploader ──
            uploaded_file = st.file_uploader(
                "📎 Upload lecture / past exam PDF",
                type=["pdf"],
                key=f"lb_upload_{tab_i}",
                help="Upload slides or a past exam — I'll summarise or quiz you from it.",
            )
            pdf_text_key = f"lb_pdf_text_{tab_i}"
            pdf_name_key = f"lb_pdf_name_{tab_i}"
            last_up_key  = f"lb_last_up_{tab_i}"

            if uploaded_file is not None:
                if st.session_state.get(last_up_key) != uploaded_file.name:
                    try:
                        import fitz
                        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
                        extracted = "\n".join(p.get_text() for p in doc)
                        doc.close()
                    except Exception:
                        uploaded_file.seek(0)
                        extracted = uploaded_file.read().decode("utf-8", errors="ignore")
                    st.session_state[pdf_text_key] = extracted
                    st.session_state[pdf_name_key] = uploaded_file.name
                    st.session_state[last_up_key]  = uploaded_file.name
                chars = len(st.session_state.get(pdf_text_key, ""))
                st.success(f"✅ **{uploaded_file.name}** loaded ({chars:,} chars) — ask me anything below.")
            else:
                for k in (pdf_text_key, pdf_name_key, last_up_key):
                    st.session_state.pop(k, None)

            pdf_text = st.session_state.get(pdf_text_key, "")
            pdf_name = st.session_state.get(pdf_name_key, "")

            # ── Quiz mode: inject system context ──
            if do_quiz:
                st.session_state[quiz_mode_key] = True
                material_hint = f"\n\nMATERIAL:\n{pdf_text[:4000]}" if pdf_text else ""
                quiz_system = (
                    f"You are an interactive quiz master for the TUM course '{course_name}'."
                    f"{material_hint}\n\n"
                    "Rules: Ask ONE question at a time. After the student answers, give brief feedback "
                    "(correct/incorrect + explanation), then ask the next question. "
                    "Vary question types (conceptual, calculation, true/false). "
                    "Start NOW with your first question."
                )
                st.session_state[chat_key_lb].append({"role": "system_quiz", "content": quiz_system})
                _q_init = f"[QUIZ START] {quiz_system}"
                from tum_pulse.tools.bedrock_client import BedrockClient as _BC
                _first_q = _BC().invoke(_q_init, max_tokens=300)
                st.session_state[chat_key_lb].append({"role": "assistant", "content": _first_q})
                st.rerun()

            # ── Exam plan trigger ──
            _quick_prompt = None
            if do_exam_plan:
                _quick_prompt = f"Prepare a 2-week study plan for {course_name}"

            # ── Chat history ──
            chat_msgs_lb = st.session_state[chat_key_lb]
            is_quiz = st.session_state.get(quiz_mode_key, False)
            if is_quiz:
                st.info("🎯 **Quiz mode active** — answer freely, I'll give feedback and ask the next question.")

            for msg in chat_msgs_lb:
                if msg["role"] == "system_quiz":
                    continue  # hidden context, don't display
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

            # ── Chat input ──
            placeholder = (
                "Type your answer…" if is_quiz
                else f"Ask about {_short_label(course_name)}, summarise, explain…"
            )
            typed_lb = st.chat_input(placeholder, key=f"input_lb_{tab_i}")
            user_msg = _quick_prompt or typed_lb

            if user_msg:
                chat_msgs_lb.append({"role": "user", "content": user_msg})
                with st.chat_message("user"):
                    st.markdown(user_msg)

                with st.chat_message("assistant"):
                    with st.spinner("🧠 Thinking…"):
                        if is_quiz:
                            # Pass full conversation to Bedrock so it can evaluate answer + ask next
                            from tum_pulse.tools.bedrock_client import BedrockClient as _BC2
                            _bc = _BC2()
                            # Build prompt from visible history
                            history_text = "\n".join(
                                f"{'Student' if m['role']=='user' else 'Quiz Master'}: {m['content']}"
                                for m in chat_msgs_lb
                                if m["role"] in ("user", "assistant")
                            )
                            quiz_ctx = st.session_state[chat_key_lb][0]["content"] if chat_msgs_lb and chat_msgs_lb[0]["role"] == "system_quiz" else ""
                            response = _bc.invoke(
                                f"{quiz_ctx}\n\nCONVERSATION SO FAR:\n{history_text}\n\n"
                                "Now give feedback on the last student answer and ask the next question.",
                                max_tokens=400,
                            )
                        elif pdf_text:
                            from tum_pulse.agents.learning_buddy_v2 import SmartLearningBuddy
                            response = SmartLearningBuddy().run_with_pdf(user_msg, pdf_text, pdf_name)
                        else:
                            from tum_pulse.agents.learning_buddy_v2 import SmartLearningBuddy
                            enriched = user_msg if course_name.lower() in user_msg.lower() \
                                else f"{user_msg} (course: {course_name})"
                            response = SmartLearningBuddy().run(enriched)
                    st.markdown(response)
                    st.session_state.last_agent = "exam_plan"

                chat_msgs_lb.append({"role": "assistant", "content": response})
                st.rerun()

    # ══════════════════════════════════════════════════════════
    # DEADLINES / ELECTIVES / ZHS — standard chat
    # ══════════════════════════════════════════════════════════
    else:
        chat_messages = st.session_state[f"chat_{active_chat}"]

        for msg in chat_messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        if st.session_state.last_agent:
            label = _AGENT_LABELS.get(st.session_state.last_agent, st.session_state.last_agent)
            st.caption(f"Last activated: **{label}**")

        _placeholders = {
            "deadlines": "Ask about your deadlines…",
            "electives": "Ask for elective recommendations…",
            "zhs":       "Search or book ZHS sport courses…",
        }
        typed = st.chat_input(_placeholders.get(active_chat, "How can I help?"))

        if typed:
            chat_messages.append({"role": "user", "content": typed})
            with st.chat_message("user"):
                st.markdown(typed)

            with st.chat_message("assistant"):
                with st.spinner("Thinking…"):
                    response, agent_called = orchestrator_run(
                        typed,
                        thread_id=student_name or st.session_state.tum_username or "default",
                    )
                st.markdown(response)
                st.session_state.last_agent = agent_called

            # Context-aware feedback badges
            if agent_called in ("elective_advice", "exam_plan", "deadlines"):
                _fb_db = SQLiteMemory()
                _fb_grades = _fb_db.get_profile("grades") or {}
                _weak = [c for c, g in _fb_grades.items() if isinstance(g, (int, float)) and g > 2.3]
                _urgent = _fb_db.get_upcoming_deadlines(days=3)
                if agent_called in ("elective_advice", "exam_plan"):
                    if _weak:
                        st.info(f"📉 Weak subjects considered: {', '.join(_weak[:3])}")
                    if _urgent:
                        st.warning("⚠️ Upcoming deadlines detected — recommendations adapted for time pressure")
                if agent_called == "elective_advice":
                    st.success("🎯 Personalised using your grades and course history")
                elif agent_called == "exam_plan":
                    st.success("🧠 Study plan adapted to your weak subjects and available time")
                elif agent_called == "deadlines":
                    st.success("📅 Aggregated live from TUMonline, Moodle and Confluence")

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
            "live":    "🟢 live",
            "mock":    "🟠 demo",
            "failed":  "🔴 failed",
            "skipped": "⚫ skipped",
            "not run": "⚪ not run",
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
    _tab_enrolled = db.get_profile("enrolled") or db.get_profile("courses") or []

    _DL_STOPWORDS = frozenset({
        "which","their","these","those","about","other","where","there",
        "using","seminar","systems","master","introduction",
    })

    def _dl_key_words(name: str) -> list[str]:
        import re as _re
        clean = _re.sub(r'\([A-Z]{1,4}\d{3,}[^)]*\)', '', name).lower()
        return [w for w in _re.split(r'\W+', clean) if len(w) > 3 and w not in _DL_STOPWORDS]

    def _deadline_matches_enrolled(dl: dict) -> bool:
        import re as _re
        if dl.get("course") == "TUM Administration":
            return True
        title = dl.get("title", "").strip()
        if title.startswith(("Exam Registration Deadline", "Course Registration",
                              "Re-enrollment", "Semester Contribution", "Exmatriculation")):
            return True
        if not _tab_enrolled:
            return True  # no enrollment data yet — show everything
        text = (title + " " + (dl.get("course") or "")).lower()
        for enr in _tab_enrolled:
            codes = _re.findall(r'[A-Z]{1,4}\d{3,}', enr)
            if any(c.lower() in text for c in codes):
                return True
            words = _dl_key_words(enr)
            if not words:
                continue
            hits = sum(1 for w in words if w in text)
            threshold = 1 if len(words) == 1 else 2
            if hits >= threshold:
                return True
        return False

    _all_deadlines = db.get_upcoming_deadlines(days=120)
    deadlines = [d for d in _all_deadlines if _deadline_matches_enrolled(d)]

    is_mock_preview = False
    if not deadlines:
        st.info(
            "No deadlines synced yet. Hit **🔄 Refresh** in the sidebar to pull live data "
            "from TUMonline and Moodle."
        )

    # ── Calendar helpers ────────────────────────────────────────────────
    def _gcal_url(title: str, date_str: str, details: str = "") -> str:
        """Build a Google Calendar 'add event' URL for a single deadline."""
        import urllib.parse
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d")
            date_compact = d.strftime("%Y%m%d")
            next_day = (d + timedelta(days=1)).strftime("%Y%m%d")
        except ValueError:
            return ""
        params = {
            "action": "TEMPLATE",
            "text": title,
            "dates": f"{date_compact}/{next_day}",
            "details": details or f"TUM Easy deadline — {title}",
        }
        return "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(params)

    def _build_ics(deadlines_list: list[dict]) -> bytes:
        """Generate iCalendar (.ics) bytes for a list of deadline dicts."""
        import uuid
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//TUM Easy//TUM Deadlines//EN",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
        ]
        for dl in deadlines_list:
            try:
                d = datetime.strptime(dl["deadline_date"], "%Y-%m-%d")
                date_compact = d.strftime("%Y%m%d")
                next_day = (d + timedelta(days=1)).strftime("%Y%m%d")
            except ValueError:
                continue
            uid = str(uuid.uuid4()) + "@tumeasy"
            title = dl["title"].replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")
            course = dl.get("course", "").replace(",", "\\,")
            source = dl.get("source", "")
            lines += [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTART;VALUE=DATE:{date_compact}",
                f"DTEND;VALUE=DATE:{next_day}",
                f"SUMMARY:{title}",
                f"DESCRIPTION:Course: {course}\\nSource: {source}",
                "STATUS:CONFIRMED",
                "BEGIN:VALARM",
                "TRIGGER:-P1D",
                "ACTION:DISPLAY",
                f"DESCRIPTION:Reminder: {title}",
                "END:VALARM",
                "END:VEVENT",
            ]
        lines.append("END:VCALENDAR")
        return "\r\n".join(lines).encode("utf-8")

    # ── Export bar ──────────────────────────────────────────────────────
    exp_col1, exp_col2 = st.columns([1, 3])
    with exp_col1:
        if deadlines and not is_mock_preview:
            ics_bytes = _build_ics(deadlines)
            st.download_button(
                label="📥 Export All (.ics)",
                data=ics_bytes,
                file_name="tum_deadlines.ics",
                mime="text/calendar",
                use_container_width=True,
                help="Import into Apple Calendar, Google Calendar, Outlook, etc.",
            )

    _SOURCE_ICON = {
        "tumonline":  "🏛️ TUMonline",
        "moodle":     "📘 Moodle",
        "confluence": "📝 Wiki",
        "mock":       "🔶 Demo",
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
        st.caption(f"{len(deadlines)} real deadline(s) from your TUM account ✅")

    this_week = [d for d in db.get_upcoming_deadlines(days=7) if _deadline_matches_enrolled(d)] if not is_mock_preview else []
    if this_week:
        st.markdown(f"<h3 style='color:{TUM_DARK_BLUE};margin-top:24px'>This Week</h3>", unsafe_allow_html=True)
        for dl in this_week:
            try:
                days_left = (datetime.strptime(dl["deadline_date"], "%Y-%m-%d").date() - datetime.now().date()).days
            except (ValueError, TypeError):
                days_left = 999
            icon = "🔴" if days_left <= 1 else "🟠" if days_left <= 3 else "🟡"
            gcal = _gcal_url(
                dl["title"],
                dl["deadline_date"],
                f"Course: {dl.get('course', '')} | Source: {dl.get('source', '')}",
            )
            ics_single = _build_ics([dl])
            card_col, btn_col1, btn_col2 = st.columns([5, 1, 1])
            with card_col:
                st.markdown(
                    f"<div class='tum-card{' tum-card-orange' if days_left <= 1 else ''}'>"
                    f"{icon} <b>{dl['deadline_date']}</b> &nbsp;—&nbsp; {dl['title']}<br>"
                    f"<span style='color:#888;font-size:0.85rem'>{dl.get('course','')}</span></div>",
                    unsafe_allow_html=True,
                )
            with btn_col1:
                if gcal:
                    st.link_button("📅 Google Cal", gcal, use_container_width=True)
            with btn_col2:
                st.download_button(
                    "📥 .ics",
                    data=ics_single,
                    file_name=f"deadline_{dl['deadline_date']}.ics",
                    mime="text/calendar",
                    use_container_width=True,
                    key=f"ics_{dl.get('id', dl['title'][:20])}",
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

                    if st.button("📌 Register", key=f"book_{i}", use_container_width=False):
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
        3. Click <b>Register</b> to register — confirmation sent to your TUM email
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
