"""Slack イベントハンドラ
仕様: docs/specs/f1-chat.md
"""

from __future__ import annotations

import logging
import re

from slack_bolt.async_app import AsyncApp

from src.services.chat import ChatService

logger = logging.getLogger(__name__)


def strip_mention(text: str) -> str:
    """メンション部分 (<@U...>) を除去する."""
    return re.sub(r"<@[A-Za-z0-9]+>\s*", "", text).strip()


def register_handlers(app: AsyncApp, chat_service: ChatService) -> None:
    """app_mention ハンドラを登録する."""

    @app.event("app_mention")
    async def handle_mention(event: dict, say: object) -> None:  # type: ignore[type-arg]
        user_id: str = event.get("user", "")
        text: str = event.get("text", "")
        thread_ts: str = event.get("thread_ts") or event.get("ts", "")

        cleaned_text = strip_mention(text)
        if not cleaned_text:
            return

        try:
            response = await chat_service.respond(
                user_id=user_id,
                text=cleaned_text,
                thread_ts=thread_ts,
            )
            await say(text=response, thread_ts=thread_ts)  # type: ignore[operator]
        except Exception:
            logger.exception("Failed to generate response")
            await say(  # type: ignore[operator]
                text="申し訳ありません、応答の生成中にエラーが発生しました。しばらくしてからもう一度お試しください。",
                thread_ts=thread_ts,
            )
