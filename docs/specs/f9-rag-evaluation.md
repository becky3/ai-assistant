# F9: RAG評価・可視化機能 (Phase 1)

## 概要

RAG検索結果の可視化とデバッグ支援機能を提供する。検索クエリに対してどのチャンクがマッチしたか、類似度スコアはどの程度かをログ出力し、Slack回答時にソース情報を表示するオプションを追加する。

## 背景

Issue #169 の修正テストで以下の課題が発覚:

- RAG検索で何がマッチしたか確認する手段がない
- 類似度スコアがどの程度でマッチしたか不明
- LLMがRAG検索結果にない情報を生成していないか（ハルシネーション）を検証できない

Phase 1 では「デバッグ・可視化」に焦点を当て、RAG検索結果を開発者とユーザーが確認できる仕組みを導入する。

### 関連Issue

- #173 (RAG検索精度の評価・検証の仕組みを導入)
- #169 (RAG検索結果がチャット回答に反映されない) の派生

## ユーザーストーリー

- 開発者として、RAG検索でどのチャンクがマッチしたかをログで確認したい
- 開発者として、各チャンクの類似度スコア（distance）を確認したい
- ユーザーとして、Slack回答時に参照された情報源を確認したい（オプション）

## 機能仕様

### 1. RAG検索結果のログ出力

`RAGKnowledgeService.retrieve()` 実行時に、検索結果の詳細をログ出力する。

#### ログ出力内容

```
INFO RAG retrieve: query="しれんのしろ アイテム"
INFO RAG result 1: distance=0.234 source="https://example.com/page1"
INFO RAG result 2: distance=0.312 source="https://example.com/page2"
DEBUG RAG result 1 text: "しれんのしろには以下のアイテムがあります..."[:100]
DEBUG RAG result 1 full text: "しれんのしろには以下のアイテムがあります。まず入口で..."
```

- **INFO レベル**: クエリ、各結果の distance・source（PII漏洩リスク軽減のためテキストは含まない）
- **DEBUG レベル**: テキストプレビュー（先頭100文字）、チャンクの全文

#### 設定

```env
# ログ出力の有効/無効（デフォルト: false）
# 注意: true にするとクエリ内容がログに出力されるためPII漏洩リスクあり
RAG_DEBUG_LOG_ENABLED=false
```

- `true`: INFO/DEBUG レベルでログ出力（開発・デバッグ用）
- `false`: ログ出力なし（本番環境推奨）

### 2. Slack回答時のソース情報表示

チャット回答時に、RAG検索で使用したソース情報を回答末尾に追記する。

#### 表示フォーマット

```
（LLMの回答本文）

---
参照元:
• https://example.com/page1
• https://example.com/page2
```

- ユニークなソースURLのみを表示（重複除去）
- 最大表示件数は `RAG_RETRIEVAL_COUNT` に従う

#### 設定

```env
# ソース情報表示の有効/無効（デフォルト: false）
RAG_SHOW_SOURCES=false
```

- `true`: 回答末尾にソース情報を追記
- `false`: ソース情報を表示しない（従来動作）

### 3. retrieve() の戻り値拡張

現在の `retrieve()` はフォーマット済み文字列のみを返しているが、ソース情報表示のために検索結果のメタデータも返す必要がある。

#### 現在の実装

```python
async def retrieve(self, query: str, n_results: int = 5) -> str:
    """フォーマット済みテキストを返す"""
```

#### 拡張後の実装

```python
@dataclass
class RAGRetrievalResult:
    """RAG検索結果."""
    context: str  # フォーマット済みテキスト（システムプロンプト注入用）
    sources: list[str]  # ユニークなソースURLリスト

async def retrieve(self, query: str, n_results: int = 5) -> RAGRetrievalResult:
    """検索結果とソース情報を返す"""
```

## 技術仕様

### 変更ファイル

| ファイル | 変更内容 |
|---------|---------|
| `src/config/settings.py` | `rag_debug_log_enabled`, `rag_show_sources` 設定追加 |
| `src/services/rag_knowledge.py` | `RAGRetrievalResult` データクラス追加、`retrieve()` のログ出力・戻り値拡張 |
| `src/services/chat.py` | `retrieve()` の新しい戻り値に対応、ソース情報を回答に追記 |
| `.env.example` | 新規設定項目追加 |

### 設定 (`src/config/settings.py`)

```python
class Settings(BaseSettings):
    # ... 既存の設定 ...

    # RAG評価・デバッグ (Phase 1)
    rag_debug_log_enabled: bool = True
    rag_show_sources: bool = False
```

### RAGRetrievalResult (`src/services/rag_knowledge.py`)

```python
from dataclasses import dataclass

@dataclass
class RAGRetrievalResult:
    """RAG検索結果.

    Attributes:
        context: フォーマット済みテキスト（システムプロンプト注入用）
        sources: ユニークなソースURLリスト（表示用）
    """
    context: str
    sources: list[str]
```

### retrieve() の実装変更

