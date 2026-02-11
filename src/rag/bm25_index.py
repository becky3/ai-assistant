"""BM25キーワード検索インデックスモジュール

仕様: docs/specs/f9-rag-chunking-hybrid.md
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import fugashi
    import rank_bm25

logger = logging.getLogger(__name__)

# fugashiのインポートを遅延させる（オプショナル依存）
_fugashi_available: bool | None = None
_tagger: "fugashi.Tagger | None" = None


def _get_fugashi_tagger() -> "fugashi.Tagger | None":
    """fugashiのTaggerをシングルトンで取得する."""
    global _fugashi_available, _tagger

    if _fugashi_available is False:
        return None

    if _tagger is not None:
        return _tagger

    try:
        import fugashi

        _tagger = fugashi.Tagger()
        _fugashi_available = True
        logger.info("fugashi tokenizer initialized successfully")
        return _tagger
    except (ImportError, RuntimeError) as e:
        _fugashi_available = False
        logger.warning("fugashi not available, falling back to simple tokenizer: %s", e)
        return None


@dataclass
class BM25Result:
    """BM25検索結果."""

    doc_id: str
    score: float
    text: str


class BM25Index:
    """BM25ベースのキーワード検索インデックス.

    仕様: docs/specs/f9-rag-chunking-hybrid.md
    """

    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        """BM25Indexを初期化する.

        Args:
            k1: 用語頻度の飽和パラメータ（デフォルト: 1.5）
            b: 文書長の正規化パラメータ（デフォルト: 0.75）
        """
        self._k1 = k1
        self._b = b

        # ドキュメントストレージ
        self._documents: dict[str, str] = {}  # id -> text
        self._doc_source_map: dict[str, str] = {}  # id -> source_url

        # BM25インデックス（遅延初期化）
        self._bm25: "rank_bm25.BM25Okapi | None" = None
        self._doc_ids: list[str] = []  # インデックス順序を保持
        self._tokenized_corpus: list[list[str]] = []

        # 再構築フラグ
        self._needs_rebuild = True

    def add_documents(
        self,
        documents: list[tuple[str, str, str]],
    ) -> int:
        """ドキュメントをインデックスに追加する.

        Args:
            documents: (id, text, source_url) のリスト

        Returns:
            追加されたドキュメント数
        """
        added = 0
        updated = 0
        for doc_id, text, source_url in documents:
            if doc_id in self._documents:
                # 既存のドキュメントを更新
                self._documents[doc_id] = text
                self._doc_source_map[doc_id] = source_url
                updated += 1
            else:
                # 新規ドキュメントを追加
                self._documents[doc_id] = text
                self._doc_source_map[doc_id] = source_url
                added += 1

        # 新規追加または更新があった場合はインデックス再構築が必要
        if added > 0 or updated > 0:
            self._needs_rebuild = True
            logger.debug(
                "BM25 index: added %d, updated %d documents", added, updated
            )

        return added

    def search(
        self,
        query: str,
        n_results: int = 10,
    ) -> list[BM25Result]:
        """クエリでキーワード検索を実行する.

        Args:
            query: 検索クエリ
            n_results: 返却する結果の最大数

        Returns:
            BM25Resultのリスト（スコア降順）
        """
        if not self._documents:
            return []

        # 必要に応じてインデックスを再構築
        if self._needs_rebuild:
            self._rebuild_index()

        if self._bm25 is None:
            return []

        # クエリをトークナイズ
        query_tokens = tokenize_japanese(query)
        if not query_tokens:
            return []

        # BM25検索
        scores = self._bm25.get_scores(query_tokens)

        # スコアでソートして上位n_results件を取得
        scored_docs = [
            (self._doc_ids[i], score) for i, score in enumerate(scores) if score > 0
        ]
        scored_docs.sort(key=lambda x: x[1], reverse=True)

        results: list[BM25Result] = []
        for doc_id, score in scored_docs[:n_results]:
            results.append(
                BM25Result(
                    doc_id=doc_id,
                    score=float(score),
                    text=self._documents[doc_id],
                )
            )

        return results

    def delete_by_source(self, source_url: str) -> int:
        """ソースURL指定でドキュメントを削除する.

        Args:
            source_url: 削除するソースURL

        Returns:
            削除されたドキュメント数
        """
        to_delete = [
            doc_id
            for doc_id, url in self._doc_source_map.items()
            if url == source_url
        ]

        for doc_id in to_delete:
            del self._documents[doc_id]
            del self._doc_source_map[doc_id]

        if to_delete:
            self._needs_rebuild = True
            logger.debug(
                "Deleted %d documents from BM25 index (source: %s)",
                len(to_delete),
                source_url,
            )

        return len(to_delete)

    def get_document_count(self) -> int:
        """インデックス内のドキュメント数を返す."""
        return len(self._documents)

    def get_source_url(self, doc_id: str) -> str | None:
        """ドキュメントIDからソースURLを取得する.

        Args:
            doc_id: ドキュメントID

        Returns:
            ソースURL、見つからない場合はNone
        """
        return self._doc_source_map.get(doc_id)

    def _rebuild_index(self) -> None:
        """BM25インデックスを再構築する."""
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            logger.warning("rank-bm25 not installed, BM25 search disabled")
            self._bm25 = None
            self._needs_rebuild = False
            return

        self._doc_ids = list(self._documents.keys())
        self._tokenized_corpus = [
            tokenize_japanese(self._documents[doc_id]) for doc_id in self._doc_ids
        ]

        if self._tokenized_corpus:
            self._bm25 = BM25Okapi(self._tokenized_corpus, k1=self._k1, b=self._b)
        else:
            self._bm25 = None

        self._needs_rebuild = False
        logger.debug("Rebuilt BM25 index with %d documents", len(self._doc_ids))


# ストップワード（日本語の一般的な助詞・助動詞など）
JAPANESE_STOPWORDS = frozenset(
    [
        "の",
        "に",
        "は",
        "を",
        "た",
        "が",
        "で",
        "て",
        "と",
        "し",
        "れ",
        "さ",
        "ある",
        "いる",
        "も",
        "する",
        "から",
        "な",
        "こと",
        "として",
        "い",
        "や",
        "れる",
        "など",
        "なっ",
        "ない",
        "この",
        "ため",
        "その",
        "あっ",
        "よう",
        "また",
        "もの",
        "という",
        "あり",
        "まで",
        "られ",
        "なる",
        "へ",
        "か",
        "だ",
        "これ",
        "によって",
        "により",
        "おり",
        "より",
        "による",
        "ず",
        "なり",
        "られる",
        "において",
        "ば",
        "なかっ",
        "なく",
        "しかし",
        "について",
        "せ",
        "だっ",
        "その他",
        "できる",
        "それ",
        "う",
        "ので",
        "なお",
        "のみ",
        "でき",
        "き",
        "つ",
        "における",
        "および",
        "いう",
        "さらに",
        "でも",
        "ら",
        "たり",
        "その後",
        "ほか",
        "ほど",
        "ます",
        "です",
        "ました",
        "でした",
    ]
)

# 名詞・動詞・形容詞の品詞タグ
INCLUDE_POS = frozenset(["名詞", "動詞", "形容詞", "固有名詞"])


@lru_cache(maxsize=10000)
def tokenize_japanese(text: str) -> list[str]:
    """日本語テキストをトークン化する.

    仕様: docs/specs/f9-rag-chunking-hybrid.md

    - 形態素解析（fugashi/MeCab）を使用（利用可能な場合）
    - 名詞・動詞・形容詞のみ抽出
    - ストップワード除去

    Args:
        text: トークン化するテキスト

    Returns:
        トークンのリスト
    """
    if not text or not text.strip():
        return []

    text = text.strip().lower()

    # fugashiが利用可能な場合は形態素解析を使用
    tagger = _get_fugashi_tagger()
    if tagger is not None:
        return _tokenize_with_fugashi(text, tagger)

    # フォールバック: 簡易トークナイザ
    return _tokenize_simple(text)


def _tokenize_with_fugashi(
    text: str,
    tagger: "fugashi.Tagger",
) -> list[str]:
    """fugashiを使って形態素解析でトークン化する."""
    tokens: list[str] = []

    for word in tagger(text):
        # 品詞情報を取得
        if not word.feature.pos1:
            continue

        pos = word.feature.pos1
        surface = word.surface

        # 名詞・動詞・形容詞のみ抽出
        if pos not in INCLUDE_POS:
            continue

        # ストップワード除去
        if surface in JAPANESE_STOPWORDS:
            continue

        # 1文字の助詞・記号をスキップ
        if len(surface) == 1 and not surface.isalnum():
            continue

        tokens.append(surface)

    return tokens


def _tokenize_simple(text: str) -> list[str]:
    """簡易トークナイザ（fugashiが使えない場合のフォールバック）."""
    # 記号で分割
    tokens = re.split(r"[\s\.,!?、。！？\n\t]+", text)

    # 空トークンとストップワードを除去
    tokens = [
        t.strip()
        for t in tokens
        if t.strip() and t.strip() not in JAPANESE_STOPWORDS and len(t.strip()) > 1
    ]

    return tokens
