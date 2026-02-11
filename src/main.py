"""AI Assistant エントリーポイント
仕様: docs/specs/overview.md, docs/specs/f5-mcp-integration.md, docs/specs/f8-thread-support.md,
      docs/specs/bot-process-guard.md
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# ChromaDBテレメトリのエラーログを抑制（常に無効化、ユーザーには不要）
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)

import src.slack.handlers as handlers_module
from src.config.settings import get_settings, load_assistant_config
from src.process_guard import (
    check_already_running,
    cleanup_children,
    remove_pid_file,
    write_pid_file,
)
from src.db.session import init_db, get_session_factory
from src.embedding.factory import get_embedding_provider
from src.llm.factory import get_provider_for_service
from src.mcp_bridge.client_manager import MCPClientManager, MCPServerConfig
from src.rag.bm25_index import BM25Index
from src.rag.vector_store import VectorStore
from src.services.chat import ChatService
from src.services.feed_collector import FeedCollector
from src.services.ogp_extractor import OgpExtractor
from src.services.rag_knowledge import RAGKnowledgeService
from src.services.summarizer import Summarizer
from src.services.thread_history import ThreadHistoryService
from src.services.topic_recommender import TopicRecommender
from src.services.user_profiler import UserProfiler
from src.services.web_crawler import WebCrawler
from src.services.safe_browsing import create_safe_browsing_client
from src.slack.app import create_app, socket_mode_handler

logger = logging.getLogger(__name__)


def _load_mcp_server_configs(config_path: str) -> list[MCPServerConfig]:
    """MCPサーバー設定ファイルを読み込む."""
    path = Path(config_path)
    if not path.exists():
        logger.warning("MCP設定ファイル '%s' が見つかりません。", config_path)
        return []

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        logger.exception("MCP設定ファイル '%s' のJSON解析に失敗しました。", config_path)
        return []

    configs: list[MCPServerConfig] = []
    for name, server_def in data.get("mcpServers", {}).items():
        configs.append(MCPServerConfig(
            name=name,
            transport=server_def.get("transport", "stdio"),
            command=server_def.get("command", ""),
            args=server_def.get("args", []),
            env=server_def.get("env", {}),
            url=server_def.get("url", ""),
            response_instruction=server_def.get("response_instruction", ""),
        ))
    return configs


async def main() -> None:
    # ログ設定（プロセスガードのログ出力に必要なため最初に実行）
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    # 重複起動検知: 既に動いていたら警告して終了
    check_already_running()
    write_pid_file()

    mcp_manager: MCPClientManager | None = None
    try:
        # 起動時刻を記録 (F7)
        handlers_module.BOT_START_TIME = datetime.now(tz=ZoneInfo(settings.timezone))

        # DB 初期化
        await init_db()

        # アシスタント設定
        assistant = load_assistant_config()
        system_prompt = assistant.get("personality", "")

        # サービスごとのLLMプロバイダー（設定に基づいて選択）
        chat_llm = get_provider_for_service(settings, settings.chat_llm_provider)
        profiler_llm = get_provider_for_service(settings, settings.profiler_llm_provider)
        topic_llm = get_provider_for_service(settings, settings.topic_llm_provider)
        summarizer_llm = get_provider_for_service(settings, settings.summarizer_llm_provider)

        # MCP初期化（有効時のみ）
        if settings.mcp_enabled:
            mcp_manager = MCPClientManager()
            server_configs = _load_mcp_server_configs(settings.mcp_servers_config)
            await mcp_manager.initialize(server_configs)
            tools = await mcp_manager.get_available_tools()
            logger.info("MCP有効: %d個のツールが利用可能", len(tools))
        else:
            logger.info("MCP無効: ツール呼び出し機能はオフです")

        # RAG初期化（有効時のみ）
        rag_service: RAGKnowledgeService | None = None
        if settings.rag_enabled:
            embedding = get_embedding_provider(settings, settings.embedding_provider)
            vector_store = VectorStore(embedding, settings.chromadb_persist_dir)
            web_crawler = WebCrawler(
                max_pages=settings.rag_max_crawl_pages,
                crawl_delay=settings.rag_crawl_delay_sec,
            )
            # Safe Browsing クライアント（URL安全性チェック）
            safe_browsing_client = create_safe_browsing_client(settings)
            if safe_browsing_client:
                logger.info("URL安全性チェック有効: Google Safe Browsing API")

            # BM25インデックス（ハイブリッド検索用）
            bm25_index: BM25Index | None = None
            if settings.rag_hybrid_search_enabled:
                bm25_index = BM25Index(
                    k1=settings.rag_bm25_k1,
                    b=settings.rag_bm25_b,
                )
                logger.info("BM25インデックス初期化完了")

            rag_service = RAGKnowledgeService(
                vector_store,
                web_crawler,
                chunk_size=settings.rag_chunk_size,
                chunk_overlap=settings.rag_chunk_overlap,
                safe_browsing_client=safe_browsing_client,
                bm25_index=bm25_index,
                hybrid_search_enabled=settings.rag_hybrid_search_enabled,
            )
            if settings.rag_hybrid_search_enabled:
                logger.info("RAG有効: ハイブリッド検索（ベクトル＋BM25）が利用可能")
            else:
                logger.info("RAG有効: ナレッジベース機能が利用可能")
        else:
            logger.info("RAG無効: ナレッジベース機能はオフです")

        # Slack アプリ（ThreadHistoryService に必要なため先に作成）
        app = create_app(settings)
        slack_client = app.client

        # Bot User ID を取得（スレッド履歴でボットの発言を識別するため）
        try:
            auth_result = await slack_client.auth_test()
        except Exception as e:
            raise RuntimeError(f"Failed to call Slack auth_test: {e}") from e

        bot_user_id: str | None = auth_result.get("user_id")
        if not bot_user_id:
            raise RuntimeError("Slack auth_test response does not contain 'user_id'.")

        # スレッド履歴サービス (F8)
        thread_history_service = ThreadHistoryService(
            slack_client=slack_client,
            bot_user_id=bot_user_id,
            limit=settings.thread_history_limit,
        )

        # チャットサービス
        session_factory = get_session_factory()
        chat_service = ChatService(
            llm=chat_llm,
            session_factory=session_factory,
            system_prompt=system_prompt,
            mcp_manager=mcp_manager,
            thread_history_service=thread_history_service,
            rag_service=rag_service,
        )

        # ユーザー情報抽出サービス
        user_profiler = UserProfiler(
            llm=profiler_llm,
            session_factory=session_factory,
        )

        # トピック提案サービス
        topic_recommender = TopicRecommender(
            llm=topic_llm,
            session_factory=session_factory,
        )

        # 要約・収集サービス
        summarizer = Summarizer(llm=summarizer_llm)
        ogp_extractor = OgpExtractor()
        feed_collector = FeedCollector(
            session_factory=session_factory,
            summarizer=summarizer,
            ogp_extractor=ogp_extractor,
            summarize_timeout=settings.feed_summarize_timeout,
            collect_days=settings.feed_collect_days,
        )
        handlers_module.register_handlers(
            app, chat_service,
            user_profiler=user_profiler,
            topic_recommender=topic_recommender,
            collector=feed_collector,
            session_factory=session_factory,
            slack_client=slack_client,
            channel_id=settings.slack_news_channel_id,
            max_articles_per_feed=settings.feed_articles_per_feed,
            feed_card_layout=settings.feed_card_layout,
            auto_reply_channels=settings.get_auto_reply_channels(),
            bot_token=settings.slack_bot_token,
            timezone=settings.timezone,
            env_name=settings.env_name,
            rag_service=rag_service,
        )

        # Socket Mode で起動（グレースフルシャットダウン対応）
        async with socket_mode_handler(app, settings) as handler:
            try:
                await handler.start_async()  # type: ignore[no-untyped-call]
            except asyncio.CancelledError:
                logger.info("シャットダウンシグナルを受信しました")
    finally:
        if mcp_manager:
            try:
                await mcp_manager.cleanup()
                logger.info("MCP接続をクリーンアップしました")
            except Exception:
                logger.warning("MCPクリーンアップ失敗", exc_info=True)
        try:
            cleanup_children()
        except Exception:
            logger.warning("子プロセスクリーンアップ失敗", exc_info=True)
        remove_pid_file()


if __name__ == "__main__":
    asyncio.run(main())
