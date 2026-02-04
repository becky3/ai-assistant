"""スケジューラ・配信フォーマットのテスト (Issue #8)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

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


def _make_article(
    feed_id: int, title: str, url: str, summary: str, image_url: str | None = None
) -> Article:
    a = Article(feed_id=feed_id, title=title, url=url, summary=summary, image_url=image_url)
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
    # horizontal形式では1つのsectionにタイトルと要約が含まれる
    assert any("要約なし" in t for t in section_texts)


def test_ac5_build_category_blocks_limits_articles() -> None:
    """AC5: max_articles を超える記事はcontextブロックで残件表示."""
    articles = [
        _make_article(1, f"Title{i}", f"https://a.com/{i}", f"summary{i}")
        for i in range(15)
    ]
    blocks = _build_category_blocks("Python", articles, max_articles=5)

    # horizontal形式: 各記事は1 section（タイトル+要約統合）
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
    assert blocks[-1]["type"] == "section"  # 最後は要約section


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
        tz="Asia/Tokyo",
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


def test_ac10_build_category_blocks_with_image() -> None:
    """AC10: image_urlがある記事でhorizontal形式ではaccessoryとして配置される."""
    articles = [
        _make_article(1, "With Image", "https://a.com/1", "summary", image_url="https://a.com/img.png"),
        _make_article(1, "No Image", "https://a.com/2", "summary"),
    ]
    blocks = _build_category_blocks("Python", articles)

    # horizontal形式: 画像はaccessoryとして配置（独立imageブロックなし）
    sections = [b for b in blocks if b["type"] == "section"]
    img_sections = [s for s in sections if "accessory" in s]
    assert len(img_sections) == 1
    assert img_sections[0]["accessory"]["image_url"] == "https://a.com/img.png"

    # タイトルsectionにリンクが含まれる
    title_sections = [s for s in sections if "<https://a.com/1|With Image>" in s["text"]["text"]]
    assert len(title_sections) == 1

    # 画像なし記事にはaccessoryなし
    no_img_sections = [s for s in sections if "No Image" in s["text"]["text"]]
    assert len(no_img_sections) >= 1
    assert "accessory" not in no_img_sections[0]


async def test_ac11_1_article_model_has_delivered_column(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC11.1: Article モデルに delivered カラムが追加されている."""
    async with db_factory() as session:
        result = await session.execute(select(Article))
        article = result.scalar_one_or_none()
        assert article is not None
        assert hasattr(article, "delivered")
        assert article.delivered is False  # デフォルト値


async def test_ac11_2_query_retrieves_only_undelivered_articles(db_factory) -> None:  # type: ignore[no-untyped-def]
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


