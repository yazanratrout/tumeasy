"""LangGraph orchestrator — routes user input to the correct TUM Pulse agent.

OPTIMIZED: Uses fast heuristic routing (keyword + context signals) instead of LLM.
This reduces routing latency from ~1000ms to <10ms while delegating complex
reasoning to the agents themselves.
"""

import json
import re
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from tum_pulse.agents.advisor import AdvisorAgent
from tum_pulse.agents.executor import ExecutorAgent
from tum_pulse.agents.learning_buddy_v2 import SmartLearningBuddy
from tum_pulse.agents.watcher import WatcherAgent
from tum_pulse.memory.database import SQLiteMemory
from tum_pulse.tools.bedrock_client import BedrockClient, HAIKU
from tum_pulse.tools.llm_cache import LLMCache


# ---------------------------------------------------------------------------
# State definition
# ---------------------------------------------------------------------------

class OrchestratorState(TypedDict):
    """Shared state passed between graph nodes."""

    messages: list[dict]
    user_input: str
    agent_called: str
    response: str
    context: dict


# ---------------------------------------------------------------------------
# Fast heuristic routing (no LLM)
# ---------------------------------------------------------------------------

# Keyword patterns for each intent category
_INTENT_KEYWORDS = {
    "deadlines": {
        "keywords": [
            "deadline", "deadlines", "submission",
            "due", "when is", "when are", "upcoming", "coming up",
            "when do i", "when do we", "final exam", "midterm",
        ],
        "priority": 3,  # Higher priority keyword match
    },
    "zhs_registration": {
        "keywords": [
            "zhs", "sport", "activity",
            "badminton", "tennis", "yoga", "gym", "swimming", "schwimmen",
            "bouldern", "climbing", "pilates", "volleyball", "basketball",
        ],
        "priority": 4,   # ZHS keywords are specific — high priority
    },
    "course_registration": {
        "keywords": [
            "register", "enroll", "sign up for",
            "anmelden", "lv anmeldung", "course registration",
            "register for lecture", "register for seminar", "register for lab",
            "enroll in course", "book course", "add course",
        ],
        "priority": 4,
    },
    "course_deregistration": {
        "keywords": [
            "drop course", "deregister", "unenroll", "abmelden",
            "withdraw from", "cancel course", "leave course",
            "drop lecture", "drop seminar", "remove course",
        ],
        "priority": 5,   # higher than course_registration so "deregister" beats "register"
    },
    "forum_post": {
        "keywords": [
            "post in forum", "write in forum", "forum post",
            "post to forum", "send to forum", "moodle forum",
            "write to class", "announce in", "discussion post",
            "study group post", "forum message",
        ],
        "priority": 4,
    },
    "elective_advice": {
        "keywords": [
            "elective", "course recommendation", "recommend",
            "should i take", "which course", "what course",
            "next semester", "choose", "selection", "major",
            "specialization", "track"
        ],
        "priority": 2,
    },
    "exam_plan": {
        "keywords": [
            "prepare", "preparation", "study", "studying", "studying for",
            "past papers", "practice", "revision", "help prepare",
            "exam help", "study plan", "learning", "tutoring",
            "explanation", "exam prep", "help studying"
        ],
        "priority": 2,
    },
}


def _classify_intent_heuristic(user_input: str, context: dict) -> str:
    """Fast heuristic routing based on keywords and context signals.

    This avoids the ~1000ms LLM call by using keyword matching + context rules.
    Complex reasoning is deferred to the agents themselves.

    Args:
        user_input: The raw message from the student.
        context: Context dict with courses, grades, deadlines, time_pressure.

    Returns:
        One of: deadlines, zhs_registration, elective_advice,
        exam_plan, general.
    """
    user_lower = user_input.lower()
    scores = {}

    # 1. Keyword matching
    for intent, config in _INTENT_KEYWORDS.items():
        keyword_count = sum(
            1 for kw in config["keywords"] if kw in user_lower
        )
        if keyword_count > 0:
            scores[intent] = keyword_count * config["priority"]

    # 2. Context-based signals
    time_pressure = context.get("time_pressure", "unknown")
    weak_subjects = context.get("weak_subjects", [])
    upcoming = context.get("upcoming", [])

    # High time pressure + upcoming deadlines → boost deadlines
    if time_pressure == "high" and upcoming:
        scores["deadlines"] = scores.get("deadlines", 0) + 2

    # Weak subjects + mention of exam/study → boost exam_plan
    if weak_subjects and any(w in user_lower for w in weak_subjects):
        scores["exam_plan"] = scores.get("exam_plan", 0) + 1.5

    # 3. Return highest-scoring intent, fallback to general
    if scores:
        return max(scores, key=scores.get)

    return "general"


