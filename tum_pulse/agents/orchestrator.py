"""LangGraph orchestrator — routes user input to the correct TUM Pulse agent."""

import json
import re
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from tum_pulse.agents.advisor import AdvisorAgent
from tum_pulse.agents.executor import ExecutorAgent
from tum_pulse.agents.learning_buddy import LearningBuddyAgent
from tum_pulse.agents.watcher import WatcherAgent
from tum_pulse.memory.database import SQLiteMemory
from tum_pulse.tools.bedrock_client import BedrockClient


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
# Routing helpers
# ---------------------------------------------------------------------------

_INTENT_PROMPT_TEMPLATE = """You are an intelligent routing assistant for a TUM student app.

USER MESSAGE:
{user_input}

STUDENT CONTEXT:
Courses: {courses}
Weak subjects (grades > 2.3): {weak_subjects}
Upcoming deadlines (next 7 days): {upcoming}
Time pressure: {time_pressure}
Recent conversation: {history}

Classify the message into exactly ONE of:
- deadlines        (asking about upcoming exams, assignments, submission deadlines)
- zhs_registration (wants to register for a ZHS sport course or activity)
- elective_advice  (wants course recommendations or help choosing electives)
- exam_plan        (wants help preparing for an exam, study plans, past papers)
- general          (anything else: greetings, factual questions, small talk)

ROUTING RULES:
- If the user uses "it", "this", "that" → resolve via conversation history
- If weak subjects or upcoming exams are involved → prefer exam_plan
- If deadlines are urgent (time_pressure=high) → prefer deadlines

Return ONLY valid JSON, nothing else:
{{
  "intent": "<one of the 5 categories>",
  "confidence": <0.0 to 1.0>,
  "reason": "<one sentence explanation>"
}}"""


def _classify_intent(
    user_input: str, context: dict, bedrock: BedrockClient
) -> str:
    """Classify user intent using Claude with full student context.

    Args:
        user_input: The raw message from the student.
        context: Rich context dict from _build_context().
        bedrock: Bedrock client for Claude invocation.

    Returns:
        One of: deadlines, zhs_registration, elective_advice,
        exam_plan, general.
    """
    prompt = _INTENT_PROMPT_TEMPLATE.format(
        user_input=user_input,
        courses=context.get("courses", []),
        weak_subjects=context.get("weak_subjects", []),
        upcoming=context.get("upcoming", []),
        time_pressure=context.get("time_pressure", "unknown"),
        history=context.get("history", []),
    )
    raw = bedrock.invoke(prompt, max_tokens=150).strip()

    try:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            intent = data.get("intent", "general").strip().lower()
            valid = {
                "deadlines", "zhs_registration",
                "elective_advice", "exam_plan", "general",
            }
            return intent if intent in valid else "general"
    except Exception:
        pass

    # Fallback: scan raw text for any valid category keyword
    valid = {
        "deadlines", "zhs_registration",
        "elective_advice", "exam_plan", "general",
    }
    for cat in valid:
        if cat in raw.lower():
            return cat
    return "general"


def _build_context(state: dict | None = None) -> dict:
    """Build rich context from SQLite profile and conversation state.

    Computes weak subjects, time pressure from upcoming deadlines,
    and recent conversation history for context-aware routing.

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
    """Classify intent with full student context and store routing decision.

    Builds context first (so time pressure and weak subjects are available
    to influence routing), then classifies intent using that context.
    """
    bedrock = BedrockClient()
    context = _build_context(state)
    intent = _classify_intent(state["user_input"], context, bedrock)
    return {**state, "agent_called": intent, "context": context}


def watcher_node(state: OrchestratorState) -> OrchestratorState:
    """Delegate to WatcherAgent for deadline queries."""
    agent = WatcherAgent()
    # Run the scraper then return this week's deadlines for the response
    agent.run()
    response = agent.get_this_week()
    return {**state, "response": response}


def executor_node(state: OrchestratorState) -> OrchestratorState:
    """Delegate to ExecutorAgent for ZHS registration tasks."""
    agent = ExecutorAgent()
    response = agent.run(state["user_input"])
    return {**state, "response": response}


def advisor_node(state: OrchestratorState) -> OrchestratorState:
    """Delegate to AdvisorAgent for elective recommendations."""
    agent = AdvisorAgent()
    response = agent.run(state["user_input"], context=state.get("context", {}))
    return {**state, "response": response}


def learning_buddy_node(state: OrchestratorState) -> OrchestratorState:
    """Delegate to LearningBuddyAgent for exam planning."""
    agent = LearningBuddyAgent()
    response = agent.run(state["user_input"], context=state.get("context", {}))
    return {**state, "response": response}


def general_node(state: OrchestratorState) -> OrchestratorState:
    """Handle general questions directly via Claude."""
    bedrock = BedrockClient()
    system = (
        "You are TUM Pulse, a helpful AI assistant for TU Munich students. "
        "You help with deadlines, course recommendations, ZHS sport registration, and exam planning. "
        "Be concise, friendly, and accurate."
    )
    response = bedrock.invoke(state["user_input"], system=system)
    return {**state, "response": response}


# ---------------------------------------------------------------------------
# Routing edge
# ---------------------------------------------------------------------------

def route_by_intent(state: OrchestratorState) -> str:
    """Return the next node name based on the classified intent."""
    mapping = {
        "deadlines": "watcher",
        "zhs_registration": "executor",
        "elective_advice": "advisor",
        "exam_plan": "learning_buddy",
        "general": "general",
    }
    return mapping.get(state.get("agent_called", "general"), "general")


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph() -> StateGraph:
    """Build and compile the LangGraph orchestrator."""
    graph = StateGraph(OrchestratorState)

    graph.add_node("router", router_node)
    graph.add_node("watcher", watcher_node)
    graph.add_node("executor", executor_node)
    graph.add_node("advisor", advisor_node)
    graph.add_node("learning_buddy", learning_buddy_node)
    graph.add_node("general", general_node)

    graph.set_entry_point("router")

    graph.add_conditional_edges(
        "router",
        route_by_intent,
        {
            "watcher": "watcher",
            "executor": "executor",
            "advisor": "advisor",
            "learning_buddy": "learning_buddy",
            "general": "general",
        },
    )

    for node in ("watcher", "executor", "advisor", "learning_buddy", "general"):
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
