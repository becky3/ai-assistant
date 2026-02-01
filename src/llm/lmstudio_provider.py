"""LM Studio (ローカルLLM) プロバイダー
仕様: docs/specs/overview.md — OpenAI SDK で base_url を localhost:1234 に向ける
"""

from __future__ import annotations

import logging

from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)
from openai.types.chat.chat_completion_message_param import ChatCompletionMessageParam

from src.llm.base import LLMProvider, LLMResponse, Message

logger = logging.getLogger(__name__)


def _to_openai_message(m: Message) -> ChatCompletionMessageParam:
    if m.role == "system":
        return ChatCompletionSystemMessageParam(role="system", content=m.content)
    if m.role == "assistant":
        return ChatCompletionAssistantMessageParam(role="assistant", content=m.content)
    return ChatCompletionUserMessageParam(role="user", content=m.content)


class LMStudioProvider(LLMProvider):
    """LM Studio (OpenAI互換API) を使用するローカルLLMプロバイダー."""

    def __init__(self, base_url: str = "http://localhost:1234/v1", model: str = "local-model") -> None:
        self._client = AsyncOpenAI(base_url=base_url, api_key="lm-studio")
        self._model = model

    async def complete(self, messages: list[Message]) -> LLMResponse:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[_to_openai_message(m) for m in messages],
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
        try:
            await self._client.models.list()
            return True
        except Exception:
            logger.debug("LM Studio is not available")
            return False
