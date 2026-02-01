"""Learning Companion エントリーポイント
仕様: docs/specs/overview.md
"""

from __future__ import annotations

import asyncio
import logging

from src.config.settings import get_settings, load_assistant_config
from src.db.session import init_db, get_session_factory
from src.llm.factory import create_online_provider
from src.services.chat import ChatService
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
    llm = create_online_provider(settings)

    # チャットサービス
    chat_service = ChatService(
        llm=llm,
        session_factory=get_session_factory(),
        system_prompt=system_prompt,
    )

    # Slack アプリ
    app = create_app(settings)
    register_handlers(app, chat_service)

    # Socket Mode で起動
    await start_socket_mode(app, settings)


if __name__ == "__main__":
    asyncio.run(main())
