"""ローカルLLMによる記事要約サービス
仕様: docs/specs/f2-feed-collection.md
"""

from __future__ import annotations

import logging

from src.llm.base import LLMProvider, Message

logger = logging.getLogger(__name__)

SUMMARIZE_PROMPT = (
    "以下の<article>内の記事情報を日本語で2〜3文で簡潔に要約してください。\n\n"
    "【重要】\n"
    "- 前置き（「この記事では」「要約すると」など）は不要です。\n"
    "- 概要が「なし」または情報が少なすぎる場合は、タイトルから内容を推測して要約してください。\n"
    "- 概要がある場合は、概要の内容に基づいて要約し、推測は入れないでください。\n"
    "- 「情報が不足しています」「内容を把握できません」のような回答は禁止です。\n"
    "  必ず要約を出力してください。\n\n"
    "出力例:\n"
    "良い例: asyncioにTaskGroupが正式導入され、エラーハンドリングが簡潔になりました。\n"
    "悪い例: この記事では、asyncioにTaskGroupが正式導入された内容を解説しています。\n"
    "悪い例: 提供された情報だけでは、記事の具体的な内容を把握できません。\n\n"
    "<article>\n"
    "タイトル: {title}\n"
    "概要: {description}\n"
    "URL: {url}\n"
    "</article>"
)


class Summarizer:
    """記事要約サービス.

    仕様: docs/specs/f2-feed-collection.md
    """

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def summarize(self, title: str, url: str, description: str = "") -> str:
        """記事を要約する."""
        prompt = SUMMARIZE_PROMPT.format(title=title, url=url, description=description or "なし")
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
