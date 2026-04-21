"""Slack用メッセージングアダプター.

仕様: docs/specs/features/cli-adapter.md
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.llm.base import Message
from src.messaging.port import MessagingPort

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

    from src.services.thread_history import ThreadHistoryService


class SlackAdapter(MessagingPort):
    """Slack API をラップするアダプター.

    仕様: docs/specs/features/cli-adapter.md
    """

    def __init__(
        self,
        slack_client: AsyncWebClient,
        bot_user_id: str,
        thread_history_service: ThreadHistoryService,
        format_instruction: str = "",
    ) -> None:
        self._client = slack_client
        self._bot_user_id = bot_user_id
        self._thread_history = thread_history_service
        self._format_instruction = format_instruction

    async def send_message(self, text: str, thread_id: str, channel: str) -> None:
        """Slack にメッセージを投稿する."""
        logger.debug("send_message: channel=%s, length=%d", channel, len(text))
        await self._client.chat_postMessage(
            channel=channel, text=text, thread_ts=thread_id,
        )

    async def upload_file(
        self,
        content: str,
        filename: str,
        thread_id: str,
        channel: str,
        comment: str,
    ) -> None:
        """Slack にファイルをアップロードする."""
        logger.info("upload_file: channel=%s, filename=%s, size=%d", channel, filename, len(content))
        await self._client.files_upload_v2(
            channel=channel,
            thread_ts=thread_id,
            content=content,
            filename=filename,
            initial_comment=comment,
        )

    async def fetch_thread_history(
        self, channel: str, thread_id: str, current_message_id: str
    ) -> list[Message] | None:
        """Slack スレッド履歴を取得する."""
        return await self._thread_history.fetch_thread_messages(
            channel=channel,
            thread_ts=thread_id,
            current_ts=current_message_id,
        )

    def get_format_instruction(self) -> str:
        """Slack mrkdwn フォーマット指示を返す."""
        return self._format_instruction

    def get_bot_user_id(self) -> str:
        """ボットのSlackユーザーIDを返す."""
        return self._bot_user_id
