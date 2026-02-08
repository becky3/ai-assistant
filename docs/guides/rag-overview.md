# RAGシステム概要

このドキュメントでは、本プロジェクトで実装されている **RAG (Retrieval-Augmented Generation)** システムの仕組みを解説します。

## RAGとは

RAGは「検索拡張生成」と呼ばれる技術で、LLM（大規模言語モデル）の回答精度を向上させる手法です。

```mermaid
graph LR
    Q[ユーザーの質問] --> R[関連情報を検索]
    R --> A[検索結果 + 質問をLLMに渡す]
    A --> O[より正確な回答]
```

### なぜRAGが必要なのか

LLMには以下の限界があります：

| 課題 | RAGによる解決 |
|------|---------------|
| 学習データ以降の情報を知らない | 最新のドキュメントを検索して補完 |
| 社内固有の情報を知らない | 社内ナレッジを検索して補完 |
| 回答の根拠が不明確 | 出典URLを明示できる |

## システム全体像

```mermaid
flowchart TB
    subgraph Ingest["知識取り込み (Ingest)"]
        URL[URL] --> Crawler[WebCrawler]
        Crawler --> HTML[HTML取得]
        HTML --> Text[テキスト抽出]
        Text --> Chunker[Chunker]
        Chunker --> Chunks[チャンク分割]
        Chunks --> Embedding1[Embedding生成]
        Embedding1 --> Store[(ChromaDB)]
    end

    subgraph Retrieve["知識検索 (Retrieve)"]
        Query[ユーザーの質問] --> Embedding2[Embedding生成]
        Embedding2 --> Search[類似度検索]
        Store --> Search
        Search --> Results[関連チャンク]
    end

    subgraph Generate["回答生成 (Generate)"]
        Results --> Prompt[システムプロンプトに注入]
        Query --> Prompt
        Prompt --> LLM[LLM]
        LLM --> Answer[回答]
    end
```

## コンポーネント詳細

### 1. WebCrawler（Webクローラー）

**役割**: 指定されたURLからWebページを取得し、テキストを抽出する

```mermaid
flowchart LR
    URL --> Validate{URL検証}
    Validate -->|OK| Fetch[HTTP取得]
    Validate -->|NG| Reject[拒否]
    Fetch --> Parse[HTML解析]
    Parse --> Extract[本文抽出]
    Extract --> Clean[クリーンアップ]
```

**主な機能**:

- SSRF対策（許可ドメインのホワイトリスト）
- リダイレクト追従の無効化（セキュリティ）
- 本文領域の自動特定（`<article>` → `<main>` → `<body>`）
- 不要タグの除去（`<script>`, `<style>`, `<nav>`等）

**ファイル**: `src/services/web_crawler.py`

---

### 2. Chunker（チャンカー）

**役割**: 長いテキストを検索に適したサイズに分割する

```mermaid
flowchart TD
    Text[テキスト] --> Size{サイズ確認}
    Size -->|小さい| Single[そのまま1チャンク]
    Size -->|大きい| Split[分割処理]
    Split --> Para[段落で分割]
    Para --> Sent[文で分割]
    Sent --> Char[文字数で分割]
    Para & Sent & Char --> Merge[マージ処理]
    Merge --> Overlap[オーバーラップ付与]
```

**なぜ分割が必要か**:

- Embeddingモデルには入力トークン制限がある
- 長すぎるテキストは検索精度が下がる
- 適切なサイズ（500文字程度）で分割すると検索精度が向上

**オーバーラップとは**:

```text
チャンク1: [ああああああああああ]
チャンク2:           [ああいいいいいいいい]  ← 50文字重複
チャンク3:                     [いいうううううううう]
```

文脈の断絶を防ぐため、チャンク間で一部のテキストを重複させます。

**ファイル**: `src/rag/chunker.py`

---

### 3. Embedding（埋め込み）

**役割**: テキストを数値ベクトル（多次元の数値配列）に変換する

```mermaid
flowchart LR
    Text1["Pythonとは"] --> Model[Embeddingモデル]
    Text2["プログラミング言語"] --> Model
    Model --> Vec1["[0.12, -0.34, 0.56, ...]"]
    Model --> Vec2["[0.11, -0.32, 0.58, ...]"]
```

**なぜベクトル化するのか**:

- テキストの「意味」を数値で表現できる
- 意味が近いテキストは、ベクトルも近くなる
- ベクトル間の距離で類似度を計算できる

**対応プロバイダー**:

| プロバイダー | モデル | 特徴 |
|-------------|--------|------|
| ローカル (LM Studio) | nomic-embed-text | 無料、プライバシー重視 |
| OpenAI | text-embedding-3-small | 高精度、API料金発生 |

**ファイル**: `src/embedding/`

---

### 4. VectorStore（ベクトルストア）

**役割**: ベクトル化されたチャンクを保存し、類似検索を行う

