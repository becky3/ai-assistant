"""LLMプロバイダー生成ファクトリ
仕様: docs/specs/overview.md (LLM使い分けルール)
"""

from __future__ import annotations

from typing import Literal

from src.config.settings import Settings, resolve_secret
from src.llm.anthropic_provider import AnthropicProvider
from src.llm.base import LLMProvider
from src.llm.lmstudio_provider import LMStudioProvider
from src.llm.openai_provider import OpenAIProvider


def create_online_provider(settings: Settings) -> LLMProvider:
    """設定に応じたオンラインLLMプロバイダーを生成する."""
    if settings.online_llm_provider == "anthropic":
        return AnthropicProvider(
            api_key=resolve_secret("ANTHROPIC_API_KEY"),
            model=settings.anthropic_model,
        )
    return OpenAIProvider(
        api_key=resolve_secret("OPENAI_API_KEY"),
        model=settings.openai_model,
    )


def create_local_provider(settings: Settings) -> LMStudioProvider:
    """ローカルLLMプロバイダーを生成する."""
    return LMStudioProvider(
        base_url=settings.lmstudio_base_url,
        model=settings.lmstudio_model,
    )


def get_provider_for_service(
    settings: Settings,
    service_llm_setting: Literal["local", "online"],
) -> LLMProvider:
    """サービスごとの設定に基づいてLLMプロバイダーを返す.

    Args:
        settings: アプリケーション設定
        service_llm_setting: サービスごとのLLM設定（"local" or "online"）

    Returns:
        対応するLLMプロバイダー
    """
    if service_llm_setting == "online":
        return create_online_provider(settings)
    return create_local_provider(settings)