def _build_context(state: dict | None = None) -> dict:
    """Build context from SQLite profile for routing decisions.

    Computes weak subjects, time pressure from upcoming deadlines, etc.
    This is fast and used only for heuristic routing, not LLM calls.

    Args:
        state: Current orchestrator state (used to extract message history).

    Returns:
        Context dict with grades, courses, upcoming, weak_subjects,
        time_pressure, and history keys.
    """
    from datetime import datetime
    try:
        db = SQLiteMemory()
        grades = db.get_profile("grades") or {}
        courses = (
            db.get_profile("courses") or
            db.get_profile("enrolled") or []
        )
        deadlines = db.get_upcoming_deadlines(days=7)

        weak_subjects = [
            c for c, g in grades.items()
            if isinstance(g, (int, float)) and g > 2.3
        ]

        try:
            days_left = [
                (
                    datetime.strptime(d["deadline_date"], "%Y-%m-%d").date()
                    - datetime.now().date()
                ).days
                for d in deadlines
                if d.get("deadline_date")
            ]
            time_pressure = (
                "high"   if any(d <= 2 for d in days_left) else
                "medium" if any(d <= 7 for d in days_left) else
                "low"
            )
        except Exception:
            time_pressure = "unknown"

        history: list = []
        if state and "messages" in state:
            history = state["messages"][-3:]

        return {
            "grades":        grades,
            "courses":       courses,
            "upcoming":      deadlines,
            "weak_subjects": weak_subjects,
            "time_pressure": time_pressure,
            "history":       history,
        }
    except Exception:
        return {
            "grades": {}, "courses": [], "upcoming": [],
            "weak_subjects": [], "time_pressure": "unknown",
            "history": [],
        }


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------

def router_node(state: OrchestratorState) -> OrchestratorState:
    """Fast heuristic routing without LLM call.

    Builds context and classifies intent using keywords + context signals,
    avoiding the ~1000ms LLM latency. Complex reasoning is handled by agents.
    """
    context = _build_context(state)
    intent = _classify_intent_heuristic(state["user_input"], context)
    return {**state, "agent_called": intent, "context": context}


def watcher_node(state: OrchestratorState) -> OrchestratorState:
    """Delegate to WatcherAgent for deadline queries.

    Passes the user's original message so the time range is parsed
    correctly (e.g. 'deadlines this month' → 30 days).
    Passes context so weak subjects are flagged in the response.
    """
    agent = WatcherAgent()
    agent.run()
    response = agent.get_this_week(
        user_input=state.get("user_input", ""),
        context=state.get("context", {}),
    )
    return {**state, "response": response}


def executor_node(state: OrchestratorState) -> OrchestratorState:
    """Delegate to ExecutorAgent for ZHS, course registration, or forum tasks."""
    agent = ExecutorAgent()
    response = agent.run(state["user_input"], context=state.get("context", {}))
    return {**state, "response": response}


def course_reg_node(state: OrchestratorState) -> OrchestratorState:
    """Delegate to ExecutorAgent for TUMonline academic course registration."""
    agent = ExecutorAgent()
    response = agent.register_academic_course(
        _extract_course_name(state["user_input"])
    )
    return {**state, "response": response}


def course_dereg_node(state: OrchestratorState) -> OrchestratorState:
    """Delegate to ExecutorAgent for TUMonline course deregistration."""
    agent = ExecutorAgent()
    response = agent.deregister_academic_course(
        _extract_course_name(state["user_input"])
    )
    return {**state, "response": response}


def forum_post_node(state: OrchestratorState) -> OrchestratorState:
    """Delegate to ExecutorAgent for Moodle forum posting."""
    import re as _re
    agent = ExecutorAgent()
    task  = state["user_input"]
    # Parse: course name + message
    msg_match = _re.search(r'(?:post|write|say|message)[:\s]+(.+)', task, _re.IGNORECASE)
    message   = msg_match.group(1).strip() if msg_match else task
    subj_match = _re.search(r'(?:subject|title)[:\s]+["\']?([^"\']+)["\']?', task, _re.IGNORECASE)
    subject    = subj_match.group(1).strip() if subj_match else ""
    # Guess course from context or task
    context_courses = state.get("context", {}).get("courses", [])
    course = context_courses[0] if context_courses else "General"
    for kw in ("for ", "in ", "to "):
        idx = task.lower().find(kw)
        if idx != -1:
            candidate = task[idx + len(kw):].split(":")[0].strip(".,")
            if candidate:
                course = candidate
                break
    response = agent.post_forum(course, message, subject)
    return {**state, "response": response}


def _extract_course_name(text: str) -> str:
    """Extract course name from a registration/deregistration sentence."""
    import re as _re
    m = _re.search(r'["\']([^"\']+)["\']', text)
    if m:
        return m.group(1).strip()
    for marker in ["for ", "in ", "from ", "drop ", "anmelden ", "abmelden ", "enroll in ", "register for "]:
        idx = text.lower().find(marker)
        if idx != -1:
            return text[idx + len(marker):].strip(".,!?").split("\n")[0]
    return text.strip()


