"""Slack用メッセージングアダプター.

仕様: docs/specs/features/cli-adapter.md
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from py_common_lib.httpx import ConstrainedClient

from src.llm.base import Message
from src.messaging.port import ArticleCard, IncomingFile, MessagingPort, ThreadRef

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

    from src.services.thread_history import ThreadHistoryService

# Slack ファイルダウンロードのタイムアウト（秒）
_FILE_DOWNLOAD_TIMEOUT = 30.0


def _build_card_blocks(
    card: ArticleCard,
    layout: Literal["vertical", "horizontal"],
) -> list[dict[str, Any]]:
    """記事カードを Block Kit blocks に描画する（スレッド内1投稿分）."""
    blocks: list[dict[str, Any]] = []
    summary = card.summary

    if layout == "horizontal":
        title_part = f":newspaper: *<{card.url}|{card.title}>*\n{card.datetime_str}\n\n"
        max_summary = max(0, 3000 - len(title_part) - 10)
        if len(summary) > max_summary:
            summary = summary[:max_summary] + "..."
        section: dict[str, Any] = {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"{title_part}{summary}"},
        }
        if card.image_url:
            section["accessory"] = {
                "type": "image",
                "image_url": card.image_url,
                "alt_text": card.title,
            }
        blocks.append(section)
    else:
        if len(summary) > 2900:
            summary = summary[:2900] + "..."
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":newspaper: *<{card.url}|{card.title}>*\n{card.datetime_str}",
            },
        })
        if card.image_url:
            blocks.append({
                "type": "image",
                "image_url": card.image_url,
                "alt_text": card.title,
            })
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": summary},
        })

    return blocks


def _build_parent_blocks(feed_name: str) -> list[dict[str, Any]]:
    """フィードの親メッセージ Block Kit blocks を構築する."""
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f":file_folder: *{feed_name}*"},
        },
    ]


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
        feed_card_layout: Literal["vertical", "horizontal"] = "horizontal",
    ) -> None:
        self._client = slack_client
        self._bot_user_id = bot_user_id
        self._thread_history = thread_history_service
        self._format_instruction = format_instruction
        self._bot_token = bot_token
        self._feed_card_layout = feed_card_layout

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

    async def post_header(self, channel: str, text: str) -> None:
        """配信見出しを header ブロックで投稿する."""
        await self._client.chat_postMessage(
            channel=channel,
            text=text,
            blocks=[
                {"type": "header", "text": {"type": "plain_text", "text": text}},
            ],
        )

    async def start_feed_thread(self, channel: str, feed_name: str) -> ThreadRef:
        """フィード親メッセージを投稿しスレッド（thread_ts）を開始する."""
        result = await self._client.chat_postMessage(
            channel=channel,
            text=f"📰 {feed_name}",
            blocks=_build_parent_blocks(feed_name),
            unfurl_links=False,
            unfurl_media=False,
        )
        return ThreadRef(channel=channel, thread_key=result["ts"])

    async def post_article_card(self, thread: ThreadRef, card: ArticleCard) -> None:
        """記事カードをスレッドに投稿する（画像エラー時は画像なしでリトライ）."""
        blocks = _build_card_blocks(card, self._feed_card_layout)
        try:
            await self._client.chat_postMessage(
                channel=thread.channel,
                text="記事",
                blocks=blocks,
                thread_ts=thread.thread_key,
                unfurl_links=False,
                unfurl_media=False,
            )
        except Exception as exc:
            error_msg = str(exc)
            if "invalid_blocks" in error_msg or "downloading image" in error_msg:
                blocks_without_images = []
                for b in blocks:
                    if b.get("type") == "image":
                        continue
                    if "accessory" in b:
                        b = {k: v for k, v in b.items() if k != "accessory"}
                    blocks_without_images.append(b)
                logger.warning(
                    "Failed to post article with images, retrying without: %s",
                    error_msg,
                )
                await self._client.chat_postMessage(
                    channel=thread.channel,
                    text="記事",
                    blocks=blocks_without_images,
                    thread_ts=thread.thread_key,
                    unfurl_links=False,
                    unfurl_media=False,
                )
            else:
                raise

    async def post_footer(self, channel: str, text: str) -> None:
        """配信フッターを section ブロックで投稿する."""
        await self._client.chat_postMessage(
            channel=channel,
            text=text,
            blocks=[
                {"type": "section", "text": {"type": "mrkdwn", "text": text}},
            ],
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
