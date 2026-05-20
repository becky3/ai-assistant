"""設定管理のテスト (Issue #2)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from src.config.settings import (
    Settings,
    _EnvLoader,
    _load_toml_config,
    load_assistant_config,
)

from .settings_defaults import TEST_SETTINGS_DEFAULTS


def test_settings_has_all_fields() -> None:
    """Settings にシークレット以外の設定項目を網羅."""
    fields = set(Settings.model_fields.keys())
    # 環境依存値
    assert {"lmstudio_base_url", "database_url", "mcp_enabled", "online_llm_provider"} <= fields
    # 共通設定値
    assert {"openai_model", "feed_articles_per_feed"} <= fields
    # シークレットフィールドが Settings から削除されていること
    assert "slack_bot_token" not in fields
    assert "openai_api_key" not in fields


def test_settings_from_defaults() -> None:
    """TEST_SETTINGS_DEFAULTS で Settings を生成できる."""
    s = Settings(**TEST_SETTINGS_DEFAULTS)
    assert s.database_url == "sqlite+aiosqlite:///./test.db"
    assert s.online_llm_provider == "openai"
    assert s.feed_articles_per_feed == 10


def test_settings_no_defaults_for_toml_fields() -> None:
    """共通設定値フィールドにデフォルト値がないこと."""
    from src.config.settings import _ENV_FIELD_NAMES

    # Claude CLI 用フィールド（デフォルト値あり、claude モード時に使用）
    _CLAUDE_CLI_FIELDS = {"claude_allowed_tools", "claude_timeout"}

    for name, field_info in Settings.model_fields.items():
        if name not in _ENV_FIELD_NAMES and name not in _CLAUDE_CLI_FIELDS:
            assert field_info.is_required(), (
                f"Settings.{name} にデフォルト値があります（config.toml 必須のため不要）"
            )


def test_get_settings_loads_from_env_and_toml(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_settings() が .env と config.toml から統合して読み込める."""
    from src.config.settings import get_settings

    # .env.example は主要動作環境 (Windows) 形式の絶対パス (C:/...) を持つ。
    # Linux/macOS では Path("C:/...").is_absolute() が False を返し
    # _validate_remote_control_repositories の絶対パス判定で弾かれるため、
    # POSIX 互換の絶対パスにオーバーライドする。
    if sys.platform != "win32":
        monkeypatch.setenv(
            "REMOTE_CONTROL_REPOSITORIES",
            "ai-assistant=/path/to/ai-assistant,agent-commons=/path/to/agent-commons",
        )
        monkeypatch.setenv(
            "ARTICLE_WRITER_REPO_PATH", "/path/to/article-writer",
        )

    # .env の代わりに git 管理されている .env.example を使用
    get_settings.cache_clear()
    with patch.object(_EnvLoader, "model_config", {**_EnvLoader.model_config, "env_file": ".env.example"}):
        settings = get_settings()
    get_settings.cache_clear()
    # .env.example から
    assert settings.lmstudio_base_url
    assert settings.online_llm_provider in ("openai", "anthropic")
    # config.toml から
    assert settings.openai_model


def test_env_example_has_no_empty_values() -> None:
    """`.env.example` の全 KEY=value 行で value が非空であること.

    Issue #837: `.env.example` は新規セットアップ時のテンプレートとして
    各キーで「何を入れるか」「どんなフォーマットか」を読み取れる必要がある。
    将来キー追加時に空欄プレースホルダーが混入することを防ぐためのガードレール。
    """
    env_example_path = Path(".env.example")
    assert env_example_path.is_file(), ".env.example が見つかりません"

    empty_keys = []
    for raw in env_example_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if not value.strip():
            empty_keys.append(key.strip())

    assert not empty_keys, (
        f".env.example の以下のキーが空欄です（フォーマット例の汎用ダミー値を設定してください）: {empty_keys}"
    )


def test_toml_config_loads() -> None:
    """config.toml がフラット構造で正しく読み込まれる."""
    data = _load_toml_config()
    assert "openai_model" in data
    assert "feed_articles_per_feed" in data
    assert "thread_history_limit" in data


def test_toml_missing_raises_file_not_found(tmp_path: Path) -> None:
    """config.toml が存在しない場合は FileNotFoundError."""
    with patch("src.config.settings._TOML_FILE", tmp_path / "nonexistent.toml"):
        with pytest.raises(FileNotFoundError, match="config.toml が見つかりません"):
            _load_toml_config()


def test_toml_env_overlap_raises(tmp_path: Path) -> None:
    """config.toml に環境依存値が含まれる場合はエラー."""
    toml_file = tmp_path / "config.toml"
    toml_file.write_text('lmstudio_base_url = "http://localhost:1234"\n')
    with patch("src.config.settings._TOML_FILE", toml_file):
        with pytest.raises(ValueError, match="環境依存設定が含まれています"):
            _load_toml_config()


def test_toml_unknown_key_raises(tmp_path: Path) -> None:
    """config.toml に未知のキーが含まれる場合はエラー."""
    toml_file = tmp_path / "config.toml"
    toml_file.write_text('unknown_setting = "value"\n')
    with patch("src.config.settings._TOML_FILE", toml_file):
        with pytest.raises(ValueError, match="未知の設定が含まれています"):
            _load_toml_config()


def test_env_loader_fields_match() -> None:
    """_EnvLoader のフィールドが _ENV_FIELD_NAMES と一致すること."""
    from src.config.settings import _ENV_FIELD_NAMES

    assert _ENV_FIELD_NAMES == frozenset(_EnvLoader.model_fields.keys())


