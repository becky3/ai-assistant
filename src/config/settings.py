"""アプリケーション設定管理
仕様: docs/specs/infrastructure/config-management.md
"""

from __future__ import annotations

import functools
import logging
import os
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import dotenv_values
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from py_common_lib.secrets import SecretNotFoundError, SecretStoreError, get_secret

logger = logging.getLogger(__name__)

DEFAULT_LMSTUDIO_BASE_URL = "http://localhost:1234"

_SERVICE_NAME = "ai-assistant"


def resolve_secret(key: str) -> str:
    """環境変数 → .env → keyring の優先順位でシークレットを取得する.

    仕様: docs/specs/infrastructure/config-management.md（設定値の解決優先順位）

    os.environ を汚染しないよう、.env は dotenv_values() で直接読み取る。

    Args:
        key: 環境変数名と同一のキー名（例: "SLACK_BOT_TOKEN"）

    Returns:
        取得したシークレット値。未設定の場合は空文字列。
    """
    # 1. シェル環境変数
    value = os.environ.get(key, "")
    if value:
        return value
    # 2. .env ファイル（os.environ を変更せず直接読み取り）
    env_values = dotenv_values()
    value = env_values.get(key) or ""
    if value:
        return value
    # 3. keyring
    try:
        return get_secret(key=key, service=_SERVICE_NAME)
    except SecretNotFoundError:
        return ""
    except SecretStoreError:
        logger.warning("keyring アクセスに失敗しました: key=%s", key, exc_info=True)
        return ""


class Settings(BaseSettings):
    """環境変数から読み込むアプリケーション設定."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Slack（環境依存値: .env で設定）
    slack_news_channel_id: str
    slack_auto_reply_channels: str

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
    openai_model: str = "gpt-4o-mini"

    # Anthropic
    anthropic_model: str = "claude-3-5-sonnet-20241022"

    # LM Studio (ローカルLLM)
    lmstudio_base_url: str
    lmstudio_model: str = "local-model"

    # Timezone
    timezone: str = "Asia/Tokyo"

    # Feed delivery
    feed_articles_per_feed: int = Field(default=10, ge=1)
    feed_card_layout: Literal["vertical", "horizontal"] = "horizontal"
    feed_summarize_timeout: int = Field(default=180, ge=0)  # 要約タイムアウト（秒、0=無制限）
    feed_collect_days: int = Field(default=7, ge=1)  # 収集対象の日数（これより古い記事はスキップ）

    # Database（環境依存値: .env で設定）
    database_url: str

    # Environment（環境依存値: .env で設定）
    env_name: str

    # MCP（環境依存値: .env で設定）
    mcp_enabled: bool
    mcp_servers_config: str
    rag_show_sources: bool = False  # RAG参照元URL表示（デバッグ用）

    # Thread History
    thread_history_limit: int = Field(default=20, ge=1, le=100)

    # Logging（環境依存値: .env で設定）
    log_level: str


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """キャッシュ付きでSettingsインスタンスを返す."""
    return Settings()  # type: ignore[call-arg]  # pydantic-settings が .env/環境変数から読み込み


def load_assistant_config(path: str | Path = "config/assistant.yaml") -> dict[str, Any]:
    """assistant.yaml を読み込んで辞書として返す."""
    with open(path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)
    return data
