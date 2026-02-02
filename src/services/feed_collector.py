"""RSS情報収集サービス
仕様: docs/specs/f2-feed-collection.md
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from time import mktime

import feedparser  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.db.models import Article, Feed
from src.services.ogp_extractor import OgpExtractor
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
        ogp_extractor: OgpExtractor | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._summarizer = summarizer
        self._ogp_extractor = ogp_extractor

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
        parsed = await asyncio.to_thread(feedparser.parse, feed.url)
        articles: list[Article] = []

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
            for entry in parsed.entries:
                url = entry.get("link", "")
                if not url or url in existing_urls:
                    continue

                title = entry.get("title", "")
                published_at = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    published_at = datetime.fromtimestamp(
                        mktime(entry.published_parsed), tz=timezone.utc
                    )

                summary = await self._summarizer.summarize(title, url)

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
                new_articles.append(article)

            await session.commit()
            articles.extend(new_articles)

        return articles
