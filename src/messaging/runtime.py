"""プラットフォーム runtime — プラットフォーム固有の結線を 1 箇所に閉じる.

仕様: docs/specs/features/cli-adapter.md, docs/specs/infrastructure/config-management.md

`.env PLATFORM` で選択されたプラットフォーム（Slack / Discord）のアダプター・
リスナーを構築する。bot identity 解決タイミングの差（Slack=接続前 auth_test /
Discord=接続後 on_ready）を各 runtime が吸収する。共通サービス（DB / LLM / MCP /
router 等）の構築は main.py に残し、本モジュールは送受信プラットフォーム層のみを扱う。
"""

from __future__ import annotations

import abc
import logging
from typing import TYPE_CHECKING

from py_common_lib.secrets import SecretNotFoundError, get_secret

from src.config.settings import SERVICE_NAME, Settings
from src.messaging.listener import MessagingListener
from src.messaging.port import MessagingPort

if TYPE_CHECKING:
    from src.messaging.router import MessageRouter

logger = logging.getLogger(__name__)


def _require_secrets(keys: list[str]) -> None:
    """必須シークレットの存在を検証する（不在で SystemExit）."""
    for key in keys:
        try:
            get_secret(key=key, service=SERVICE_NAME)
        except SecretNotFoundError:
            raise SystemExit(
                f"必須シークレット {key} が未設定です。keyring で設定してください。"
            )


class PlatformRuntime(abc.ABC):
    """プラットフォーム固有の構築を抽象化する.

    仕様: docs/specs/features/cli-adapter.md
    """

    @abc.abstractmethod
    def validate_secrets(self) -> None:
        """選択プラットフォームの必須シークレットを検証する."""

    @abc.abstractmethod
    async def create_adapter(self) -> MessagingPort:
        """送信アダプター（MessagingPort 実装）を構築する."""

    @abc.abstractmethod
    def create_listener(self, router: MessageRouter) -> MessagingListener:
        """受信リスナー（MessagingListener 実装）を構築する."""

    @property
    @abc.abstractmethod
    def news_channel_id(self) -> str:
        """フィード配信先チャンネル ID を返す."""


class SlackRuntime(PlatformRuntime):
    """Slack 用 runtime（Bolt + Socket Mode）."""

    def __init__(self, settings: Settings, format_instruction: str) -> None:
        self._settings = settings
        self._format_instruction = format_instruction
        self._app: object | None = None
        self._bot_user_id = ""

    def validate_secrets(self) -> None:
        _require_secrets(
            ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_SIGNING_SECRET"]
        )

    async def create_adapter(self) -> MessagingPort:
        from src.messaging.slack_adapter import SlackAdapter
        from src.services.thread_history import ThreadHistoryService
        from src.slack.app import create_app

        app = create_app()
        self._app = app
        slack_client = app.client

        try:
            auth_result = await slack_client.auth_test()
        except Exception as e:
            raise RuntimeError(f"Failed to call Slack auth_test: {e}") from e

        bot_user_id: str | None = auth_result.get("user_id")
        if not bot_user_id:
            raise RuntimeError("Slack auth_test response does not contain 'user_id'.")
        self._bot_user_id = bot_user_id
        bot_id: str | None = auth_result.get("bot_id")

        thread_history_service = ThreadHistoryService(
            slack_client=slack_client,
            bot_user_id=bot_user_id,
            bot_id=bot_id,
            limit=self._settings.thread_history_limit,
        )

        return SlackAdapter(
            slack_client=slack_client,
            bot_user_id=bot_user_id,
            thread_history_service=thread_history_service,
            format_instruction=self._format_instruction,
            bot_token=get_secret(key="SLACK_BOT_TOKEN", service=SERVICE_NAME),
            feed_card_layout=self._settings.feed_card_layout,
        )

    def create_listener(self, router: MessageRouter) -> MessagingListener:
        from slack_bolt.async_app import AsyncApp

        from src.messaging.slack_listener import SlackListener

        assert isinstance(self._app, AsyncApp), "create_adapter() を先に呼び出してください"
        return SlackListener(
            app=self._app,
            router=router,
            bot_user_id=self._bot_user_id,
            auto_reply_channels=self._settings.get_auto_reply_channels(),
        )

    @property
    def news_channel_id(self) -> str:
        return self._settings.slack_news_channel_id


class DiscordRuntime(PlatformRuntime):
    """Discord 用 runtime（discord.py Gateway）."""

    def __init__(self, settings: Settings, format_instruction: str) -> None:
        self._settings = settings
        self._format_instruction = format_instruction
        self._client: object | None = None
        self._bot_token = ""

    def validate_secrets(self) -> None:
        _require_secrets(["DISCORD_BOT_TOKEN"])

    async def create_adapter(self) -> MessagingPort:
        from src.messaging.discord_adapter import DiscordAdapter
        from src.messaging.discord_listener import create_client

        self._bot_token = get_secret(key="DISCORD_BOT_TOKEN", service=SERVICE_NAME)
        client = create_client()
        self._client = client

        return DiscordAdapter(
            client,
            format_instruction=self._format_instruction,
            feed_card_layout=self._settings.feed_card_layout,
            thread_history_limit=self._settings.thread_history_limit,
        )

    def create_listener(self, router: MessageRouter) -> MessagingListener:
        import discord

        from src.messaging.discord_listener import DiscordListener

        assert isinstance(self._client, discord.Client), (
            "create_adapter() を先に呼び出してください"
        )
        return DiscordListener(
            self._client,
            router,
            bot_token=self._bot_token,
            auto_reply_channels=self._settings.get_discord_auto_reply_channels(),
        )

    @property
    def news_channel_id(self) -> str:
        return self._settings.discord_news_channel_id


def create_runtime(settings: Settings, assistant: dict[str, object]) -> PlatformRuntime:
    """settings.platform に応じたプラットフォーム runtime を生成する.

    canonical 内部マークアップは Slack mrkdwn（`format_instruction`）に統一する。
    Discord 向けの Discord Markdown 変換は DiscordAdapter の送信時に行うため、
    LLM へ渡す整形指示はプラットフォーム間で共通とする（仕様: S2-U3 設計判断）。
    """
    format_instruction = str(assistant.get("format_instruction", ""))
    if settings.platform == "discord":
        logger.info("プラットフォーム: discord")
        return DiscordRuntime(settings, format_instruction)
    logger.info("プラットフォーム: slack")
    return SlackRuntime(settings, format_instruction)