def test_assistant_yaml_loaded() -> None:
    """assistant.yamlの読み込みユーティリティを含む."""
    config = load_assistant_config(Path("config/assistant.yaml"))
    assert isinstance(config["name"], str) and config["name"]
    assert isinstance(config["personality"], str) and config["personality"]


# F6: get_auto_reply_channels のテスト
def test_get_auto_reply_channels_empty_string() -> None:
    """F6: 空文字列の場合は空リストを返す."""
    s = Settings(**{**TEST_SETTINGS_DEFAULTS, "slack_auto_reply_channels": ""})
    assert s.get_auto_reply_channels() == []


def test_get_auto_reply_channels_single_channel() -> None:
    """F6: 単一チャンネルIDが正しくパースされる."""
    s = Settings(**{**TEST_SETTINGS_DEFAULTS, "slack_auto_reply_channels": "C0123456789"})
    assert s.get_auto_reply_channels() == ["C0123456789"]


def test_get_auto_reply_channels_multiple_channels() -> None:
    """F6: カンマ区切りの複数チャンネルIDが正しくパースされる."""
    s = Settings(**{**TEST_SETTINGS_DEFAULTS, "slack_auto_reply_channels": "C111,C222,C333"})
    assert s.get_auto_reply_channels() == ["C111", "C222", "C333"]


def test_get_auto_reply_channels_strips_whitespace() -> None:
    """F6: チャンネルID周辺の空白がトリムされる."""
    s = Settings(
        **{**TEST_SETTINGS_DEFAULTS, "slack_auto_reply_channels": "  C111 , C222  ,  C333  "}
    )
    assert s.get_auto_reply_channels() == ["C111", "C222", "C333"]


def test_get_auto_reply_channels_filters_empty_tokens() -> None:
    """F6: 空トークン（連続カンマなど）がフィルタリングされる."""
    s = Settings(
        **{**TEST_SETTINGS_DEFAULTS, "slack_auto_reply_channels": "C111,,C222,,,C333"}
    )
    assert s.get_auto_reply_channels() == ["C111", "C222", "C333"]


def test_remote_control_repositories_rejects_invalid_key_chars() -> None:
    """REMOTE_CONTROL_REPOSITORIES: key に英数._- 以外を含むと ValueError."""
    with pytest.raises(ValueError, match="英数・"):
        Settings(
            **{
                **TEST_SETTINGS_DEFAULTS,
                "remote_control_repositories": "ai/assistant=/abs/path",
            },
        )


def test_remote_control_repositories_rejects_path_traversal_key() -> None:
    """REMOTE_CONTROL_REPOSITORIES: key に `..` を含むと ValueError."""
    with pytest.raises(ValueError, match="英数・"):
        Settings(
            **{
                **TEST_SETTINGS_DEFAULTS,
                "remote_control_repositories": "..=/abs/path",
            },
        )


def test_remote_control_repositories_rejects_relative_path() -> None:
    """REMOTE_CONTROL_REPOSITORIES: path が絶対パスでないと ValueError."""
    with pytest.raises(ValueError, match="絶対パス"):
        Settings(
            **{
                **TEST_SETTINGS_DEFAULTS,
                "remote_control_repositories": "ai-assistant=relative/path",
            },
        )


def test_remote_control_repositories_accepts_valid_entries() -> None:
    """REMOTE_CONTROL_REPOSITORIES: 制約を満たす key/path はパースされる."""
    import os

    abs_path = "C:/abs/path" if os.name == "nt" else "/abs/path"
    s = Settings(
        **{
            **TEST_SETTINGS_DEFAULTS,
            "remote_control_repositories": f"ai-assistant={abs_path}",
        },
    )
    assert s.get_remote_control_repositories() == {"ai-assistant": abs_path}


def test_article_writer_repo_path_accepts_absolute_path() -> None:
    """ARTICLE_WRITER_REPO_PATH: 絶対パスは受け入れる."""
    import os

    abs_path = "C:/abs/article-writer" if os.name == "nt" else "/abs/article-writer"
    s = Settings(
        **{
            **TEST_SETTINGS_DEFAULTS,
            "article_writer_repo_path": abs_path,
        },
    )
    assert s.article_writer_repo_path == abs_path


def test_article_writer_repo_path_accepts_empty_for_disable() -> None:
    """ARTICLE_WRITER_REPO_PATH: 空文字は機能無効として受け入れる."""
    s = Settings(
        **{
            **TEST_SETTINGS_DEFAULTS,
            "article_writer_repo_path": "",
        },
    )
    assert s.article_writer_repo_path == ""


def test_article_writer_repo_path_normalizes_whitespace_to_empty() -> None:
    """ARTICLE_WRITER_REPO_PATH: 空白のみの値は空文字に正規化される."""
    s = Settings(
        **{
            **TEST_SETTINGS_DEFAULTS,
            "article_writer_repo_path": "   ",
        },
    )
    assert s.article_writer_repo_path == ""


def test_article_writer_repo_path_rejects_relative_path() -> None:
    """ARTICLE_WRITER_REPO_PATH: 相対パスは ValueError で拒否される（4 段防御のうち層 4）."""
    import pydantic

    with pytest.raises(pydantic.ValidationError, match="絶対パス"):
        Settings(
            **{
                **TEST_SETTINGS_DEFAULTS,
                "article_writer_repo_path": "../article-writer",
            },
        )
