"""LM Studio (ローカルLLM) プロバイダー
仕様: docs/specs/overview.md, docs/specs/infrastructure/mcp-integration.md
OpenAI SDK で base_url を localhost:1234 に向ける。
Function Calling対応モデル（Qwen3等）ではツール呼び出しも可能。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionToolMessageParam,
    ChatCompletionToolParam,
    ChatCompletionUserMessageParam,
)
from openai.types.chat.chat_completion_message_param import ChatCompletionMessageParam
from openai.types.chat.chat_completion_message_tool_call_param import (
    ChatCompletionMessageToolCallParam,
    Function,
)

from src.config.settings import DEFAULT_LMSTUDIO_BASE_URL
from src.llm.base import LLMProvider, LLMResponse, Message, ToolCall, ToolDefinition

logger = logging.getLogger(__name__)


def _to_openai_message(m: Message) -> ChatCompletionMessageParam:
    if m.role == "system":
        return ChatCompletionSystemMessageParam(role="system", content=m.content)
    if m.role == "tool":
        return ChatCompletionToolMessageParam(
            role="tool",
            content=m.content,
            tool_call_id=m.tool_call_id,
        )
    if m.role == "assistant":
        if m.tool_calls:
            return ChatCompletionAssistantMessageParam(
                role="assistant",
                content=m.content or None,
                tool_calls=[
                    ChatCompletionMessageToolCallParam(
                        id=tc.id,
                        type="function",
                        function=Function(
                            name=tc.name,
                            arguments=json.dumps(tc.arguments),
                        ),
                    )
                    for tc in m.tool_calls
                ],
            )
        return ChatCompletionAssistantMessageParam(role="assistant", content=m.content)
    return ChatCompletionUserMessageParam(role="user", content=m.content)


def _tool_def_to_openai(td: ToolDefinition) -> ChatCompletionToolParam:
    """ToolDefinition を OpenAI Function Calling 形式に変換する."""
    return ChatCompletionToolParam(
        type="function",
        function={
            "name": td.name,
            "description": td.description,
            "parameters": td.input_schema,
        },
    )


class LMStudioProvider(LLMProvider):
    """LM Studio (OpenAI互換API) を使用するローカルLLMプロバイダー."""

    def __init__(self, base_url: str = DEFAULT_LMSTUDIO_BASE_URL, model: str = "local-model") -> None:
        normalized = base_url.rstrip("/")
        if not normalized.endswith("/v1"):
            normalized = f"{normalized}/v1"
        self._client = AsyncOpenAI(base_url=normalized, api_key="lm-studio")
        self._model = model

    async def complete(
        self,
        messages: list[Message],
        *,
        reasoning_effort: Literal["none", "low", "medium", "high"] | None = None,
    ) -> LLMResponse:
        extra_kwargs: dict[str, Any] = {}
        if reasoning_effort is not None:
            extra_kwargs["reasoning_effort"] = reasoning_effort
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[_to_openai_message(m) for m in messages],
            **extra_kwargs,
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

    async def complete_with_tools(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
    ) -> LLMResponse:
        """OpenAI互換 Function Calling でツール付き問い合わせを行う."""
        openai_tools = [_tool_def_to_openai(td) for td in tools]
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[_to_openai_message(m) for m in messages],
            tools=openai_tools,
        )
        choice = response.choices[0]
        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
            }

        tool_calls: list[ToolCall] = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                if not hasattr(tc, "function"):
                    continue
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=json.loads(tc.function.arguments),
                    )
                )

        stop_reason = "tool_use" if tool_calls else "end_turn"

        return LLMResponse(
            content=choice.message.content or "",
            model=response.model,
            usage=usage,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
        )

    async def is_available(self) -> bool:
        try:
            await self._client.models.list()
            return True
        except Exception:
            logger.debug("LM Studio is not available")
            return False
