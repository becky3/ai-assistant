"""OpenAI LLMプロバイダー
仕様: docs/specs/f1-chat.md
"""

from __future__ import annotations

import logging

from openai import AsyncOpenAI

from src.llm.base import LLMProvider, LLMResponse, Message

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    """OpenAI API を使用するプロバイダー."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def complete(self, messages: list[Message]) -> LLMResponse:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
        )
        choice = response.choices[0]
        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
            }
        return LLMResponse(
            content=choice.message.content or "",
            model=response.model,
            usage=usage,
        )

    async def is_available(self) -> bool:
        return bool(self._client.api_key)
