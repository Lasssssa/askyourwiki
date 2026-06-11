"""Shared elements for the different LLM backends (Anthropic, vLLM, ...)."""

from __future__ import annotations

from collections.abc import AsyncIterator

SYSTEM_PROMPT_TEMPLATE = """You are an assistant that answers questions based ONLY on the \
content of the GitLab wikis provided below. If the answer to the question cannot be found in \
these wikis, say so clearly rather than making up an answer. Always answer in the same language \
as the user's question.

{context}
"""


class BaseChat:
    """Common interface: backends must implement `stream_response`."""

    def __init__(self, model: str, max_history_messages: int = 5) -> None:
        self.model = model
        self.max_history_messages = max_history_messages

    def _build_messages(self, message: str, history: list[dict[str, str]]) -> list[dict[str, str]]:
        # Keep the last N exchanges (1 exchange = 1 user message + 1 assistant message).
        max_messages = self.max_history_messages * 2
        trimmed_history = history[-max_messages:] if history else []

        messages: list[dict[str, str]] = []
        for entry in trimmed_history:
            role = entry.get("role")
            content = entry.get("content", "")
            if role not in ("user", "assistant") or not content:
                continue
            messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": message})
        return messages

    def stream_response(
        self,
        message: str,
        history: list[dict[str, str]],
        context_text: str,
    ) -> AsyncIterator[str]:
        raise NotImplementedError
