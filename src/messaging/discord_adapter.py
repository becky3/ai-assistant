"""Discord 用メッセージングアダプター.

仕様: docs/specs/features/cli-adapter.md

discord.py の Client を保持し、channel id を解決して送信する。記事カードは
`discord.Embed` に描画する。本文の 2000 文字制限分割もアダプター内に閉じる。
"""

from __future__ import annotations

import io
import logging
from typing import Literal

import discord
from py_common_lib.httpx import ConstrainedClient

from src.llm.base import Message
from src.messaging.port import ArticleCard, IncomingFile, MessagingPort, ThreadRef

logger = logging.getLogger(__name__)

# Discord の本文文字数制限
_MESSAGE_LIMIT = 2000
# Discord Embed description の文字数制限
_EMBED_DESCRIPTION_LIMIT = 4096
# ファイルダウンロードのタイムアウト（秒）
_FILE_DOWNLOAD_TIMEOUT = 30.0


def _split_message(text: str, limit: int = _MESSAGE_LIMIT) -> list[str]:
    """Discord の文字数制限に合わせてテキストを分割する（改行優先）."""
    if len(text) <= limit:
        return [text] if text else [""]

    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        # 1 行が limit を超える場合は強制分割
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]

        candidate = line if not current else f"{current}\n{line}"
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate

    if current:
        chunks.append(current)
    return chunks


def _build_embed(card: ArticleCard) -> discord.Embed:
    """記事カードを discord.Embed に描画する."""
    description = f"{card.datetime_str}\n\n{card.summary}"
    if len(description) > _EMBED_DESCRIPTION_LIMIT:
        description = description[: _EMBED_DESCRIPTION_LIMIT - 3] + "..."
    embed = discord.Embed(
        title=card.title,
        url=card.url,
        description=description,
    )
    if card.image_url:
        embed.set_image(url=card.image_url)
    return embed


class DiscordAdapter(MessagingPort):
    """Discord API をラップするアダプター.

    仕様: docs/specs/features/cli-adapter.md
    """

    def __init__(
        self,
        client: discord.Client,
        *,
        format_instruction: str = "",
        feed_card_layout: Literal["vertical", "horizontal"] = "horizontal",
        thread_history_limit: int = 20,
    ) -> None:
        self._client = client
        self._format_instruction = format_instruction
        self._feed_card_layout = feed_card_layout
        self._thread_history_limit = thread_history_limit

    async def _resolve_channel(self, channel_id: str) -> discord.abc.Messageable:
        """channel id から送信可能なチャンネルオブジェクトを解決する."""
        cid = int(channel_id)
        channel = self._client.get_channel(cid)
        if channel is None:
            channel = await self._client.fetch_channel(cid)
        if not isinstance(channel, discord.abc.Messageable):
            raise RuntimeError(f"チャンネル {channel_id} はメッセージ送信に対応していません")
        return channel

    async def send_message(self, text: str, thread_id: str, channel: str) -> None:
        """Discord にメッセージを送信する（2000 文字で分割）."""
        logger.debug("send_message: channel=%s, length=%d", thread_id, len(text))
        target = await self._resolve_channel(thread_id or channel)
        for chunk in _split_message(text):
            await target.send(chunk)

    async def upload_file(
        self,
        content: str,
        filename: str,
        thread_id: str,
        channel: str,
        comment: str,
    ) -> None:
        """Discord にファイルをアップロードする."""
        logger.info(
            "upload_file: channel=%s, filename=%s, size=%d",
            thread_id, filename, len(content),
        )
        target = await self._resolve_channel(thread_id or channel)
        file = discord.File(io.BytesIO(content.encode("utf-8")), filename=filename)
        await target.send(content=comment or None, file=file)

    async def read_file(self, file: IncomingFile) -> bytes:
        """Discord 添付ファイルをダウンロードする.

        Discord CDN の URL は署名付き公開 URL のため認証ヘッダーは不要。
        """
        logger.debug("read_file start: name=%s, mimetype=%s", file.name, file.mimetype)
        async with ConstrainedClient(request_timeout=_FILE_DOWNLOAD_TIMEOUT) as client:
            response = await client.get(file.download_url)
            response.raise_for_status()
            logger.debug(
                "read_file complete: name=%s, size=%d", file.name, len(response.content)
            )
            return response.content

    async def post_header(self, channel: str, text: str) -> None:
        """配信見出しをプレーンテキストで投稿する."""
        target = await self._resolve_channel(channel)
        await target.send(text)

    async def start_feed_thread(self, channel: str, feed_name: str) -> ThreadRef:
        """フィード親メッセージを投稿しスレッド（独立 channel）を生成する."""
        target = await self._resolve_channel(channel)
        parent = await target.send(f"📰 **{feed_name}**")
        thread = await parent.create_thread(name=feed_name)
        return ThreadRef(channel=str(thread.id), thread_key=str(thread.id))

    async def post_article_card(self, thread: ThreadRef, card: ArticleCard) -> None:
        """記事カードを Embed としてスレッドに投稿する."""
        target = await self._resolve_channel(thread.thread_key)
        await target.send(embed=_build_embed(card))

    async def post_footer(self, channel: str, text: str) -> None:
        """配信フッターをプレーンテキストで投稿する."""
        target = await self._resolve_channel(channel)
        await target.send(text)

    async def fetch_thread_history(
        self, channel: str, thread_id: str, current_message_id: str
    ) -> list[Message] | None:
        """Discord スレッド履歴を取得する.

        thread_id が discord.Thread の場合のみ履歴を返す。通常チャンネルでは
        None を返し、呼び出し元の DB フォールバックに委ねる。
        """
        target = await self._resolve_channel(thread_id)
        if not isinstance(target, discord.Thread):
            return None

        messages: list[Message] = []
        async for m in target.history(
            limit=self._thread_history_limit, oldest_first=True
        ):
            if str(m.id) == current_message_id:
                continue
            text = m.content
            if not text:
                continue
            if m.author.id == (self._client.user.id if self._client.user else None):
                messages.append(Message(role="assistant", content=text))
            else:
                content = f"<@{m.author.id}>: {text}"
                messages.append(Message(role="user", content=content))
        return messages

    def get_format_instruction(self) -> str:
        """Discord Markdown フォーマット指示を返す."""
        return self._format_instruction

    def get_bot_user_id(self) -> str:
        """ボットの Discord ユーザー ID を返す（未解決時は空文字）."""
        user = self._client.user
        return str(user.id) if user is not None else ""
