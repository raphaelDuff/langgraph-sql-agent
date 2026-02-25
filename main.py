from franq_agent.graph import build_graph


def main() -> None:
    graph = build_graph()
    config = {"configurable": {"thread_id": "cli-session"}}

    print("Franq Data Assistant (type 'exit' to quit)\n")

    while True:
        question = input("You: ").strip()
        if question.lower() in {"exit", "quit"}:
            break
        if not question:
            continue

        result = graph.invoke({"question": question}, config=config)

        print(f"\nAssistant: {result.get('final_answer', 'No answer generated.')}")

        sql = result.get("last_sql_query")
        if sql:
            print(f"\n[SQL]\n{sql}")

        viz = result.get("data_viz_type")
        if viz and viz != "none":
            print(f"[Visualization hint: {viz}]")

        print()


if __name__ == "__main__":
    main()
