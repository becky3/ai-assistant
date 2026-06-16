"""配信フォーマット・配信ジョブのテスト (Issue #8, #123, #851)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.db.models import Article, Base, Feed
from src.messaging.port import ThreadRef
from src.messaging.slack_adapter import _build_card_blocks, _build_parent_blocks
from src.scheduler.jobs import (
    _format_article_datetime,
    _to_card,
    daily_collect_and_deliver,
    feed_test_deliver,
)
from src.services.feed_collector import NO_SUMMARY_TEXT


def _make_article(
    feed_id: int,
    title: str,
    url: str,
    summary: str,
    image_url: str | None = None,
    published_at: datetime | None = None,
    collected_at: datetime | None = None,
) -> Article:
    a = Article(
        feed_id=feed_id,
        title=title,
        url=url,
        summary=summary,
        image_url=image_url,
    )
    if published_at is not None:
        a.published_at = published_at
    if collected_at is not None:
        a.collected_at = collected_at
    else:
        a.collected_at = datetime(2026, 2, 6, 0, 0, 0, tzinfo=timezone.utc)
    return a


def _card(
    title: str = "Title",
    url: str = "https://a.com/1",
    summary: str = "summary",
    image_url: str | None = None,
    published_at: datetime | None = None,
    collected_at: datetime | None = None,
):  # type: ignore[no-untyped-def]
    """テスト用に Article → ArticleCard を作る."""
    return _to_card(
        _make_article(1, title, url, summary, image_url, published_at, collected_at)
    )


def _make_messaging() -> AsyncMock:
    """start_feed_thread が ThreadRef を返す messaging モック."""
    messaging = AsyncMock()
    messaging.start_feed_thread.return_value = ThreadRef(
        channel="C123", thread_key="parent.123"
    )
    return messaging


# --- カード描画（SlackAdapter）テスト ---


def test_build_card_blocks_displays_published_datetime() -> None:
    """更新日時がタイトル下に表示される（JST 変換）."""
    dt = datetime(2026, 2, 5, 14, 30, 0, tzinfo=timezone.utc)
    blocks = _build_card_blocks(_card(published_at=dt), "horizontal")
    first_text = blocks[0]["text"]["text"]
    assert "02-05 23:30" in first_text


def test_build_card_blocks_shows_fallback_text_for_empty_summary() -> None:
    """要約が空の場合は「（要約なし）」と表示する."""
    blocks = _build_card_blocks(_card(summary=""), "horizontal")
    section_texts = [
        b["text"]["text"] for b in blocks if b["type"] == "section"
    ]
    assert any(NO_SUMMARY_TEXT in t for t in section_texts)


def test_build_parent_blocks_includes_feed_name() -> None:
    """親メッセージにフィード名が表示される."""
    blocks = _build_parent_blocks("Python公式ブログ")
    assert len(blocks) == 1
    assert "Python公式ブログ" in blocks[0]["text"]["text"]


def test_format_article_datetime_falls_back_to_collected_at() -> None:
    """published_at が無い場合は collected_at にフォールバックする."""
    collected = datetime(2026, 2, 6, 9, 0, 0, tzinfo=timezone.utc)
    article = _make_article(
        1, "Title", "https://a.com/1", "summary",
        published_at=None, collected_at=collected,
    )
    dt_str = _format_article_datetime(article)
    # collected_at (UTC 9:00 → JST 18:00)
    assert "02-06 18:00" in dt_str


def test_build_card_blocks_horizontal_uses_accessory_for_image() -> None:
    """horizontal 形式では画像が accessory として配置される."""
    blocks = _build_card_blocks(
        _card(title="With Image", image_url="https://a.com/img.png"), "horizontal"
    )
    sections = [b for b in blocks if b["type"] == "section"]
    img_sections = [s for s in sections if "accessory" in s]
    assert len(img_sections) == 1
    assert img_sections[0]["accessory"]["image_url"] == "https://a.com/img.png"

    blocks_no_img = _build_card_blocks(_card(title="No Image"), "horizontal")
    sections_no_img = [b for b in blocks_no_img if b["type"] == "section"]
    content_sections = [
        s for s in sections_no_img if "No Image" in s.get("text", {}).get("text", "")
    ]
    assert len(content_sections) >= 1
    assert "accessory" not in content_sections[0]


def test_vertical_layout_renders_independent_image_block() -> None:
    """vertical レイアウトでは独立 image ブロックが表示される."""
    blocks = _build_card_blocks(
        _card(summary="summary text", image_url="https://a.com/img.png"), "vertical"
    )
    image_blocks = [b for b in blocks if b["type"] == "image"]
    assert len(image_blocks) == 1
    assert image_blocks[0]["image_url"] == "https://a.com/img.png"
    sections = [b for b in blocks if b["type"] == "section"]
    assert len(sections) == 2  # タイトル+日時 + 要約


def test_horizontal_layout_renders_image_as_accessory() -> None:
    """horizontal レイアウトでは画像が accessory として右側に表示される."""
    blocks = _build_card_blocks(
        _card(summary="summary text", image_url="https://a.com/img.png"), "horizontal"
    )
    image_blocks = [b for b in blocks if b["type"] == "image"]
    assert len(image_blocks) == 0
    sections = [b for b in blocks if b["type"] == "section"]
    assert len(sections) == 1
    content_section = sections[0]
    assert content_section["accessory"]["type"] == "image"
    assert content_section["accessory"]["image_url"] == "https://a.com/img.png"
    text = content_section["text"]["text"]
    assert "<https://a.com/1|Title>" in text
    assert "summary text" in text


def test_horizontal_layout_no_accessory_when_image_absent() -> None:
    """horizontal レイアウトで画像がない記事では accessory が付かない."""
    blocks = _build_card_blocks(_card(summary="summary text"), "horizontal")
    sections = [b for b in blocks if b["type"] == "section"]
    content_sections = [s for s in sections if "accessory" in s]
    assert len(content_sections) == 0


def test_vertical_layout_shows_title_and_summary_without_image() -> None:
    """vertical レイアウトで画像がない記事でもタイトル+要約が表示される."""
    blocks = _build_card_blocks(_card(summary="summary text"), "vertical")
    image_blocks = [b for b in blocks if b["type"] == "image"]
    assert len(image_blocks) == 0
    sections = [b for b in blocks if b["type"] == "section"]
    assert len(sections) == 2


# --- 配信ジョブ（daily_collect_and_deliver）テスト ---


@pytest.fixture
async def db_factory():  # type: ignore[no-untyped-def]
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        feed = Feed(url="https://example.com/rss", name="Test Feed", category="Python")
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


def _make_sequential_collector(undelivered: list[Article]) -> AsyncMock:
    """逐次型 daily_collect_and_deliver 用のコレクターモックを作成する."""
    collector = AsyncMock()

    async def mock_collect_feed(feed, on_article_ready=None, skip_summary=False):  # type: ignore[no-untyped-def]
        feed_articles = [a for a in undelivered if a.feed_id == feed.id]
        for article in feed_articles:
            if on_article_ready:
                should_continue = await on_article_ready(article)
                if not should_continue:
                    break
        return feed_articles

    collector.collect_feed = AsyncMock(side_effect=mock_collect_feed)
    return collector


async def test_daily_collect_and_deliver_posts_header_parent_thread_footer(db_factory) -> None:  # type: ignore[no-untyped-def]
    """daily_collect_and_deliver がヘッダー/親スレッド/記事/フッターを Port 経由で投稿する."""
    async with db_factory() as session:
        feeds = list((await session.execute(select(Feed))).scalars().all())
        undelivered = list(
            (await session.execute(
                select(Article).where(Article.delivered == False)  # noqa: E712
            )).scalars().all()
        )
    collector = _make_sequential_collector(undelivered)
    collector.get_enabled_feeds.return_value = feeds

    messaging = _make_messaging()
    await daily_collect_and_deliver(
        collector=collector,
        session_factory=db_factory,
        messaging=messaging,
        channel_id="C123",
    )

    collector.get_enabled_feeds.assert_called_once()
    collector.collect_feed.assert_called_once()
    messaging.post_header.assert_called_once()
    assert "今日のニュース" in messaging.post_header.call_args.args[1]
    messaging.start_feed_thread.assert_called_once()
    assert messaging.post_article_card.call_count == 1
    messaging.post_footer.assert_called_once()
    assert ":bulb:" in messaging.post_footer.call_args.args[1]
    # 記事カードは start_feed_thread が返した ThreadRef に投稿される
    posted_thread = messaging.post_article_card.call_args.args[0]
    assert posted_thread.thread_key == "parent.123"


async def test_daily_collect_and_deliver_does_not_crash_on_error(db_factory) -> None:  # type: ignore[no-untyped-def]
    """ジョブ内でエラーが発生してもクラッシュしない（投稿なし）."""
    collector = AsyncMock()
    collector.get_enabled_feeds.side_effect = RuntimeError("DB error")
    messaging = _make_messaging()

    await daily_collect_and_deliver(
        collector=collector,
        session_factory=db_factory,
        messaging=messaging,
        channel_id="C123",
    )
    messaging.post_header.assert_not_called()
    messaging.post_article_card.assert_not_called()


async def test_article_model_has_delivered_column_default_false(db_factory) -> None:  # type: ignore[no-untyped-def]
    """Article モデルに delivered カラムが追加されている."""
    async with db_factory() as session:
        result = await session.execute(select(Article))
        article = result.scalar_one_or_none()
        assert article is not None
        assert hasattr(article, "delivered")
        assert article.delivered is False


async def test_query_filters_only_undelivered_articles(db_factory) -> None:  # type: ignore[no-untyped-def]
    """配信対象クエリが delivered == False の記事のみを取得する."""
    async with db_factory() as session:
        feed = (await session.execute(select(Feed))).scalar_one()
        session.add_all([
            Article(
                feed_id=feed.id, title="Undelivered",
                url="https://example.com/undelivered",
                summary="undelivered summary", delivered=False,
            ),
            Article(
                feed_id=feed.id, title="Delivered",
                url="https://example.com/delivered",
                summary="delivered summary", delivered=True,
            ),
        ])
        await session.commit()
        result = await session.execute(
            select(Article).where(Article.delivered == False)  # noqa: E712
        )
        titles = [a.title for a in result.scalars().all()]
        assert "Undelivered" in titles
        assert "Delivered" not in titles


async def test_delivered_flag_set_true_after_posting(db_factory) -> None:  # type: ignore[no-untyped-def]
    """配信完了後、配信された記事の delivered が True に更新される."""
    async with db_factory() as session:
        feeds = list((await session.execute(select(Feed))).scalars().all())
        undelivered = list(
            (await session.execute(
                select(Article).where(Article.delivered == False)  # noqa: E712
            )).scalars().all()
        )
    collector = _make_sequential_collector(undelivered)
    collector.get_enabled_feeds.return_value = feeds

    messaging = _make_messaging()
    await daily_collect_and_deliver(
        collector=collector,
        session_factory=db_factory,
        messaging=messaging,
        channel_id="C123",
    )

    async with db_factory() as session:
        articles = list((await session.execute(select(Article))).scalars().all())
        assert all(a.delivered is True for a in articles)


async def test_already_delivered_articles_not_redelivered(db_factory) -> None:  # type: ignore[no-untyped-def]
    """deliver を複数回実行しても、配信済みの記事は再配信されない."""
    async with db_factory() as session:
        feeds = list((await session.execute(select(Feed))).scalars().all())
        undelivered = list(
            (await session.execute(
                select(Article).where(Article.delivered == False)  # noqa: E712
            )).scalars().all()
        )
    collector = _make_sequential_collector(undelivered)
    collector.get_enabled_feeds.return_value = feeds

    messaging = _make_messaging()
    await daily_collect_and_deliver(
        collector=collector, session_factory=db_factory,
        messaging=messaging, channel_id="C123",
    )
    first_count = messaging.post_article_card.call_count

    collector2 = _make_sequential_collector([])
    collector2.get_enabled_feeds.return_value = feeds
    await daily_collect_and_deliver(
        collector=collector2, session_factory=db_factory,
        messaging=messaging, channel_id="C123",
    )
    second_count = messaging.post_article_card.call_count

    assert first_count == 1
    assert second_count == 1  # 増えない


async def test_newly_collected_articles_delivered_in_next_run(db_factory) -> None:  # type: ignore[no-untyped-def]
    """新規収集された記事（delivered == False）は次回配信対象になる."""
    async with db_factory() as session:
        feeds = list((await session.execute(select(Feed))).scalars().all())
        undelivered = list(
            (await session.execute(
                select(Article).where(Article.delivered == False)  # noqa: E712
            )).scalars().all()
        )
    collector = _make_sequential_collector(undelivered)
    collector.get_enabled_feeds.return_value = feeds

    messaging = _make_messaging()
    await daily_collect_and_deliver(
        collector=collector, session_factory=db_factory,
        messaging=messaging, channel_id="C123",
    )
    first_count = messaging.post_article_card.call_count

    async with db_factory() as session:
        feed = (await session.execute(select(Feed))).scalar_one()
        new_article = Article(
            feed_id=feed.id, title="New Article",
            url="https://example.com/new", summary="new summary", delivered=False,
        )
        session.add(new_article)
        await session.commit()
        new_id = new_article.id

    async with db_factory() as session:
        new_articles = list(
            (await session.execute(select(Article).where(Article.id == new_id))).scalars().all()
        )
    collector2 = _make_sequential_collector(new_articles)
    collector2.get_enabled_feeds.return_value = feeds
    await daily_collect_and_deliver(
        collector=collector2, session_factory=db_factory,
        messaging=messaging, channel_id="C123",
    )
    second_count = messaging.post_article_card.call_count
    assert second_count > first_count


async def test_daily_collect_and_deliver_limits_to_max_per_feed(db_factory) -> None:  # type: ignore[no-untyped-def]
    """max_articles_per_feed を超える記事は配信されない."""
    async with db_factory() as session:
        feed = (await session.execute(select(Feed))).scalar_one()
        feeds = [feed]
        for i in range(15):
            session.add(Article(
                feed_id=feed.id, title=f"Art{i}",
                url=f"https://example.com/extra{i}", summary="s", delivered=False,
                collected_at=datetime.now(tz=timezone.utc),
            ))
        await session.commit()
        undelivered = list(
            (await session.execute(
                select(Article).where(Article.delivered == False)  # noqa: E712
            )).scalars().all()
        )
    collector = _make_sequential_collector(undelivered)
    collector.get_enabled_feeds.return_value = feeds

    messaging = _make_messaging()
    await daily_collect_and_deliver(
        collector=collector, session_factory=db_factory,
        messaging=messaging, channel_id="C123", max_articles_per_feed=5,
    )
    assert messaging.post_article_card.call_count == 5


# --- AC12: 設定（feed_card_layout）テスト ---


def test_settings_feed_card_layout_defaults_to_horizontal() -> None:
    """config.toml のデフォルト値で feed_card_layout は 'horizontal'."""
    from src.config.settings import Settings

    from .settings_defaults import TEST_SETTINGS_DEFAULTS

    s = Settings(**TEST_SETTINGS_DEFAULTS)
    assert s.feed_card_layout == "horizontal"


def test_settings_rejects_invalid_feed_card_layout() -> None:
    """不正な feed_card_layout 値を設定した場合、ValidationError が発生する."""
    from pydantic import ValidationError

    from src.config.settings import Settings

    from .settings_defaults import TEST_SETTINGS_DEFAULTS

    with pytest.raises(ValidationError):
        Settings(**{**TEST_SETTINGS_DEFAULTS, "feed_card_layout": "invalid"})


# --- AC15: feed test コマンド ---


@pytest.fixture
async def db_factory_with_delivered():  # type: ignore[no-untyped-def]
    """配信済み・未配信の両方の記事を含むDBファクトリ."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        feed1 = Feed(url="https://example.com/rss1", name="Feed 1", category="Python", enabled=True)
        feed2 = Feed(url="https://example.com/rss2", name="Feed 2", category="ML", enabled=True)
        session.add_all([feed1, feed2])
        await session.commit()
        session.add_all([
            Article(
                feed_id=feed1.id, title="Delivered Art", url="https://example.com/d1",
                summary="delivered", delivered=True,
                collected_at=datetime.now(tz=timezone.utc),
            ),
            Article(
                feed_id=feed1.id, title="Undelivered Art", url="https://example.com/u1",
                summary="undelivered", delivered=False,
                collected_at=datetime.now(tz=timezone.utc),
            ),
        ])
        session.add(Article(
            feed_id=feed2.id, title="Delivered Art 2", url="https://example.com/d2",
            summary="delivered 2", delivered=True,
            collected_at=datetime.now(tz=timezone.utc),
        ))
        await session.commit()
    yield factory
    await engine.dispose()


