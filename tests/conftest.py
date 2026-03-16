"""テスト共通フィクスチャ."""

from __future__ import annotations

import pytest

from src.config.settings import get_settings


@pytest.fixture(autouse=True)
def _env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings の必須環境依存値をテスト用のデフォルトで設定する.

    Phase3 (#781) でデフォルト値を廃止したため、テスト実行時に
    環境変数が未設定だと ValidationError になる。
    get_settings() の lru_cache もクリアし、テスト間の状態共有を防ぐ。
    """
    get_settings.cache_clear()
    defaults = {
        "LMSTUDIO_BASE_URL": "http://localhost:1234",
        "DATABASE_URL": "sqlite+aiosqlite:///./test.db",
    }
    for key, value in defaults.items():
        monkeypatch.setenv(key, value)
