"""Intégration avec l'API hébergée Anthropic pour le chat sur les wikis GitLab."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic, APIError

from chat.base import SYSTEM_PROMPT_TEMPLATE, BaseChat

logger = logging.getLogger(__name__)


class AnthropicChat(BaseChat):
    """Encapsule les appels à l'API hébergée Anthropic pour le chat avec streaming."""

    def __init__(self, api_key: str, model: str, max_history_messages: int = 5) -> None:
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY doit être configuré.")
        if not model:
            raise ValueError("ANTHROPIC_MODEL doit être configuré.")
        super().__init__(model=model, max_history_messages=max_history_messages)
        self._client = AsyncAnthropic(api_key=api_key)

    async def stream_response(
        self,
        message: str,
        history: list[dict[str, str]],
        context_text: str,
    ) -> AsyncIterator[str]:
        """Génère la réponse du modèle en streaming, token par token (texte brut)."""
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(context=context_text)
        messages = self._build_messages(message, history)

        try:
            async with self._client.messages.stream(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        except APIError as exc:
            logger.error("Erreur lors de l'appel à l'API Anthropic: %s", exc)
            yield f"\n\n[Erreur: impossible d'obtenir une réponse du modèle ({exc})]"
