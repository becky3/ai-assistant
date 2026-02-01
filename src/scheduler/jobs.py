"""APScheduler 毎朝の収集・配信ジョブ
仕様: docs/specs/f2-feed-collection.md
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.db.models import Article, Feed
from src.services.feed_collector import FeedCollector

logger = logging.getLogger(__name__)

DEFAULT_TZ = ZoneInfo("Asia/Tokyo")


def format_daily_digest(
    articles: list[Article],
    feeds: dict[int, Feed],
    tz: ZoneInfo = DEFAULT_TZ,
) -> str:
    """カテゴリ別にフォーマットされた配信メッセージを生成する."""
    if not articles:
        return ""

    today = datetime.now(tz=tz).strftime("%Y-%m-%d")
    lines = [f":newspaper: 今日の学習ニュース ({today})", ""]

    # カテゴリ別にグループ化
    by_category: dict[str, list[Article]] = {}
    for article in articles:
        feed = feeds.get(article.feed_id)
        category = feed.category if feed and feed.category else "その他"
        by_category.setdefault(category, []).append(article)

    for category, cat_articles in by_category.items():
        lines.append(f"【{category}】")
        for a in cat_articles:
            raw_summary = (a.summary or "").strip()
            if not raw_summary:
                summary = "要約なし"
            else:
                summary = raw_summary[:100] + "..." if len(raw_summary) > 100 else raw_summary
            lines.append(f"• *{a.title}* - {summary}")
            lines.append(f"  :link: {a.url}")
        lines.append("")

    lines.append(":bulb: 気になる記事があれば、スレッドで聞いてね！")
    return "\n".join(lines)


async def daily_collect_and_deliver(
    collector: FeedCollector,
    session_factory: async_sessionmaker[AsyncSession],
    slack_client: object,
    channel_id: str,
) -> None:
    """毎朝の収集・配信ジョブ."""
    logger.info("Starting daily feed collection and delivery")

    try:
        # 記事収集（副作用でDBに保存される）
        await collector.collect_all()

        # 直近24時間の記事を取得してフォーマット
        since = datetime.now(tz=timezone.utc) - timedelta(hours=24)
        async with session_factory() as session:
            result = await session.execute(
                select(Article).where(Article.collected_at >= since)
            )
            recent_articles = list(result.scalars().all())

            feed_result = await session.execute(select(Feed))
            feeds = {f.id: f for f in feed_result.scalars().all()}

        if not recent_articles:
            logger.info("No new articles to deliver")
            return

        message = format_daily_digest(recent_articles, feeds)
        if message:
            await slack_client.chat_postMessage(channel=channel_id, text=message)  # type: ignore[attr-defined]
            logger.info("Delivered %d articles to %s", len(recent_articles), channel_id)
    except Exception:
        logger.exception("Error in daily_collect_and_deliver job")


def setup_scheduler(
    collector: FeedCollector,
    session_factory: async_sessionmaker[AsyncSession],
    slack_client: object,
    channel_id: str,
    hour: int = 7,
    minute: int = 0,
    timezone: str = "Asia/Tokyo",
) -> AsyncIOScheduler:
    """スケジューラを設定して返す."""
    scheduler = AsyncIOScheduler(timezone=timezone)
    scheduler.add_job(
        daily_collect_and_deliver,
        "cron",
        hour=hour,
        minute=minute,
        kwargs={
            "collector": collector,
            "session_factory": session_factory,
            "slack_client": slack_client,
            "channel_id": channel_id,
        },
        id="daily_feed_job",
    )
    return scheduler
