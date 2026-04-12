"""配信フォーマットのテスト (Issue #8, #123)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.db.models import Article, Base, Feed
from src.scheduler.jobs import (
    _build_article_blocks,
    _build_parent_message,
    _format_article_datetime,
    daily_collect_and_deliver,
    feed_test_deliver,
    format_daily_digest,
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


def test_format_daily_digest_returns_per_feed_block_kit_dict() -> None:
    """AC5/AC14: format_daily_digest がフィード別のBlock Kit blocksを返す."""
    feeds = {
        1: Feed(id=1, url="https://a.com/rss", name="A Feed", category="Python"),
        2: Feed(id=2, url="https://b.com/rss", name="B Feed", category="機械学習"),
    }
    articles = [
        _make_article(1, "asyncioの新機能", "https://a.com/1", "asyncio要約"),
        _make_article(2, "transformer効率化", "https://b.com/1", "transformer要約"),
    ]

    result = format_daily_digest(articles, feeds)

    assert isinstance(result, dict)
    # フィードIDがキーとして使われる
    assert 1 in result
    assert 2 in result
    # 各フィードに (parent_blocks, article_blocks_list) タプルが返る
    parent_blocks, article_blocks_list = result[1]
    assert any(b["type"] == "section" for b in parent_blocks)
    assert len(article_blocks_list) == 1  # 1記事
    assert any(b["type"] == "section" for b in article_blocks_list[0])


def test_format_daily_digest_returns_empty_dict_when_no_articles() -> None:
    """AC5: 記事がない場合は空辞書を返す."""
    assert format_daily_digest([], {}) == {}


def test_format_daily_digest_shows_fallback_text_for_empty_summary() -> None:
    """AC5: 要約が空の場合は「（要約なし）」と表示する."""
    feeds = {1: Feed(id=1, url="https://a.com/rss", name="A Feed", category="Python")}
    articles = [_make_article(1, "Title", "https://a.com/1", "")]

    result = format_daily_digest(articles, feeds)
    _, article_blocks_list = result[1]
    # 記事のblocksを確認
    article_blocks = article_blocks_list[0]
    section_texts = [
        b["text"]["text"] for b in article_blocks if b["type"] == "section"
    ]
    assert any(NO_SUMMARY_TEXT in t for t in section_texts)


def test_build_parent_message_includes_feed_name() -> None:
    """AC14.1: 親メッセージにフィード名が表示される."""
    blocks = _build_parent_message("Python公式ブログ")
    assert len(blocks) == 1
    text = blocks[0]["text"]["text"]
    assert "Python公式ブログ" in text


def test_format_daily_digest_returns_separate_blocks_per_article() -> None:
    """AC14.2: 記事ごとに個別のBlock Kitブロックリストが返される."""
    feeds = {1: Feed(id=1, url="https://a.com/rss", name="A Feed", category="Python")}
    articles = [
        _make_article(1, "Title1", "https://a.com/1", "summary1"),
        _make_article(1, "Title2", "https://a.com/2", "summary2"),
        _make_article(1, "Title3", "https://a.com/3", "summary3"),
    ]

    result = format_daily_digest(articles, feeds)
    _, article_blocks_list = result[1]
    # 3記事 = 3つの独立したブロックリスト
    assert len(article_blocks_list) == 3


def test_build_article_blocks_displays_published_datetime() -> None:
    """AC14.3: 更新日時がタイトル下に表示される."""
    dt = datetime(2026, 2, 5, 14, 30, 0, tzinfo=timezone.utc)
    article = _make_article(1, "Title", "https://a.com/1", "summary", published_at=dt)
    blocks = _build_article_blocks(article)

    # 記事ブロックのテキストに日時が含まれる
    first_text = blocks[0]["text"]["text"]
    assert "02-05" in first_text
    assert "02-05 23:30" in first_text


def test_format_article_datetime_falls_back_to_collected_at() -> None:
    """AC14.4: published_at が無い場合は collected_at にフォールバックする."""
    collected = datetime(2026, 2, 6, 9, 0, 0, tzinfo=timezone.utc)
    article = _make_article(
        1, "Title", "https://a.com/1", "summary",
        published_at=None, collected_at=collected,
    )
    dt_str = _format_article_datetime(article)
    # collected_at (UTC 9:00 → JST 18:00) の文字列が返る
    assert "02-06 18:00" in dt_str


def test_format_daily_digest_truncates_articles_beyond_max_per_feed() -> None:
    """max_articles_per_feed を超える記事は切り詰められる."""
    feeds = {1: Feed(id=1, url="https://a.com/rss", name="A Feed", category="Python")}
    articles = [
        _make_article(1, f"Title{i}", f"https://a.com/{i}", f"summary{i}")
        for i in range(15)
    ]
    result = format_daily_digest(articles, feeds, max_articles_per_feed=5)
    _, article_blocks_list = result[1]
    assert len(article_blocks_list) == 5


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


async def test_daily_collect_and_deliver_posts_header_parent_thread_footer(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC4/AC14: daily_collect_and_deliver がフィード別にSlack投稿する（逐次型）."""
    collector = AsyncMock()

    # get_enabled_feeds が DB 内のフィードを返すようモック
    async with db_factory() as session:
        feed_result = await session.execute(select(Feed))
        feeds = list(feed_result.scalars().all())
    collector.get_enabled_feeds.return_value = feeds

    # collect_feed: on_article_ready コールバックを呼び出して逐次投稿をシミュレート
    async with db_factory() as session:
        article_result = await session.execute(
            select(Article).where(Article.delivered == False)  # noqa: E712
        )
        undelivered = list(article_result.scalars().all())

    async def mock_collect_feed(feed, on_article_ready=None, skip_summary=False):  # type: ignore[no-untyped-def]
        feed_articles = [a for a in undelivered if a.feed_id == feed.id]
        for article in feed_articles:
            if on_article_ready:
                should_continue = await on_article_ready(article)
                if not should_continue:
                    break
        return feed_articles

    collector.collect_feed = AsyncMock(side_effect=mock_collect_feed)

    slack_client = AsyncMock()
    slack_client.chat_postMessage.return_value = {"ts": "parent.123"}

    await daily_collect_and_deliver(
        collector=collector,
        session_factory=db_factory,
        slack_client=slack_client,
        channel_id="C123",
    )

    collector.get_enabled_feeds.assert_called_once()
    collector.collect_feed.assert_called_once()
    # ヘッダー(1) + 親メッセージ(1) + スレッド記事(1) + フッター(1) = 4回
    assert slack_client.chat_postMessage.call_count == 4

    calls = slack_client.chat_postMessage.call_args_list
    # ヘッダー
    assert "今日のニュース" in calls[0].kwargs["text"]
    assert "blocks" in calls[0].kwargs
    # 親メッセージ
    assert "blocks" in calls[1].kwargs
    # スレッド記事（thread_ts がある）
    assert "thread_ts" in calls[2].kwargs
    assert calls[2].kwargs["thread_ts"] == "parent.123"
    # フッター
    assert ":bulb:" in calls[3].kwargs["text"]


