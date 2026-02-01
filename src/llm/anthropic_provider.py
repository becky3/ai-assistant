"""Anthropic LLMプロバイダー
仕様: docs/specs/f1-chat.md
"""

from __future__ import annotations

import logging

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam

from src.llm.base import LLMProvider, LLMResponse, Message

logger = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    """Anthropic API を使用するプロバイダー."""

    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20241022") -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    async def complete(self, messages: list[Message]) -> LLMResponse:
        # Anthropic はシステムメッセージを別パラメータで渡す
        system_prompt = ""
        chat_messages: list[MessageParam] = []
        for m in messages:
            if m.role == "system":
                system_prompt += m.content + "\n"
            else:
                chat_messages.append({"role": m.role, "content": m.content})

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            messages=chat_messages,
            system=system_prompt.strip() if system_prompt else "",
        )
        content = ""
        for block in response.content:
            if block.type == "text":
                content += block.text

        return LLMResponse(
            content=content,
            model=response.model,
            usage={
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
            },
        )

    async def is_available(self) -> bool:
        return bool(self._client.api_key)
