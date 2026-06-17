"""Discord 用 MessagingListener 実装.

仕様: docs/specs/features/cli-adapter.md

discord.py の Gateway（常設 WebSocket）接続を束ね、受信側の抽象
`MessagingListener` を満たす。イベント（`on_message`）→ `IncomingMessage`
正規化 → `MessageRouter` への dispatch を担う。Slack の Socket Mode と
同じ常駐 bot 構成に載る。
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING

import discord

from src.messaging.listener import MessagingListener
from src.messaging.port import IncomingFile, IncomingMessage
from src.process_guard import BOT_READY_SIGNAL

if TYPE_CHECKING:
    from src.messaging.router import MessageRouter

logger = logging.getLogger(__name__)

# Discord のメンション表記 (<@123>, <@!123> ユーザー / <@&123> ロール) にマッチする
_MENTION_PATTERN = re.compile(r"<@[!&]?\d+>\s*")


def strip_mention(text: str) -> str:
    """Discord メンション部分 (<@id> / <@!id> / <@&id>) を除去する."""
    result = _MENTION_PATTERN.sub("", text).strip()
    if result != text:
        logger.debug("strip_mention: %r -> %r", text, result)
    return result


def _to_incoming_files(
    attachments: list[discord.Attachment] | None,
) -> list[IncomingFile] | None:
    """Discord の添付ファイルを中立な IncomingFile リストに正規化する."""
    if not attachments:
        return None
    return [
        IncomingFile(
            name=att.filename,
            mimetype=att.content_type or "",
            download_url=att.url,
            size=att.size,
        )
        for att in attachments
    ]


def create_client() -> discord.Client:
    """MESSAGE CONTENT INTENT を有効化した discord.Client を生成する.

    privileged な message_content intent はギルドチャンネルで本文・添付を
    読むために必須（Developer Portal 側でも有効化が必要。仕様: セットアップ手順）。
    """
    intents = discord.Intents.default()
    intents.message_content = True
    return discord.Client(intents=intents)


class DiscordListener(MessagingListener):
    """discord.py Gateway を束ねる受信リスナー.

    仕様: docs/specs/features/cli-adapter.md
    """

    def __init__(
        self,
        client: discord.Client,
        router: MessageRouter,
        *,
        bot_token: str,
        auto_reply_channels: list[str] | None = None,
    ) -> None:
        self._client = client
        self._router = router
        self._bot_token = bot_token
        self._auto_reply_channels = set(auto_reply_channels or [])
        self._bot_user_id = ""
        self._register_events()

    @property
    def bot_user_id(self) -> str:
        """解決済みの bot ユーザー ID（on_ready で確定。未接続時は空文字）."""
        return self._bot_user_id

    def _register_events(self) -> None:
        """on_ready / on_message を client に登録する."""

        @self._client.event
        async def on_ready() -> None:
            user = self._client.user
            if user is not None:
                self._bot_user_id = str(user.id)
            print(BOT_READY_SIGNAL, flush=True)
            logger.info("Discord 接続完了: bot_user_id=%s", self._bot_user_id)

        @self._client.event
        async def on_message(message: discord.Message) -> None:
            await self._handle_message(message)

    def _is_bot_mentioned(
        self, message: discord.Message, me: discord.ClientUser
    ) -> bool:
        """bot へのメンションか判定する.

        本文中の明示的なユーザーメンション（raw_mentions）に加え、bot 用の
        管理ロール（インテグレーションロール）へのメンションも受理する。Discord
        では `@bot名` がユーザーではなく同名の bot 管理ロールに解決される場合が
        あるため。message.mentions はリプライ ping 先も含むため使わない。
        """
        if me.id in message.raw_mentions:
            return True
        guild = message.guild
        if guild is None or not message.raw_role_mentions:
            return False
        bot_member = guild.me
        if bot_member is None:
            return False
        managed_role_ids = {r.id for r in bot_member.roles if r.is_bot_managed()}
        return bool(managed_role_ids.intersection(message.raw_role_mentions))

    def _is_auto_reply_channel(self, channel: discord.abc.Messageable) -> bool:
        """チャンネル（またはスレッド親）が auto-reply 対象か判定する."""
        if not self._auto_reply_channels:
            return False
        channel_id = getattr(channel, "id", None)
        if channel_id is not None and str(channel_id) in self._auto_reply_channels:
            return True
        parent_id = getattr(channel, "parent_id", None)
        return parent_id is not None and str(parent_id) in self._auto_reply_channels

    async def _handle_message(self, message: discord.Message) -> None:
        """受信メッセージをフィルタ・正規化し router に dispatch する."""
        me = self._client.user
        if me is None:
            return  # 未 ready

        if message.author.id == me.id:
            return  # 自己発言（最優先で除外しループ防止）

        mentioned = self._is_bot_mentioned(message, me)

        if message.author.bot and not mentioned:
            # 他 bot は自 bot メンション時のみ受理（外部 Discord reminder bot の
            # 定期トリガー経路。メンション無しの他 bot 発言はループ防止のため無視）
            logger.debug("message filtered: bot author without mention")
            return

        channel = message.channel
        in_auto_reply = self._is_auto_reply_channel(channel)
        if not mentioned and not in_auto_reply:
            return

        if mentioned:
            content = strip_mention(message.content)
        else:
            content = message.content.strip()
        if not content:
            logger.debug("message filtered: empty text after strip")
            return

        # Slack 同様にスレッドへ返信する。既にスレッド内ならそのスレッド、通常
        # チャンネルなら発言にスレッドを作成して返信先とする。is_in_thread は
        # 「元発言が既存スレッド内だったか」を表し、ChatService のスレッド履歴取得
        # 可否に使う（新規スレッド初回は False = DB フォールバック）。
        original_in_thread = isinstance(channel, discord.Thread)
        if original_in_thread:
            target_id = str(channel.id)
        else:
            target_id = await self._ensure_reply_thread(message, content)

        logger.info(
            "discord message: user=%s, channel=%s, thread=%s, mentioned=%s, text=%r",
            message.author.id, channel.id, target_id, mentioned, content[:200],
        )

        msg = IncomingMessage(
            user_id=str(message.author.id),
            text=content,
            thread_id=target_id,
            channel=target_id,
            is_in_thread=original_in_thread,
            message_id=str(message.id),
            files=_to_incoming_files(message.attachments),
        )
        await self._router.process_message(msg)

    async def _ensure_reply_thread(
        self, message: discord.Message, content: str
    ) -> str:
        """発言にスレッドを作成し、その channel id を返す（失敗時は元チャンネル）.

        Discord のスレッドは独立 channel のため、Slack の thread_ts 相当として
        発言ごとにスレッドを作る。作成失敗時（権限不足・既存スレッド等）は元の
        チャンネルにフォールバックする。
        """
        name = " ".join(content.split())[:80] or "chat"
        try:
            thread = await message.create_thread(name=name)
            return str(thread.id)
        except Exception:
            logger.warning(
                "スレッド作成に失敗しました。チャンネルに返信します", exc_info=True
            )
            return str(message.channel.id)

    async def run(self) -> None:
        """Gateway に接続し、シャットダウンまでイベントを dispatch する."""
        try:
            await self._client.start(self._bot_token)
        except asyncio.CancelledError:
            logger.info("シャットダウンシグナルを受信しました")
            await self._client.close()