async def test_feed_test_deliver_uses_existing_articles_without_collection(db_factory_with_delivered) -> None:  # type: ignore[no-untyped-def]
    """feed test は新規収集を行わない（既存記事のみ出力）."""
    messaging = _make_messaging()
    await feed_test_deliver(
        session_factory=db_factory_with_delivered,
        messaging=messaging,
        channel_id="C123",
    )
    assert messaging.post_article_card.call_count > 0


async def test_feed_test_deliver_includes_already_delivered_articles(db_factory_with_delivered) -> None:  # type: ignore[no-untyped-def]
    """feed test は配信済み記事も含めて出力する."""
    messaging = _make_messaging()
    await feed_test_deliver(
        session_factory=db_factory_with_delivered,
        messaging=messaging,
        channel_id="C123",
    )
    # 親スレッド(2 feeds) + 記事(feed1 に2件 + feed2 に1件 = 3)
    assert messaging.start_feed_thread.call_count == 2
    assert messaging.post_article_card.call_count == 3
    messaging.post_header.assert_called_once()
    messaging.post_footer.assert_called_once()


async def test_feed_test_deliver_limits_output_to_max_feeds() -> None:
    """feed test は上から max_feeds 分のフィードのみ対象とする."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        feeds = []
        for i in range(10):
            f = Feed(url=f"https://example.com/rss{i}", name=f"Feed {i}", category="Cat", enabled=True)
            session.add(f)
            feeds.append(f)
        await session.commit()
        for f in feeds:
            session.add(Article(
                feed_id=f.id, title=f"Art for {f.name}",
                url=f"https://example.com/art{f.id}", summary="summary",
                collected_at=datetime.now(tz=timezone.utc),
            ))
        await session.commit()

    messaging = _make_messaging()
    await feed_test_deliver(
        session_factory=factory,
        messaging=messaging,
        channel_id="C123",
        max_feeds=3,
    )
    assert messaging.start_feed_thread.call_count == 3
    assert messaging.post_article_card.call_count == 3
    await engine.dispose()


async def test_feed_test_deliver_preserves_delivered_flag(db_factory_with_delivered) -> None:  # type: ignore[no-untyped-def]
    """feed test は delivered フラグを更新しない."""
    messaging = _make_messaging()
    async with db_factory_with_delivered() as session:
        before = {a.url: a.delivered for a in (await session.execute(select(Article))).scalars().all()}

    await feed_test_deliver(
        session_factory=db_factory_with_delivered,
        messaging=messaging,
        channel_id="C123",
    )

    async with db_factory_with_delivered() as session:
        after = {a.url: a.delivered for a in (await session.execute(select(Article))).scalars().all()}
    assert before == after


async def test_feed_test_deliver_outputs_parent_and_thread_format(db_factory_with_delivered) -> None:  # type: ignore[no-untyped-def]
    """feed test は親メッセージ+スレッド形式で出力する（テストヘッダー付き）."""
    messaging = _make_messaging()
    await feed_test_deliver(
        session_factory=db_factory_with_delivered,
        messaging=messaging,
        channel_id="C123",
    )
    header_text = messaging.post_header.call_args.args[1]
    assert "今日のニュース" in header_text
    assert "テスト" in header_text
    # 記事は start_feed_thread が返した ThreadRef に投稿される
    assert messaging.post_article_card.call_count > 0
    for call in messaging.post_article_card.call_args_list:
        assert call.args[0].thread_key == "parent.123"
