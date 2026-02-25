from sqlalchemy import create_engine, text, inspect
from typing import Any
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "anexo_desafio_1.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL)

LOW_CARDINALITY_THRESHOLD = 20
CATEGORICAL_TYPES = ("CHAR", "TEXT", "VARCHAR", "STRING")


def _is_categorical_type(col_type: str) -> bool:
    return any(t in col_type.upper() for t in CATEGORICAL_TYPES)


def _get_categorical_info(conn, table: str, col: str, limit: int) -> list[str] | None:
    """
    Returns distinct values if low cardinality, else None.
    Uses single query with LIMIT + 1 strategy.
    """
    rows = conn.execute(
        text(
            f"""
            SELECT "{col}"
            FROM (
                SELECT DISTINCT "{col}"
                FROM "{table}"
                WHERE "{col}" IS NOT NULL
                LIMIT :limit
            ) sub
        """
        ),
        {"limit": limit + 1},  # fetch one extra to detect overflow
    ).fetchall()

    if not rows or len(rows) > limit:
        return None  # exceeded threshold or empty

    return [row[0] for row in rows]


def get_schema() -> dict[str, Any]:
    """
    Discover tables, columns, and nominal categorical columns with their values.
    Optimized: single query per column.
    """
    inspector = inspect(engine)
    schema: dict[str, Any] = {}

    with engine.connect() as conn:
        for table in inspector.get_table_names():
            columns = inspector.get_columns(table)
            pk_cols = set(
                inspector.get_pk_constraint(table).get("constrained_columns", [])
            )

            table_info: dict[str, Any] = {
                "columns": [],
                "categorical_columns": {},
            }

            for col in columns:
                col_name = col["name"]
                col_type = str(col["type"])

                table_info["columns"].append(
                    {
                        "name": col_name,
                        "type": col_type,
                        "pk": col_name in pk_cols,
                    }
                )

                # Skip non-text types and primary keys
                if not _is_categorical_type(col_type) or col_name in pk_cols:
                    continue

                values = _get_categorical_info(
                    conn, table, col_name, LOW_CARDINALITY_THRESHOLD
                )

                if values is not None:
                    table_info["categorical_columns"][col_name] = values

            schema[table] = table_info

    return schema


def execute_query(sql: str) -> list[dict[str, Any]]:
    """Execute a SQL query and return results as a list of dicts."""
    with engine.connect() as conn:
        result = conn.execute(text(sql))
        return [dict(row._mapping) for row in result.fetchall()]


def format_schema(schema: dict[str, list[dict[str, Any]]]) -> str:
    lines = []
    for table, columns in schema.items():
        col_defs = ", ".join(
            f"{col['name']} ({col['type']})" + (" PK" if col.get("pk") else "")
            for col in columns
        )
        lines.append(f"  {table}({col_defs})")
    return "\n".join(lines)
