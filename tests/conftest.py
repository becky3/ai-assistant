"""テスト共通フィクスチャ."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings の必須環境依存値をテスト用のデフォルトで設定する.

    Phase3 (#781) でデフォルト値を廃止したため、テスト実行時に
    環境変数が未設定だと ValidationError になる。
    """
    defaults = {
        "SLACK_NEWS_CHANNEL_ID": "",
        "SLACK_AUTO_REPLY_CHANNELS": "",
        "LMSTUDIO_BASE_URL": "http://localhost:1234",
        "DATABASE_URL": "sqlite+aiosqlite:///./test.db",
        "ENV_NAME": "",
        "MCP_ENABLED": "false",
        "MCP_SERVERS_CONFIG": "config/mcp_servers.json",
        "LOG_LEVEL": "INFO",
    }
    for key, value in defaults.items():
        monkeypatch.setenv(key, value)
