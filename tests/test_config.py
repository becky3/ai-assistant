"""設定管理のテスト (Issue #2)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from py_common_lib.secrets import SecretNotFoundError, SecretStoreError

from src.config.settings import Settings, load_assistant_config, resolve_secret


def test_settings_loads_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """pydantic-settingsで.envから設定値を読み込める."""
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
    monkeypatch.setenv("ONLINE_LLM_PROVIDER", "anthropic")

    s = Settings()
    assert s.database_url == "sqlite+aiosqlite:///./test.db"
    assert s.online_llm_provider == "anthropic"


def test_all_config_sections_present() -> None:
    """Settings にシークレット以外の設定項目を網羅."""
    fields = set(Settings.model_fields.keys())
    # OpenAI (モデル名のみ、API キーは resolve_secret 経由)
    assert "openai_model" in fields
    # Anthropic (モデル名のみ、API キーは resolve_secret 経由)
    assert "anthropic_model" in fields
    # LM Studio
    assert {"lmstudio_base_url", "lmstudio_model"} <= fields
    # DB
    assert "database_url" in fields
    # Timezone
    assert "timezone" in fields
    # シークレットフィールドが Settings から削除されていること
    assert "slack_bot_token" not in fields
    assert "openai_api_key" not in fields
    assert "anthropic_api_key" not in fields


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
    with patch("src.config.settings.dotenv_values", return_value={"SLACK_BOT_TOKEN": "xoxb-dotenv"}):
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
    """assistant.yamlの読み込みユーティリティを含む.

    assistant.yamlはユーザーが自由にカスタマイズするファイルのため、
    具体的な値ではなく構造（必須キーの存在・型）のみ検証する。
    """
    config = load_assistant_config(Path("config/assistant.yaml"))
    assert isinstance(config["name"], str) and config["name"]
    assert isinstance(config["personality"], str) and config["personality"]


# F6: get_auto_reply_channels のテスト
def test_get_auto_reply_channels_empty_string(monkeypatch: pytest.MonkeyPatch) -> None:
    """F6: 空文字列の場合は空リストを返す."""
    monkeypatch.setenv("SLACK_AUTO_REPLY_CHANNELS", "")
    s = Settings()
    assert s.get_auto_reply_channels() == []


def test_get_auto_reply_channels_single_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    """F6: 単一チャンネルIDが正しくパースされる."""
    monkeypatch.setenv("SLACK_AUTO_REPLY_CHANNELS", "C0123456789")
    s = Settings()
    assert s.get_auto_reply_channels() == ["C0123456789"]


def test_get_auto_reply_channels_multiple_channels(monkeypatch: pytest.MonkeyPatch) -> None:
    """F6: カンマ区切りの複数チャンネルIDが正しくパースされる."""
    monkeypatch.setenv("SLACK_AUTO_REPLY_CHANNELS", "C111,C222,C333")
    s = Settings()
    assert s.get_auto_reply_channels() == ["C111", "C222", "C333"]


def test_get_auto_reply_channels_strips_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    """F6: チャンネルID周辺の空白がトリムされる."""
    monkeypatch.setenv("SLACK_AUTO_REPLY_CHANNELS", "  C111 , C222  ,  C333  ")
    s = Settings()
    assert s.get_auto_reply_channels() == ["C111", "C222", "C333"]


def test_get_auto_reply_channels_filters_empty_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """F6: 空トークン（連続カンマなど）がフィルタリングされる."""
    monkeypatch.setenv("SLACK_AUTO_REPLY_CHANNELS", "C111,,C222,,,C333")
    s = Settings()
    assert s.get_auto_reply_channels() == ["C111", "C222", "C333"]
