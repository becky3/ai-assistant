"""ローカルLLMによる記事要約サービス
仕様: docs/specs/f2-feed-collection.md
"""

from __future__ import annotations

import logging

from src.llm.base import LLMProvider, Message

logger = logging.getLogger(__name__)

SUMMARIZE_PROMPT = (
    "以下の記事タイトルとURLから、記事の内容を日本語で2〜3文で簡潔に要約してください。\n\n"
    "【重要】前置き（「この記事では」「要約すると」など）は不要です。本文の内容をそのまま書いてください。\n\n"
    "例:\n"
    "良い例: asyncioにTaskGroupが正式導入され、エラーハンドリングが簡潔になりました。\n"
    "悪い例: この記事では、asyncioにTaskGroupが正式導入された内容を解説しています。\n\n"
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
            content = response.content.strip()
            if not content:
                logger.warning("LLM returned empty summary for article: %s", url)
                return title
            return content
        except Exception:
            logger.exception("Failed to summarize article: %s", url)
            return title
