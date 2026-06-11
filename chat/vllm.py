"""Integration with a self-hosted model served by vLLM (OpenAI-compatible API)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from openai import APIError, AsyncOpenAI

from chat.base import SYSTEM_PROMPT_TEMPLATE, BaseChat

logger = logging.getLogger(__name__)


class VLLMChat(BaseChat):
    """Wraps calls to a vLLM server via its `/v1/chat/completions` endpoint."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "EMPTY",
        max_history_messages: int = 5,
    ) -> None:
        if not base_url:
            raise ValueError("VLLM_BASE_URL must be configured.")
        if not model:
            raise ValueError("VLLM_MODEL must be configured.")
        super().__init__(model=model, max_history_messages=max_history_messages)
        # vLLM requires a non-empty key even though it isn't checked by default.
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key or "EMPTY")

    async def stream_response(
        self,
        message: str,
        history: list[dict[str, str]],
        context_text: str,
    ) -> AsyncIterator[str]:
        """Streams the model's response via the OpenAI-compatible "chat completions" API."""
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(context=context_text)
        messages = [{"role": "system", "content": system_prompt}] + self._build_messages(message, history)

        try:
            stream = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=4096,
                stream=True,
            )
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except APIError as exc:
            logger.error("Error while calling the vLLM server: %s", exc)
            yield f"\n\n[Error: could not get a response from the vLLM model ({exc})]"
