"""RSS情報収集サービス
仕様: docs/specs/f2-feed-collection.md
"""

from __future__ import annotations

import logging
from datetime import datetime
from time import mktime

import feedparser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.db.models import Article, Feed
from src.services.summarizer import Summarizer

logger = logging.getLogger(__name__)


class FeedCollector:
    """RSSフィードからの情報収集サービス.

    仕様: docs/specs/f2-feed-collection.md
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        summarizer: Summarizer,
    ) -> None:
        self._session_factory = session_factory
        self._summarizer = summarizer

    async def collect_all(self) -> list[Article]:
        """有効な全フィードから記事を収集する."""
        collected: list[Article] = []
        async with self._session_factory() as session:
            feeds = await self._get_enabled_feeds(session)

        for feed in feeds:
            try:
                articles = await self._collect_feed(feed)
                collected.extend(articles)
            except Exception:
                logger.exception("Failed to collect feed: %s (%s)", feed.name, feed.url)
                continue

        return collected

    async def _get_enabled_feeds(self, session: AsyncSession) -> list[Feed]:
        """有効なフィード一覧を取得する."""
        result = await session.execute(
            select(Feed).where(Feed.enabled.is_(True))
        )
        return list(result.scalars().all())

    async def _collect_feed(self, feed: Feed) -> list[Article]:
        """単一フィードから記事を収集する."""
        parsed = feedparser.parse(feed.url)
        articles: list[Article] = []

        async with self._session_factory() as session:
            for entry in parsed.entries:
                url = entry.get("link", "")
                if not url:
                    continue

                # 重複チェック
                existing = await session.execute(
                    select(Article).where(Article.url == url)
                )
                if existing.scalar_one_or_none() is not None:
                    continue

                title = entry.get("title", "")
                published_at = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    published_at = datetime.fromtimestamp(mktime(entry.published_parsed))

                # 要約生成
                summary = await self._summarizer.summarize(title, url)

                article = Article(
                    feed_id=feed.id,
                    title=title,
                    url=url,
                    summary=summary,
                    published_at=published_at,
                )
                session.add(article)
                articles.append(article)

            await session.commit()

        return articles
