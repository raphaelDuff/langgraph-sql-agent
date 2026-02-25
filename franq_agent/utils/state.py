from enum import auto, StrEnum
from typing import Any, Optional, TypedDict


class QuestionType(StrEnum):
    SQL = auto()
    DIRECT = auto()


class DataVizType(StrEnum):
    TABLE = auto()
    BAR = auto()
    LINE = auto()
    PIE = auto()
    NONE = auto()


class _AgentStateRequired(TypedDict):
    question: str


class AgentState(_AgentStateRequired, total=False):
    # Conversation
    messages: list[dict[str, str]]

    # Context resolution
    resolved_question: str

    # Classification
    question_type: QuestionType
    requires_sql: bool

    # Schema
    schema: dict[str, list[dict[str, Any]]]

    # Planning
    plan: dict[str, Any]

    # SQL generation + execution
    sql_query: Optional[str]
    last_sql_query: Optional[str]
    query_result: Optional[list[dict[str, Any]]]
    execution_error: Optional[str]
    repair_attempts: int

    # Visualization
    data_viz_type: Optional[DataVizType]

    # Final output
    final_answer: Optional[str]
