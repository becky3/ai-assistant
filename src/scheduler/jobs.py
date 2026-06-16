"""配信ジョブ — プラットフォーム抽象（MessagingPort）経由で配信する.
仕様: docs/specs/features/feed-management.md

記事カードの描画（Slack Block Kit / Discord Embed）は各アダプターに閉じ、
本モジュールは収集連動・配信順序・DB 配信フラグ更新のオーケストレーションのみを担う。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.db.models import Article, Feed
from src.messaging.port import ArticleCard
from src.services.feed_collector import NO_SUMMARY_TEXT, FeedCollector

if TYPE_CHECKING:
    from src.messaging.port import MessagingPort

logger = logging.getLogger(__name__)

DEFAULT_TZ = ZoneInfo("Asia/Tokyo")

_FOOTER_TEXT = ":bulb: 気になる記事があれば、スレッドで聞いてね！"


def _format_article_datetime(article: Article, tz: ZoneInfo = DEFAULT_TZ) -> str:
    """記事の更新日時をフォーマットする.

    published_at を優先し、None の場合は collected_at にフォールバック。
    """
    dt = article.published_at or article.collected_at
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    local_dt = dt.astimezone(tz)
    return local_dt.strftime("%m-%d %H:%M")


def _to_card(article: Article) -> ArticleCard:
    """Article を中立な ArticleCard に変換する（要約欠落時はフォールバック文言）."""
    summary = (article.summary or "").strip() or NO_SUMMARY_TEXT
    return ArticleCard(
        title=article.title,
        url=article.url,
        datetime_str=_format_article_datetime(article),
        summary=summary,
        image_url=article.image_url,
    )


async def daily_collect_and_deliver(
    collector: FeedCollector,
    session_factory: async_sessionmaker[AsyncSession],
    messaging: MessagingPort,
    channel_id: str,
    max_articles_per_feed: int = 10,
    skip_summary: bool = False,
) -> tuple[int, int]:
    """毎朝の収集・配信ジョブ（フィードごとに収集→即投稿の逐次型）.

    Returns:
        (配信フィード数, 配信記事数) のタプル。
    """
    logger.info(
        "daily_collect_and_deliver start: channel=%s, max_articles_per_feed=%s, skip_summary=%s",
        channel_id, max_articles_per_feed, skip_summary,
    )

    try:
        feeds_list = await collector.get_enabled_feeds()
        if not feeds_list:
            logger.info("daily_collect_and_deliver complete: result=no_enabled_feeds")
            return (0, 0)

        # skip-summary時はmax_articles_per_feedを無制限にする（全件収集・配信）
        effective_max = max_articles_per_feed if not skip_summary else float("inf")

        today = datetime.now(tz=DEFAULT_TZ).strftime("%Y-%m-%d")
        header_posted = False
        total_delivered: list[int] = []
        delivered_feed_count = 0

        for feed in feeds_list:
            thread = None
            posted_count = 0
            posted_article_ids: list[int] = []

            # 投稿共通処理
            async def _post_single_article(article: Article) -> None:
                nonlocal header_posted, thread, posted_count

                # ヘッダーメッセージ（初回のみ）
                if not header_posted:
                    await messaging.post_header(
                        channel_id, f":newspaper: 今日のニュース ({today})"
                    )
                    header_posted = True

                # 親メッセージ＋スレッド（フィード初回のみ）
                if thread is None:
                    thread = await messaging.start_feed_thread(channel_id, feed.name)

                await messaging.post_article_card(thread, _to_card(article))
                posted_count += 1
                posted_article_ids.append(article.id)
                await asyncio.sleep(1)

            # 1記事要約完了時に即投稿するコールバック
            # False を返すと収集を中止する
            async def on_article_ready(article: Article) -> bool:
                if posted_count >= effective_max:
                    return False
                await _post_single_article(article)
                return posted_count < effective_max

            # フィード単位で収集（1記事ごとにコールバックで即投稿）
            try:
                await collector.collect_feed(feed, on_article_ready=on_article_ready, skip_summary=skip_summary)
            except Exception:
                logger.exception("Failed to collect feed: %s (%s)", feed.name, feed.url)
                continue

            # 収集後、DB上の過去の未配信記事も投稿対象にする
            if posted_count < effective_max:
                async with session_factory() as session:
                    remaining = int(effective_max - posted_count) if effective_max != float("inf") else None
                    result = await session.execute(
                        select(Article)
                        .where(
                            Article.feed_id == feed.id,
                            Article.delivered == False,  # noqa: E712
                            Article.id.notin_(posted_article_ids) if posted_article_ids else True,  # type: ignore[arg-type]
                        )
                        .order_by(Article.published_at.asc().nullslast(), Article.collected_at.asc())
                        .limit(remaining)
                    )
                    old_articles = list(result.scalars().all())

                for article in old_articles:
                    await _post_single_article(article)

            # 配信済みフラグを即更新
            if posted_article_ids:
                async with session_factory() as session:
                    await session.execute(
                        update(Article)
                        .where(Article.id.in_(posted_article_ids))
                        .values(delivered=True)
                    )
                    await session.commit()
                total_delivered.extend(posted_article_ids)
                delivered_feed_count += 1

        # フッターメッセージ（1件でも配信した場合のみ）
        if header_posted:
            await messaging.post_footer(channel_id, _FOOTER_TEXT)

        logger.info(
            "daily_collect_and_deliver complete: feeds=%d, articles=%d, channel=%s",
            delivered_feed_count, len(total_delivered), channel_id,
        )
        return (delivered_feed_count, len(total_delivered))
    except Exception:
        logger.exception("Error in daily_collect_and_deliver job")
        logger.info("daily_collect_and_deliver complete: result=error")
        return (0, 0)


async def feed_test_deliver(
    session_factory: async_sessionmaker[AsyncSession],
    messaging: MessagingPort,
    channel_id: str,
    max_feeds: int = 3,
    max_articles_per_feed: int = 5,
) -> None:
    """feed test 用配信（要約スキップ・配信済み含む・上限3フィード・各5記事）.

    収集ステップをスキップし、既存記事を本番同等のレイアウトで配信する。
    仕様: docs/specs/features/feed-management.md
    """
    logger.info(
        "feed_test_deliver start: channel=%s, max_feeds=%d, max_articles_per_feed=%d",
        channel_id, max_feeds, max_articles_per_feed,
    )
    async with session_factory() as session:
        feed_result = await session.execute(
            select(Feed)
            .where(Feed.enabled == True)  # noqa: E712
            .order_by(Feed.id.asc())
            .limit(max_feeds)
        )
        test_feeds = list(feed_result.scalars().all())

    if not test_feeds:
        logger.info("feed_test_deliver complete: result=no_enabled_feeds")
        return

    # テストヘッダー（本番同等 +（テスト））
    today = datetime.now(tz=DEFAULT_TZ).strftime("%Y-%m-%d")
    await messaging.post_header(
        channel_id, f":newspaper: 今日のニュース ({today})（テスト）"
    )

    feeds_delivered = 0
    for feed in test_feeds:
        # 既存記事を取得（delivered 問わず）— 収集はスキップ
        async with session_factory() as session:
            article_result = await session.execute(
                select(Article).where(Article.feed_id == feed.id)
            )
            articles = list(article_result.scalars().all())

        if not articles:
            continue

        # 投稿日時昇順（published_at 優先）で上限件数まで配信
        sorted_articles = sorted(
            articles, key=lambda a: (a.published_at or a.collected_at)
        )[:max_articles_per_feed]

        thread = await messaging.start_feed_thread(channel_id, feed.name)
        for article in sorted_articles:
            await messaging.post_article_card(thread, _to_card(article))
            await asyncio.sleep(1)
        feeds_delivered += 1

    await messaging.post_footer(channel_id, _FOOTER_TEXT)

    # delivered フラグは更新しない（テストなので副作用なし）
    logger.info("feed_test_deliver complete: feeds=%d", feeds_delivered)
