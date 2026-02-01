"""LLMプロバイダー共通インターフェース
仕様: docs/specs/f1-chat.md, docs/specs/overview.md
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Message:
    """LLMに送る1メッセージ."""

    role: Literal["system", "user", "assistant"]
    content: str


@dataclass
class LLMResponse:
    """LLMからの応答."""

    content: str
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)


class LLMProvider(abc.ABC):
    """全LLMプロバイダーの共通インターフェース."""

    @abc.abstractmethod
    async def complete(self, messages: list[Message]) -> LLMResponse:
        """メッセージリストを受け取り、応答を返す."""

    @abc.abstractmethod
    async def is_available(self) -> bool:
        """プロバイダーが利用可能かどうかを返す."""
