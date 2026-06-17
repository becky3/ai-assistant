"""DiscordListener のテスト (Issue #850)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord

from src.messaging.discord_listener import (
    DiscordListener,
    _to_incoming_files,
    strip_mention,
)
from src.process_guard import BOT_READY_SIGNAL


class FakeClient:
    """discord.Client の event 登録だけを模した最小フェイク."""

    def __init__(self) -> None:
        self.user: Any = None
        self.events: dict[str, Any] = {}

    def event(self, coro: Any) -> Any:
        self.events[coro.__name__] = coro
        return coro


def _make_listener(
    auto_reply_channels: list[str] | None = None,
) -> tuple[DiscordListener, FakeClient, AsyncMock]:
    client = FakeClient()
    router = AsyncMock()
    listener = DiscordListener(
        client,  # type: ignore[arg-type]
        router,
        bot_token="token",
        auto_reply_channels=auto_reply_channels,
    )
    return listener, client, router


def _make_message(
    *,
    author_id: int,
    content: str,
    channel: Any,
    is_bot: bool = False,
    mentions: list[Any] | None = None,
    attachments: list[Any] | None = None,
    message_id: int = 999,
) -> MagicMock:
    msg = MagicMock(spec=discord.Message)
    msg.author = MagicMock()
    msg.author.id = author_id
    msg.author.bot = is_bot
    msg.content = content
    msg.channel = channel
    msg.mentions = mentions or []
    msg.attachments = attachments or []
    msg.id = message_id
    return msg


def test_strip_mention() -> None:
    assert strip_mention("<@123> hello") == "hello"
    assert strip_mention("<@!456>  world") == "world"
    assert strip_mention("no mention") == "no mention"


def test_to_incoming_files() -> None:
    att = MagicMock()
    att.filename = "feeds.csv"
    att.content_type = "text/csv"
    att.url = "https://cdn.discord/feeds.csv"
    att.size = 1234
    files = _to_incoming_files([att])
    assert files is not None
    assert files[0].name == "feeds.csv"
    assert files[0].mimetype == "text/csv"
    assert files[0].download_url == "https://cdn.discord/feeds.csv"
    assert files[0].size == 1234
    assert _to_incoming_files(None) is None
    assert _to_incoming_files([]) is None


def test_registers_events_and_bot_user_id_empty() -> None:
    listener, client, _ = _make_listener()
    assert "on_ready" in client.events
    assert "on_message" in client.events
    assert listener.bot_user_id == ""


async def test_on_ready_resolves_bot_user_id(capsys) -> None:  # type: ignore[no-untyped-def]
    listener, client, _ = _make_listener()
    client.user = MagicMock()
    client.user.id = 42

    await client.events["on_ready"]()

    assert listener.bot_user_id == "42"
    assert BOT_READY_SIGNAL in capsys.readouterr().out


async def test_ignores_self_message() -> None:
    listener, client, router = _make_listener()
    client.user = MagicMock()
    client.user.id = 42
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 100
    msg = _make_message(author_id=42, content="hi", channel=channel, mentions=[client.user])

    await client.events["on_message"](msg)

    router.process_message.assert_not_awaited()


async def test_ignores_other_bot() -> None:
    listener, client, router = _make_listener()
    client.user = MagicMock()
    client.user.id = 42
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 100
    msg = _make_message(
        author_id=7, content="<@42> hi", channel=channel, is_bot=True,
        mentions=[client.user],
    )

    await client.events["on_message"](msg)

    router.process_message.assert_not_awaited()


async def test_ignores_no_mention_outside_auto_reply() -> None:
    listener, client, router = _make_listener()
    client.user = MagicMock()
    client.user.id = 42
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 100
    msg = _make_message(author_id=7, content="just chatting", channel=channel)

    await client.events["on_message"](msg)

    router.process_message.assert_not_awaited()


async def test_mention_dispatches_with_strip() -> None:
    listener, client, router = _make_listener()
    client.user = MagicMock()
    client.user.id = 42
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 100
    att = MagicMock()
    att.filename = "a.csv"
    att.content_type = "text/csv"
    att.url = "https://cdn/a.csv"
    att.size = 10
    msg = _make_message(
        author_id=7, content="<@42> feed list", channel=channel,
        mentions=[client.user], attachments=[att], message_id=555,
    )

    await client.events["on_message"](msg)

    router.process_message.assert_awaited_once()
    dispatched = router.process_message.await_args.args[0]
    assert dispatched.text == "feed list"
    assert dispatched.user_id == "7"
    assert dispatched.channel == "100"
    assert dispatched.thread_id == "100"
    assert dispatched.is_in_thread is False
    assert dispatched.message_id == "555"
    assert dispatched.files is not None and dispatched.files[0].name == "a.csv"


async def test_auto_reply_channel_without_mention() -> None:
    listener, client, router = _make_listener(auto_reply_channels=["200"])
    client.user = MagicMock()
    client.user.id = 42
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 200
    msg = _make_message(author_id=7, content="hello bot", channel=channel)

    await client.events["on_message"](msg)

    router.process_message.assert_awaited_once()
    dispatched = router.process_message.await_args.args[0]
    assert dispatched.text == "hello bot"


async def test_thread_message_marked_in_thread() -> None:
    listener, client, router = _make_listener()
    client.user = MagicMock()
    client.user.id = 42
    thread = MagicMock(spec=discord.Thread)
    thread.id = 300
    msg = _make_message(
        author_id=7, content="<@42> hi", channel=thread, mentions=[client.user],
    )

    await client.events["on_message"](msg)

    router.process_message.assert_awaited_once()
    dispatched = router.process_message.await_args.args[0]
    assert dispatched.is_in_thread is True
    assert dispatched.channel == "300"
