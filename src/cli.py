"""CLIエントリーポイント — REPL + ワンショットモード.

仕様: docs/specs/features/cli-adapter.md

使用方法:
    # REPL モード
    uv run python -m src.cli

    # ワンショットモード
    uv run python -m src.cli --message "こんにちは"

    # user-id 指定
    uv run python -m src.cli --user-id alice
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.config.settings import get_settings, load_assistant_config
from src.db.session import get_session_factory, init_db
from src.llm.base import LLMProvider
from src.llm.factory import get_provider_for_service
from src.mcp_bridge.client_manager import MCPClientManager, build_mcp_server_configs
from src.messaging.cli_adapter import CliAdapter
from src.messaging.port import IncomingMessage
from src.messaging.router import MessageRouter
from src.services.chat import ChatService
from src.services.feed_collector import FeedCollector
from src.services.ogp_extractor import OgpExtractor
from src.services.summarizer import Summarizer

logger = logging.getLogger(__name__)




def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """コマンドライン引数をパースする."""
    parser = argparse.ArgumentParser(
        description="AI Assistant CLI — Slackなしで動作確認",
    )
    parser.add_argument(
        "--user-id",
        default="cli-user",
        help="ユーザーID（デフォルト: cli-user）",
    )
    parser.add_argument(
        "--message",
        default=None,
        help="ワンショットモード: 指定時は単発メッセージを処理して終了",
    )
    parser.add_argument(
        "--db-dir",
        default=".tmp/.cli_data",
        help="DB保存先ディレクトリ（デフォルト: .tmp/.cli_data）",
    )
    return parser.parse_args(argv)


def _apply_db_dir(db_dir: str) -> None:
    """Settings の DB パスを指定ディレクトリ配下に上書きする."""
    settings = get_settings()
    db_path = Path(db_dir)
    db_path.mkdir(parents=True, exist_ok=True)
    settings.database_url = f"sqlite+aiosqlite:///{db_path / 'ai_assistant.db'}"


async def _setup(
    user_id: str,
) -> tuple[MessageRouter, CliAdapter, MCPClientManager | None]:
    """サービス群を初期化してMessageRouterを返す."""
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    await init_db()

    assistant = load_assistant_config()
    system_prompt = assistant.get("personality", "")

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
    mcp_manager: MCPClientManager | None = None
    if settings.mcp_enabled:
        mcp_manager = MCPClientManager()
        server_configs = build_mcp_server_configs(settings, assistant)
        await mcp_manager.initialize(server_configs)

    cli_adapter = CliAdapter(user_id=user_id)

    session_factory = get_session_factory()
    chat_service = ChatService(
        llm=chat_llm,
        session_factory=session_factory,
        system_prompt=system_prompt,
        mcp_manager=None if is_claude_mode else mcp_manager,
        thread_history_fetcher=cli_adapter.fetch_thread_history,
        format_instruction=cli_adapter.get_format_instruction(),
        claude_mode=is_claude_mode,
        claude_allowed_tools=settings.claude_allowed_tools,
        claude_timeout=settings.claude_timeout,
    )

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

    bot_start_time = datetime.now(tz=ZoneInfo(settings.timezone))

    router = MessageRouter(
        messaging=cli_adapter,
        chat_service=chat_service,
        collector=feed_collector,
        session_factory=session_factory,
        channel_id="cli",
        max_articles_per_feed=settings.feed_articles_per_feed,
        feed_card_layout=settings.feed_card_layout,
        bot_token=None,
        timezone=settings.timezone,
        env_name=settings.env_name,
        mcp_manager=mcp_manager,
        bot_start_time=bot_start_time,
        slack_client=None,
        rag_bluesky_handle=settings.rag_bluesky_handle,
        rag_zenn_username=settings.rag_zenn_username,
        rag_bluesky_max_posts=settings.rag_bluesky_max_posts,
        rag_zenn_max_articles=settings.rag_zenn_max_articles,
    )

    return router, cli_adapter, mcp_manager


async def run_oneshot(router: MessageRouter, user_id: str, text: str) -> None:
    """ワンショットモードで1メッセージを処理する."""
    thread_id = f"cli-{uuid.uuid4()}"
    msg = IncomingMessage(
        user_id=user_id,
        text=text,
        thread_id=thread_id,
        channel="cli",
        is_in_thread=False,
        message_id=f"cli-msg-{uuid.uuid4()}",
    )
    await router.process_message(msg)


async def run_repl(router: MessageRouter, user_id: str) -> None:
    """REPLモードで対話セッションを実行する."""
    thread_id = f"cli-{uuid.uuid4()}"
    print("AI Assistant CLI (quit/exit で終了)")
    print(f"user-id: {user_id} | session: {thread_id}")
    print("-" * 40)

    while True:
        try:
            text = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nセッションを終了します。")
            break

        if not text:
            continue

        if text.lower() in ("quit", "exit"):
            print("セッションを終了します。")
            break

        msg = IncomingMessage(
            user_id=user_id,
            text=text,
            thread_id=thread_id,
            channel="cli",
            is_in_thread=False,
            message_id=f"cli-msg-{uuid.uuid4()}",
        )
        await router.process_message(msg)


async def async_main(argv: list[str] | None = None) -> None:
    """非同期メインエントリーポイント."""
    args = parse_args(argv)
    _apply_db_dir(args.db_dir)
    logger.info("DB dir: %s", args.db_dir)
    router, _adapter, mcp_manager = await _setup(args.user_id)

    try:
        if args.message is not None:
            await run_oneshot(router, args.user_id, args.message)
        else:
            await run_repl(router, args.user_id)
    finally:
        if mcp_manager:
            try:
                await mcp_manager.cleanup()
            except Exception:
                logger.warning("MCPクリーンアップ失敗", exc_info=True)


def main() -> None:
    """同期エントリーポイント."""
    from src.compat import configure_stdio_encoding

    configure_stdio_encoding()
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
