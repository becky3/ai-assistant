"""RSS情報収集サービス
仕様: docs/specs/f2-feed-collection.md
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from html import unescape
from time import mktime

import feedparser  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.db.models import Article, Feed
from src.services.ogp_extractor import OgpExtractor
from src.services.summarizer import Summarizer

logger = logging.getLogger(__name__)


def strip_html(text: str) -> str:
    """HTMLタグを除去してプレーンテキストに変換する."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


class FeedCollector:
    """RSSフィードからの情報収集サービス.

    仕様: docs/specs/f2-feed-collection.md
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        summarizer: Summarizer,
        ogp_extractor: OgpExtractor | None = None,
        summarize_timeout: int = 180,
        collect_days: int = 7,
    ) -> None:
        self._session_factory = session_factory
        self._summarizer = summarizer
        self._ogp_extractor = ogp_extractor
        self._summarize_timeout = summarize_timeout
        self._collect_days = collect_days

    async def collect_all(
        self,
        skip_summary: bool = False,
    ) -> list[Article]:
        """有効な全フィードから記事を収集する.

        Args:
            skip_summary: Trueの場合、LLM要約をスキップしdescriptionを要約として保存する。
        """
        collected: list[Article] = []
        async with self._session_factory() as session:
            feeds = await self._get_enabled_feeds(session)

        logger.info("collect_all: %d feeds to process (skip_summary=%s)", len(feeds), skip_summary)
        for i, feed in enumerate(feeds, 1):
            try:
                logger.info("collect_all: [%d/%d] %s", i, len(feeds), feed.name)
                articles = await self._collect_feed(feed, skip_summary=skip_summary)
                collected.extend(articles)
            except Exception:
                logger.exception("Failed to collect feed: %s (%s)", feed.name, feed.url)
                continue

        logger.info("collect_all: done — %d articles collected", len(collected))
        return collected

    async def get_enabled_feeds(self) -> list[Feed]:
        """有効なフィード一覧を取得する（公開API）."""
        async with self._session_factory() as session:
            return await self._get_enabled_feeds(session)

    async def collect_feed(
        self,
        feed: Feed,
        on_article_ready: Callable[[Article], Awaitable[bool]] | None = None,
        skip_summary: bool = False,
    ) -> list[Article]:
        """単一フィードから記事を収集する（公開API）.

        on_article_ready: 記事1件の処理完了時に呼ばれるコールバック。
            True を返すと収集続行、False を返すと収集を中止する。
        skip_summary: Trueの場合、LLM要約をスキップしdescriptionまたはプレースホルダを使用する。
        """
        return await self._collect_feed(feed, on_article_ready=on_article_ready, skip_summary=skip_summary)

    async def _get_enabled_feeds(self, session: AsyncSession) -> list[Feed]:
        """有効なフィード一覧を取得する."""
        result = await session.execute(
            select(Feed).where(Feed.enabled.is_(True)).order_by(Feed.url.asc())
        )
        return list(result.scalars().all())

    async def _collect_feed(
        self,
        feed: Feed,
        on_article_ready: Callable[[Article], Awaitable[bool]] | None = None,
        skip_summary: bool = False,
    ) -> list[Article]:
        """単一フィードから記事を収集する.

        Args:
            on_article_ready: 記事1件の処理完了時に呼ばれるコールバック。
                True を返すと収集続行、False を返すと収集を中止する。
            skip_summary: Trueの場合、LLM要約をスキップしdescriptionを要約として保存する。
        """
        parsed = await asyncio.to_thread(feedparser.parse, feed.url)
        articles: list[Article] = []
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=self._collect_days)

        async with self._session_factory() as session:
            # エントリ内の全URLを収集し、一括で既存記事を取得する
            urls = [entry.get("link", "") for entry in parsed.entries if entry.get("link")]
            existing_urls: set[str] = set()
            if urls:
                result = await session.execute(
                    select(Article.url).where(Article.url.in_(urls))
                )
                existing_urls = set(result.scalars().all())

            new_articles: list[Article] = []
            stopped = False
            for entry in parsed.entries:
                if stopped:
                    break

                url = entry.get("link", "")
                if not url or url in existing_urls:
                    continue

                title = entry.get("title", "")
                description = strip_html(
                    entry.get("summary", "") or entry.get("description", "")
                )
                published_at = None
                parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
                if parsed_time:
                    published_at = datetime.fromtimestamp(
                        mktime(parsed_time), tz=timezone.utc
                    )

                # 日付カット: published_atがあり、collect_days以前の記事はスキップ
                if published_at is not None and published_at < cutoff:
                    continue

                if skip_summary:
                    summary = description if description else "（要約なし）"
                else:
                    try:
                        timeout = self._summarize_timeout if self._summarize_timeout > 0 else None
                        summary = await asyncio.wait_for(
                            self._summarizer.summarize(title, url, description),
                            timeout=timeout,
                        )
                    except TimeoutError:
                        logger.warning(
                            "Summarization timed out after %ds, aborting feed: %s",
                            self._summarize_timeout, feed.name,
                        )
                        break

                image_url = None
                if self._ogp_extractor:
                    entry_dict = {
                        k: entry.get(k, None)
                        for k in ("media_content", "enclosures", "media_thumbnail", "summary", "content")
                    }
                    image_url = await self._ogp_extractor.extract_image_url(
                        url, entry_dict
                    )

                article = Article(
                    feed_id=feed.id,
                    title=title,
                    url=url,
                    summary=summary,
                    image_url=image_url,
                    published_at=published_at,
                )
                session.add(article)
                existing_urls.add(url)
                new_articles.append(article)

                # 1記事処理完了のコールバック（投稿など）
                # False を返すと収集を中止する
                if on_article_ready:
                    await session.flush()
                    should_continue = await on_article_ready(article)
                    if not should_continue:
                        stopped = True

            await session.commit()
            articles.extend(new_articles)

        return articles

    async def add_feed(self, url: str, name: str, category: str = "一般") -> Feed:
        """フィードを追加する.

        Args:
            url: RSSフィードのURL
            name: フィード名
            category: カテゴリ名（デフォルト: "一般"）

        Returns:
            追加されたFeedオブジェクト

        Raises:
            ValueError: URLが既に登録されている場合
        """
        async with self._session_factory() as session:
            # 重複チェック
            result = await session.execute(select(Feed).where(Feed.url == url))
            existing = result.scalar_one_or_none()
            if existing:
                raise ValueError("既に登録されています")

            feed = Feed(url=url, name=name, category=category, enabled=True)
            session.add(feed)
            await session.commit()
            await session.refresh(feed)
            return feed

    async def delete_feed(self, url: str) -> None:
        """フィードを削除する（関連記事も CASCADE 削除される）.

        Args:
            url: 削除するRSSフィードのURL

        Raises:
            ValueError: URLが見つからない場合
        """
        async with self._session_factory() as session:
            result = await session.execute(select(Feed).where(Feed.url == url))
            feed = result.scalar_one_or_none()
            if not feed:
                raise ValueError("登録されていません")

            await session.delete(feed)
            await session.commit()

    async def enable_feed(self, url: str) -> None:
        """フィードを有効化する.

        Args:
            url: 有効化するRSSフィードのURL

        Raises:
            ValueError: URLが見つからない場合
        """
        async with self._session_factory() as session:
            result = await session.execute(select(Feed).where(Feed.url == url))
            feed = result.scalar_one_or_none()
            if not feed:
                raise ValueError("登録されていません")

            feed.enabled = True
            await session.commit()

    async def disable_feed(self, url: str) -> None:
        """フィードを無効化する.

        Args:
            url: 無効化するRSSフィードのURL

        Raises:
            ValueError: URLが見つからない場合
        """
        async with self._session_factory() as session:
            result = await session.execute(select(Feed).where(Feed.url == url))
            feed = result.scalar_one_or_none()
            if not feed:
                raise ValueError("登録されていません")

            feed.enabled = False
            await session.commit()

    async def list_feeds(self) -> tuple[list[Feed], list[Feed]]:
        """全フィードを有効/無効で分類して取得する.

        Returns:
            (有効フィードリスト, 無効フィードリスト) のタプル
        """
        async with self._session_factory() as session:
            result = await session.execute(select(Feed).order_by(Feed.url.asc()))
            all_feeds = list(result.scalars().all())

        enabled = [f for f in all_feeds if f.enabled]
        disabled = [f for f in all_feeds if not f.enabled]
        return (enabled, disabled)

    async def delete_all_feeds(self) -> int:
        """全フィードを削除する（関連記事もCASCADE削除される）.

        Returns:
            削除されたフィード数
        """
        async with self._session_factory() as session:
            result = await session.execute(select(Feed))
            feeds = list(result.scalars().all())
            count = len(feeds)
            for feed in feeds:
                await session.delete(feed)
            await session.commit()
            return count

    async def get_all_feeds(self) -> list[Feed]:
        """全フィード（有効・無効問わず）を取得する.

        Returns:
            全Feedオブジェクトのリスト
        """
        async with self._session_factory() as session:
            result = await session.execute(select(Feed).order_by(Feed.url.asc()))
            return list(result.scalars().all())
