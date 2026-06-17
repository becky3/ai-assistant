"""アプリケーション設定管理
仕様: docs/specs/infrastructure/config-management.md

設定値はセキュリティレベルに応じて3層に分離し、各値の取得元を1つに固定する（フォールバックなし）:
- シークレット: OS セキュアストレージ (keyring) — サービス層で get_secret() を直接呼び出す
- 環境依存値: .env（_EnvLoader）
- 共通設定値: config/config.toml
"""

from __future__ import annotations

import functools
import re
import tomllib
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# REMOTE_CONTROL_REPOSITORIES の key として許可する文字種。
# ファイル名・セッション名にそのまま埋め込まれるため、パストラバーサルを誘発する
# 文字（`/`, `\`, 先頭 `.` 等）を排除する。先頭は英数のみ許容して `..` を弾く
_REMOTE_CONTROL_REPO_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

DEFAULT_LMSTUDIO_BASE_URL = "http://localhost:1234"

SERVICE_NAME = "ai-assistant"
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_TOML_FILE = _PROJECT_ROOT / "config" / "config.toml"


class _EnvLoader(BaseSettings):
    """環境依存設定のローダー（内部用）.

    .env および環境変数から、デプロイ先・マシンごとに異なる値を取得する。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # プラットフォーム選択（slack / discord、デフォルト slack）
    platform: Literal["slack", "discord"] = "slack"

    # Slack（CLI実行時は空文字列で動作）
    slack_news_channel_id: str = ""
    slack_auto_reply_channels: str = ""

    # Discord（PLATFORM=discord 時に使用。Slack のみ運用なら未設定で可）
    discord_news_channel_id: str = ""
    discord_auto_reply_channels: str = ""

    # LM Studio 接続先
    lmstudio_base_url: str

    # Database
    database_url: str

    # Environment（未指定時は空＝非表示）
    env_name: str = ""

    # MCP
    mcp_enabled: bool = False
    mcp_rag_transport: str = "http"
    mcp_rag_url: str = ""

    # Logging
    log_level: str = "INFO"
    debug_log_enabled: bool = False
    log_dir: str = ""

    # RAG 定期更新アカウント（rag update コマンドで使用）
    rag_bluesky_handle: str = ""
    rag_zenn_username: str = ""

    # LLM プロバイダー選択（マシンの LLM 環境に依存）
    online_llm_provider: Literal["openai", "anthropic"]
    chat_llm_provider: Literal["local", "online", "claude"]
    summarizer_llm_provider: Literal["local", "online"]

    # Remote Control 起動（リポジトリパス・許可ユーザーはホスト依存）
    remote_control_allowed_users: str = ""
    remote_control_repositories: str = ""
    remote_control_log_dir: str = ""

    # 記事自動投稿（article-writer リポジトリの絶対パス。空文字なら機能無効）
    article_writer_repo_path: str = ""


# .env 管理フィールド名の集合（重複検出に使用）
_ENV_FIELD_NAMES = frozenset(_EnvLoader.model_fields.keys())


class Settings(BaseModel):
    """アプリケーション統合設定.

    仕様: docs/specs/infrastructure/config-management.md

    各設定値の取得元は1つに固定（フォールバックなし）:
    - 環境依存値(.env): slack_news_channel_id, lmstudio_base_url, chat_llm_provider 等
    - 共通設定値(config.toml): openai_model, feed_articles_per_feed 等
    - シークレットは Settings に含まない（使用箇所で get_secret() を直接呼び出す）
    """

    # --- .env から取得（環境依存値） ---
    platform: Literal["slack", "discord"]
    slack_news_channel_id: str
    slack_auto_reply_channels: str
    discord_news_channel_id: str
    discord_auto_reply_channels: str
    lmstudio_base_url: str
    database_url: str
    env_name: str
    mcp_enabled: bool
    mcp_rag_transport: str
    mcp_rag_url: str
    log_level: str
    debug_log_enabled: bool
    log_dir: str
    rag_bluesky_handle: str
    rag_zenn_username: str
    online_llm_provider: Literal["openai", "anthropic"]
    chat_llm_provider: Literal["local", "online", "claude"]
    summarizer_llm_provider: Literal["local", "online"]
    remote_control_allowed_users: str
    remote_control_repositories: str
    remote_control_log_dir: str
    article_writer_repo_path: str

    def get_auto_reply_channels(self) -> list[str]:
        """Slack 自動返信チャンネルのリストを返す（カンマ区切りを解析）."""
        if not self.slack_auto_reply_channels:
            return []
        return [ch.strip() for ch in self.slack_auto_reply_channels.split(",") if ch.strip()]

    def get_discord_auto_reply_channels(self) -> list[str]:
        """Discord 自動返信チャンネルのリストを返す（カンマ区切りを解析）."""
        if not self.discord_auto_reply_channels:
            return []
        return [
            ch.strip()
            for ch in self.discord_auto_reply_channels.split(",")
            if ch.strip()
        ]

    def get_remote_control_allowed_users(self) -> list[str]:
        """Remote Control を起動可能な Slack user_id のリストを返す."""
        if not self.remote_control_allowed_users:
            return []
        return [
            u.strip()
            for u in self.remote_control_allowed_users.split(",")
            if u.strip()
        ]

    def get_remote_control_repositories(self) -> dict[str, str]:
        """Remote Control の repo-key → 絶対パス対応表を返す.

        書式・検証規則は `_parse_remote_control_repositories` を参照。
        """
        return _parse_remote_control_repositories(self.remote_control_repositories)

    # --- config.toml から取得（共通設定値、config.toml 必須） ---

    # LLM モデル名
    openai_model: str
    anthropic_model: str
    lmstudio_model: str

    # App
    timezone: str

    # Feed
    feed_articles_per_feed: int = Field(ge=1)
    feed_card_layout: Literal["vertical", "horizontal"]
    feed_summarize_timeout: int = Field(ge=0)
    feed_summarize_reasoning_effort: Literal["none", "low", "medium", "high"]
    feed_collect_days: int = Field(ge=1)

    # Thread
    thread_history_limit: int = Field(ge=1, le=100)

    # RAG
    rag_show_sources: bool
    rag_bluesky_max_posts: int = Field(ge=1)  # 定期更新でクロールする BlueSky 投稿数の上限
    rag_zenn_max_articles: int = Field(ge=1)  # 定期更新でクロールする Zenn 記事数の上限

    # Claude CLI（chat_llm_provider="claude" の場合に使用。未指定時はデフォルト値を利用）
    claude_allowed_tools: str = ""
    claude_timeout: int = Field(default=120, ge=1)

    # Logging（ログファイルのローテーション設定）
    log_file_max_bytes: int = Field(ge=1)  # ログファイル1つあたりの最大サイズ

    # Remote Control 起動（共通設定値）
    # 起動後にログから接続 URL を抽出するタイムアウト秒数。
    # 上限はサーバー応答性の悪化（長時間ポーリング）を防ぐためのハードリミット
    remote_control_url_timeout: int = Field(ge=1, le=300)

    # 記事自動投稿（共通設定値）
    # claude -p '/auto-publish-diary' のタイムアウト秒数。
    # 上限は実機 QA 実測 ~13 分を踏まえ、極端な長時間ハングを防ぐためのハードリミット
    article_publish_timeout: int = Field(ge=60, le=3600)

    @field_validator("remote_control_repositories")
    @classmethod
    def _validate_remote_control_repositories(cls, value: str) -> str:
        """起動時に文法検証する（パース成功すれば値はそのまま採用）."""
        _parse_remote_control_repositories(value)
        return value

    @field_validator("article_writer_repo_path")
    @classmethod
    def _validate_article_writer_repo_path(cls, value: str) -> str:
        """起動時に絶対パスのみ許容する（fail-fast）.

        `--dangerously-skip-permissions` 起動の安全性ガードレールとして、
        相対パス指定による意図しないディレクトリでの起動を排除する。
        """
        stripped = value.strip()
        if not stripped:
            return ""
        if not Path(stripped).is_absolute():
            msg = (
                "ARTICLE_WRITER_REPO_PATH は絶対パスで指定してください: "
                f"'{stripped}'"
            )
            raise ValueError(msg)
        return stripped


def _parse_remote_control_repositories(value: str) -> dict[str, str]:
    """`<key>=<path>` カンマ区切り文字列を dict にパースする.

    Settings の起動時バリデータと get_remote_control_repositories() の共通パーサ。
    以下をすべて ValueError として検出する:

    - 区切り文字 `=` 不在
    - 空の key / path
    - 重複 key
    - key に `[A-Za-z0-9._-]` 以外の文字が含まれる（パストラバーサル防止）
    - path が絶対パスでない（fail-fast による意図しないディレクトリでの起動防止）
    """
    if not value:
        return {}
    result: dict[str, str] = {}
    for raw_entry in value.split(","):
        entry = raw_entry.strip()
        if not entry:
            continue
        if "=" not in entry:
            msg = (
                "REMOTE_CONTROL_REPOSITORIES の項目は '<key>=<path>' 形式で記述してください: "
                f"'{entry}'"
            )
            raise ValueError(msg)
        key, path = entry.split("=", 1)
        key = key.strip()
        path = path.strip()
        if not key or not path:
            msg = (
                f"REMOTE_CONTROL_REPOSITORIES の項目に空の key/path が含まれます: '{entry}'"
            )
            raise ValueError(msg)
        if not _REMOTE_CONTROL_REPO_KEY_PATTERN.match(key):
            msg = (
                "REMOTE_CONTROL_REPOSITORIES の key は英数・`.`・`_`・`-` のみ使用できます: "
                f"'{key}'"
            )
            raise ValueError(msg)
        if not Path(path).is_absolute():
            msg = (
                "REMOTE_CONTROL_REPOSITORIES の path は絶対パスで指定してください: "
                f"'{entry}'"
            )
            raise ValueError(msg)
        if key in result:
            msg = f"REMOTE_CONTROL_REPOSITORIES に重複した key があります: '{key}'"
            raise ValueError(msg)
        result[key] = path
    return result


def _load_toml_config() -> dict[str, Any]:
    """config.toml を読み込み、層の重複と未知キーを検証する.

    仕様: config.toml が存在しない場合は FileNotFoundError を送出する。
    """
    if not _TOML_FILE.exists():
        msg = f"config.toml が見つかりません: {_TOML_FILE}"
        raise FileNotFoundError(msg)
    with open(_TOML_FILE, "rb") as f:
        data: dict[str, Any] = tomllib.load(f)

    # config.toml に環境依存値が混入していないか検証
    env_overlap = set(data.keys()) & _ENV_FIELD_NAMES
    if env_overlap:
        msg = (
            f"config.toml に環境依存設定が含まれています（.env に移動してください）: "
            f"{sorted(env_overlap)}"
        )
        raise ValueError(msg)

    # 未知のキーを検証
    toml_field_names = frozenset(Settings.model_fields.keys()) - _ENV_FIELD_NAMES
    unknown = set(data.keys()) - toml_field_names
    if unknown:
        msg = f"config.toml に未知の設定が含まれています: {sorted(unknown)}"
        raise ValueError(msg)

    return data


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """キャッシュ付きでSettingsインスタンスを返す.

    .env から環境依存値、config/config.toml から共通設定値を取得し、
    統合した Settings を返す。
    """
    toml_data = _load_toml_config()
    env_loader = _EnvLoader()  # type: ignore[call-arg]  # pydantic-settings が .env/環境変数から読み込み
    return Settings(**toml_data, **env_loader.model_dump())


def load_assistant_config(path: str | Path = "config/assistant.yaml") -> dict[str, Any]:
    """assistant.yaml を読み込んで辞書として返す."""
    with open(path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)
    return data
