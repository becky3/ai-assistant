"""Anthropic LLMプロバイダー
仕様: docs/specs/f1-chat.md, docs/specs/f5-mcp-integration.md
"""

from __future__ import annotations

import logging

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam, TextBlockParam, ToolParam, ToolUseBlockParam

from src.llm.base import LLMProvider, LLMResponse, Message, ToolCall, ToolDefinition

logger = logging.getLogger(__name__)


def _build_anthropic_messages(messages: list[Message]) -> tuple[str, list[MessageParam]]:
    """Message リストを Anthropic API 形式に変換する.

    Returns:
        (system_prompt, chat_messages) のタプル
    """
    system_prompt = ""
    chat_messages: list[MessageParam] = []

    for m in messages:
        if m.role == "system":
            system_prompt += m.content + "\n"
        elif m.role == "assistant":
            if m.tool_calls:
                content_blocks: list[TextBlockParam | ToolUseBlockParam] = []
                if m.content:
                    content_blocks.append(TextBlockParam(type="text", text=m.content))
                for tc in m.tool_calls:
                    content_blocks.append(ToolUseBlockParam(
                        type="tool_use",
                        id=tc.id,
                        name=tc.name,
                        input=tc.arguments,
                    ))
                chat_messages.append({"role": "assistant", "content": content_blocks})
            else:
                chat_messages.append({"role": "assistant", "content": m.content})
        elif m.role == "tool":
            chat_messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": m.tool_call_id,
                        "content": m.content,
                    }
                ],
            })
        else:
            chat_messages.append({"role": "user", "content": m.content})

    return system_prompt.strip(), chat_messages


def _tool_def_to_anthropic(td: ToolDefinition) -> ToolParam:
    """ToolDefinition を Anthropic Tool Use 形式に変換する."""
    return {
        "name": td.name,
        "description": td.description,
        "input_schema": td.input_schema,
    }


class AnthropicProvider(LLMProvider):
    """Anthropic API を使用するプロバイダー."""

    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20241022") -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    async def complete(self, messages: list[Message]) -> LLMResponse:
        system_prompt, chat_messages = _build_anthropic_messages(messages)

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            messages=chat_messages,
            system=system_prompt if system_prompt else "",
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

    async def complete_with_tools(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
    ) -> LLMResponse:
        """Anthropic Tool Use でツール付き問い合わせを行う."""
        system_prompt, chat_messages = _build_anthropic_messages(messages)
        anthropic_tools = [_tool_def_to_anthropic(td) for td in tools]

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            messages=chat_messages,
            system=system_prompt if system_prompt else "",
            tools=anthropic_tools,
        )

        content = ""
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=dict(block.input) if isinstance(block.input, dict) else {},
                    )
                )

        stop_reason = "tool_use" if response.stop_reason == "tool_use" else "end_turn"

        return LLMResponse(
            content=content,
            model=response.model,
            usage={
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
            },
            tool_calls=tool_calls,
            stop_reason=stop_reason,
        )

    async def is_available(self) -> bool:
        return bool(self._client.api_key)
