"""OGP画像URL抽出サービス

仕様: docs/specs/f2-feed-collection.md (AC10)
"""

from __future__ import annotations

import logging
import re
from html import unescape
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

IMG_SRC_PATTERN = re.compile(
    r'<img\s+[^>]*src=["\']([^"\']+)["\']',
    re.IGNORECASE,
)

OG_IMAGE_PATTERN = re.compile(
    r'<meta\s+[^>]*property=["\']og:image["\']\s+[^>]*content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
OG_IMAGE_PATTERN_REV = re.compile(
    r'<meta\s+[^>]*content=["\']([^"\']+)["\']\s+[^>]*property=["\']og:image["\']',
    re.IGNORECASE,
)


class OgpExtractor:
    """記事のOGP画像URLを抽出するサービス.

    仕様: docs/specs/f2-feed-collection.md (AC10)
    """

    def __init__(self, timeout: float = 5.0) -> None:
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def extract_image_url(
        self, url: str, entry: dict[str, Any] | None = None
    ) -> str | None:
        """記事のOGP画像URLを取得する.

        1. RSSエントリの media_content / enclosure から画像URL取得を試みる
        2. なければ記事URLにGETしてog:imageを抽出
        3. 失敗時はNone
        """
        # 1. RSSエントリから取得を試みる
        if entry:
            image = self._extract_from_entry(entry)
            if image:
                return unescape(image)

        # 2. 記事URLからOGPタグを取得
        try:
            result = await self._fetch_og_image(url)
            return unescape(result) if result else None
        except Exception:
            logger.debug("Failed to fetch OGP image for %s", url, exc_info=True)
            return None

    def _extract_from_entry(self, entry: dict[str, Any]) -> str | None:
        """RSSエントリからメディアURLを抽出する."""
        # media_content
        media_content = entry.get("media_content")
        if media_content and isinstance(media_content, list):
            for media in media_content:
                if isinstance(media, dict) and media.get("url"):
                    media_type = media.get("type", "")
                    if not media_type or media_type.startswith("image"):
                        return str(media["url"])

        # enclosures
        enclosures = entry.get("enclosures")
        if enclosures and isinstance(enclosures, list):
            for enc in enclosures:
                if isinstance(enc, dict) and str(enc.get("type") or "").startswith("image"):
                    if enc.get("href"):
                        return str(enc["href"])

        # media_thumbnail (Reddit等)
        media_thumbnail = entry.get("media_thumbnail")
        if media_thumbnail and isinstance(media_thumbnail, list):
            for thumb in media_thumbnail:
                if isinstance(thumb, dict) and thumb.get("url"):
                    return str(thumb["url"])

        # summary / content 内の <img> タグ (Medium等)
        for field in ("summary", "content"):
            value = entry.get(field, "")
            if isinstance(value, list) and value:
                value = value[0].get("value", "") if isinstance(value[0], dict) else str(value[0])
            if value:
                match = IMG_SRC_PATTERN.search(str(value)[:5000])
                if match:
                    return match.group(1)

        return None

    async def _fetch_og_image(self, url: str) -> str | None:
        """記事URLにアクセスしてog:imageメタタグを抽出する."""
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.get(url, allow_redirects=False) as resp:
                    if resp.status in (301, 302, 303, 307, 308):
                        logger.warning(
                            "Redirect detected (SSRF protection): %s -> %s",
                            url,
                            resp.headers.get("Location", "unknown"),
                        )
                        return None
                    if resp.status != 200:
                        return None
                    html = await resp.text(errors="replace")
        except aiohttp.ClientError as e:
            logger.warning(
                "Network error while fetching OG image from %s: %s",
                url,
                e,
                exc_info=True,
            )
            return None
        except TimeoutError:
            logger.warning(
                "Timeout while fetching OG image from %s (timeout=%s)",
                url,
                self._timeout,
            )
            return None
        except Exception as e:
            logger.error(
                "Unexpected error while fetching OG image from %s: %s",
                url,
                e,
                exc_info=True,
            )
            return None

        # <head> 部分のみ検索（パフォーマンス最適化）
        head_end = html.lower().find("</head>")
        search_text = html[: head_end + 7] if head_end != -1 else html[:10000]

        match = OG_IMAGE_PATTERN.search(search_text)
        if not match:
            match = OG_IMAGE_PATTERN_REV.search(search_text)
        if match:
            return match.group(1)
        return None
