"""ローカルLLMによる記事要約サービス
仕様: docs/specs/f2-feed-collection.md
"""

from __future__ import annotations

import logging

from src.llm.base import LLMProvider, Message

logger = logging.getLogger(__name__)

SUMMARIZE_PROMPT = (
    "以下の記事タイトルとURLから、記事の内容を日本語で2〜3文で簡潔に要約してください。\n\n"
    "タイトル: {title}\nURL: {url}"
)


class Summarizer:
    """記事要約サービス.

    仕様: docs/specs/f2-feed-collection.md
    """

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def summarize(self, title: str, url: str) -> str:
        """記事を要約する."""
        prompt = SUMMARIZE_PROMPT.format(title=title, url=url)
        try:
            response = await self._llm.complete([
                Message(role="user", content=prompt),
            ])
            return response.content.strip()
        except Exception:
            logger.exception("Failed to summarize article: %s", url)
            return ""
