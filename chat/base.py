"""Éléments communs aux différents backends LLM (Anthropic, vLLM, ...)."""

from __future__ import annotations

from collections.abc import AsyncIterator

SYSTEM_PROMPT_TEMPLATE = """Tu es un assistant qui répond aux questions en te basant UNIQUEMENT sur le \
contenu des wikis GitLab fournis ci-dessous. Si la réponse à la question ne se trouve pas dans ces \
wikis, dis-le clairement plutôt que d'inventer une réponse. Réponds toujours dans la même langue que \
la question posée par l'utilisateur.

{context}
"""


class BaseChat:
    """Interface commune: les backends doivent implémenter `stream_response`."""

    def __init__(self, model: str, max_history_messages: int = 5) -> None:
        self.model = model
        self.max_history_messages = max_history_messages

    def _build_messages(self, message: str, history: list[dict[str, str]]) -> list[dict[str, str]]:
        # On garde les N derniers échanges (1 échange = 1 message user + 1 message assistant).
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
