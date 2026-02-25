from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from franq_agent.utils.state import AgentState, DataVizType, QuestionType
from franq_agent.utils.db import execute_query, format_schema, get_schema
from typing import Any
import json
from utils import strip_code_fence


llm = ChatAnthropic(
    model_name="claude-sonnet-4-6", temperature=0, timeout=None, stop=None
)

FORBIDDEN_KEYWORDS = {
    "DROP",
    "DELETE",
    "UPDATE",
    "INSERT",
    "CREATE",
    "ALTER",
    "TRUNCATE",
    "REPLACE",
}
MAX_REPAIR_ATTEMPTS = 3


def resolve_context(state: AgentState) -> AgentState:
    """Rewrites follow-up questions into standalone questions using conversation history."""
    question = state["question"]
    messages: list[dict[str, str]] = state.get("messages") or []
    last_summary = state.get("last_result_summary")
    last_sql = state.get("last_sql_query")

    if not messages:
        state["resolved_question"] = question
        state["messages"] = [{"role": "user", "content": question}]
        return state

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """You are a query contextualizer.
Your job is to rewrite follow-up questions into fully self-contained questions using the conversation history.
If the question is NOT a follow-up, return it unchanged.
Return only the rewritten question, nothing else.""",
            ),
            (
                "human",
                """Conversation history:
{messages}

Last SQL executed:
{last_sql}

Last result summary:
{last_summary}

New question:
{question}""",
            ),
        ]
    )

    response = llm.invoke(
        prompt.format_messages(
            messages=messages,
            last_sql=last_sql or "N/A",
            last_summary=last_summary or "N/A",
            question=question,
        )
    )

    state["resolved_question"] = str(response.content)
    state["messages"] = messages + [{"role": "user", "content": question}]
    return state


def classify_question(state: AgentState) -> AgentState:
    """Decides whether the question needs SQL or can be answered directly."""
    question = state.get("resolved_question")
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """You are a classifier for a business data analytics assistant backed by a SQLite database.
Classify questions into exactly one of:
- "sql"    → requires querying the database to answer
- "direct" → greeting, meta question, or answerable without data

Respond with ONLY the word: sql  OR  direct""",
            ),
            (
                "human",
                "Question: {question}",
            ),
        ]
    )
    response = llm.invoke(prompt.format_messages(question=question))
    raw = str(response.content).strip().lower()

    try:
        question_type = QuestionType(raw)
    except ValueError:
        question_type = QuestionType.SQL

    state["question_type"] = question_type
    state["requires_sql"] = question_type == QuestionType.SQL
    return state


def schema_discovery(state: AgentState) -> AgentState:
    """Fetches the live database schema dynamically — no hardcoding."""
    state["schema"] = get_schema()
    return state


def plan_query(state: AgentState) -> AgentState:
    """Creates a reasoning plan before generating SQL."""
    question = state.get("resolved_question") or state["question"]
    schema: dict[str, list[dict[str, Any]]] = state.get("schema") or {}
    schema_text = format_schema(schema)

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """You are a senior data analyst. Plan how to answer business questions using a database.

Always respond with ONLY valid JSON, no markdown, with this structure:
{{
  "steps": ["list of reasoning steps"],
  "tables_needed": ["table names required"],
  "approach": "one-sentence description of the SQL strategy"
}}""",
            ),
            (
                "human",
                """Schema:
{schema}

Question: {question}""",
            ),
        ]
    )

    response = llm.invoke(prompt.format_messages(schema=schema_text, question=question))
    content = strip_code_fence(str(response.content))

    try:
        plan = json.loads(content)
    except json.JSONDecodeError:
        plan = {"steps": ["Direct query"], "tables_needed": [], "approach": content}

    state["plan"] = plan
    return state


def generate_sql(state: AgentState) -> AgentState:
    """Generates a SQLite SELECT query from the plan."""
    question = state.get("resolved_question") or state["question"]
    schema: dict[str, list[dict[str, Any]]] = state.get("schema") or {}
    schema_text = format_schema(schema)
    plan = state.get("plan") or {}

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """You are a SQLite expert. Write a single SELECT query to answer the question.

Rules:
- Only SELECT statements (no writes)
- All column/table names must exist in the schema provided
- Verify the categorical_columns and the values to match the words before filtering the data
- Use proper SQLite date functions where needed (strftime, date, etc.)
- Return ONLY the SQL query, no explanation, no markdown""",
            ),
            (
                "human",
                """Schema:
{schema}

Query plan:
{plan}

Question: {question}""",
            ),
        ]
    )

    response = llm.invoke(
        prompt.format_messages(
            schema=schema_text, plan=json.dumps(plan), question=question
        )
    )

    state["sql_query"] = strip_code_fence(str(response.content))
    state["repair_attempts"] = 0
    state["execution_error"] = None
    return state


