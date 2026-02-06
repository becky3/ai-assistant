"""OpenAI LLMプロバイダー
仕様: docs/specs/f1-chat.md, docs/specs/f5-mcp-integration.md
"""

from __future__ import annotations

import json
import logging

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


class OpenAIProvider(LLMProvider):
    """OpenAI API を使用するプロバイダー."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        self._client = AsyncOpenAI(api_key=api_key)
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

    async def complete_with_tools(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
    ) -> LLMResponse:
        """OpenAI Function Calling でツール付き問い合わせを行う."""
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
        return bool(self._client.api_key)
