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

from src.config.settings import Settings, get_settings, load_assistant_config
from src.process_guard import (
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
    from src.messaging.runtime import create_runtime
    from src.services.article_publisher import ArticleWriterPublisher
    from src.services.chat import ChatService
    from src.services.feed_collector import FeedCollector
    from src.services.ogp_extractor import OgpExtractor
    from src.services.remote_control import RemoteControlLauncher
    from src.services.summarizer import Summarizer
    from src.scheduler.daily_scheduler import DailyScheduler
    from src.scheduler.schedule_config import load_schedule

    # プラットフォーム runtime の構築（.env PLATFORM で slack / discord を選択）
    assistant = load_assistant_config()
    runtime = create_runtime(settings, assistant)

    # 必須シークレットの起動時バリデーション（選択プラットフォームのみ。仕様: config-management.md エッジケース）
    runtime.validate_secrets()

    mcp_manager: MCPClientManager | None = None
    remote_control_launcher: RemoteControlLauncher | None = None
    scheduler: DailyScheduler | None = None
    try:
        # 起動時刻を記録 (F5)
        bot_start_time = datetime.now(tz=ZoneInfo(settings.timezone))

        # DB 初期化
        await init_db()

        # アシスタント設定（assistant は runtime 構築時に読み込み済み）
        system_prompt = assistant.get("personality", "")

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

        # プラットフォームアダプター（Slack=auth_test で bot identity 解決 / Discord=client 生成）
        # 仕様: bot identity 解決タイミングの差は runtime が吸収する
        messaging_adapter = await runtime.create_adapter()

        # チャットサービス
        session_factory = get_session_factory()
        chat_service = ChatService(
            llm=chat_llm,
            session_factory=session_factory,
            system_prompt=system_prompt,
            mcp_manager=None if is_claude_mode else mcp_manager,
            thread_history_fetcher=messaging_adapter.fetch_thread_history,
            format_instruction=messaging_adapter.get_format_instruction(),
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
        # 許可ユーザーは選択プラットフォームの allowlist を runtime 経由で取得する
        rc_repositories = settings.get_remote_control_repositories()
        rc_allowed_users = runtime.remote_control_allowed_users
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
                "Remote Control 起動は無効（許可ユーザー（プラットフォーム別 allowlist）/ "
                "REMOTE_CONTROL_REPOSITORIES のいずれかが未設定）",
            )

        # 記事自動投稿サービス（ARTICLE_WRITER_REPO_PATH 設定がある場合のみ有効化）
        # 空白のみの値は settings 側の field_validator で空文字に正規化済み
        if settings.article_writer_repo_path:
            article_writer_publisher = ArticleWriterPublisher(
                repo_path=Path(settings.article_writer_repo_path),
                timeout=settings.article_publish_timeout,
            )
            logger.info(
                "記事自動投稿を有効化: repo_path=%s, timeout=%ds",
                settings.article_writer_repo_path,
                settings.article_publish_timeout,
            )
        else:
            article_writer_publisher = None
            logger.info(
                "記事自動投稿は無効（ARTICLE_WRITER_REPO_PATH が未設定）",
            )

        # MessageRouter (F9)
        router = MessageRouter(
            messaging=messaging_adapter,
            chat_service=chat_service,
            collector=feed_collector,
            session_factory=session_factory,
            channel_id=runtime.news_channel_id,
            max_articles_per_feed=settings.feed_articles_per_feed,
            timezone=settings.timezone,
            env_name=settings.env_name,
            mcp_manager=mcp_manager,
            bot_start_time=bot_start_time,
            rag_bluesky_handle=settings.rag_bluesky_handle,
            rag_zenn_username=settings.rag_zenn_username,
            rag_bluesky_max_posts=settings.rag_bluesky_max_posts,
            rag_zenn_max_articles=settings.rag_zenn_max_articles,
            remote_control_launcher=remote_control_launcher,
            remote_control_allowed_users=rc_allowed_users,
            article_writer_publisher=article_writer_publisher,
        )

        # 受信リスナー（MessagingListener 抽象経由で起動）
        listener = runtime.create_listener(router)

        # 定時実行スケジューラ（config/schedule.toml があれば毎日定時にコマンド実行）
        scheduler = DailyScheduler(
            load_schedule(),
            router,
            messaging_adapter,
            default_channel=runtime.news_channel_id,
            timezone=settings.timezone,
        )
        scheduler.start()

        # 接続して起動（グレースフルシャットダウン対応）
        await listener.run()
    finally:
        if scheduler is not None:
            try:
                await scheduler.stop()
            except Exception:
                logger.warning("スケジューラ停止失敗", exc_info=True)
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