```python
async def retrieve(self, query: str, n_results: int = 5) -> RAGRetrievalResult:
    """関連知識を検索し、結果を返す.

    Args:
        query: 検索クエリ
        n_results: 返却する結果の最大数

    Returns:
        RAGRetrievalResult: コンテキストとソース情報
    """
    from src.config.settings import get_settings
    settings = get_settings()

    results = await self._vector_store.search(query, n_results=n_results)

    if not results:
        return RAGRetrievalResult(context="", sources=[])

    # デバッグログ出力
    if settings.rag_debug_log_enabled:
        logger.info("RAG retrieve: query=%r", query)
        for i, result in enumerate(results, start=1):
            source_url = result.metadata.get("source_url", "不明")
            text_preview = result.text[:100] + "..." if len(result.text) > 100 else result.text
            logger.info(
                "RAG result %d: distance=%.3f source=%r text=%r",
                i, result.distance, source_url, text_preview
            )
            logger.debug("RAG result %d full text: %r", i, result.text)

    # フォーマット済みテキストを構築
    formatted_parts: list[str] = []
    sources: list[str] = []
    for i, result in enumerate(results, start=1):
        source_url = result.metadata.get("source_url", "不明")
        formatted_parts.append(
            f"--- 参考情報 {i} ---\n出典: {source_url}\n{result.text}"
        )
        if source_url != "不明" and source_url not in sources:
            sources.append(source_url)

    return RAGRetrievalResult(
        context="\n\n".join(formatted_parts),
        sources=sources,
    )
```

### ChatService の変更

```python
async def respond(self, ...) -> str:
    # RAGコンテキスト取得
    rag_context = ""
    rag_sources: list[str] = []
    if self._rag_service:
        try:
            settings = get_settings()
            result = await self._rag_service.retrieve(
                text, n_results=settings.rag_retrieval_count
            )
            rag_context = result.context
            rag_sources = result.sources
        except Exception:
            logger.exception("Failed to retrieve RAG context")

    # ... LLM応答生成 ...

    # ソース情報追記（設定有効時のみ）
    if settings.rag_show_sources and rag_sources:
        sources_text = "\n---\n参照元:\n" + "\n".join(f"• {url}" for url in rag_sources)
        assistant_text += sources_text

    return await self._save_and_return(...)
```

## 受け入れ条件

### ログ出力

- [ ] **AC1**: `RAG_DEBUG_LOG_ENABLED=true` の場合、`retrieve()` 実行時に検索クエリがINFOログに出力されること
- [ ] **AC2**: 各検索結果の distance、source_url、テキスト先頭100文字がINFOログに出力されること
- [ ] **AC3**: 各検索結果の全文がDEBUGログに出力されること
- [ ] **AC4**: `RAG_DEBUG_LOG_ENABLED=false` の場合、ログが出力されないこと

### ソース情報表示

- [ ] **AC5**: `RAG_SHOW_SOURCES=true` の場合、Slack回答末尾にソースURLリストが表示されること
- [ ] **AC6**: ソースURLは重複なく表示されること
- [ ] **AC7**: `RAG_SHOW_SOURCES=false` の場合、ソース情報が表示されないこと（従来動作）

### 後方互換性

- [ ] **AC8**: 新設定のデフォルト値により、既存の動作に影響がないこと（`rag_show_sources=false`）
- [ ] **AC9**: RAG無効時（`rag_enabled=false`）は新機能が動作しないこと

## テスト方針

### ユニットテスト

| テストファイル | テスト | 対応AC |
|--------------|--------|--------|
| `tests/test_rag_knowledge.py` | `test_ac1_retrieve_logs_query` | AC1 |
| `tests/test_rag_knowledge.py` | `test_ac2_retrieve_logs_results` | AC2 |
| `tests/test_rag_knowledge.py` | `test_ac3_retrieve_logs_full_text_debug` | AC3 |
| `tests/test_rag_knowledge.py` | `test_ac4_retrieve_no_log_when_disabled` | AC4 |
| `tests/test_rag_knowledge.py` | `test_ac5_retrieve_returns_sources` | AC5 |
| `tests/test_rag_knowledge.py` | `test_ac6_sources_are_unique` | AC6 |

### 統合テスト

| テストファイル | テスト | 対応AC |
|--------------|--------|--------|
| `tests/test_rag_knowledge.py` | `test_ac5_chat_shows_sources` | AC5 |
| `tests/test_rag_knowledge.py` | `test_ac7_chat_hides_sources_when_disabled` | AC7 |
| `tests/test_rag_knowledge.py` | `test_ac8_backward_compatible` | AC8 |
| `tests/test_rag_knowledge.py` | `test_ac9_no_effect_when_rag_disabled` | AC9 |

### テスト戦略

- `caplog` fixture を使用してログ出力を検証
- `monkeypatch` で設定値を切り替え
- `RAGKnowledgeService` の `VectorStore` をモック化して検索結果を制御

## 関連ファイル

### 変更ファイル

| ファイル | 変更内容 |
|---------|---------|
| `src/config/settings.py` | `rag_debug_log_enabled`, `rag_show_sources` 設定追加 |
| `src/services/rag_knowledge.py` | `RAGRetrievalResult` 追加、`retrieve()` 拡張 |
| `src/services/chat.py` | ソース情報追記ロジック |
| `.env.example` | 新規設定項目追加 |

### 参照ファイル

| ファイル | 参照理由 |
|---------|---------|
| `src/rag/vector_store.py` | `RetrievalResult.distance` の使用 |
| `docs/specs/f9-rag-knowledge.md` | 基盤となるRAG機能の仕様 |

## 将来の拡張 (Phase 2以降)

- **Phase 2**: 評価メトリクス（Precision/Recall計測、Ground Truthとの比較）
- **Phase 3**: 自動評価パイプライン（CI/CDでのRAG精度テスト）
