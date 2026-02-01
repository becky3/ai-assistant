"""設定管理のテスト (Issue #2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config.settings import Settings, load_assistant_config


def test_ac1_settings_loads_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC1: pydantic-settingsで.envから全設定値を読み込める."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
    monkeypatch.setenv("ONLINE_LLM_PROVIDER", "anthropic")

    s = Settings()
    assert s.slack_bot_token == "xoxb-test"
    assert s.openai_api_key == "sk-test"
    assert s.anthropic_api_key == "sk-ant-test"
    assert s.database_url == "sqlite+aiosqlite:///./test.db"
    assert s.online_llm_provider == "anthropic"


def test_ac2_all_config_sections_present() -> None:
    """AC2: Slack/OpenAI/Anthropic/LM Studio/DB/スケジューラの設定項目を網羅."""
    fields = set(Settings.model_fields.keys())
    # Slack
    assert {"slack_bot_token", "slack_signing_secret", "slack_app_token"} <= fields
    # OpenAI
    assert {"openai_api_key", "openai_model"} <= fields
    # Anthropic
    assert {"anthropic_api_key", "anthropic_model"} <= fields
    # LM Studio
    assert {"lmstudio_base_url", "lmstudio_model"} <= fields
    # DB
    assert "database_url" in fields
    # Scheduler
    assert {"daily_feed_hour", "daily_feed_minute", "timezone"} <= fields


def test_ac3_assistant_yaml_loaded() -> None:
    """AC3: assistant.yamlの読み込みユーティリティを含む."""
    config = load_assistant_config(Path("config/assistant.yaml"))
    assert config["name"] == "Manabu"
    assert "personality" in config
