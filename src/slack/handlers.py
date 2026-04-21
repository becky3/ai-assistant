"""Slack イベントハンドラ
仕様: docs/specs/features/chat-response.md, docs/specs/features/auto-reply.md, docs/specs/features/cli-adapter.md

イベント→IncomingMessage変換 + MessageRouter委譲の薄いラッパー。
ビジネスロジックは MessageRouter (src/messaging/router.py) に集約。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from slack_bolt.async_app import AsyncApp

from src.messaging.port import IncomingMessage

if TYPE_CHECKING:
    from src.messaging.router import MessageRouter

_MENTION_PATTERN = re.compile(r"<@[A-Za-z0-9]+(?:\|[^>]+)?>\s*")


def strip_mention(text: str) -> str:
    """メンション部分 (<@U...> または <@U...|name>) を除去する."""
    return _MENTION_PATTERN.sub("", text).strip()


def register_handlers(
    app: AsyncApp,
    router: MessageRouter,
    auto_reply_channels: list[str] | None = None,
) -> None:
    """app_mention および message ハンドラを登録する."""

    @app.event("app_mention")
    async def handle_mention(event: dict, say: object) -> None:  # type: ignore[type-arg]
        user_id: str = event.get("user", "")
        text: str = event.get("text", "")
        raw_thread_ts: str | None = event.get("thread_ts")
        event_ts: str = event.get("ts", "")
        thread_ts: str = raw_thread_ts or event_ts
        files: list[dict[str, object]] | None = event.get("files")
        channel: str = event.get("channel", "")

        cleaned_text = strip_mention(text)
        if not cleaned_text:
            return

        msg = IncomingMessage(
            user_id=user_id,
            text=cleaned_text,
            thread_id=thread_ts,
            channel=channel,
            is_in_thread=raw_thread_ts is not None,
            message_id=event_ts,
            files=files,
        )
        await router.process_message(msg)

    @app.event("message")
    async def handle_message(event: dict, say: object) -> None:  # type: ignore[type-arg]
        """自動返信チャンネルでのメッセージ処理.

        フィルタリング:
        - bot_id がある → 無視（Bot自身の投稿）
        - subtype がある → 無視（編集、削除など）
        - channel が auto_reply_channels に含まれない → 無視
        - メンション付き → 無視（app_mention で処理される）
        """
        if not auto_reply_channels:
            return

        if event.get("bot_id"):
            return

        if event.get("subtype"):
            return

        channel: str = event.get("channel", "")
        if channel not in auto_reply_channels:
            return

        text: str = event.get("text", "")

        if _MENTION_PATTERN.search(text):
            return

        user_id: str = event.get("user", "")
        if not user_id:
            return

        raw_thread_ts: str | None = event.get("thread_ts")
        event_ts: str = event.get("ts", "")
        thread_ts: str = raw_thread_ts or event_ts
        files: list[dict[str, object]] | None = event.get("files")

        cleaned_text = text.strip()
        if not cleaned_text:
            return

        msg = IncomingMessage(
            user_id=user_id,
            text=cleaned_text,
            thread_id=thread_ts,
            channel=channel,
            is_in_thread=raw_thread_ts is not None,
            message_id=event_ts,
            files=files,
        )
        await router.process_message(msg)
