"""スケジューラ・配信フォーマットのテスト (Issue #8)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.db.models import Article, Base, Feed
from src.scheduler.jobs import (
    _build_category_blocks,
    daily_collect_and_deliver,
    format_daily_digest,
    setup_scheduler,
)


def _make_article(feed_id: int, title: str, url: str, summary: str) -> Article:
    a = Article(feed_id=feed_id, title=title, url=url, summary=summary)
    return a


def test_ac5_format_daily_digest_returns_dict_with_blocks() -> None:
    """AC5: format_daily_digest がカテゴリ別のBlock Kit blocksを返す."""
    feeds = {
        1: Feed(id=1, url="https://a.com/rss", name="A", category="Python"),
        2: Feed(id=2, url="https://b.com/rss", name="B", category="機械学習"),
    }
    articles = [
        _make_article(1, "asyncioの新機能", "https://a.com/1", "asyncio要約"),
        _make_article(2, "transformer効率化", "https://b.com/1", "transformer要約"),
    ]

    result = format_daily_digest(articles, feeds)

    assert isinstance(result, dict)
    assert "Python" in result
    assert "機械学習" in result
    # Each category has blocks list
    python_blocks = result["Python"]
    assert any(b["type"] == "header" for b in python_blocks)
    assert any(b["type"] == "section" for b in python_blocks)


def test_ac5_format_empty_articles() -> None:
    """AC5: 記事がない場合は空辞書を返す."""
    assert format_daily_digest([], {}) == {}


def test_ac5_format_empty_summary_shows_fallback() -> None:
    """AC5: 要約が空の場合は「要約なし」と表示する."""
    feeds = {1: Feed(id=1, url="https://a.com/rss", name="A", category="Python")}
    articles = [_make_article(1, "Title", "https://a.com/1", "")]

    result = format_daily_digest(articles, feeds)
    python_blocks = result["Python"]
    section_texts = [
        b["text"]["text"] for b in python_blocks if b["type"] == "section"
    ]
    assert any("要約なし" in t for t in section_texts)


def test_ac5_build_category_blocks_limits_articles() -> None:
    """AC5: max_articles を超える記事はcontextブロックで残件表示."""
    articles = [
        _make_article(1, f"Title{i}", f"https://a.com/{i}", f"summary{i}")
        for i in range(15)
    ]
    blocks = _build_category_blocks("Python", articles, max_articles=5)

    section_blocks = [b for b in blocks if b["type"] == "section"]
    assert len(section_blocks) == 5
    context_blocks = [b for b in blocks if b["type"] == "context"]
    assert len(context_blocks) == 1
    assert "他 10 件" in context_blocks[0]["elements"][0]["text"]


def test_ac5_build_category_blocks_no_trailing_divider() -> None:
    """AC5: 最後の記事の後にdividerが入らない."""
    articles = [
        _make_article(1, "Title1", "https://a.com/1", "s1"),
        _make_article(1, "Title2", "https://a.com/2", "s2"),
    ]
    blocks = _build_category_blocks("Python", articles)
    assert blocks[-1]["type"] == "section"


def test_ac4_scheduler_registers_cron_job() -> None:
    """AC4: 毎朝指定時刻にスケジューラが収集・配信ジョブを実行する."""
    collector = MagicMock()
    session_factory = MagicMock()
    slack_client = MagicMock()

    scheduler = setup_scheduler(
        collector=collector,
        session_factory=session_factory,
        slack_client=slack_client,
        channel_id="C123",
        hour=7,
        minute=30,
        timezone="Asia/Tokyo",
    )

    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == "daily_feed_job"
    trigger = jobs[0].trigger
    hour_field = next(f for f in trigger.fields if getattr(f, "name", None) == "hour")
    minute_field = next(f for f in trigger.fields if getattr(f, "name", None) == "minute")
    assert str(hour_field) == "7"
    assert str(minute_field) == "30"


@pytest.fixture
async def db_factory():  # type: ignore[no-untyped-def]
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        feed = Feed(url="https://example.com/rss", name="Test", category="Python")
        session.add(feed)
        await session.commit()
        session.add(Article(
            feed_id=feed.id,
            title="Recent",
            url="https://example.com/1",
            summary="summary",
            collected_at=datetime.now(tz=timezone.utc),
        ))
        await session.commit()
    yield factory
    await engine.dispose()


async def test_ac4_daily_collect_and_deliver_posts_to_slack(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC4: daily_collect_and_deliver がSlackに複数メッセージを投稿する."""
    collector = AsyncMock()
    collector.collect_all.return_value = []
    slack_client = AsyncMock()

    await daily_collect_and_deliver(
        collector=collector,
        session_factory=db_factory,
        slack_client=slack_client,
        channel_id="C123",
    )

    collector.collect_all.assert_called_once()
    # ヘッダー + カテゴリ(1) + フッター = 3回
    assert slack_client.chat_postMessage.call_count == 3

    calls = slack_client.chat_postMessage.call_args_list
    # ヘッダー
    assert "今日の学習ニュース" in calls[0].kwargs["text"]
    assert "blocks" in calls[0].kwargs
    # カテゴリメッセージ
    assert "blocks" in calls[1].kwargs
    # フッター
    assert ":bulb:" in calls[2].kwargs["text"]


async def test_ac4_daily_collect_and_deliver_handles_error(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC4: ジョブ内でエラーが発生してもクラッシュしない."""
    collector = AsyncMock()
    collector.collect_all.side_effect = RuntimeError("DB error")
    slack_client = AsyncMock()

    await daily_collect_and_deliver(
        collector=collector,
        session_factory=db_factory,
        slack_client=slack_client,
        channel_id="C123",
    )
    slack_client.chat_postMessage.assert_not_called()
