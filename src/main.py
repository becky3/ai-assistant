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

import src.slack.handlers as handlers_module
from src.config.settings import get_settings, load_assistant_config
from src.process_guard import (
    check_already_running,
    cleanup_children,
    remove_pid_file,
    write_pid_file,
)
from src.db.session import init_db, get_session_factory
from src.llm.factory import get_provider_for_service
from src.mcp_bridge.client_manager import MCPClientManager, MCPServerConfig
from src.services.chat import ChatService
from src.services.thread_history import ThreadHistoryService
from src.services.feed_collector import FeedCollector
from src.services.ogp_extractor import OgpExtractor
from src.services.summarizer import Summarizer
from src.services.topic_recommender import TopicRecommender
from src.services.user_profiler import UserProfiler
from src.slack.app import create_app, start_socket_mode

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
    # 重複起動検知: 既に動いていたら警告して終了
    check_already_running()
    write_pid_file()

    settings = get_settings()

    # 起動時刻を記録 (F7)
    handlers_module.BOT_START_TIME = datetime.now(tz=ZoneInfo(settings.timezone))

    # ログ設定
    logging.basicConfig(level=settings.log_level)

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
    mcp_manager: MCPClientManager | None = None
    if settings.mcp_enabled:
        mcp_manager = MCPClientManager()
        server_configs = _load_mcp_server_configs(settings.mcp_servers_config)
        await mcp_manager.initialize(server_configs)
        tools = await mcp_manager.get_available_tools()
        logger.info("MCP有効: %d個のツールが利用可能", len(tools))
    else:
        logger.info("MCP無効: ツール呼び出し機能はオフです")

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
    )

    # Socket Mode で起動
    try:
        await start_socket_mode(app, settings)
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
