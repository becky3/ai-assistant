"""アプリケーション設定管理
仕様: docs/specs/infrastructure/config-management.md

設定値はセキュリティレベルに応じて3層に分離し、各値の取得元を明確にする:
- シークレット: OS セキュアストレージ (keyring) — resolve_secret() で取得
- 環境依存値: .env（_EnvLoader）
- 共通設定値: config/config.toml
"""

from __future__ import annotations

import functools
import logging
import os
import tomllib
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from py_common_lib.secrets import SecretNotFoundError, SecretStoreError, get_secret

logger = logging.getLogger(__name__)

DEFAULT_LMSTUDIO_BASE_URL = "http://localhost:1234"

_SERVICE_NAME = "ai-assistant"
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_TOML_FILE = _PROJECT_ROOT / "config" / "config.toml"


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


class _EnvLoader(BaseSettings):
    """環境依存設定のローダー（内部用）.

    .env および環境変数から、デプロイ先・マシンごとに異なる値を取得する。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Slack（CLI実行時は空文字列で動作）
    slack_news_channel_id: str = ""
    slack_auto_reply_channels: str = ""

    # LM Studio 接続先
    lmstudio_base_url: str

    # Database
    database_url: str

    # Environment（未指定時は空＝非表示）
    env_name: str = ""

    # MCP
    mcp_enabled: bool = False
    mcp_servers_config: str = "config/mcp_servers.json"

    # Logging
    log_level: str = "INFO"


# .env 管理フィールド名の集合（重複検出に使用）
_ENV_FIELD_NAMES = frozenset(_EnvLoader.model_fields.keys())


class Settings(BaseModel):
    """アプリケーション統合設定.

    仕様: docs/specs/infrastructure/config-management.md

    各設定値の取得元:
    - 環境依存値(.env): slack_news_channel_id, lmstudio_base_url 等
    - 共通設定値(config.toml): online_llm_provider, feed_articles_per_feed 等
    """

    # --- .env から取得（環境依存値） ---
    slack_news_channel_id: str
    slack_auto_reply_channels: str
    lmstudio_base_url: str
    database_url: str
    env_name: str
    mcp_enabled: bool
    mcp_servers_config: str
    log_level: str

    def get_auto_reply_channels(self) -> list[str]:
        """自動返信チャンネルのリストを返す（カンマ区切りを解析）."""
        if not self.slack_auto_reply_channels:
            return []
        return [ch.strip() for ch in self.slack_auto_reply_channels.split(",") if ch.strip()]

    # --- config.toml から取得（共通設定値、config.toml 不存在時はデフォルトで動作） ---

    # LLM
    online_llm_provider: Literal["openai", "anthropic"] = "openai"
    chat_llm_provider: Literal["local", "online"] = "local"
    profiler_llm_provider: Literal["local", "online"] = "local"
    topic_llm_provider: Literal["local", "online"] = "local"
    summarizer_llm_provider: Literal["local", "online"] = "local"
    openai_model: str = "gpt-4o-mini"
    anthropic_model: str = "claude-3-5-sonnet-20241022"
    lmstudio_model: str = "local-model"

    # App
    timezone: str = "Asia/Tokyo"

    # Feed
    feed_articles_per_feed: int = Field(default=10, ge=1)
    feed_card_layout: Literal["vertical", "horizontal"] = "horizontal"
    feed_summarize_timeout: int = Field(default=180, ge=0)
    feed_collect_days: int = Field(default=7, ge=1)

    # Thread
    thread_history_limit: int = Field(default=20, ge=1, le=100)

    # RAG
    rag_show_sources: bool = False


# TOML セクション → Settings フィールド名のマッピング
_TOML_KEY_MAP: dict[str, dict[str, str]] = {
    "llm": {
        "online_llm_provider": "online_llm_provider",
        "chat_llm_provider": "chat_llm_provider",
        "profiler_llm_provider": "profiler_llm_provider",
        "topic_llm_provider": "topic_llm_provider",
        "summarizer_llm_provider": "summarizer_llm_provider",
        "openai_model": "openai_model",
        "anthropic_model": "anthropic_model",
        "lmstudio_model": "lmstudio_model",
    },
    "app": {
        "timezone": "timezone",
    },
    "feed": {
        "articles_per_feed": "feed_articles_per_feed",
        "card_layout": "feed_card_layout",
        "summarize_timeout": "feed_summarize_timeout",
        "collect_days": "feed_collect_days",
    },
    "thread": {
        "history_limit": "thread_history_limit",
    },
    "rag": {
        "show_sources": "rag_show_sources",
    },
}


def _load_toml_config() -> dict[str, Any]:
    """config.toml を読み込み、Settings フィールド名にフラット化する.

    仕様: config.toml が存在しない場合は空 dict を返す（デフォルト値で動作）。
    """
    if not _TOML_FILE.exists():
        return {}
    with open(_TOML_FILE, "rb") as f:
        data: dict[str, Any] = tomllib.load(f)

    # config.toml に環境依存値が混入していないか検証
    all_toml_keys: set[str] = set()
    for section_data in data.values():
        if isinstance(section_data, dict):
            all_toml_keys.update(section_data.keys())
    env_overlap = all_toml_keys & _ENV_FIELD_NAMES
    if env_overlap:
        msg = (
            f"config.toml に環境依存設定が含まれています（.env に移動してください）: "
            f"{sorted(env_overlap)}"
        )
        raise ValueError(msg)

    # セクション構造を Settings フィールド名にフラット化
    flat: dict[str, Any] = {}
    for section, key_map in _TOML_KEY_MAP.items():
        section_data = data.get(section, {})
        for toml_key, field_name in key_map.items():
            if toml_key in section_data:
                flat[field_name] = section_data[toml_key]
    return flat


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """キャッシュ付きでSettingsインスタンスを返す.

    .env から環境依存値、config/config.toml から共通設定値を取得し、
    統合した Settings を返す。
    """
    toml_data = _load_toml_config()
    env_loader = _EnvLoader()  # type: ignore[call-arg]  # pydantic-settings が .env/環境変数から読み込み
    # 優先順位: 環境変数(.env) > config.toml > デフォルト値
    # 共通設定値も環境変数で上書き可能（デバッグ・CI用）
    merged = {**toml_data, **env_loader.model_dump()}
    # 環境変数に共通設定値のキーがあれば上書き
    for field_name in Settings.model_fields:
        env_key = field_name.upper()
        env_val = os.environ.get(env_key)
        if env_val is not None and field_name not in _ENV_FIELD_NAMES:
            merged[field_name] = env_val
    return Settings(**merged)


def load_assistant_config(path: str | Path = "config/assistant.yaml") -> dict[str, Any]:
    """assistant.yaml を読み込んで辞書として返す."""
    with open(path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)
    return data
