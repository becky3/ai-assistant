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


# ===== AC7: フィード管理機能のテスト =====


async def test_ac7_1_add_feed_with_category(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC7.1: フィードを追加できる（カテゴリ指定あり）."""
    summarizer = AsyncMock(spec=Summarizer)
    collector = FeedCollector(session_factory=db_factory, summarizer=summarizer)

    feed = await collector.add_feed("https://new.example.com/rss", "New Feed", "Python")

    assert feed.url == "https://new.example.com/rss"
    assert feed.name == "New Feed"
    assert feed.category == "Python"
    assert feed.enabled is True

    # DB確認
    async with db_factory() as session:
        result = await session.execute(select(Feed).where(Feed.url == "https://new.example.com/rss"))
        saved = result.scalar_one()
        assert saved.category == "Python"


async def test_ac7_2_add_multiple_feeds(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC7.2: 複数フィードを一括追加できる（複数add_feed呼び出し想定）."""
    summarizer = AsyncMock(spec=Summarizer)
    collector = FeedCollector(session_factory=db_factory, summarizer=summarizer)

    feed1 = await collector.add_feed("https://feed1.com/rss", "Feed 1", "Python")
    feed2 = await collector.add_feed("https://feed2.com/rss", "Feed 2", "Python")

    assert feed1.url == "https://feed1.com/rss"
    assert feed2.url == "https://feed2.com/rss"

    async with db_factory() as session:
        result = await session.execute(select(Feed))
        all_feeds = list(result.scalars().all())
        # 初期フィード(Test Feed) + feed1 + feed2 = 3件
        assert len(all_feeds) == 3


async def test_ac7_3_list_feeds_classified(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC7.3: フィード一覧を有効/無効で分類表示できる."""
    summarizer = AsyncMock(spec=Summarizer)
    collector = FeedCollector(session_factory=db_factory, summarizer=summarizer)

    # 無効フィードを追加
    async with db_factory() as session:
        session.add(Feed(url="https://disabled.com/rss", name="Disabled", enabled=False))
        await session.commit()

    enabled, disabled = await collector.list_feeds()

    assert len(enabled) == 1  # 初期の Test Feed
    assert enabled[0].url == "https://example.com/rss"
    assert len(disabled) == 1
    assert disabled[0].url == "https://disabled.com/rss"


async def test_ac7_4_delete_feed_cascades_articles(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC7.4: フィード削除時に関連記事もCASCADE削除される."""
    summarizer = AsyncMock(spec=Summarizer)
    collector = FeedCollector(session_factory=db_factory, summarizer=summarizer)

    # 記事を追加
    async with db_factory() as session:
        feed_result = await session.execute(select(Feed))
        feed = feed_result.scalar_one()
        session.add(Article(feed_id=feed.id, title="Test Article", url="https://example.com/a"))
        await session.commit()

    # フィードを削除
    await collector.delete_feed("https://example.com/rss")

    # フィードが削除されたことを確認
    async with db_factory() as session:
        feed_result = await session.execute(select(Feed).where(Feed.url == "https://example.com/rss"))
        assert feed_result.scalar_one_or_none() is None

        # 関連記事も削除されたことを確認
        article_result = await session.execute(select(Article))
        articles = list(article_result.scalars().all())
        assert len(articles) == 0


async def test_ac7_5_delete_multiple_feeds(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC7.5: 複数フィードを一括削除できる（複数delete_feed呼び出し想定）."""
    summarizer = AsyncMock(spec=Summarizer)
    collector = FeedCollector(session_factory=db_factory, summarizer=summarizer)

    # 複数フィードを追加
    await collector.add_feed("https://feed1.com/rss", "Feed 1")
    await collector.add_feed("https://feed2.com/rss", "Feed 2")

    # 複数削除
    await collector.delete_feed("https://feed1.com/rss")
    await collector.delete_feed("https://feed2.com/rss")

    async with db_factory() as session:
        result = await session.execute(select(Feed))
        all_feeds = list(result.scalars().all())
        # 初期フィード(Test Feed)のみ残る
        assert len(all_feeds) == 1
        assert all_feeds[0].url == "https://example.com/rss"


async def test_ac7_6_enable_feed(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC7.6: フィードを有効化できる."""
    summarizer = AsyncMock(spec=Summarizer)
    collector = FeedCollector(session_factory=db_factory, summarizer=summarizer)

    # 無効フィードを追加
    async with db_factory() as session:
        session.add(Feed(url="https://disabled.com/rss", name="Disabled", enabled=False))
        await session.commit()

    await collector.enable_feed("https://disabled.com/rss")

    async with db_factory() as session:
        result = await session.execute(select(Feed).where(Feed.url == "https://disabled.com/rss"))
        feed = result.scalar_one()
        assert feed.enabled is True


async def test_ac7_7_disable_feed(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC7.7: フィードを無効化できる."""
    summarizer = AsyncMock(spec=Summarizer)
    collector = FeedCollector(session_factory=db_factory, summarizer=summarizer)

    await collector.disable_feed("https://example.com/rss")

    async with db_factory() as session:
        result = await session.execute(select(Feed).where(Feed.url == "https://example.com/rss"))
        feed = result.scalar_one()
        assert feed.enabled is False


async def test_ac7_8_enable_disable_multiple_feeds(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC7.8: 複数フィードを一括で有効化/無効化できる."""
    summarizer = AsyncMock(spec=Summarizer)
    collector = FeedCollector(session_factory=db_factory, summarizer=summarizer)

    # 複数フィードを追加
    await collector.add_feed("https://feed1.com/rss", "Feed 1")
    await collector.add_feed("https://feed2.com/rss", "Feed 2")

    # 複数無効化
    await collector.disable_feed("https://feed1.com/rss")
    await collector.disable_feed("https://feed2.com/rss")

    async with db_factory() as session:
        result = await session.execute(select(Feed).where(Feed.url.in_(["https://feed1.com/rss", "https://feed2.com/rss"])))
        feeds = list(result.scalars().all())
        assert all(not f.enabled for f in feeds)

    # 複数有効化
    await collector.enable_feed("https://feed1.com/rss")
    await collector.enable_feed("https://feed2.com/rss")

    async with db_factory() as session:
        result = await session.execute(select(Feed).where(Feed.url.in_(["https://feed1.com/rss", "https://feed2.com/rss"])))
        feeds = list(result.scalars().all())
        assert all(f.enabled for f in feeds)


async def test_ac7_9_duplicate_url_error(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC7.9: 重複URLの追加時にValueErrorが発生する."""
    summarizer = AsyncMock(spec=Summarizer)
    collector = FeedCollector(session_factory=db_factory, summarizer=summarizer)

    with pytest.raises(ValueError, match="既に登録されています"):
        await collector.add_feed("https://example.com/rss", "Duplicate")


async def test_ac7_10_nonexistent_feed_delete_error(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC7.10: 存在しないフィードの削除時にValueErrorが発生する."""
    summarizer = AsyncMock(spec=Summarizer)
    collector = FeedCollector(session_factory=db_factory, summarizer=summarizer)

    with pytest.raises(ValueError, match="登録されていません"):
        await collector.delete_feed("https://nonexistent.com/rss")


async def test_ac7_11_nonexistent_feed_enable_error(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC7.11: 存在しないフィードの有効化時にValueErrorが発生する."""
    summarizer = AsyncMock(spec=Summarizer)
    collector = FeedCollector(session_factory=db_factory, summarizer=summarizer)

    with pytest.raises(ValueError, match="登録されていません"):
        await collector.enable_feed("https://nonexistent.com/rss")


async def test_ac7_12_nonexistent_feed_disable_error(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC7.12: 存在しないフィードの無効化時にValueErrorが発生する."""
    summarizer = AsyncMock(spec=Summarizer)
    collector = FeedCollector(session_factory=db_factory, summarizer=summarizer)

    with pytest.raises(ValueError, match="登録されていません"):
        await collector.disable_feed("https://nonexistent.com/rss")


async def test_ac7_13_add_feed_default_category(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC7.13: カテゴリ省略時はデフォルトカテゴリ「一般」が設定される."""
    summarizer = AsyncMock(spec=Summarizer)
    collector = FeedCollector(session_factory=db_factory, summarizer=summarizer)

    feed = await collector.add_feed("https://default.com/rss", "Default Feed")

    assert feed.category == "一般"
