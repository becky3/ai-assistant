"""LLM抽象化層のテスト (Issue #4)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.config.settings import Settings
from src.llm.base import LLMProvider
from src.llm.factory import create_local_provider, create_online_provider, get_provider_with_fallback
from src.llm.lmstudio_provider import LMStudioProvider


def test_ac1_llm_provider_abc_has_complete() -> None:
    """AC1: LLMProvider ABCに async complete(messages) -> LLMResponse を定義."""
    assert hasattr(LLMProvider, "complete")
    assert hasattr(LLMProvider, "is_available")

    # ABC なので直接インスタンス化できない
    with pytest.raises(TypeError):
        LLMProvider()  # type: ignore[abstract]


def test_ac2_three_providers_exist() -> None:
    """AC2: OpenAI/Anthropic/LM Studio の3プロバイダーが存在する."""
    from src.llm.anthropic_provider import AnthropicProvider
    from src.llm.openai_provider import OpenAIProvider

    assert issubclass(OpenAIProvider, LLMProvider)
    assert issubclass(AnthropicProvider, LLMProvider)
    assert issubclass(LMStudioProvider, LLMProvider)


def test_ac3_lmstudio_uses_openai_sdk() -> None:
    """AC3: LM StudioはOpenAI SDKでbase_url変更で対応."""
    provider = LMStudioProvider(base_url="http://localhost:1234/v1")
    assert provider._client.base_url.host == "localhost"


def test_ac4_factory_creates_openai_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC4: ファクトリで設定値からOpenAIプロバイダーを生成できる."""
    monkeypatch.setenv("ONLINE_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    settings = Settings()
    provider = create_online_provider(settings)
    from src.llm.openai_provider import OpenAIProvider
    assert isinstance(provider, OpenAIProvider)


def test_ac4_factory_creates_anthropic_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC4: ファクトリで設定値からAnthropicプロバイダーを生成できる."""
    monkeypatch.setenv("ONLINE_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    settings = Settings()
    provider = create_online_provider(settings)
    from src.llm.anthropic_provider import AnthropicProvider
    assert isinstance(provider, AnthropicProvider)


def test_ac4_factory_creates_local_provider() -> None:
    """AC4: ファクトリでローカルプロバイダーを生成できる."""
    settings = Settings()
    provider = create_local_provider(settings)
    assert isinstance(provider, LMStudioProvider)


async def test_ac5_fallback_to_online_when_local_unavailable() -> None:
    """AC5: ローカル不可時のフォールバック対応."""
    local = AsyncMock(spec=LLMProvider)
    local.is_available.return_value = False
    online = AsyncMock(spec=LLMProvider)
    online.is_available.return_value = True

    result = await get_provider_with_fallback(local, online)
    assert result is online


async def test_ac5_uses_local_when_available() -> None:
    """AC5: ローカル利用可能時はローカルを返す."""
    local = AsyncMock(spec=LLMProvider)
    local.is_available.return_value = True
    online = AsyncMock(spec=LLMProvider)

    result = await get_provider_with_fallback(local, online)
    assert result is local
