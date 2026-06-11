"""Integration with the hosted Anthropic API for chatting over GitLab wikis."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic, APIError

from chat.base import SYSTEM_PROMPT_TEMPLATE, BaseChat

logger = logging.getLogger(__name__)


class AnthropicChat(BaseChat):
    """Wraps calls to the hosted Anthropic API for streaming chat."""

    def __init__(self, api_key: str, model: str, max_history_messages: int = 5) -> None:
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY must be configured.")
        if not model:
            raise ValueError("ANTHROPIC_MODEL must be configured.")
        super().__init__(model=model, max_history_messages=max_history_messages)
        self._client = AsyncAnthropic(api_key=api_key)

    async def stream_response(
        self,
        message: str,
        history: list[dict[str, str]],
        context_text: str,
    ) -> AsyncIterator[str]:
        """Streams the model's response token by token (plain text)."""
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
            logger.error("Error while calling the Anthropic API: %s", exc)
            yield f"\n\n[Error: could not get a response from the model ({exc})]"
