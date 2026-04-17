"""LangGraph orchestrator — routes user input to the correct TUM Pulse agent."""

from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from tum_pulse.agents.advisor import AdvisorAgent
from tum_pulse.agents.executor import ExecutorAgent
from tum_pulse.agents.learning_buddy import LearningBuddyAgent
from tum_pulse.agents.watcher import WatcherAgent
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


# ---------------------------------------------------------------------------
# Routing helpers
# ---------------------------------------------------------------------------

_INTENT_PROMPT_TEMPLATE = """You are an intent classifier for a TUM student assistant.
Classify the user's message into exactly ONE of these categories:
- deadlines        (asking about upcoming exams, assignments, submission due dates)
- zhs_registration (wants to register for a ZHS sport course or activity)
- elective_advice  (wants course recommendations or help choosing electives)
- exam_plan        (wants help preparing for an exam, study plans, past papers)
- general          (anything else: greetings, factual questions, small talk)

User message: "{user_input}"

Reply with ONLY the category name, nothing else."""


def _classify_intent(user_input: str, bedrock: BedrockClient) -> str:
    """Use Claude to classify the user's intent into a routing category."""
    prompt = _INTENT_PROMPT_TEMPLATE.format(user_input=user_input)
    raw = bedrock.invoke(prompt, max_tokens=20).strip().lower()

    valid = {"deadlines", "zhs_registration", "elective_advice", "exam_plan", "general"}
    for category in valid:
        if category in raw:
            return category
    return "general"


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------

def router_node(state: OrchestratorState) -> OrchestratorState:
    """Classify intent and store the routing decision in state."""
    bedrock = BedrockClient()
    intent = _classify_intent(state["user_input"], bedrock)
    return {**state, "agent_called": intent}


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
    response = agent.run(state["user_input"])
    return {**state, "response": response}


def learning_buddy_node(state: OrchestratorState) -> OrchestratorState:
    """Delegate to LearningBuddyAgent for exam planning."""
    agent = LearningBuddyAgent()
    response = agent.run(state["user_input"])
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