```mermaid
flowchart TB
    subgraph Storage["ChromaDB"]
        direction LR
        ID1[ID] --- Vec1[ベクトル] --- Text1[テキスト] --- Meta1[メタデータ]
        ID2[ID] --- Vec2[ベクトル] --- Text2[テキスト] --- Meta2[メタデータ]
        ID3[ID] --- Vec3[ベクトル] --- Text3[テキスト] --- Meta3[メタデータ]
    end

    Query[クエリベクトル] --> Search{コサイン類似度検索}
    Storage --> Search
    Search --> Top[上位N件を返却]
```

**保存されるデータ**:

```python
DocumentChunk(
    id="a1b2c3d4e5f6_0",      # URLハッシュ + チャンク番号
    text="Pythonは...",       # チャンク本文
    metadata={
        "source_url": "https://example.com/python",
        "title": "Python入門",
        "chunk_index": 0,
        "crawled_at": "2024-01-15T10:30:00Z"
    }
)
```

**ファイル**: `src/rag/vector_store.py`

---

### 5. RAGKnowledgeService（オーケストレーター）

**役割**: 上記コンポーネントを統合し、取り込み・検索の一連の処理を提供

```mermaid
flowchart TB
    subgraph Service["RAGKnowledgeService"]
        Ingest[ingest_page / ingest_from_index]
        Retrieve[retrieve]
        Delete[delete_source]
        Stats[get_stats]
    end

    Crawler[WebCrawler] --> Service
    Chunker[Chunker] --> Service
    Store[VectorStore] --> Service

    Service --> Chat[ChatService]
```

**ファイル**: `src/services/rag_knowledge.py`

---

## データフロー詳細

### 知識取り込み (Ingest)

```mermaid
sequenceDiagram
    participant User as ユーザー
    participant Slack as Slack
    participant RAG as RAGKnowledgeService
    participant Crawler as WebCrawler
    participant Chunker as Chunker
    participant VS as VectorStore
    participant Embed as Embedding

    User->>Slack: @bot rag add https://example.com/doc
    Slack->>RAG: ingest_page(url)
    RAG->>Crawler: crawl_page(url)
    Crawler-->>RAG: CrawledPage(url, title, text)
    RAG->>Chunker: chunk_text(text)
    Chunker-->>RAG: ["チャンク1", "チャンク2", ...]
    RAG->>VS: add_documents(chunks)
    VS->>Embed: embed(texts)
    Embed-->>VS: [[0.1, 0.2, ...], ...]
    VS-->>RAG: 保存件数
    RAG-->>Slack: "3チャンクを保存しました"
    Slack-->>User: 完了通知
```

### 知識検索 (Retrieve)

```mermaid
sequenceDiagram
    participant User as ユーザー
    participant Chat as ChatService
    participant RAG as RAGKnowledgeService
    participant VS as VectorStore
    participant Embed as Embedding
    participant LLM as LLM

    User->>Chat: "Pythonのリスト操作について教えて"
    Chat->>RAG: retrieve("Pythonのリスト操作")
    RAG->>VS: search(query)
    VS->>Embed: embed([query])
    Embed-->>VS: クエリベクトル
    VS-->>RAG: [関連チャンク1, 関連チャンク2, ...]
    RAG-->>Chat: フォーマット済みコンテキスト

    Note over Chat: システムプロンプトに<br/>参考情報として注入

    Chat->>LLM: システムプロンプト + 質問
    LLM-->>Chat: 回答
    Chat-->>User: "リストの操作には... (参考情報に基づく回答)"
```

## 技術スタック

| コンポーネント | 技術 | 選定理由 |
|---------------|------|----------|
| ベクトルDB | ChromaDB | 軽量、Python native、永続化対応 |
| Embedding | LM Studio / OpenAI | ローカル/クラウドの選択可能 |
| HTTPクライアント | aiohttp | 非同期対応 |
| HTML解析 | BeautifulSoup | 安定性、機能の豊富さ |

## 設定項目

`.env` ファイルで設定可能な項目：

```bash
# RAG機能の有効/無効
RAG_ENABLED=true

# Embeddingプロバイダー (local / online)
EMBEDDING_PROVIDER=local

# クロール許可ドメイン (SSRF対策)
RAG_ALLOWED_DOMAINS=docs.python.org,example.com

# チャンク設定
RAG_CHUNK_SIZE=500
RAG_CHUNK_OVERLAP=50

# 検索時の返却件数
RAG_RETRIEVAL_COUNT=5
```

## Slackコマンド

```
@bot rag add <URL>              # 単一ページを取り込み
@bot rag crawl <URL> [パターン]  # リンク集から一括取り込み
@bot rag status                 # 統計情報を表示
@bot rag delete <URL>           # 指定URLの知識を削除
```

## 関連ファイル

- 仕様書: `docs/specs/f9-rag-knowledge.md`
- RAGサービス: `src/services/rag_knowledge.py`
- ベクトルストア: `src/rag/vector_store.py`
- チャンカー: `src/rag/chunker.py`
- Webクローラー: `src/services/web_crawler.py`
- Embedding: `src/embedding/`