def sql_guardrail(state: AgentState) -> AgentState:
    """Blocks any non-SELECT SQL before it reaches the executor."""
    sql = state.get("sql_query") or ""

    for kw in FORBIDDEN_KEYWORDS:
        if kw in sql.upper().split():
            state["execution_error"] = (
                f"Safety block: SQL contains forbidden keyword '{kw}'. "
                "Only read-only SELECT statements are permitted."
            )
            state["sql_query"] = None
            return state

    return state


def execute_sql(state: AgentState) -> AgentState:
    """Runs the SQL query against the SQLite database."""
    sql = state.get("sql_query")

    if not sql:
        return state

    try:
        results = execute_query(sql)
        state["query_result"] = results
        state["execution_error"] = None
        state["last_sql_query"] = sql
    except Exception as exc:
        state["execution_error"] = str(exc)
        state["query_result"] = None

    return state


def repair_sql(state: AgentState) -> AgentState:
    """Asks the LLM to fix the broken SQL using the error message as feedback."""
    question = state.get("resolved_question") or state["question"]
    schema: dict[str, list[dict[str, Any]]] = state.get("schema") or {}
    schema_text = format_schema(schema)
    failed_sql = state.get("sql_query") or state.get("last_sql_query") or ""
    error = state.get("execution_error") or "Unknown error"

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """You are a SQLite expert fixing a broken query.
Return ONLY the corrected SQL query, no explanation, no markdown.""",
            ),
            (
                "human",
                """Schema:
{schema}

Original question: {question}

Broken SQL:
{sql}

Error:
{error}""",
            ),
        ]
    )

    response = llm.invoke(
        prompt.format_messages(
            schema=schema_text, question=question, sql=failed_sql, error=error
        )
    )

    state["sql_query"] = strip_code_fence(str(response.content))
    state["repair_attempts"] = (state.get("repair_attempts") or 0) + 1
    state["execution_error"] = None
    return state


def finalize_answer(state: AgentState) -> AgentState:
    """Interprets SQL results, picks visualization, and produces the final answer."""
    question = state.get("resolved_question") or state["question"]
    question_type = state.get("question_type")
    results: list[dict[str, Any]] = state.get("query_result") or []
    sql = state.get("last_sql_query") or ""
    error = state.get("execution_error")

    # ── Direct question (no SQL needed) ───────────────────────────────────────
    if question_type == "direct":
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful data analytics assistant. Answer questions concisely.",
                ),
                (
                    "human",
                    "Question: {question}",
                ),
            ]
        )
        response = llm.invoke(prompt.format_messages(question=question))
        final_answer = str(response.content).strip()
        state["data_viz_type"] = DataVizType.NONE

    # ── SQL path: execution failed ─────────────────────────────────────────────
    elif error and not results:
        attempts = state.get("repair_attempts") or 0
        final_answer = (
            f"Unable to retrieve data after {attempts} repair attempt(s). "
            f"Last error: {error}"
        )
        state["data_viz_type"] = DataVizType.NONE

    # ── SQL path: results available ────────────────────────────────────────────
    else:
        sample = results[:50]
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """You are a business data analyst. Given a question, SQL query, and results:
1. Interpret the results and write a concise, business-focused answer.
2. Pick the best visualization using this guide:
   - "table" → ranked lists, multi-column detail, or >10 rows
   - "bar"   → comparison across categories (1 categorical + 1-2 numeric columns)
   - "line"  → time series / trends (date column + numeric column)
   - "pie"   → proportions with ≤8 categories (2 columns only)
   - "none"  → single scalar value

Always respond with valid JSON only, no markdown:
{{"answer": "...", "viz_type": "table|bar|line|pie|none"}}""",
                ),
                (
                    "human",
                    """Question: {question}

SQL executed:
{sql}

Results ({total_rows} rows total, showing up to 50):
{results}""",
                ),
            ]
        )

        response = llm.invoke(
            prompt.format_messages(
                question=question,
                sql=sql,
                results=json.dumps(sample, default=str, indent=2),
                total_rows=len(results),
            )
        )

        raw = strip_code_fence(str(response.content))

        try:
            parsed = json.loads(raw)
            final_answer = parsed.get("answer", "").strip()
            try:
                state["data_viz_type"] = DataVizType(
                    parsed.get("viz_type", "table").lower()
                )
            except ValueError:
                state["data_viz_type"] = DataVizType.TABLE
        except json.JSONDecodeError:
            final_answer = raw.strip()
            state["data_viz_type"] = DataVizType.TABLE

    state["final_answer"] = final_answer
    existing: list[dict[str, str]] = state.get("messages") or []
    state["messages"] = existing + [{"role": "assistant", "content": final_answer}]
    return state
