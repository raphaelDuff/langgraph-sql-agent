from dotenv import load_dotenv

load_dotenv()

import pandas as pd
import plotly.express as px
import streamlit as st

from langchain_core.runnables import RunnableConfig

from franq_agent.graph import build_graph

# ─── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(page_title="Franq Data Assistant", page_icon="📊", layout="wide")
st.title("📊 Franq Data Assistant")
st.caption(
    "Ask business questions in plain language — I'll query the database and explain the results."
)


# ─── Chart renderer ───────────────────────────────────────────────────────────


def _render_chart(df: pd.DataFrame, viz_type: str, title: str) -> None:
    cols = df.columns.tolist()

    if viz_type == "table":
        st.dataframe(df, use_container_width=True)

    elif viz_type == "bar" and len(cols) >= 2:
        fig = px.bar(df, x=cols[0], y=cols[1], title=title)
        st.plotly_chart(fig, use_container_width=True)

    elif viz_type == "line" and len(cols) >= 2:
        fig = px.line(df, x=cols[0], y=cols[1], title=title)
        st.plotly_chart(fig, use_container_width=True)

    elif viz_type == "pie" and len(cols) >= 2:
        fig = px.pie(df, names=cols[0], values=cols[1], title=title)
        st.plotly_chart(fig, use_container_width=True)

    else:
        st.dataframe(df, use_container_width=True)


# ─── Session state ────────────────────────────────────────────────────────────

if "graph" not in st.session_state:
    st.session_state.graph = build_graph()

if "thread_id" not in st.session_state:
    st.session_state.thread_id = "streamlit-session"

if "history" not in st.session_state:
    # Each entry: {"question": str, "answer": str, "sql": str|None,
    #              "viz_type": str|None, "data": list|None}
    st.session_state.history = []

# ─── Chat display ─────────────────────────────────────────────────────────────

for turn in st.session_state.history:
    with st.chat_message("user"):
        st.write(turn["question"])

    with st.chat_message("assistant"):
        st.write(turn["answer"])

        if turn.get("sql"):
            with st.expander("🔍 SQL executed"):
                st.code(turn["sql"], language="sql")

        data = turn.get("data")
        viz_type = turn.get("viz_type")

        if data and viz_type and viz_type != "none":
            df = pd.DataFrame(data)
            _render_chart(df, viz_type, turn["question"])

# ─── Input ────────────────────────────────────────────────────────────────────

question = st.chat_input("Ask a question about the data…")

if question:
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            config = RunnableConfig(configurable={"thread_id": st.session_state.thread_id})
            result = st.session_state.graph.invoke(
                {"question": question}, config=config
            )

        answer = result.get("final_answer", "No answer generated.")
        sql = result.get("last_sql_query")
        data_viz_type = result.get("data_viz_type")
        data = result.get("query_result") or []

        st.write(answer)

        if sql:
            with st.expander("🔍 SQL executed"):
                st.code(sql, language="sql")

        if data and data_viz_type and data_viz_type != "none":
            df = pd.DataFrame(data)
            _render_chart(df, data_viz_type, question)

    st.session_state.history.append(
        {
            "question": question,
            "answer": answer,
            "sql": sql,
            "data_viz_type": data_viz_type,
            "data": data,
        }
    )
