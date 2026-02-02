"""Slack イベントハンドラ
仕様: docs/specs/f1-chat.md, docs/specs/f2-feed-collection.md, docs/specs/f3-user-profiling.md, docs/specs/f4-topic-recommend.md
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING

from slack_bolt.async_app import AsyncApp

from src.services.chat import ChatService
from src.services.topic_recommender import TopicRecommender
from src.services.user_profiler import UserProfiler

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from src.services.feed_collector import FeedCollector

logger = logging.getLogger(__name__)

_PROFILE_KEYWORDS = ("プロファイル", "プロフィール", "profile")
_TOPIC_KEYWORDS = ("おすすめ", "トピック", "何を学ぶ", "何学ぶ", "学習提案", "recommend")
_DELIVER_KEYWORDS = ("deliver",)


def strip_mention(text: str) -> str:
    """メンション部分 (<@U...>) を除去する."""
    return re.sub(r"<@[A-Za-z0-9]+>\s*", "", text).strip()


def register_handlers(
    app: AsyncApp,
    chat_service: ChatService,
    user_profiler: UserProfiler | None = None,
    topic_recommender: TopicRecommender | None = None,
    collector: FeedCollector | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    slack_client: object | None = None,
    channel_id: str | None = None,
    max_articles_per_category: int = 10,
) -> None:
    """app_mention ハンドラを登録する."""

    @app.event("app_mention")
    async def handle_mention(event: dict, say: object) -> None:  # type: ignore[type-arg]
        user_id: str = event.get("user", "")
        text: str = event.get("text", "")
        thread_ts: str = event.get("thread_ts") or event.get("ts", "")

        cleaned_text = strip_mention(text)
        if not cleaned_text:
            return

        # プロファイル確認キーワード (AC4)
        if user_profiler is not None and any(
            kw in cleaned_text.lower() for kw in _PROFILE_KEYWORDS
        ):
            profile_text = await user_profiler.get_profile(user_id)
            if profile_text:
                await say(text=profile_text, thread_ts=thread_ts)  # type: ignore[operator]
            else:
                await say(  # type: ignore[operator]
                    text="まだプロファイル情報がありません。会話を続けると自動的に記録されます！",
                    thread_ts=thread_ts,
                )
            return

        # 配信テストキーワード (F2)
        if (
            collector is not None
            and session_factory is not None
            and slack_client is not None
            and channel_id is not None
            and any(kw in cleaned_text.lower() for kw in _DELIVER_KEYWORDS)
        ):
            from src.scheduler.jobs import daily_collect_and_deliver

            try:
                await say(text="配信を開始します...", thread_ts=thread_ts)  # type: ignore[operator]
                await daily_collect_and_deliver(
                    collector, session_factory, slack_client, channel_id,
                    max_articles_per_category=max_articles_per_category,
                )
                await say(text="配信が完了しました", thread_ts=thread_ts)  # type: ignore[operator]
            except Exception:
                logger.exception("Failed to run manual delivery")
                await say(  # type: ignore[operator]
                    text="配信中にエラーが発生しました。",
                    thread_ts=thread_ts,
                )
            return

        # トピック提案キーワード (F4)
        if topic_recommender is not None and any(
            kw in cleaned_text.lower() for kw in _TOPIC_KEYWORDS
        ):
            try:
                recommendation = await topic_recommender.recommend(user_id)
                await say(text=recommendation, thread_ts=thread_ts)  # type: ignore[operator]
            except Exception:
                logger.exception("Failed to generate topic recommendation")
                await say(  # type: ignore[operator]
                    text="申し訳ありません、トピック提案の生成中にエラーが発生しました。",
                    thread_ts=thread_ts,
                )
            return

        try:
            response = await chat_service.respond(
                user_id=user_id,
                text=cleaned_text,
                thread_ts=thread_ts,
            )
            await say(text=response, thread_ts=thread_ts)  # type: ignore[operator]

            # ユーザー情報抽出を非同期で実行 (AC3)
            if user_profiler is not None:
                asyncio.create_task(
                    _safe_extract_profile(user_profiler, user_id, cleaned_text)
                )
        except Exception:
            logger.exception("Failed to generate response")
            await say(  # type: ignore[operator]
                text="申し訳ありません、応答の生成中にエラーが発生しました。しばらくしてからもう一度お試しください。",
                thread_ts=thread_ts,
            )


async def _safe_extract_profile(
    profiler: UserProfiler, user_id: str, message: str
) -> None:
    """プロファイル抽出を安全に実行する（例外をログに記録）."""
    try:
        await profiler.extract_profile(user_id, message)
    except Exception:
        logger.exception("Failed to extract user profile for %s", user_id)
