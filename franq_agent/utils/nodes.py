from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from franq_agent.utils.state import AgentState, QuestionType
from franq_agent.utils.db import get_schema


llm = ChatAnthropic(
    model_name="claude-sonnet-4-6", temperature=0, timeout=None, stop=None
)


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
