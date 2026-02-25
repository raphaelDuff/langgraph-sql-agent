def strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        inner = parts[1]
        # strip leading language tag (e.g. "sql\n", "json\n")
        newline = inner.find("\n")
        if newline != -1:
            inner = inner[newline + 1 :]
        return inner.strip()
    return text
