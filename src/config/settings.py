"""アプリケーション設定管理
仕様: docs/specs/overview.md
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, model_validator
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
    feed_collect_days: int = Field(default=7, ge=1)  # 収集対象の日数（これより古い記事はスキップ）

    # Database
    database_url: str = "sqlite+aiosqlite:///./ai_assistant.db"

    # Environment
    env_name: str = ""

    # MCP
    mcp_enabled: bool = False
    mcp_servers_config: str = "config/mcp_servers.json"

    # Thread History
    thread_history_limit: int = Field(default=20, ge=1, le=100)

    # RAG / Embedding
    rag_enabled: bool = False
    embedding_provider: Literal["local", "online"] = "local"
    embedding_model_local: str = "nomic-embed-text"
    embedding_model_online: str = "text-embedding-3-small"
    chromadb_persist_dir: str = "./chroma_db"
    rag_chunk_size: int = Field(default=500, ge=1)
    rag_chunk_overlap: int = Field(default=50, ge=0)
    rag_retrieval_count: int = Field(default=5, ge=1)
    rag_max_crawl_pages: int = Field(default=50, ge=1)
    rag_crawl_delay_sec: float = Field(default=1.0, ge=0)
    rag_similarity_threshold: float | None = Field(default=None, ge=0.0, le=2.0)  # cosine距離閾値

    # RAG評価・デバッグ (Phase 1)
    rag_debug_log_enabled: bool = False  # 本番ではPII漏洩リスクのためデフォルト無効
    rag_show_sources: bool = False

    # RAGハイブリッド検索 (Phase 2)
    rag_hybrid_search_enabled: bool = False  # ハイブリッド検索の有効/無効
    rag_vector_weight: float = Field(default=0.5, ge=0.0, le=1.0)  # ベクトル検索の重み
    rag_bm25_k1: float = Field(default=1.5, gt=0.0)  # BM25の用語頻度パラメータ
    rag_bm25_b: float = Field(default=0.75, ge=0.0, le=1.0)  # BM25の文書長正規化パラメータ
    rag_rrf_k: int = Field(default=60, ge=1)  # RRFの定数

    # Safe Browsing (URL安全性チェック)
    rag_url_safety_check: bool = False
    google_safe_browsing_api_key: str = ""
    rag_url_safety_cache_ttl: int = Field(default=300, ge=0)  # キャッシュTTL秒 (0=デフォルトTTL使用)
    rag_url_safety_fail_open: bool = True  # API障害時の動作（True: URLを許可, False: URLを拒否）
    rag_url_safety_timeout: float = Field(default=5.0, gt=0)  # APIリクエストタイムアウト秒

    @model_validator(mode="after")
    def validate_chunk_settings(self) -> "Settings":
        """チャンク設定の相関バリデーション."""
        if self.rag_chunk_overlap >= self.rag_chunk_size:
            raise ValueError(
                f"rag_chunk_overlap ({self.rag_chunk_overlap}) must be less than "
                f"rag_chunk_size ({self.rag_chunk_size})"
            )
        return self

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
