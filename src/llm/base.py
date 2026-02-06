"""LLMプロバイダー共通インターフェース
仕様: docs/specs/f1-chat.md, docs/specs/overview.md, docs/specs/f5-mcp-integration.md
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ToolDefinition:
    """LLMに渡すツール定義（プロバイダー非依存の中間表現）."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ToolCall:
    """LLMが要求するツール呼び出し."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """ツール実行結果."""

    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass
class Message:
    """LLMに送る1メッセージ."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str = ""  # role="tool" 時: 対応するツール呼び出しID
    tool_calls: list[ToolCall] = field(default_factory=list)  # role="assistant" 時: LLMが要求するツール呼び出し


@dataclass
class LLMResponse:
    """LLMからの応答."""

    content: str
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = ""


class LLMProvider(abc.ABC):
    """全LLMプロバイダーの共通インターフェース."""

    @abc.abstractmethod
    async def complete(self, messages: list[Message]) -> LLMResponse:
        """メッセージリストを受け取り、応答を返す."""

    async def complete_with_tools(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
    ) -> LLMResponse:
        """ツール情報付きでLLMに問い合わせる.

        デフォルト実装はツールを無視して complete() にフォールバックする。
        ツール対応プロバイダー（OpenAI, Anthropic）はこのメソッドをオーバーライドする。
        """
        return await self.complete(messages)

    @abc.abstractmethod
    async def is_available(self) -> bool:
        """プロバイダーが利用可能かどうかを返す."""
