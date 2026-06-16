"""Slack用メッセージングアダプター.

仕様: docs/specs/features/cli-adapter.md
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from py_common_lib.httpx import ConstrainedClient

from src.llm.base import Message
from src.messaging.port import IncomingFile, MessagingPort

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

    from src.services.thread_history import ThreadHistoryService

# Slack ファイルダウンロードのタイムアウト（秒）
_FILE_DOWNLOAD_TIMEOUT = 30.0


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
        bot_token: str = "",
    ) -> None:
        self._client = slack_client
        self._bot_user_id = bot_user_id
        self._thread_history = thread_history_service
        self._format_instruction = format_instruction
        self._bot_token = bot_token

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

    async def read_file(self, file: IncomingFile) -> bytes:
        """Slack ファイルを token 付きでダウンロードする.

        プライベートファイルの取得には Bearer 認証が必要。失敗時は例外を送出する。
        """
        logger.info("read_file: name=%s, mimetype=%s", file.name, file.mimetype)
        headers = (
            {"Authorization": f"Bearer {self._bot_token}"} if self._bot_token else {}
        )
        async with ConstrainedClient(
            request_timeout=_FILE_DOWNLOAD_TIMEOUT,
            headers=headers,
        ) as client:
            response = await client.get(file.download_url)
            if response.status_code == 302:
                logger.error("File download redirected - auth may have failed")
                raise RuntimeError(
                    "ファイルのダウンロードに失敗しました（認証エラー）。Bot権限を確認してください。"
                )
            response.raise_for_status()
            return response.content

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
