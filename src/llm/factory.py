"""LLMプロバイダー生成ファクトリ
仕様: docs/specs/overview.md (LLM使い分けルール)
"""

from __future__ import annotations

import logging

from src.config.settings import Settings
from src.llm.anthropic_provider import AnthropicProvider
from src.llm.base import LLMProvider
from src.llm.lmstudio_provider import LMStudioProvider
from src.llm.openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)


def create_online_provider(settings: Settings) -> LLMProvider:
    """設定に応じたオンラインLLMプロバイダーを生成する."""
    if settings.online_llm_provider == "anthropic":
        return AnthropicProvider(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
        )
    return OpenAIProvider(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
    )


def create_local_provider(settings: Settings) -> LMStudioProvider:
    """ローカルLLMプロバイダーを生成する."""
    return LMStudioProvider(
        base_url=settings.lmstudio_base_url,
        model=settings.lmstudio_model,
    )


async def get_provider_with_fallback(
    local: LLMProvider,
    online: LLMProvider,
) -> LLMProvider:
    """ローカル優先で、利用不可ならオンラインにフォールバックする."""
    if await local.is_available():
        return local
    logger.info("Local LLM unavailable, falling back to online provider")
    return online