def advisor_node(state: OrchestratorState) -> OrchestratorState:
    """Delegate to AdvisorAgent for elective recommendations."""
    agent = AdvisorAgent()
    response = agent.run(state["user_input"], context=state.get("context", {}))
    return {**state, "response": response}


def learning_buddy_node(state: OrchestratorState) -> OrchestratorState:
    """Delegate to SmartLearningBuddy for study plans and lecture summaries.
    
    Uses cache for fast course/document selection, then generates summaries or plans.
    """
    try:
        agent = SmartLearningBuddy()
        response = agent.run(state["user_input"], context=state.get("context", {}))
    except Exception as e:
        response = f"[SmartLearningBuddy Error] {str(e)}"
    return {**state, "response": response}


def general_node(state: OrchestratorState) -> OrchestratorState:
    """Handle general questions via Haiku (fast, cached 1h)."""
    bedrock = BedrockClient()
    llm_cache = LLMCache()
    system = (
        "You are TUM Pulse, a helpful AI assistant for TU Munich students. "
        "You help with deadlines, course recommendations, ZHS sport registration, and exam planning. "
        "Be concise, friendly, and accurate."
    )
    context = state.get("context", {})
    context_str = ""
    if context.get("courses"):
        context_str += f"\nStudent's courses: {context['courses']}"
    if context.get("weak_subjects"):
        context_str += f"\nWeak subjects to strengthen: {context['weak_subjects']}"

    user_msg = state["user_input"]
    if context_str:
        user_msg = f"{user_msg}{context_str}"

    cached = llm_cache.get(user_msg, model=HAIKU)
    if cached:
        return {**state, "response": cached}

    response = bedrock.invoke(user_msg, system=system, model=HAIKU)
    llm_cache.set(user_msg, response, ttl_seconds=3600, model=HAIKU)
    return {**state, "response": response}


# ---------------------------------------------------------------------------
# Routing edge
# ---------------------------------------------------------------------------

def route_by_intent(state: OrchestratorState) -> str:
    """Return the next node name based on the classified intent."""
    mapping = {
        "deadlines":            "watcher",
        "zhs_registration":     "executor",
        "course_registration":  "course_reg",
        "course_deregistration": "course_dereg",
        "forum_post":           "forum_post",
        "elective_advice":      "advisor",
        "exam_plan":            "learning_buddy",
        "general":              "general",
    }
    return mapping.get(state.get("agent_called", "general"), "general")


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph() -> StateGraph:
    """Build and compile the LangGraph orchestrator."""
    graph = StateGraph(OrchestratorState)

    graph.add_node("router",       router_node)
    graph.add_node("watcher",      watcher_node)
    graph.add_node("executor",     executor_node)
    graph.add_node("course_reg",   course_reg_node)
    graph.add_node("course_dereg", course_dereg_node)
    graph.add_node("forum_post",   forum_post_node)
    graph.add_node("advisor",      advisor_node)
    graph.add_node("learning_buddy", learning_buddy_node)
    graph.add_node("general",      general_node)

    graph.set_entry_point("router")

    graph.add_conditional_edges(
        "router",
        route_by_intent,
        {
            "watcher":      "watcher",
            "executor":     "executor",
            "course_reg":   "course_reg",
            "course_dereg": "course_dereg",
            "forum_post":   "forum_post",
            "advisor":      "advisor",
            "learning_buddy": "learning_buddy",
            "general":      "general",
        },
    )

    for node in ("watcher", "executor", "course_reg", "course_dereg", "forum_post",
                 "advisor", "learning_buddy", "general"):
        graph.add_edge(node, END)

    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)


# Singleton compiled graph
_compiled_graph = None


def get_graph():
    """Return the compiled graph, building it once on first call."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run(user_input: str, thread_id: str = "default") -> tuple[str, str]:
    """Run the orchestrator for a single user message.

    Args:
        user_input: The student's message.
        thread_id: Conversation thread identifier for checkpointing.

    Returns:
        Tuple of (response_text, agent_called).
    """
    graph = get_graph()
    initial_state: OrchestratorState = {
        "messages": [{"role": "user", "content": user_input}],
        "user_input": user_input,
        "agent_called": "",
        "response": "",
        "context": {},
    }
    config = {"configurable": {"thread_id": thread_id}}

    try:
        final_state = graph.invoke(initial_state, config=config)
        return final_state.get("response", "No response generated."), final_state.get("agent_called", "general")
    except Exception as exc:
        return f"[Orchestrator error] {exc}", "error"


if __name__ == "__main__":
    test_inputs = [
        "What deadlines do I have this week?",
        "Register me for Badminton at ZHS on Friday",
        "What electives should I take next semester?",
        "Help me prepare for my Analysis 2 exam",
        "What is TUM known for?",
    ]
    for msg in test_inputs:
        response, agent = run(msg)
        print(f"\n[{agent.upper()}] {msg}\n→ {response[:200]}")
