"""Learning Companion エントリーポイント
仕様: docs/specs/overview.md
"""

from __future__ import annotations

import asyncio
import logging

from src.config.settings import get_settings, load_assistant_config
from src.db.session import init_db, get_session_factory
from src.llm.factory import create_local_provider, create_online_provider, get_provider_with_fallback
from src.services.chat import ChatService
from src.services.feed_collector import FeedCollector
from src.services.ogp_extractor import OgpExtractor
from src.services.summarizer import Summarizer
from src.services.topic_recommender import TopicRecommender
from src.services.user_profiler import UserProfiler
from src.slack.app import create_app, start_socket_mode
from src.slack.handlers import register_handlers


async def main() -> None:
    settings = get_settings()

    # ログ設定
    logging.basicConfig(level=settings.log_level)

    # DB 初期化
    await init_db()

    # アシスタント設定
    assistant = load_assistant_config()
    system_prompt = assistant.get("personality", "")

    # LLM プロバイダー
    online_llm = create_online_provider(settings)
    local_llm = create_local_provider(settings)

    # ユーザー情報抽出用LLM（ローカル優先、フォールバック）
    profiler_llm = await get_provider_with_fallback(local_llm, online_llm)

    # チャットサービス
    session_factory = get_session_factory()
    chat_service = ChatService(
        llm=online_llm,
        session_factory=session_factory,
        system_prompt=system_prompt,
    )

    # ユーザー情報抽出サービス
    user_profiler = UserProfiler(
        llm=profiler_llm,
        session_factory=session_factory,
    )

    # トピック提案サービス
    topic_recommender = TopicRecommender(
        llm=online_llm,
        session_factory=session_factory,
    )

    # 要約・収集サービス
    summarizer_llm = await get_provider_with_fallback(local_llm, online_llm)
    summarizer = Summarizer(llm=summarizer_llm)
    ogp_extractor = OgpExtractor()
    feed_collector = FeedCollector(
        session_factory=session_factory,
        summarizer=summarizer,
        ogp_extractor=ogp_extractor,
    )

    # Slack アプリ
    app = create_app(settings)
    slack_client = app.client
    register_handlers(
        app, chat_service,
        user_profiler=user_profiler,
        topic_recommender=topic_recommender,
        collector=feed_collector,
        session_factory=session_factory,
        slack_client=slack_client,
        channel_id=settings.slack_news_channel_id,
        max_articles_per_category=settings.feed_articles_per_category,
        feed_card_layout=settings.feed_card_layout,
    )

    # Socket Mode で起動
    await start_socket_mode(app, settings)


if __name__ == "__main__":
    asyncio.run(main())
