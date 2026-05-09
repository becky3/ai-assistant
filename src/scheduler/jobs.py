"""配信ジョブ・フォーマット
仕様: docs/specs/features/feed-management.md
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.db.models import Article, Feed
from src.services.feed_collector import NO_SUMMARY_TEXT, FeedCollector

logger = logging.getLogger(__name__)

DEFAULT_TZ = ZoneInfo("Asia/Tokyo")


def _format_article_datetime(article: Article, tz: ZoneInfo = DEFAULT_TZ) -> str:
    """記事の更新日時をフォーマットする.

    published_at を優先し、None の場合は collected_at にフォールバック。
    """
    dt = article.published_at or article.collected_at
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    local_dt = dt.astimezone(tz)
    return local_dt.strftime("%m-%d %H:%M")


def _build_article_blocks(
    article: Article,
    layout: Literal["vertical", "horizontal"] = "horizontal",
    tz: ZoneInfo = DEFAULT_TZ,
) -> list[dict[str, Any]]:
    """1記事分のBlock Kitブロックを構築する（スレッド内1投稿分）."""
    if layout not in ("vertical", "horizontal"):
        msg = f"Invalid layout: {layout!r}. Must be 'vertical' or 'horizontal'."
        raise ValueError(msg)

    blocks: list[dict[str, Any]] = []

    dt_str = _format_article_datetime(article, tz)

    summary = (article.summary or "").strip()
    if not summary:
        summary = NO_SUMMARY_TEXT

    if layout == "horizontal":
        title_part = f":newspaper: *<{article.url}|{article.title}>*\n{dt_str}\n\n"
        max_summary = max(0, 3000 - len(title_part) - 10)
        if len(summary) > max_summary:
            summary = summary[:max_summary] + "..."
        section: dict[str, Any] = {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{title_part}{summary}",
            },
        }
        if article.image_url:
            section["accessory"] = {
                "type": "image",
                "image_url": article.image_url,
                "alt_text": article.title,
            }
        blocks.append(section)
    else:
        # 縦長形式
        if len(summary) > 2900:
            summary = summary[:2900] + "..."
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":newspaper: *<{article.url}|{article.title}>*\n{dt_str}",
            },
        })
        if article.image_url:
            blocks.append({
                "type": "image",
                "image_url": article.image_url,
                "alt_text": article.title,
            })
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": summary,
            },
        })

    return blocks


def _build_parent_message(feed_name: str) -> list[dict[str, Any]]:
    """フィードの親メッセージBlock Kitブロックを構築する."""
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":file_folder: *{feed_name}*",
            },
        },
    ]


def format_daily_digest(
    articles: list[Article],
    feeds: dict[int, Feed],
    max_articles_per_feed: int = 10,
    layout: Literal["vertical", "horizontal"] = "horizontal",
) -> dict[int, tuple[list[dict[str, Any]], list[list[dict[str, Any]]]]]:
    """フィード別にBlock Kitブロックを生成する.

    Returns:
        feed_id をキーとし、(親メッセージblocks, [記事blocksリスト]) タプルを値とする辞書。
        記事blocksリストは1記事ごとのBlock Kitブロックリスト。
        記事がない場合は空辞書。
    """
    if not articles:
        return {}

    by_feed: dict[int, list[Article]] = {}
    for article in articles:
        by_feed.setdefault(article.feed_id, []).append(article)

    result: dict[int, tuple[list[dict[str, Any]], list[list[dict[str, Any]]]]] = {}
    for feed_id in sorted(
        by_feed,
        key=lambda fid: (feeds[fid].url if fid in feeds else ""),
        reverse=True,
    ):
        feed = feeds.get(feed_id)
        feed_name = feed.name if feed else "不明なフィード"

        # 投稿日時昇順（published_at 優先、なければ collected_at）
        sorted_articles = sorted(
            by_feed[feed_id],
            key=lambda a: (a.published_at or a.collected_at),
        )
        display_articles = sorted_articles[:max_articles_per_feed]
        parent_blocks = _build_parent_message(feed_name)

        article_blocks_list: list[list[dict[str, Any]]] = []
        for article in display_articles:
            article_blocks_list.append(_build_article_blocks(article, layout=layout))

        result[feed_id] = (parent_blocks, article_blocks_list)

    return result


async def post_article_to_thread(
    slack_client: AsyncWebClient,
    channel_id: str,
    thread_ts: str,
    blocks: list[dict[str, Any]],
) -> None:
    """1記事分のブロックをスレッドに投稿する（画像エラー時リトライ付き）."""
    try:
        await slack_client.chat_postMessage(
            channel=channel_id,
            text="記事",
            blocks=blocks,
            thread_ts=thread_ts,
            unfurl_links=False,
            unfurl_media=False,
        )
    except Exception as exc:
        error_msg = str(exc)
        if "invalid_blocks" in error_msg or "downloading image" in error_msg:
            blocks_without_images = []
            for b in blocks:
                if b.get("type") == "image":
                    continue
                if "accessory" in b:
                    b = {k: v for k, v in b.items() if k != "accessory"}
                blocks_without_images.append(b)
            logger.warning(
                "Failed to post article with images, retrying without: %s",
                error_msg,
            )
            await slack_client.chat_postMessage(
                channel=channel_id,
                text="記事",
                blocks=blocks_without_images,
                thread_ts=thread_ts,
                unfurl_links=False,
                unfurl_media=False,
            )
        else:
            raise


async def _deliver_feed_to_slack(
    articles: list[Article],
    feed: Feed,
    slack_client: AsyncWebClient,
    channel_id: str,
    max_articles_per_feed: int,
    layout: Literal["vertical", "horizontal"],
) -> None:
    """1フィード分の記事をSlackに配信する共通処理."""
    feeds_dict = {feed.id: feed}
    digest = format_daily_digest(
        articles, feeds_dict,
        max_articles_per_feed=max_articles_per_feed,
        layout=layout,
    )
    for feed_id, (parent_blocks, article_blocks_list) in digest.items():
        parent_result = await slack_client.chat_postMessage(
            channel=channel_id,
            text=f"📰 {feed.name}",
            blocks=parent_blocks,
            unfurl_links=False,
            unfurl_media=False,
        )
        parent_ts = parent_result["ts"]

        for article_blocks in article_blocks_list:
            await post_article_to_thread(
                slack_client, channel_id, parent_ts, article_blocks,
            )
            await asyncio.sleep(1)


async def _post_header(
    slack_client: AsyncWebClient,
    channel_id: str,
    header_text: str,
) -> None:
    """ヘッダーメッセージを投稿する."""
    await slack_client.chat_postMessage(
        channel=channel_id,
        text=header_text,
        blocks=[
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": header_text,
                },
            },
        ],
    )


async def _post_footer(slack_client: AsyncWebClient, channel_id: str) -> None:
    """フッターメッセージを投稿する."""
    await slack_client.chat_postMessage(
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


async def daily_collect_and_deliver(
    collector: FeedCollector,
    session_factory: async_sessionmaker[AsyncSession],
    slack_client: AsyncWebClient,
    channel_id: str,
    max_articles_per_feed: int = 10,
    layout: Literal["vertical", "horizontal"] = "horizontal",
    skip_summary: bool = False,
) -> tuple[int, int]:
    """毎朝の収集・配信ジョブ（フィードごとに収集→即投稿の逐次型）.

    Returns:
        (配信フィード数, 配信記事数) のタプル。
    """
    logger.info(
        "daily_collect_and_deliver start: channel=%s, max_articles_per_feed=%s, layout=%s, skip_summary=%s",
        channel_id, max_articles_per_feed, layout, skip_summary,
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
            # 親メッセージ投稿用の状態
            parent_ts: str | None = None
            posted_count = 0
            posted_article_ids: list[int] = []

            # 投稿共通処理
            async def _post_single_article(article: Article) -> None:
                nonlocal header_posted, parent_ts, posted_count

                # ヘッダーメッセージ（初回のみ）
                if not header_posted:
                    await _post_header(
                        slack_client, channel_id,
                        f":newspaper: 今日のニュース ({today})",
                    )
                    header_posted = True

                # 親メッセージ（フィード初回のみ）
                if parent_ts is None:
                    parent_blocks = _build_parent_message(feed.name)
                    parent_result = await slack_client.chat_postMessage(
                        channel=channel_id,
                        text=f"📰 {feed.name}",
                        blocks=parent_blocks,
                        unfurl_links=False,
                        unfurl_media=False,
                    )
                    parent_ts = parent_result["ts"]

                # スレッドに記事を投稿
                article_blocks = _build_article_blocks(article, layout=layout)
                await post_article_to_thread(
                    slack_client, channel_id, parent_ts, article_blocks,
                )
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
            await _post_footer(slack_client, channel_id)

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
    slack_client: AsyncWebClient,
    channel_id: str,
    layout: Literal["vertical", "horizontal"] = "horizontal",
    max_feeds: int = 3,
    max_articles_per_feed: int = 5,
) -> None:
    """feed test 用配信（要約スキップ・配信済み含む・上限3フィード・各5記事）.

    本番と同じ _deliver_feed_to_slack を使用し、収集ステップのみスキップする。
    仕様: docs/specs/features/feed-management.md
    """
    logger.info(
        "feed_test_deliver start: channel=%s, max_feeds=%d, max_articles_per_feed=%d, layout=%s",
        channel_id, max_feeds, max_articles_per_feed, layout,
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
    await _post_header(
        slack_client, channel_id,
        f":newspaper: 今日のニュース ({today})（テスト）",
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

        # 本番と同じ共通配信処理
        await _deliver_feed_to_slack(
            articles, feed, slack_client, channel_id,
            max_articles_per_feed, layout,
        )
        feeds_delivered += 1

    await _post_footer(slack_client, channel_id)

    # delivered フラグは更新しない（テストなので副作用なし）
    logger.info("feed_test_deliver complete: feeds=%d", feeds_delivered)