async def test_ac11_3_delivered_flag_updated_after_posting(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC11.3: Slack配信完了後、配信された記事の delivered が True に更新される."""
    collector = AsyncMock()
    collector.collect_all.return_value = []
    slack_client = AsyncMock()

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


async def test_ac11_4_no_redelivery_on_multiple_executions(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC11.4: deliver を複数回実行しても、既に配信済みの記事は再配信されない."""
    collector = AsyncMock()
    collector.collect_all.return_value = []
    slack_client = AsyncMock()

    # 1回目の配信
    await daily_collect_and_deliver(
        collector=collector,
        session_factory=db_factory,
        slack_client=slack_client,
        channel_id="C123",
    )
    first_call_count = slack_client.chat_postMessage.call_count

    # 2回目の配信（新規記事がない場合）
    await daily_collect_and_deliver(
        collector=collector,
        session_factory=db_factory,
        slack_client=slack_client,
        channel_id="C123",
    )
    second_call_count = slack_client.chat_postMessage.call_count

    # 1回目は配信されるが、2回目は配信されない
    assert first_call_count == 3  # ヘッダー + カテゴリ + フッター
    assert second_call_count == 3  # 増えない（新規投稿なし）


async def test_ac11_5_new_articles_are_delivered(db_factory) -> None:  # type: ignore[no-untyped-def]
    """AC11.5: 新規収集された記事（delivered == False）は次回配信対象になる."""
    collector = AsyncMock()
    collector.collect_all.return_value = []
    slack_client = AsyncMock()

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

    # 2回目の配信（新規記事あり）
    await daily_collect_and_deliver(
        collector=collector,
        session_factory=db_factory,
        slack_client=slack_client,
        channel_id="C123",
    )
    second_call_count = slack_client.chat_postMessage.call_count

    # 新規記事が配信される
    assert second_call_count > first_call_count


# --- AC12: 配信カード形式の切り替え ---


def test_ac12_1_settings_has_feed_card_layout() -> None:
    """AC12.1: Settings に feed_card_layout フィールドがあり、デフォルトは 'horizontal'."""
    from src.config.settings import Settings

    s = Settings(
        slack_bot_token="x",
        slack_signing_secret="x",
        slack_app_token="x",
    )
    assert s.feed_card_layout == "horizontal"


def test_ac12_2_vertical_layout_has_independent_image_block() -> None:
    """AC12.2: vertical レイアウトでは独立imageブロックが表示される."""
    articles = [
        _make_article(1, "Title", "https://a.com/1", "summary text", image_url="https://a.com/img.png"),
    ]
    blocks = _build_category_blocks("Python", articles, layout="vertical")

    image_blocks = [b for b in blocks if b["type"] == "image"]
    assert len(image_blocks) == 1
    assert image_blocks[0]["image_url"] == "https://a.com/img.png"

    # タイトルと要約が別々のsectionになっている
    sections = [b for b in blocks if b["type"] == "section"]
    assert len(sections) == 2  # タイトルsection + 要約section


def test_ac12_3_horizontal_layout_has_accessory_image() -> None:
    """AC12.3: horizontal レイアウトでは画像がaccessoryとして右側に表示される."""
    articles = [
        _make_article(1, "Title", "https://a.com/1", "summary text", image_url="https://a.com/img.png"),
    ]
    blocks = _build_category_blocks("Python", articles, layout="horizontal")

    # 独立imageブロックがない
    image_blocks = [b for b in blocks if b["type"] == "image"]
    assert len(image_blocks) == 0

    # sectionが1つで、accessoryに画像がある
    sections = [b for b in blocks if b["type"] == "section"]
    assert len(sections) == 1
    assert sections[0]["accessory"]["type"] == "image"
    assert sections[0]["accessory"]["image_url"] == "https://a.com/img.png"

    # タイトルと要約が同じsectionに含まれる
    text = sections[0]["text"]["text"]
    assert "<https://a.com/1|Title>" in text
    assert "summary text" in text


def test_ac12_4_horizontal_layout_no_image() -> None:
    """AC12.4: horizontal レイアウトで画像がない記事ではaccessoryが付かない."""
    articles = [
        _make_article(1, "Title", "https://a.com/1", "summary text"),
    ]
    blocks = _build_category_blocks("Python", articles, layout="horizontal")

    sections = [b for b in blocks if b["type"] == "section"]
    assert len(sections) == 1
    assert "accessory" not in sections[0]


def test_ac12_5_vertical_layout_no_image() -> None:
    """AC12.5: vertical レイアウトで画像がない記事でもタイトル+要約が正常に表示される."""
    articles = [
        _make_article(1, "Title", "https://a.com/1", "summary text"),
    ]
    blocks = _build_category_blocks("Python", articles, layout="vertical")

    image_blocks = [b for b in blocks if b["type"] == "image"]
    assert len(image_blocks) == 0

    sections = [b for b in blocks if b["type"] == "section"]
    assert len(sections) == 2  # タイトル + 要約


def test_ac12_6_format_daily_digest_passes_layout() -> None:
    """AC12.6: format_daily_digest が layout を _build_category_blocks に渡す."""
    feeds = {1: Feed(id=1, url="https://a.com/rss", name="A", category="Python")}
    articles = [
        _make_article(1, "Title", "https://a.com/1", "summary", image_url="https://a.com/img.png"),
    ]

    # horizontal
    result_h = format_daily_digest(articles, feeds, layout="horizontal")
    sections_h = [b for b in result_h["Python"] if b["type"] == "section"]
    assert any("accessory" in s for s in sections_h)

    # vertical
    result_v = format_daily_digest(articles, feeds, layout="vertical")
    image_blocks = [b for b in result_v["Python"] if b["type"] == "image"]
    assert len(image_blocks) == 1


async def test_ac12_7_manual_deliver_uses_layout() -> None:
    """AC12.7: 手動配信コマンドで register_handlers の layout が daily_collect_and_deliver に渡される."""
    from unittest.mock import patch

    from src.slack.handlers import register_handlers

    chat_service = AsyncMock()
    collector = AsyncMock()
    session_factory = AsyncMock()
    slack_client = AsyncMock()
    channel_id = "C_TEST"

    app = AsyncMock()
    handlers: dict = {}

    def capture_event(event_type: str):  # type: ignore[no-untyped-def]
        def decorator(func):  # type: ignore[no-untyped-def]
            handlers[event_type] = func
            return func
        return decorator

    app.event = capture_event
    register_handlers(
        app, chat_service,
        collector=collector,
        session_factory=session_factory,
        slack_client=slack_client,
        channel_id=channel_id,
        feed_card_layout="vertical",
    )

    say = AsyncMock()
    event = {"user": "U123", "text": "<@UBOT> deliver", "ts": "123.456"}

    mock_deliver = AsyncMock()
    with patch("src.scheduler.jobs.daily_collect_and_deliver", mock_deliver):
        await handlers["app_mention"](event=event, say=say)

    mock_deliver.assert_called_once_with(
        collector, session_factory, slack_client, channel_id,
        max_articles_per_category=10,
        layout="vertical",
    )


def test_ac12_8_invalid_layout_raises_validation_error() -> None:
    """AC12.8: 不正な feed_card_layout 値を設定した場合、ValidationErrorが発生する."""
    from pydantic import ValidationError

    from src.config.settings import Settings

    with pytest.raises(ValidationError):
        Settings(
            slack_bot_token="x",
            slack_signing_secret="x",
            slack_app_token="x",
            feed_card_layout="invalid",  # type: ignore[arg-type]
        )
