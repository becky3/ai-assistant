"""Slackスレッド履歴取得サービス
仕様: docs/specs/f8-thread-support.md
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from slack_sdk.web.async_client import AsyncWebClient

from src.llm.base import Message

logger = logging.getLogger(__name__)


class ThreadHistoryService:
    """Slackスレッドから会話履歴を取得するサービス.

    仕様: docs/specs/f8-thread-support.md
    """

    def __init__(
        self,
        slack_client: AsyncWebClient,
        bot_user_id: str,
        limit: int = 20,
    ) -> None:
        self._client = slack_client
        self._bot_user_id = bot_user_id
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
            # サブタイプ付き（編集通知等）やテキストなしのメッセージはスキップ
            text = msg.get("text", "")
            if not text or msg.get("subtype"):
                continue

            user_id = msg.get("user", "")
            if user_id == self._bot_user_id:
                role: Literal["user", "assistant"] = "assistant"
                content = text
            else:
                role = "user"
                # 複数ユーザーの発言を区別するためユーザーIDを付与
                content = f"<@{user_id}>: {text}" if user_id else text

            messages.append(Message(role=role, content=content))

        return messages
