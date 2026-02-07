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
    slack_auto_reply_channels: str = ""

    def get_auto_reply_channels(self) -> list[str]:
        """自動返信チャンネルのリストを返す（カンマ区切りを解析）."""
        if not self.slack_auto_reply_channels:
            return []
        return [ch.strip() for ch in self.slack_auto_reply_channels.split(",") if ch.strip()]

    # LLM Provider Selection (global online provider)
    online_llm_provider: Literal["openai", "anthropic"] = "openai"

    # Per-service LLM selection ("local" or "online", default: local)
    chat_llm_provider: Literal["local", "online"] = "local"
    profiler_llm_provider: Literal["local", "online"] = "local"
    topic_llm_provider: Literal["local", "online"] = "local"
    summarizer_llm_provider: Literal["local", "online"] = "local"

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

    # Feed delivery
    feed_articles_per_feed: int = Field(default=10, ge=1)
    feed_card_layout: Literal["vertical", "horizontal"] = "horizontal"
    feed_summarize_timeout: int = Field(default=180, ge=0)  # 要約タイムアウト（秒、0=無制限）

    # Database
    database_url: str = "sqlite+aiosqlite:///./ai_assistant.db"

    # Environment
    env_name: str = ""

    # MCP
    mcp_enabled: bool = False
    mcp_servers_config: str = "config/mcp_servers.json"

    # Thread History
    thread_history_limit: int = Field(default=20, ge=1, le=100)

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
