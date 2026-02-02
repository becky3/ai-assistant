"""APScheduler 毎朝の収集・配信ジョブ
仕様: docs/specs/f2-feed-collection.md
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.db.models import Article, Feed
from src.services.feed_collector import FeedCollector

logger = logging.getLogger(__name__)

DEFAULT_TZ = ZoneInfo("Asia/Tokyo")


def _build_category_blocks(
    category: str,
    articles: list[Article],
    max_articles: int = 10,
) -> list[dict[str, Any]]:
    """1カテゴリ分の Block Kit blocks を構築する."""
    display_articles = articles[:max_articles]
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"【{category}】 — {len(display_articles)}件の記事",
            },
        },
    ]

    for i, a in enumerate(display_articles):
        raw_summary = (a.summary or "").strip()
        summary = raw_summary[:100] + "..." if len(raw_summary) > 100 else raw_summary
        if not summary:
            summary = "要約なし"

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{a.title}*\n{summary}\n:link: <{a.url}|記事を読む>",
            },
        })

        if i < len(display_articles) - 1:
            blocks.append({"type": "divider"})

    if len(articles) > max_articles:
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"他 {len(articles) - max_articles} 件の記事があります",
                },
            ],
        })

    return blocks


def format_daily_digest(
    articles: list[Article],
    feeds: dict[int, Feed],
    max_articles_per_category: int = 10,
) -> dict[str, list[dict[str, Any]]]:
    """カテゴリ別にBlock Kit blocksを生成する.

    Returns:
        カテゴリ名をキー、Block Kit blocks リストを値とする辞書。
        記事がない場合は空辞書。
    """
    if not articles:
        return {}

    by_category: dict[str, list[Article]] = {}
    for article in articles:
        feed = feeds.get(article.feed_id)
        category = feed.category if feed and feed.category else "その他"
        by_category.setdefault(category, []).append(article)

    return {
        category: _build_category_blocks(category, cat_articles, max_articles_per_category)
        for category, cat_articles in by_category.items()
    }


async def daily_collect_and_deliver(
    collector: FeedCollector,
    session_factory: async_sessionmaker[AsyncSession],
    slack_client: object,
    channel_id: str,
    max_articles_per_category: int = 10,
) -> None:
    """毎朝の収集・配信ジョブ."""
    logger.info("Starting daily feed collection and delivery")

    try:
        await collector.collect_all()

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

        today = datetime.now(tz=DEFAULT_TZ).strftime("%Y-%m-%d")
        digest = format_daily_digest(
            recent_articles, feeds, max_articles_per_category=max_articles_per_category
        )
        if not digest:
            return

        # ヘッダーメッセージ
        await slack_client.chat_postMessage(  # type: ignore[attr-defined]
            channel=channel_id,
            text=f":newspaper: 今日の学習ニュース ({today})",
            blocks=[
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f":newspaper: 今日の学習ニュース ({today})",
                    },
                },
            ],
        )

        # カテゴリごとに別メッセージ
        for category, blocks in digest.items():
            await slack_client.chat_postMessage(  # type: ignore[attr-defined]
                channel=channel_id,
                text=f"【{category}】",
                blocks=blocks,
            )

        # フッターメッセージ
        await slack_client.chat_postMessage(  # type: ignore[attr-defined]
            channel=channel_id,
            text=":bulb: 気になる記事があれば、スレッドで聞いてね！",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": ":bulb: 気になる記事があれば、スレッドで聞いてね！",
                    },
                },
            ],
        )

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
    max_articles_per_category: int = 10,
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
            "max_articles_per_category": max_articles_per_category,
        },
        id="daily_feed_job",
    )
    return scheduler
