"""プラットフォーム runtime のテスト (Issue #850)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from py_common_lib.secrets import SecretNotFoundError
from slack_bolt.async_app import AsyncApp

from src.messaging.discord_adapter import DiscordAdapter
from src.messaging.discord_listener import DiscordListener
from src.messaging.runtime import (
    DiscordRuntime,
    SlackRuntime,
    create_runtime,
)
from src.messaging.slack_adapter import SlackAdapter
from src.messaging.slack_listener import SlackListener

from .settings_defaults import TEST_SETTINGS_DEFAULTS

from src.config.settings import Settings


def _settings(**overrides: Any) -> Settings:
    return Settings(**{**TEST_SETTINGS_DEFAULTS, **overrides})


def test_create_runtime_selects_slack() -> None:
    rt = create_runtime(_settings(platform="slack"), {"format_instruction": "x"})
    assert isinstance(rt, SlackRuntime)


def test_create_runtime_selects_discord() -> None:
    # canonical 統一設計のため Discord 専用整形キーは持たない（format_instruction を共用）
    rt = create_runtime(_settings(platform="discord"), {"format_instruction": "y"})
    assert isinstance(rt, DiscordRuntime)


def test_news_channel_id_per_platform() -> None:
    slack_rt = create_runtime(
        _settings(platform="slack", slack_news_channel_id="C_SLACK"), {}
    )
    discord_rt = create_runtime(
        _settings(platform="discord", discord_news_channel_id="111"), {}
    )
    assert slack_rt.news_channel_id == "C_SLACK"
    assert discord_rt.news_channel_id == "111"


def test_slack_validate_secrets_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get_secret(*, key: str, service: str) -> str:
        raise SecretNotFoundError(f"missing {key}")

    monkeypatch.setattr("src.messaging.runtime.get_secret", fake_get_secret)
    rt = SlackRuntime(_settings(), "")
    with pytest.raises(SystemExit):
        rt.validate_secrets()


def test_discord_validate_secrets_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get_secret(*, key: str, service: str) -> str:
        raise SecretNotFoundError(f"missing {key}")

    monkeypatch.setattr("src.messaging.runtime.get_secret", fake_get_secret)
    rt = DiscordRuntime(_settings(), "")
    with pytest.raises(SystemExit):
        rt.validate_secrets()


async def test_discord_runtime_builds_adapter_and_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.messaging.runtime.get_secret",
        lambda *, key, service: "discord-token",
    )
    rt = DiscordRuntime(_settings(discord_auto_reply_channels="111"), "discord-fmt")

    adapter = await rt.create_adapter()
    assert isinstance(adapter, DiscordAdapter)
    assert adapter.get_format_instruction() == "discord-fmt"

    listener = rt.create_listener(MagicMock())
    assert isinstance(listener, DiscordListener)


async def test_slack_runtime_builds_adapter_and_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.messaging.runtime.get_secret",
        lambda *, key, service: "slack-token",
    )

    fake_app = MagicMock(spec=AsyncApp)
    fake_app.client.auth_test = AsyncMock(
        return_value={"user_id": "UBOT", "bot_id": "BBOT"}
    )
    monkeypatch.setattr("src.slack.app.create_app", lambda: fake_app)

    rt = SlackRuntime(_settings(slack_news_channel_id="C1"), "slack-fmt")

    adapter = await rt.create_adapter()
    assert isinstance(adapter, SlackAdapter)
    assert adapter.get_bot_user_id() == "UBOT"

    listener = rt.create_listener(MagicMock())
    assert isinstance(listener, SlackListener)
    assert listener.bot_user_id == "UBOT"
