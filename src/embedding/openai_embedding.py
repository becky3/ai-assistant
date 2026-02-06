"""OpenAI Embeddings APIプロバイダー
仕様: docs/specs/f9-rag-knowledge.md
"""

from __future__ import annotations

import logging

from openai import AsyncOpenAI

from src.embedding.base import EmbeddingProvider

logger = logging.getLogger(__name__)


class OpenAIEmbedding(EmbeddingProvider):
    """OpenAI Embeddings APIを使用するプロバイダー.

    仕様: docs/specs/f9-rag-knowledge.md
    """

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """テキストリストをベクトルリストに変換する."""
        response = await self._client.embeddings.create(
            model=self._model,
            input=texts,
        )
        return [item.embedding for item in response.data]

    async def is_available(self) -> bool:
        """APIキーの存在で利用可能性を判定する."""
        return bool(self._client.api_key)
