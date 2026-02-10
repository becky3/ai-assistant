"""RAGインフラモジュール

仕様: docs/specs/f9-rag-knowledge.md, docs/specs/f9-rag-chunking-hybrid.md

Note:
    chromadbに依存するモジュール（vector_store, hybrid_search, evaluation）は
    遅延インポートされる。直接インポートする場合は個別モジュールから行うこと。
"""

# 外部依存のないモジュール（常にインポート可能）
from src.rag.bm25_index import BM25Index, BM25Result, tokenize_japanese
from src.rag.chunker import chunk_text
from src.rag.content_detector import (
    ContentBlock,
    ContentType,
    detect_content_type,
    split_by_content_type,
)
from src.rag.heading_chunker import HeadingChunk, chunk_by_headings
from src.rag.hybrid_search import (
    HybridSearchEngine,
    HybridSearchResult,
    reciprocal_rank_fusion,
)
from src.rag.table_chunker import TableChunk, chunk_table_data


def __getattr__(name: str) -> object:
    """遅延インポート: chromadb依存モジュールはアクセス時にインポート."""
    if name in ("DocumentChunk", "RetrievalResult", "VectorStore"):
        from src.rag import vector_store
        return getattr(vector_store, name)
    if name in (
        "EvaluationDatasetQuery",
        "EvaluationReport",
        "PrecisionRecallResult",
        "QueryEvaluationResult",
        "calculate_precision_recall",
        "check_negative_sources",
        "evaluate_retrieval",
        "load_evaluation_dataset",
    ):
        from src.rag import evaluation
        return getattr(evaluation, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Chunking
    "chunk_text",
    "chunk_by_headings",
    "chunk_table_data",
    # Content detection
    "ContentType",
    "ContentBlock",
    "detect_content_type",
    "split_by_content_type",
    # Chunk types
    "DocumentChunk",
    "HeadingChunk",
    "TableChunk",
    # Vector store
    "RetrievalResult",
    "VectorStore",
    # BM25
    "BM25Index",
    "BM25Result",
    "tokenize_japanese",
    # Hybrid search
    "HybridSearchEngine",
    "HybridSearchResult",
    "reciprocal_rank_fusion",
    # Evaluation
    "PrecisionRecallResult",
    "QueryEvaluationResult",
    "EvaluationReport",
    "EvaluationDatasetQuery",
    "calculate_precision_recall",
    "check_negative_sources",
    "load_evaluation_dataset",
    "evaluate_retrieval",
]
