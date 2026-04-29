"""AI Assistant エントリーポイント
仕様: docs/specs/overview.md, docs/specs/infrastructure/mcp-integration.md, docs/specs/features/thread-support.md,
      docs/specs/infrastructure/bot-process-guard.md, docs/specs/features/cli-adapter.md
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from py_common_lib.logging import SessionRotatingFileHandler
from py_common_lib.secrets import SecretNotFoundError, get_secret

from src.config.settings import SERVICE_NAME, Settings, get_settings, load_assistant_config
from src.process_guard import (
    BOT_READY_SIGNAL,
    check_already_running,
    cleanup_children,
    remove_pid_file,
    write_pid_file,
)

if TYPE_CHECKING:
    from src.llm.base import LLMProvider

logger = logging.getLogger(__name__)

_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def _configure_logging(settings: Settings) -> None:
    """ログ設定を構築する（フォーマット統一・ファイル出力・デバッグ切替）."""
    # debug_log_enabled=True の場合は log_level 設定を上書きして DEBUG にする
    log_level: int | str = logging.DEBUG if settings.debug_log_enabled else settings.log_level
    formatter = logging.Formatter(_LOG_FORMAT)

    root = logging.getLogger()
    root.setLevel(log_level)

    if not root.handlers:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)
    else:
        for handler in root.handlers:
            handler.setFormatter(formatter)

    log_dir = settings.log_dir
    if log_dir and not any(isinstance(h, SessionRotatingFileHandler) for h in root.handlers):
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        file_handler = SessionRotatingFileHandler(
            log_dir=log_path,
            prefix="bot",
            started_at=datetime.now(),
            max_bytes=settings.log_file_max_bytes,
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)


async def main() -> None:
    # ログ設定（プロセスガードのログ出力に必要なため最初に実行）
    settings = get_settings()
    _configure_logging(settings)

    # 重複起動検知: 既に動いていたら警告して終了
    check_already_running()
    write_pid_file()

    from src.db.session import get_session_factory, init_db
    from src.llm.factory import get_provider_for_service
    from src.mcp_bridge.client_manager import MCPClientManager, build_mcp_server_configs
    from src.messaging.router import MessageRouter
    from src.messaging.slack_adapter import SlackAdapter
    from src.services.chat import ChatService
    from src.services.feed_collector import FeedCollector
    from src.services.ogp_extractor import OgpExtractor
    from src.services.remote_control import RemoteControlLauncher
    from src.services.summarizer import Summarizer
    from src.services.thread_history import ThreadHistoryService
    from src.slack.app import create_app, socket_mode_handler
    from src.slack.handlers import register_handlers

    # 必須シークレットの起動時バリデーション（仕様: config-management.md エッジケース）
    _required_secrets = ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_SIGNING_SECRET"]
    for _key in _required_secrets:
        try:
            get_secret(key=_key, service=SERVICE_NAME)
        except SecretNotFoundError:
            raise SystemExit(
                f"必須シークレット {_key} が未設定です。"
                f"keyring で設定してください。"
            )

    mcp_manager: MCPClientManager | None = None
    remote_control_launcher: RemoteControlLauncher | None = None
    try:
        # 起動時刻を記録 (F5)
        bot_start_time = datetime.now(tz=ZoneInfo(settings.timezone))

        # DB 初期化
        await init_db()

        # アシスタント設定
        assistant = load_assistant_config()
        system_prompt = assistant.get("personality", "")
        slack_format = assistant.get("format_instruction", "")

        # サービスごとのLLMプロバイダー（設定に基づいて選択）
        # claude モード時は LLM プロバイダーを生成しない（Claude CLI が直接処理する）
        is_claude_mode = settings.chat_llm_provider == "claude"
        if is_claude_mode:
            import shutil
            if not shutil.which("claude"):
                raise SystemExit(
                    "chat_llm_provider='claude' ですが、claude コマンドが見つかりません。"
                    "Claude CLI をインストールしてください。"
                )
        chat_llm: LLMProvider | None = None
        if not is_claude_mode:
            # mypy は != "claude" で Literal["local", "online"] への絞り込みを行えないため type: ignore
            chat_llm = get_provider_for_service(settings, settings.chat_llm_provider)  # type: ignore[arg-type]
        summarizer_llm = get_provider_for_service(settings, settings.summarizer_llm_provider)

        # MCP初期化（有効時のみ）
        if settings.mcp_enabled:
            mcp_manager = MCPClientManager()
            server_configs = build_mcp_server_configs(settings, assistant)
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
        bot_id: str | None = auth_result.get("bot_id")

        # スレッド履歴サービス (F6)
        thread_history_service = ThreadHistoryService(
            slack_client=slack_client,
            bot_user_id=bot_user_id,
            bot_id=bot_id,
            limit=settings.thread_history_limit,
        )

        # SlackAdapter (F9)
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
            mcp_manager=None if is_claude_mode else mcp_manager,
            thread_history_fetcher=slack_adapter.fetch_thread_history,
            format_instruction=slack_adapter.get_format_instruction(),
            claude_mode=is_claude_mode,
            claude_allowed_tools=settings.claude_allowed_tools,
            claude_timeout=settings.claude_timeout,
        )

        # 要約・収集サービス
        summarizer = Summarizer(
            llm=summarizer_llm,
            reasoning_effort=settings.feed_summarize_reasoning_effort,
        )
        ogp_extractor = OgpExtractor()
        feed_collector = FeedCollector(
            session_factory=session_factory,
            summarizer=summarizer,
            ogp_extractor=ogp_extractor,
            summarize_timeout=settings.feed_summarize_timeout,
            collect_days=settings.feed_collect_days,
        )

        # Remote Control 起動サービス（allowlist 設定がある場合のみ有効化）
        rc_repositories = settings.get_remote_control_repositories()
        rc_allowed_users = settings.get_remote_control_allowed_users()
        if rc_repositories and rc_allowed_users:
            rc_log_dir = (
                Path(settings.remote_control_log_dir)
                if settings.remote_control_log_dir
                else Path(".tmp/remote-control")
            )
            remote_control_launcher = RemoteControlLauncher(
                repositories=rc_repositories,
                log_dir=rc_log_dir,
                url_timeout=settings.remote_control_url_timeout,
            )
            logger.info(
                "Remote Control 起動を有効化: repos=%s, users=%d",
                sorted(rc_repositories.keys()), len(rc_allowed_users),
            )
        else:
            remote_control_launcher = None
            logger.info(
                "Remote Control 起動は無効（REMOTE_CONTROL_ALLOWED_USERS / REMOTE_CONTROL_REPOSITORIES のいずれかが未設定）",
            )

        # MessageRouter (F9)
        router = MessageRouter(
            messaging=slack_adapter,
            chat_service=chat_service,
            collector=feed_collector,
            session_factory=session_factory,
            channel_id=settings.slack_news_channel_id,
            max_articles_per_feed=settings.feed_articles_per_feed,
            feed_card_layout=settings.feed_card_layout,
            bot_token=get_secret(key="SLACK_BOT_TOKEN", service=SERVICE_NAME),
            timezone=settings.timezone,
            env_name=settings.env_name,
            mcp_manager=mcp_manager,
            bot_start_time=bot_start_time,
            slack_client=slack_client,
            rag_bluesky_handle=settings.rag_bluesky_handle,
            rag_zenn_username=settings.rag_zenn_username,
            rag_bluesky_max_posts=settings.rag_bluesky_max_posts,
            rag_zenn_max_articles=settings.rag_zenn_max_articles,
            remote_control_launcher=remote_control_launcher,
            remote_control_allowed_users=rc_allowed_users,
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
            # Slack 経由で起動した remote-control プロセスは bot 停止時にも生かす
            # （外出先ユーザーの作業中断を避けるため）
            exclude_pids = (
                remote_control_launcher.get_active_pids()
                if remote_control_launcher is not None
                else set()
            )
            cleanup_children(exclude_pids=exclude_pids)
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