async def test_daily_collect_and_deliver_does_not_crash_on_error(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC4: ジョブ内でエラーが発生してもクラッシュしない."""
    collector = AsyncMock()
    collector.get_enabled_feeds.side_effect = RuntimeError("DB error")
    slack_client = AsyncMock()

    await daily_collect_and_deliver(
        collector=collector,
        session_factory=db_factory,
        slack_client=slack_client,
        channel_id="C123",
    )
    slack_client.chat_postMessage.assert_not_called()


def test_build_article_blocks_horizontal_uses_accessory_for_image() -> None:
    """AC10: image_urlがある記事でhorizontal形式ではaccessoryとして配置される."""
    article_with_img = _make_article(
        1, "With Image", "https://a.com/1", "summary",
        image_url="https://a.com/img.png",
    )
    blocks = _build_article_blocks(article_with_img, layout="horizontal")

    sections = [b for b in blocks if b["type"] == "section"]
    img_sections = [s for s in sections if "accessory" in s]
    assert len(img_sections) == 1
    assert img_sections[0]["accessory"]["image_url"] == "https://a.com/img.png"

    # 画像なし記事
    article_no_img = _make_article(1, "No Image", "https://a.com/2", "summary")
    blocks_no_img = _build_article_blocks(article_no_img, layout="horizontal")
    sections_no_img = [b for b in blocks_no_img if b["type"] == "section"]
    content_sections = [s for s in sections_no_img if "No Image" in s.get("text", {}).get("text", "")]
    assert len(content_sections) >= 1
    assert "accessory" not in content_sections[0]


async def test_article_model_has_delivered_column_default_false(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC11.1: Article モデルに delivered カラムが追加されている."""
    async with db_factory() as session:
        result = await session.execute(select(Article))
        article = result.scalar_one_or_none()
        assert article is not None
        assert hasattr(article, "delivered")
        assert article.delivered is False  # デフォルト値


async def test_query_filters_only_undelivered_articles(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC11.2: 配信対象クエリが delivered == False の記事のみを取得する."""
    async with db_factory() as session:
        feed_result = await session.execute(select(Feed))
        feed = feed_result.scalar_one()

        # 未配信記事を追加
        undelivered = Article(
            feed_id=feed.id,
            title="Undelivered",
            url="https://example.com/undelivered",
            summary="undelivered summary",
            delivered=False,
        )
        # 配信済み記事を追加
        delivered = Article(
            feed_id=feed.id,
            title="Delivered",
            url="https://example.com/delivered",
            summary="delivered summary",
            delivered=True,
        )
        session.add_all([undelivered, delivered])
        await session.commit()

        # 未配信記事のみ取得
        result = await session.execute(
            select(Article).where(Article.delivered == False)  # noqa: E712
        )
        articles = list(result.scalars().all())
        titles = [a.title for a in articles]

        assert "Undelivered" in titles
        assert "Delivered" not in titles


def _make_sequential_collector(db_factory, undelivered: list[Article]) -> AsyncMock:  # type: ignore[no-untyped-def]
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


async def test_delivered_flag_set_true_after_slack_posting(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC11.3: Slack配信完了後、配信された記事の delivered が True に更新される."""
    async with db_factory() as session:
        feeds = list((await session.execute(select(Feed))).scalars().all())
        undelivered = list(
            (await session.execute(
                select(Article).where(Article.delivered == False)  # noqa: E712
            )).scalars().all()
        )

    collector = _make_sequential_collector(db_factory, undelivered)
    collector.get_enabled_feeds.return_value = feeds

    slack_client = AsyncMock()
    slack_client.chat_postMessage.return_value = {"ts": "parent.123"}

    await daily_collect_and_deliver(
        collector=collector,
        session_factory=db_factory,
        slack_client=slack_client,
        channel_id="C123",
    )

    # 配信後、記事の delivered フラグが True になっていることを確認
    async with db_factory() as session:
        result = await session.execute(select(Article))
        articles = list(result.scalars().all())
        assert all(a.delivered is True for a in articles)


async def test_already_delivered_articles_not_redelivered(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC11.4: deliver を複数回実行しても、既に配信済みの記事は再配信されない."""
    async with db_factory() as session:
        feeds = list((await session.execute(select(Feed))).scalars().all())
        undelivered = list(
            (await session.execute(
                select(Article).where(Article.delivered == False)  # noqa: E712
            )).scalars().all()
        )

    collector = _make_sequential_collector(db_factory, undelivered)
    collector.get_enabled_feeds.return_value = feeds

    slack_client = AsyncMock()
    slack_client.chat_postMessage.return_value = {"ts": "parent.123"}

    # 1回目の配信
    await daily_collect_and_deliver(
        collector=collector,
        session_factory=db_factory,
        slack_client=slack_client,
        channel_id="C123",
    )
    first_call_count = slack_client.chat_postMessage.call_count

    # 2回目の配信（collect_feed が新記事を返さない）
    collector2 = _make_sequential_collector(db_factory, [])
    collector2.get_enabled_feeds.return_value = feeds
    await daily_collect_and_deliver(
        collector=collector2,
        session_factory=db_factory,
        slack_client=slack_client,
        channel_id="C123",
    )
    second_call_count = slack_client.chat_postMessage.call_count

    # 1回目は配信されるが、2回目は配信されない
    assert first_call_count == 4  # ヘッダー + 親 + スレッド記事 + フッター
    assert second_call_count == 4  # 増えない（新規投稿なし）


async def test_newly_collected_articles_delivered_in_next_run(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC11.5: 新規収集された記事（delivered == False）は次回配信対象になる."""
    async with db_factory() as session:
        feeds = list((await session.execute(select(Feed))).scalars().all())
        undelivered = list(
            (await session.execute(
                select(Article).where(Article.delivered == False)  # noqa: E712
            )).scalars().all()
        )

    collector = _make_sequential_collector(db_factory, undelivered)
    collector.get_enabled_feeds.return_value = feeds

    slack_client = AsyncMock()
    slack_client.chat_postMessage.return_value = {"ts": "parent.123"}

    # 1回目の配信
    await daily_collect_and_deliver(
        collector=collector,
        session_factory=db_factory,
        slack_client=slack_client,
        channel_id="C123",
    )
    first_call_count = slack_client.chat_postMessage.call_count

    # 新規記事を追加
    async with db_factory() as session:
        feed_result = await session.execute(select(Feed))
        feed = feed_result.scalar_one()
        new_article = Article(
            feed_id=feed.id,
            title="New Article",
            url="https://example.com/new",
            summary="new summary",
            delivered=False,
        )
        session.add(new_article)
        await session.commit()
        new_id = new_article.id

    # 2回目の配信（新規記事あり）
    async with db_factory() as session:
        new_articles = list(
            (await session.execute(
                select(Article).where(Article.id == new_id)
            )).scalars().all()
        )
    collector2 = _make_sequential_collector(db_factory, new_articles)
    collector2.get_enabled_feeds.return_value = feeds

    await daily_collect_and_deliver(
        collector=collector2,
        session_factory=db_factory,
        slack_client=slack_client,
        channel_id="C123",
    )
    second_call_count = slack_client.chat_postMessage.call_count

    # 新規記事が配信される
    assert second_call_count > first_call_count


# --- AC12: 配信カード形式の切り替え ---


def test_settings_feed_card_layout_defaults_to_horizontal() -> None:
    """AC12.1: config.toml のデフォルト値で feed_card_layout は 'horizontal'."""
    from src.config.settings import Settings

    from .settings_defaults import TEST_SETTINGS_DEFAULTS

    s = Settings(**TEST_SETTINGS_DEFAULTS)
    assert s.feed_card_layout == "horizontal"


def test_vertical_layout_renders_independent_image_block() -> None:
    """AC12.2: vertical レイアウトでは独立imageブロックが表示される."""
    article = _make_article(
        1, "Title", "https://a.com/1", "summary text",
        image_url="https://a.com/img.png",
    )
    blocks = _build_article_blocks(article, layout="vertical")

    image_blocks = [b for b in blocks if b["type"] == "image"]
    assert len(image_blocks) == 1
    assert image_blocks[0]["image_url"] == "https://a.com/img.png"

    # タイトル+日時section + 要約section = 2 sections
    sections = [b for b in blocks if b["type"] == "section"]
    assert len(sections) == 2  # タイトル+日時 + 要約


def test_horizontal_layout_renders_image_as_accessory() -> None:
    """AC12.3: horizontal レイアウトでは画像がaccessoryとして右側に表示される."""
    article = _make_article(
        1, "Title", "https://a.com/1", "summary text",
        image_url="https://a.com/img.png",
    )
    blocks = _build_article_blocks(article, layout="horizontal")

    # 独立imageブロックがない
    image_blocks = [b for b in blocks if b["type"] == "image"]
    assert len(image_blocks) == 0

    # 記事section = 1 section（タイトル+日時+要約が統合）
    sections = [b for b in blocks if b["type"] == "section"]
    assert len(sections) == 1
    # 記事sectionにaccessoryあり
    content_section = sections[0]
    assert content_section["accessory"]["type"] == "image"
    assert content_section["accessory"]["image_url"] == "https://a.com/img.png"

    # タイトルと要約が同じsectionに含まれる
    text = content_section["text"]["text"]
    assert "<https://a.com/1|Title>" in text
    assert "summary text" in text


def test_horizontal_layout_no_accessory_when_image_absent() -> None:
    """AC12.4: horizontal レイアウトで画像がない記事ではaccessoryが付かない."""
    article = _make_article(1, "Title", "https://a.com/1", "summary text")
    blocks = _build_article_blocks(article, layout="horizontal")

    sections = [b for b in blocks if b["type"] == "section"]
    # 記事のコンテンツsection（日時を除く）
    content_sections = [s for s in sections if "accessory" in s]
    assert len(content_sections) == 0


def test_vertical_layout_shows_title_and_summary_without_image() -> None:
    """AC12.5: vertical レイアウトで画像がない記事でもタイトル+要約が正常に表示される."""
    article = _make_article(1, "Title", "https://a.com/1", "summary text")
    blocks = _build_article_blocks(article, layout="vertical")

    image_blocks = [b for b in blocks if b["type"] == "image"]
    assert len(image_blocks) == 0

    sections = [b for b in blocks if b["type"] == "section"]
    assert len(sections) == 2  # タイトル+日時 + 要約


def test_format_daily_digest_passes_layout_to_article_blocks() -> None:
    """AC12.6: format_daily_digest が layout を _build_article_blocks に渡す."""
    feeds = {1: Feed(id=1, url="https://a.com/rss", name="A Feed", category="Python")}
    articles = [
        _make_article(1, "Title", "https://a.com/1", "summary", image_url="https://a.com/img.png"),
    ]

    # horizontal
    result_h = format_daily_digest(articles, feeds, layout="horizontal")
    _, article_blocks_list_h = result_h[1]
    sections_h = [b for b in article_blocks_list_h[0] if b["type"] == "section"]
    assert any("accessory" in s for s in sections_h)

    # vertical
    result_v = format_daily_digest(articles, feeds, layout="vertical")
    _, article_blocks_list_v = result_v[1]
    image_blocks = [b for b in article_blocks_list_v[0] if b["type"] == "image"]
    assert len(image_blocks) == 1


async def test_manual_deliver_command_passes_layout_from_router() -> None:
    """AC12.7: 手動配信コマンドで MessageRouter の layout が daily_collect_and_deliver に渡される."""
    from unittest.mock import patch

    from src.messaging.port import IncomingMessage
    from src.messaging.router import MessageRouter

    messaging = AsyncMock()
    chat_service = AsyncMock()
    collector = AsyncMock()
    session_factory = AsyncMock()
    slack_client = AsyncMock()
    channel_id = "C_TEST"

    router = MessageRouter(
        messaging=messaging,
        chat_service=chat_service,
        collector=collector,
        session_factory=session_factory,
        channel_id=channel_id,
        max_articles_per_feed=10,
        feed_card_layout="vertical",
        bot_token=None,
        timezone="Asia/Tokyo",
        env_name="",
        mcp_manager=None,
        bot_start_time=None,
        slack_client=slack_client,
        rag_bluesky_handle="",
        rag_zenn_username="",
        rag_bluesky_max_posts=100,
        rag_zenn_max_articles=10,
    )

    msg = IncomingMessage(
        user_id="U123",
        text="deliver",
        thread_id="123.456",
        channel="C_TEST",
        is_in_thread=False,
        message_id="123.456",
    )

    mock_deliver = AsyncMock()
    with patch("src.scheduler.jobs.daily_collect_and_deliver", mock_deliver):
        await router.process_message(msg)

    mock_deliver.assert_called_once_with(
        collector, session_factory, slack_client, channel_id,
        max_articles_per_feed=10,
        layout="vertical",
    )


def test_settings_rejects_invalid_feed_card_layout() -> None:
    """AC12.8: 不正な feed_card_layout 値を設定した場合、ValidationErrorが発生する."""
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

        # Feed 1: 配信済み1件 + 未配信1件
        session.add_all([
            Article(
                feed_id=feed1.id,
                title="Delivered Art",
                url="https://example.com/d1",
                summary="delivered",
                delivered=True,
                collected_at=datetime.now(tz=timezone.utc),
            ),
            Article(
                feed_id=feed1.id,
                title="Undelivered Art",
                url="https://example.com/u1",
                summary="undelivered",
                delivered=False,
                collected_at=datetime.now(tz=timezone.utc),
            ),
        ])
        # Feed 2: 配信済み1件
        session.add(Article(
            feed_id=feed2.id,
            title="Delivered Art 2",
            url="https://example.com/d2",
            summary="delivered 2",
            delivered=True,
            collected_at=datetime.now(tz=timezone.utc),
        ))
        await session.commit()
    yield factory
    await engine.dispose()


async def test_feed_test_deliver_uses_existing_articles_without_collection(db_factory_with_delivered) -> None:  # type: ignore[no-untyped-def]
    """AC15.1: feed test は新規収集を行わない（既存記事のみ出力）."""
    slack_client = AsyncMock()
    slack_client.chat_postMessage.return_value = {"ts": "parent.123"}

    await feed_test_deliver(
        session_factory=db_factory_with_delivered,
        slack_client=slack_client,
        channel_id="C123",
    )

    # Slackに投稿されていること（新規収集なしで既存記事を配信）
    assert slack_client.chat_postMessage.call_count > 0


async def test_feed_test_deliver_includes_already_delivered_articles(db_factory_with_delivered) -> None:  # type: ignore[no-untyped-def]
    """AC15.2: feed test は配信済み記事も含めて出力する."""
    slack_client = AsyncMock()
    slack_client.chat_postMessage.return_value = {"ts": "parent.123"}

    await feed_test_deliver(
        session_factory=db_factory_with_delivered,
        slack_client=slack_client,
        channel_id="C123",
    )

    # ヘッダー(1) + 親メッセージ(2) + スレッド記事(3: feed1に2件 + feed2に1件) + フッター(1) = 7
    assert slack_client.chat_postMessage.call_count == 7


async def test_feed_test_deliver_limits_output_to_max_feeds() -> None:
    """AC15.3: feed test は上から max_feeds 分のフィードのみ対象とする."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        # 10フィードを作成
        feeds = []
        for i in range(10):
            f = Feed(url=f"https://example.com/rss{i}", name=f"Feed {i}", category="Cat", enabled=True)
            session.add(f)
            feeds.append(f)
        await session.commit()

        # 各フィードに1記事
        for f in feeds:
            session.add(Article(
                feed_id=f.id,
                title=f"Art for {f.name}",
                url=f"https://example.com/art{f.id}",
                summary="summary",
                collected_at=datetime.now(tz=timezone.utc),
            ))
        await session.commit()

    slack_client = AsyncMock()
    slack_client.chat_postMessage.return_value = {"ts": "parent.123"}

    await feed_test_deliver(
        session_factory=factory,
        slack_client=slack_client,
        channel_id="C123",
        max_feeds=3,
    )

    # ヘッダー(1) + 親メッセージ(3) + スレッド記事(3) + フッター(1) = 8
    assert slack_client.chat_postMessage.call_count == 8

    await engine.dispose()


async def test_feed_test_deliver_preserves_delivered_flag(db_factory_with_delivered) -> None:  # type: ignore[no-untyped-def]
    """AC15.4: feed test は delivered フラグを更新しない."""
    slack_client = AsyncMock()
    slack_client.chat_postMessage.return_value = {"ts": "parent.123"}

    # テスト配信前の delivered フラグを記録
    async with db_factory_with_delivered() as session:
        result = await session.execute(select(Article))
        before = {a.url: a.delivered for a in result.scalars().all()}

    await feed_test_deliver(
        session_factory=db_factory_with_delivered,
        slack_client=slack_client,
        channel_id="C123",
    )

    # テスト配信後の delivered フラグが変わっていないことを確認
    async with db_factory_with_delivered() as session:
        result = await session.execute(select(Article))
        after = {a.url: a.delivered for a in result.scalars().all()}

    assert before == after


async def test_feed_test_deliver_outputs_parent_and_thread_format(db_factory_with_delivered) -> None:  # type: ignore[no-untyped-def]
    """AC15.5: feed test は親メッセージ+スレッド形式で出力する."""
    slack_client = AsyncMock()
    slack_client.chat_postMessage.return_value = {"ts": "parent.456"}

    await feed_test_deliver(
        session_factory=db_factory_with_delivered,
        slack_client=slack_client,
        channel_id="C123",
    )

    calls = slack_client.chat_postMessage.call_args_list
    # ヘッダー
    assert "今日のニュース" in calls[0].kwargs["text"]
    assert "テスト" in calls[0].kwargs["text"]
    # スレッド記事には thread_ts がある
    thread_calls = [c for c in calls if "thread_ts" in c.kwargs]
    assert len(thread_calls) > 0
    for tc in thread_calls:
        assert tc.kwargs["thread_ts"] == "parent.456"
