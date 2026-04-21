"""Slackスレッド履歴取得サービス
仕様: docs/specs/features/thread-support.md
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from slack_sdk.web.async_client import AsyncWebClient

from src.llm.base import Message

logger = logging.getLogger(__name__)


def extract_text_from_blocks(blocks: list[dict[str, Any]]) -> str:
    """Block Kit の blocks フィールドからテキストを抽出する.

    仕様: docs/specs/features/thread-support.md
    """
    parts: list[str] = []
    for block in blocks:
        if block.get("type") == "section":
            text_obj = block.get("text")
            if isinstance(text_obj, dict):
                text_val = text_obj.get("text", "")
                if text_val:
                    parts.append(text_val)
        elif block.get("type") == "rich_text":
            for element in block.get("elements", []):
                section_parts: list[str] = []
                for sub in element.get("elements", []):
                    if sub.get("type") in ("text", "link"):
                        text_val = sub.get("text", "")
                        if text_val:
                            section_parts.append(text_val)
                if section_parts:
                    parts.append("".join(section_parts))
    return "\n".join(parts)


class ThreadHistoryService:
    """Slackスレッドから会話履歴を取得するサービス.

    仕様: docs/specs/features/thread-support.md
    """

    def __init__(
        self,
        slack_client: AsyncWebClient,
        bot_user_id: str,
        bot_id: str | None,
        limit: int = 20,
    ) -> None:
        self._client = slack_client
        self._bot_user_id = bot_user_id
        self._bot_id = bot_id
        self._limit = limit

    async def fetch_thread_messages(
        self,
        channel: str,
        thread_ts: str,
        current_ts: str,
    ) -> list[Message] | None:
        """スレッドのメッセージ履歴を取得し、LLM用のMessageリストに変換する.

        Args:
            channel: チャンネルID
            thread_ts: スレッドの親メッセージのタイムスタンプ
            current_ts: 今回のトリガーメッセージのタイムスタンプ（除外用）

        Returns:
            Message のリスト。取得失敗時は None（呼び出し元でフォールバック判定）。
        """
        try:
            result = await self._client.conversations_replies(
                channel=channel,
                ts=thread_ts,
                limit=self._limit,
            )
            raw_messages: list[dict[str, Any]] = result.get("messages", [])
        except Exception:
            logger.exception(
                "Failed to fetch thread replies: channel=%s, thread_ts=%s",
                channel,
                thread_ts,
            )
            return None

        if not raw_messages:
            return []

        # 今回のトリガーメッセージを除外（ChatService 側で追加されるため）
        history_messages = [m for m in raw_messages if m.get("ts") != current_ts]

        # limit 件に絞る（古い方から切り捨て）
        if len(history_messages) > self._limit:
            history_messages = history_messages[-self._limit :]

        messages: list[Message] = []
        for msg in history_messages:
            subtype = msg.get("subtype")
            # bot_message 以外のサブタイプ（編集通知等）はスキップ
            if subtype and subtype != "bot_message":
                continue

            text = msg.get("text", "")
            blocks = msg.get("blocks")
            if isinstance(blocks, list):
                blocks_text = extract_text_from_blocks(blocks)
                if blocks_text:
                    text = blocks_text

            if not text:
                continue

            user_id = msg.get("user", "")
            msg_bot_id = msg.get("bot_id")
            is_bot = user_id == self._bot_user_id or (
                bool(msg_bot_id) and msg_bot_id == self._bot_id
            )
            if is_bot:
                role: Literal["user", "assistant"] = "assistant"
                content = text
            else:
                role = "user"
                # 複数ユーザーの発言を区別するためユーザーIDを付与
                content = f"<@{user_id}>: {text}" if user_id else text

            messages.append(Message(role=role, content=content))

        return messages
