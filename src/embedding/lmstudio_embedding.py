"""LM Studio経由のEmbeddingプロバイダー
仕様: docs/specs/f9-rag-knowledge.md
"""

from __future__ import annotations

import logging

from openai import AsyncOpenAI

from src.embedding.base import EmbeddingProvider

logger = logging.getLogger(__name__)


class LMStudioEmbedding(EmbeddingProvider):
    """LM Studio経由のEmbeddingプロバイダー.

    仕様: docs/specs/f9-rag-knowledge.md
    """

    def __init__(
        self,
        base_url: str = "http://localhost:1234/v1",
        model: str = "nomic-embed-text",
    ) -> None:
        self._client = AsyncOpenAI(base_url=base_url, api_key="lm-studio")
        self._model = model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """テキストリストをベクトルリストに変換する."""
        response = await self._client.embeddings.create(
            model=self._model,
            input=texts,
        )
        return [item.embedding for item in response.data]

    async def is_available(self) -> bool:
        """モデル一覧取得で疎通確認する."""
        try:
            await self._client.models.list()
            return True
        except Exception as e:
            logger.debug("LM Studio embedding is not available: %s", e)
            return False
