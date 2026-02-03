"""RSS情報収集・記事要約のテスト (Issue #7)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.db.models import Article, Base, Feed
from src.services.feed_collector import FeedCollector
from src.services.ogp_extractor import OgpExtractor
from src.services.summarizer import Summarizer


@pytest.fixture
async def db_factory():  # type: ignore[no-untyped-def]
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    # テスト用フィードを追加
    async with factory() as session:
        session.add(Feed(url="https://example.com/rss", name="Test Feed", category="Python"))
        await session.commit()
    yield factory
    await engine.dispose()


def _make_parsed_feed(entries: list[dict]) -> MagicMock:  # type: ignore[type-arg]
    """feedparser.parse の戻り値をモックする."""
    mock = MagicMock()
    mock_entries = []
    for e in entries:
        entry = MagicMock()
        entry.get = lambda key, default="", _e=e: _e.get(key, default)
        entry.published_parsed = e.get("published_parsed")
        mock_entries.append(entry)
    mock.entries = mock_entries
    return mock


async def test_ac1_rss_feed_is_fetched_and_parsed(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC1: feedsテーブルに登録されたRSSフィードから記事を取得できる."""
    summarizer = AsyncMock(spec=Summarizer)
    summarizer.summarize.return_value = "要約テスト"

    collector = FeedCollector(session_factory=db_factory, summarizer=summarizer)

    parsed = _make_parsed_feed([
        {"link": "https://example.com/1", "title": "Article 1"},
    ])

    with patch("src.services.feed_collector.feedparser.parse", return_value=parsed):
        with patch("src.services.feed_collector.asyncio.to_thread", side_effect=lambda fn, *a: fn(*a)):
            articles = await collector.collect_all()

    assert len(articles) == 1
    assert articles[0].title == "Article 1"


async def test_ac2_duplicate_articles_skipped(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC2: 既に収集済みの記事はスキップする."""
    # 既存記事を追加
    async with db_factory() as session:
        feed_result = await session.execute(select(Feed))
        feed = feed_result.scalar_one()
        session.add(Article(feed_id=feed.id, title="Old", url="https://example.com/old"))
        await session.commit()

    summarizer = AsyncMock(spec=Summarizer)
    summarizer.summarize.return_value = "要約"

    collector = FeedCollector(session_factory=db_factory, summarizer=summarizer)

    parsed = _make_parsed_feed([
        {"link": "https://example.com/old", "title": "Old Article"},
        {"link": "https://example.com/new", "title": "New Article"},
    ])

    with patch("src.services.feed_collector.feedparser.parse", return_value=parsed):
        with patch("src.services.feed_collector.asyncio.to_thread", side_effect=lambda fn, *a: fn(*a)):
            articles = await collector.collect_all()

    assert len(articles) == 1
    assert articles[0].url == "https://example.com/new"


async def test_ac3_articles_are_summarized_by_local_llm(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC3: 新規記事をローカルLLMで要約しarticlesテーブルに保存する."""
    summarizer = AsyncMock(spec=Summarizer)
    summarizer.summarize.return_value = "LLMによる要約"

    collector = FeedCollector(session_factory=db_factory, summarizer=summarizer)

    parsed = _make_parsed_feed([
        {"link": "https://example.com/a", "title": "Test", "summary": "記事の概要"},
    ])

    with patch("src.services.feed_collector.feedparser.parse", return_value=parsed):
        with patch("src.services.feed_collector.asyncio.to_thread", side_effect=lambda fn, *a: fn(*a)):
            await collector.collect_all()

    summarizer.summarize.assert_called_once_with("Test", "https://example.com/a", "記事の概要")

    async with db_factory() as session:
        result = await session.execute(select(Article).where(Article.url == "https://example.com/a"))
        article = result.scalar_one()
        assert article.summary == "LLMによる要約"


async def test_ac3_description_fallback_when_no_summary(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC3: summaryが無くdescriptionのみの場合、descriptionがSummarizerに渡される."""
    summarizer = AsyncMock(spec=Summarizer)
    summarizer.summarize.return_value = "LLMによる要約"

    collector = FeedCollector(session_factory=db_factory, summarizer=summarizer)

    # summaryキーなし、descriptionのみ
    parsed = _make_parsed_feed([
        {"link": "https://example.com/desc", "title": "Desc Test", "description": "descriptionの内容"},
    ])

    with patch("src.services.feed_collector.feedparser.parse", return_value=parsed):
        with patch("src.services.feed_collector.asyncio.to_thread", side_effect=lambda fn, *a: fn(*a)):
            await collector.collect_all()

    summarizer.summarize.assert_called_once_with("Desc Test", "https://example.com/desc", "descriptionの内容")


async def test_ac8_rss_failure_continues_other_feeds(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC8: RSS取得失敗時はログ記録し他フィードの処理を継続する."""
    # 2つ目のフィードを追加
    async with db_factory() as session:
        session.add(Feed(url="https://bad.example.com/rss", name="Bad Feed", category="Other"))
        await session.commit()

    summarizer = AsyncMock(spec=Summarizer)
    summarizer.summarize.return_value = "要約"

    collector = FeedCollector(session_factory=db_factory, summarizer=summarizer)

    good_parsed = _make_parsed_feed([
        {"link": "https://example.com/good", "title": "Good"},
    ])

    def mock_parse(url: str):  # type: ignore[no-untyped-def]
        if "bad" in url:
            raise ConnectionError("Feed unavailable")
        return good_parsed

    with patch("src.services.feed_collector.feedparser.parse", side_effect=mock_parse):
        with patch("src.services.feed_collector.asyncio.to_thread", side_effect=lambda fn, *a: fn(*a)):
            articles = await collector.collect_all()

    # bad フィードが失敗しても good フィードの記事は収集される
    assert len(articles) == 1
    assert articles[0].title == "Good"


async def test_ac10_ogp_extractor_integration(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC10: OgpExtractorが統合され、image_urlが記事に設定される."""
    summarizer = AsyncMock(spec=Summarizer)
    summarizer.summarize.return_value = "要約"

    ogp_extractor = AsyncMock(spec=OgpExtractor)
    ogp_extractor.extract_image_url.return_value = "https://example.com/img.png"

    collector = FeedCollector(
        session_factory=db_factory,
        summarizer=summarizer,
        ogp_extractor=ogp_extractor,
    )

    parsed = _make_parsed_feed([
        {"link": "https://example.com/ogp", "title": "OGP Test"},
    ])

    with patch("src.services.feed_collector.feedparser.parse", return_value=parsed):
        with patch("src.services.feed_collector.asyncio.to_thread", side_effect=lambda fn, *a: fn(*a)):
            articles = await collector.collect_all()

    assert len(articles) == 1
    assert articles[0].image_url == "https://example.com/img.png"
    ogp_extractor.extract_image_url.assert_called_once()


async def test_ac10_no_ogp_extractor_backward_compat(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC10: OgpExtractor未指定時もimage_url=Noneで正常動作する."""
    summarizer = AsyncMock(spec=Summarizer)
    summarizer.summarize.return_value = "要約"

    collector = FeedCollector(session_factory=db_factory, summarizer=summarizer)

    parsed = _make_parsed_feed([
        {"link": "https://example.com/noimg", "title": "No Image"},
    ])

    with patch("src.services.feed_collector.feedparser.parse", return_value=parsed):
        with patch("src.services.feed_collector.asyncio.to_thread", side_effect=lambda fn, *a: fn(*a)):
            articles = await collector.collect_all()

    assert len(articles) == 1
    assert articles[0].image_url is None
