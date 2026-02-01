"""アプリケーション設定管理
仕様: docs/specs/overview.md
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """環境変数から読み込むアプリケーション設定."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Slack
    slack_bot_token: str = ""
    slack_signing_secret: str = ""
    slack_app_token: str = ""
    slack_news_channel_id: str = ""

    # LLM Provider Selection
    online_llm_provider: Literal["openai", "anthropic"] = "openai"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-5-sonnet-20241022"

    # LM Studio (ローカルLLM)
    lmstudio_base_url: str = "http://localhost:1234/v1"
    lmstudio_model: str = "local-model"

    # Scheduler
    daily_feed_hour: int = Field(default=7, ge=0, le=23)
    daily_feed_minute: int = Field(default=0, ge=0, le=59)
    timezone: str = "Asia/Tokyo"

    # Database
    database_url: str = "sqlite+aiosqlite:///./learning_companion.db"

    # Logging
    log_level: str = "INFO"


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """キャッシュ付きでSettingsインスタンスを返す."""
    return Settings()


def load_assistant_config(path: str | Path = "config/assistant.yaml") -> dict[str, Any]:
    """assistant.yaml を読み込んで辞書として返す."""
    with open(path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)
    return data
