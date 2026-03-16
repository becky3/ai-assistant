"""AI Assistant エントリーポイント
仕様: docs/specs/overview.md, docs/specs/infrastructure/mcp-integration.md, docs/specs/features/thread-support.md,
      docs/specs/infrastructure/bot-process-guard.md, docs/specs/features/cli-adapter.md
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from src.config.settings import get_settings, load_assistant_config, resolve_secret
from src.process_guard import (
    BOT_READY_SIGNAL,
    check_already_running,
    cleanup_children,
    remove_pid_file,
    write_pid_file,
)

if TYPE_CHECKING:
    from src.mcp_bridge.client_manager import MCPServerConfig

logger = logging.getLogger(__name__)


def _load_mcp_server_configs(config_path: str) -> list[MCPServerConfig]:
    """MCPサーバー設定ファイルを読み込む."""
    from src.mcp_bridge.client_manager import MCPServerConfig

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
            system_instruction=server_def.get("system_instruction", ""),
            response_instruction=server_def.get("response_instruction", ""),
            auto_context_tool=server_def.get("auto_context_tool", ""),
        ))
    return configs


async def main() -> None:
    # ログ設定（プロセスガードのログ出力に必要なため最初に実行）
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    # 重複起動検知: 既に動いていたら警告して終了
    check_already_running()
    write_pid_file()

    from src.db.session import get_session_factory, init_db
    from src.llm.factory import get_provider_for_service
    from src.mcp_bridge.client_manager import MCPClientManager
    from src.messaging.router import MessageRouter
    from src.messaging.slack_adapter import SlackAdapter
    from src.services.chat import ChatService
    from src.services.feed_collector import FeedCollector
    from src.services.ogp_extractor import OgpExtractor
    from src.services.summarizer import Summarizer
    from src.services.thread_history import ThreadHistoryService
    from src.services.topic_recommender import TopicRecommender
    from src.services.user_profiler import UserProfiler
    from src.slack.app import create_app, socket_mode_handler
    from src.slack.handlers import register_handlers

    # 必須シークレットの起動時バリデーション（仕様: config-management.md エッジケース）
    _required_secrets = ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"]
    for _key in _required_secrets:
        if not resolve_secret(_key):
            raise SystemExit(
                f"必須シークレット {_key} が未設定です。"
                f"keyring または環境変数で設定してください。"
            )

    mcp_manager: MCPClientManager | None = None
    try:
        # 起動時刻を記録 (F7)
        bot_start_time = datetime.now(tz=ZoneInfo(settings.timezone))

        # DB 初期化
        await init_db()

        # アシスタント設定
        assistant = load_assistant_config()
        system_prompt = assistant.get("personality", "")
        slack_format = assistant.get("format_instruction", "")

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

        # Slack アプリ（ThreadHistoryService に必要なため先に作成）
        app = create_app()
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

        # SlackAdapter (F11)
        slack_adapter = SlackAdapter(
            slack_client=slack_client,
            bot_user_id=bot_user_id,
            thread_history_service=thread_history_service,
            format_instruction=slack_format,
        )

        # チャットサービス
        session_factory = get_session_factory()
        chat_service = ChatService(
            llm=chat_llm,
            session_factory=session_factory,
            system_prompt=system_prompt,
            mcp_manager=mcp_manager,
            thread_history_fetcher=slack_adapter.fetch_thread_history,
            format_instruction=slack_adapter.get_format_instruction(),
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

        # MessageRouter (F11)
        router = MessageRouter(
            messaging=slack_adapter,
            chat_service=chat_service,
            user_profiler=user_profiler,
            topic_recommender=topic_recommender,
            collector=feed_collector,
            session_factory=session_factory,
            channel_id=settings.slack_news_channel_id,
            max_articles_per_feed=settings.feed_articles_per_feed,
            feed_card_layout=settings.feed_card_layout,
            bot_token=resolve_secret("SLACK_BOT_TOKEN"),
            timezone=settings.timezone,
            env_name=settings.env_name,
            mcp_manager=mcp_manager,
            bot_start_time=bot_start_time,
            slack_client=slack_client,
        )

        register_handlers(
            app, router,
            auto_reply_channels=settings.get_auto_reply_channels(),
        )

        # Socket Mode で起動（グレースフルシャットダウン対応）
        async with socket_mode_handler(app) as handler:
            print(BOT_READY_SIGNAL, flush=True)
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
    import argparse

    parser = argparse.ArgumentParser(description="AI Assistant Bot")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--start", action="store_true", help="Start the bot")
    group.add_argument("--restart", action="store_true", help="Restart the bot")
    group.add_argument("--stop", action="store_true", help="Stop the bot")
    group.add_argument("--status", action="store_true", help="Show bot status")
    args = parser.parse_args()

    if args.start or args.restart or args.stop or args.status:
        from src.bot_manager import handle_command

        handle_command(args)
    else:
        asyncio.run(main())
