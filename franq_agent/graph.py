from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from .utils.nodes import (
    classify_question,
    execute_sql,
    finalize_answer,
    generate_sql,
    plan_query,
    repair_sql,
    resolve_context,
    schema_discovery,
    sql_guardrail,
)
from .utils.state import AgentState


def _route_after_classify(state: AgentState) -> str:
    """Skip the SQL pipeline entirely for greetings / meta questions."""
    return "schema" if state.get("requires_sql") else "finalize"


def _route_after_execution(state: AgentState) -> str:
    """Retry with repair up to MAX_REPAIR_ATTEMPTS times, then give up gracefully."""
    if state.get("execution_error"):
        attempts = state.get("repair_attempts") or 0
        if attempts < 3:
            return "repair"
        return "finalize"
    return "finalize"


def build_graph() -> CompiledStateGraph:
    builder = StateGraph(AgentState)

    builder.add_node("resolve_context", resolve_context)
    builder.add_node("classify", classify_question)
    builder.add_node("schema", schema_discovery)
    builder.add_node("planner", plan_query)
    builder.add_node("generate_sql", generate_sql)
    builder.add_node("guardrail", sql_guardrail)
    builder.add_node("execute", execute_sql)
    builder.add_node("repair", repair_sql)
    builder.add_node("finalize", finalize_answer)

    builder.set_entry_point("resolve_context")
    builder.add_edge("resolve_context", "classify")
    builder.add_edge("schema", "planner")
    builder.add_edge("planner", "generate_sql")
    builder.add_edge("generate_sql", "guardrail")
    builder.add_edge("guardrail", "execute")
    builder.add_edge("repair", "guardrail")
    builder.add_edge("finalize", END)

    builder.add_conditional_edges(
        "classify",
        _route_after_classify,
        {"schema": "schema", "finalize": "finalize"},
    )
    builder.add_conditional_edges(
        "execute",
        _route_after_execution,
        {"finalize": "finalize", "repair": "repair"},
    )

    return builder.compile(checkpointer=MemorySaver())
