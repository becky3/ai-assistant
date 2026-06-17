"""DiscordAdapter のテスト (Issue #850)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord

from src.messaging.discord_adapter import (
    DiscordAdapter,
    _build_embed,
    _split_message,
)
from src.messaging.port import ArticleCard, IncomingFile


def _make_adapter(client: Any) -> DiscordAdapter:
    return DiscordAdapter(client, format_instruction="discord-md", thread_history_limit=20)


def _make_channel() -> MagicMock:
    """送信可能なチャンネル mock（isinstance Messageable を満たす）."""
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    return channel


def test_split_message_short() -> None:
    assert _split_message("hello") == ["hello"]


def test_split_message_by_newline() -> None:
    line = "a" * 1500
    text = f"{line}\n{line}"
    chunks = _split_message(text)
    assert len(chunks) == 2
    assert all(len(c) <= 2000 for c in chunks)


def test_split_message_long_single_line() -> None:
    text = "b" * 4500
    chunks = _split_message(text)
    assert len(chunks) == 3
    assert all(len(c) <= 2000 for c in chunks)
    assert "".join(chunks) == text


def test_build_embed() -> None:
    card = ArticleCard(
        title="Sample Title",
        url="https://example.com",
        datetime_str="06-17 10:00",
        summary="要約本文",
        image_url="https://example.com/img.png",
    )
    embed = _build_embed(card)
    assert embed.title == "Sample Title"
    assert embed.url == "https://example.com"
    assert embed.description is not None and "要約本文" in embed.description
    assert embed.image.url == "https://example.com/img.png"


async def test_send_message_splits() -> None:
    channel = _make_channel()
    client = MagicMock()
    client.get_channel = MagicMock(return_value=channel)
    adapter = _make_adapter(client)

    line = "x" * 1500
    await adapter.send_message(f"{line}\n{line}", thread_id="100", channel="100")

    assert channel.send.await_count == 2


async def test_send_message_converts_to_discord_markdown() -> None:
    channel = _make_channel()
    client = MagicMock()
    client.get_channel = MagicMock(return_value=channel)
    adapter = _make_adapter(client)

    await adapter.send_message("*太字* :bulb:", thread_id="100", channel="100")

    channel.send.assert_awaited_once_with("**太字** 💡")


async def test_post_header_converts() -> None:
    channel = _make_channel()
    client = MagicMock()
    client.get_channel = MagicMock(return_value=channel)
    adapter = _make_adapter(client)

    await adapter.post_header("100", ":newspaper: 今日のニュース")

    channel.send.assert_awaited_once_with("📰 今日のニュース")


async def test_send_message_fetch_fallback() -> None:
    channel = _make_channel()
    client = MagicMock()
    client.get_channel = MagicMock(return_value=None)
    client.fetch_channel = AsyncMock(return_value=channel)
    adapter = _make_adapter(client)

    await adapter.send_message("hi", thread_id="100", channel="100")

    client.fetch_channel.assert_awaited_once_with(100)
    channel.send.assert_awaited_once_with("hi")


async def test_upload_file() -> None:
    channel = _make_channel()
    client = MagicMock()
    client.get_channel = MagicMock(return_value=channel)
    adapter = _make_adapter(client)

    await adapter.upload_file(
        content="url,name,category\n", filename="feeds.csv",
        thread_id="100", channel="100", comment="エクスポート",
    )

    channel.send.assert_awaited_once()
    kwargs = channel.send.await_args.kwargs
    assert kwargs["content"] == "エクスポート"
    assert isinstance(kwargs["file"], discord.File)


async def test_read_file(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.content = b"csv-bytes"

    client_inst = AsyncMock()
    client_inst.get = AsyncMock(return_value=response)

    class FakeConstrained:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> Any:
            return client_inst

        async def __aexit__(self, *args: Any) -> None:
            return None

    monkeypatch.setattr(
        "src.messaging.discord_adapter.ConstrainedClient", FakeConstrained
    )

    adapter = _make_adapter(MagicMock())
    file = IncomingFile(
        name="feeds.csv", mimetype="text/csv",
        download_url="https://cdn/feeds.csv", size=10,
    )
    result = await adapter.read_file(file)

    assert result == b"csv-bytes"
    client_inst.get.assert_awaited_once_with("https://cdn/feeds.csv")


async def test_start_feed_thread() -> None:
    thread = MagicMock()
    thread.id = 777
    parent = MagicMock()
    parent.create_thread = AsyncMock(return_value=thread)
    channel = _make_channel()
    channel.send = AsyncMock(return_value=parent)
    client = MagicMock()
    client.get_channel = MagicMock(return_value=channel)
    adapter = _make_adapter(client)

    ref = await adapter.start_feed_thread("100", "Tech News")

    assert ref.channel == "777"
    assert ref.thread_key == "777"
    parent.create_thread.assert_awaited_once_with(name="Tech News")


async def test_open_thread() -> None:
    thread = MagicMock()
    thread.id = 888
    parent = MagicMock()
    parent.create_thread = AsyncMock(return_value=thread)
    channel = _make_channel()
    channel.send = AsyncMock(return_value=parent)
    client = MagicMock()
    client.get_channel = MagicMock(return_value=channel)
    adapter = _make_adapter(client)

    ref = await adapter.open_thread("100", "🕒 定時実行: deliver")

    assert ref.channel == "888"
    assert ref.thread_key == "888"
    parent.create_thread.assert_awaited_once()


async def test_post_article_card() -> None:
    thread_channel = _make_channel()
    client = MagicMock()
    client.get_channel = MagicMock(return_value=thread_channel)
    adapter = _make_adapter(client)

    from src.messaging.port import ThreadRef
    card = ArticleCard(
        title="T", url="https://e.com", datetime_str="06-17", summary="s",
    )
    await adapter.post_article_card(ThreadRef(channel="777", thread_key="777"), card)

    thread_channel.send.assert_awaited_once()
    assert isinstance(thread_channel.send.await_args.kwargs["embed"], discord.Embed)


async def test_fetch_thread_history_non_thread_returns_none() -> None:
    channel = _make_channel()  # TextChannel, not Thread
    client = MagicMock()
    client.get_channel = MagicMock(return_value=channel)
    adapter = _make_adapter(client)

    result = await adapter.fetch_thread_history("100", "100", "1")
    assert result is None


async def test_fetch_thread_history_includes_starter() -> None:
    """starter message（親チャンネルの元発言）が履歴の先頭に含まれる."""
    async def _history(*args: Any, **kwargs: Any) -> Any:
        for m in thread_messages:
            yield m

    bot_user = MagicMock()
    bot_user.id = 42
    client = MagicMock()
    client.user = bot_user

    def _msg(mid: int, author_id: int, content: str) -> MagicMock:
        m = MagicMock()
        m.id = mid
        m.author = MagicMock()
        m.author.id = author_id
        m.content = content
        return m

    # starter（元発言「こんにちわ」）は親チャンネル側。thread.history には含まれない
    starter = _msg(50, 7, "こんにちわ")
    thread_messages = [
        _msg(51, 42, "やっほー"),  # bot のスレッド初回返信
        _msg(99, 7, "最初に何て言った？"),  # current（除外）
    ]

    thread = MagicMock(spec=discord.Thread)
    thread.starter_message = starter
    thread.history = MagicMock(side_effect=_history)
    client.get_channel = MagicMock(return_value=thread)

    adapter = _make_adapter(client)
    result = await adapter.fetch_thread_history("300", "300", "99")

    assert result is not None
    assert len(result) == 2
    assert result[0].role == "user"
    assert result[0].content == "<@7>: こんにちわ"  # starter が先頭
    assert result[1].role == "assistant"
    assert result[1].content == "やっほー"


async def test_fetch_thread_history_converts_messages() -> None:
    async def _history(*args: Any, **kwargs: Any) -> Any:
        for m in messages:
            yield m

    bot_user = MagicMock()
    bot_user.id = 42
    client = MagicMock()
    client.user = bot_user

    thread = MagicMock(spec=discord.Thread)
    thread.starter_message = None  # starter なし（history のみ検証）
    thread.parent = None
    thread.history = MagicMock(side_effect=_history)
    client.get_channel = MagicMock(return_value=thread)

    def _msg(mid: int, author_id: int, content: str) -> MagicMock:
        m = MagicMock()
        m.id = mid
        m.author = MagicMock()
        m.author.id = author_id
        m.content = content
        return m

    messages = [
        _msg(1, 7, "user says hi"),
        _msg(2, 42, "bot replies"),
        _msg(3, 7, ""),  # 空はスキップ
        _msg(99, 7, "current excluded"),
    ]

    adapter = _make_adapter(client)
    result = await adapter.fetch_thread_history("300", "300", "99")

    assert result is not None
    assert len(result) == 2
    assert result[0].role == "user"
    assert result[0].content == "<@7>: user says hi"
    assert result[1].role == "assistant"
    assert result[1].content == "bot replies"


def test_get_bot_user_id_and_format() -> None:
    client = MagicMock()
    client.user = None
    adapter = _make_adapter(client)
    assert adapter.get_bot_user_id() == ""
    assert adapter.get_format_instruction() == "discord-md"

    client.user = MagicMock()
    client.user.id = 42
    assert adapter.get_bot_user_id() == "42"
