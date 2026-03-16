"""設定管理のテスト (Issue #2)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from py_common_lib.secrets import SecretNotFoundError, SecretStoreError

from src.config.settings import (
    Settings,
    _EnvLoader,
    _load_toml_config,
    load_assistant_config,
    resolve_secret,
)

from .settings_defaults import TEST_SETTINGS_DEFAULTS


def test_settings_has_all_fields() -> None:
    """Settings にシークレット以外の設定項目を網羅."""
    fields = set(Settings.model_fields.keys())
    # 環境依存値
    assert {"lmstudio_base_url", "database_url", "mcp_enabled"} <= fields
    # 共通設定値
    assert {"online_llm_provider", "openai_model", "feed_articles_per_feed"} <= fields
    # シークレットフィールドが Settings から削除されていること
    assert "slack_bot_token" not in fields
    assert "openai_api_key" not in fields


def test_settings_from_defaults() -> None:
    """TEST_SETTINGS_DEFAULTS で Settings を生成できる."""
    s = Settings(**TEST_SETTINGS_DEFAULTS)
    assert s.database_url == "sqlite+aiosqlite:///./test.db"
    assert s.online_llm_provider == "openai"
    assert s.feed_articles_per_feed == 10


def test_get_settings_loads_from_env_and_toml() -> None:
    """get_settings() が .env と config.toml から統合して読み込める."""
    from src.config.settings import get_settings

    settings = get_settings()
    # .env から
    assert settings.lmstudio_base_url
    # config.toml から
    assert settings.online_llm_provider in ("openai", "anthropic")


def test_toml_config_loads() -> None:
    """config.toml が正しくフラット化される."""
    data = _load_toml_config()
    assert "online_llm_provider" in data
    assert "feed_articles_per_feed" in data
    assert "thread_history_limit" in data


def test_toml_env_overlap_raises(tmp_path: Path) -> None:
    """config.toml に環境依存値が含まれる場合はエラー."""
    toml_file = tmp_path / "config.toml"
    toml_file.write_text('[bad]\nlmstudio_base_url = "http://localhost:1234"\n')
    with patch("src.config.settings._TOML_FILE", toml_file):
        with pytest.raises(ValueError, match="環境依存設定が含まれています"):
            _load_toml_config()


def test_env_loader_fields_match() -> None:
    """_EnvLoader のフィールドが _ENV_FIELD_NAMES と一致すること."""
    from src.config.settings import _ENV_FIELD_NAMES

    assert _ENV_FIELD_NAMES == frozenset(_EnvLoader.model_fields.keys())


def test_resolve_secret_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_secret は環境変数を優先する."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-from-env")
    assert resolve_secret("SLACK_BOT_TOKEN") == "xoxb-from-env"


def test_resolve_secret_from_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    """環境変数・.env 未設定時は keyring から取得する."""
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    with (
        patch("src.config.settings.dotenv_values", return_value={}),
        patch("src.config.settings.get_secret", return_value="xoxb-from-keyring"),
    ):
        assert resolve_secret("SLACK_BOT_TOKEN") == "xoxb-from-keyring"


def test_resolve_secret_from_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """.env ファイルから取得できる（os.environ は汚染しない）."""
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    with patch(
        "src.config.settings.dotenv_values",
        return_value={"SLACK_BOT_TOKEN": "xoxb-dotenv"},
    ):
        assert resolve_secret("SLACK_BOT_TOKEN") == "xoxb-dotenv"


def test_resolve_secret_returns_empty_when_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """環境変数も .env も keyring もない場合は空文字列を返す."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with (
        patch("src.config.settings.dotenv_values", return_value={}),
        patch("src.config.settings.get_secret", side_effect=SecretNotFoundError("not found")),
    ):
        assert resolve_secret("OPENAI_API_KEY") == ""


def test_resolve_secret_returns_empty_on_store_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """keyring バックエンドアクセス失敗時も空文字列を返す（warning ログ出力）."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with (
        patch("src.config.settings.dotenv_values", return_value={}),
        patch("src.config.settings.get_secret", side_effect=SecretStoreError("backend error")),
    ):
        assert resolve_secret("OPENAI_API_KEY") == ""


def test_resolve_secret_empty_env_falls_through_to_keyring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """環境変数が空文字列の場合は .env → keyring にフォールバックする."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "")
    with (
        patch("src.config.settings.dotenv_values", return_value={}),
        patch("src.config.settings.get_secret", return_value="xoxb-from-keyring"),
    ):
        assert resolve_secret("SLACK_BOT_TOKEN") == "xoxb-from-keyring"


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
