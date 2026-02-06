# F9: RAGナレッジ機能

## 概要

外部Webページから収集した知識をベクトルDBに蓄積し、ユーザーの質問に関連する情報を自動検索してチャット応答に活用するRAG（Retrieval-Augmented Generation）機能を実装する。

## 背景

- 現在のアシスタントはLLMの学習済み知識とリアルタイムの会話コンテキストのみで応答している
- 特定のWebサイトの情報を知識ベースとして蓄積し、ユーザーの質問に関連する情報を自動的に検索・活用できるようにしたい
- Embeddingモデルはローカル（LM Studio）とオンライン（OpenAI）を切替可能にし、既存のLLM使い分けルールと整合させる
- ChromaDB（SQLiteベース）を採用し、既存プロジェクトの軽量構成と親和させる

### RAGアーキテクチャの概要

```
┌─────────────────────────────────────────────────┐
│              Slack (ユーザーインターフェース)         │
│  rag crawl / rag add / rag status / rag delete  │
└───────────────────────┬─────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────┐
│          RAGKnowledgeService（オーケストレーション）   │
│  - ingest_from_index()  - retrieve()            │
│  - ingest_page()        - get_stats()           │
└──┬──────────────┬───────────────┬───────────────┘
   │              │               │
┌──▼────┐  ┌─────▼──────┐  ┌────▼────────┐
│ Web   │  │ Chunker    │  │ VectorStore │
│Crawler│  │ (テキスト   │  │ (ChromaDB)  │
│       │  │  分割)     │  │             │
└───────┘  └────────────┘  └──────┬──────┘
                                  │
                           ┌──────▼──────┐
                           │ Embedding   │
                           │ Provider    │
                           │ (LM Studio  │
                           │  / OpenAI)  │
                           └─────────────┘
```

**チャット応答時のフロー**:

```
1. ユーザーがSlackで質問
2. ChatService が RAGKnowledgeService.retrieve(質問文) を呼び出し
3. 質問文をEmbedding → ChromaDBで類似チャンク検索
4. 関連知識をシステムプロンプトに付加
5. LLMが関連知識を踏まえて応答を生成
6. 応答をSlackに投稿
```

## ユーザーストーリー

- ユーザーとして、Slackでボットに知識ベースの内容について質問すると、取り込み済みWebページの情報に基づいた回答を得たい
- ユーザーとして、リンク集ページのURLを指定するだけで、配下の記事を一括で知識ベースに取り込みたい
- ユーザーとして、単一のWebページを手軽に知識ベースに追加したい
- ユーザーとして、知識ベースの現在の状態（件数等）を確認したい
- ユーザーとして、不要になった知識をソースURL単位で削除したい
- 管理者として、RAG機能の有効/無効を `.env` で制御したい
- 管理者として、Embeddingプロバイダーをローカルとオンラインで切り替えたい

## 入出力仕様

### Slackコマンド

```
@bot rag crawl <URL> [パターン]  — リンク集ページからクロール＆取り込み
@bot rag add <URL>               — 単一ページ取り込み
@bot rag status                  — ナレッジベース統計表示
@bot rag delete <URL>            — ソースURL指定で削除
```

### 入力例

```
ユーザー: @bot rag crawl https://example.com/articles
ユーザー: @bot rag crawl https://example.com/docs \.html$
ユーザー: @bot rag add https://example.com/guide/getting-started
ユーザー: @bot rag status
ユーザー: @bot rag delete https://example.com/guide/getting-started
```

### 処理フロー（rag crawl）

```
1. ユーザーが @bot rag crawl <URL> [パターン] を送信
2. ハンドラが RAGKnowledgeService.ingest_from_index() を呼び出し
3. WebCrawler がリンク集ページからURLリストを抽出（パターンでフィルタ）
4. WebCrawler が各ページの本文テキストを並行クロール
5. Chunker がテキストをオーバーラップ付きチャンクに分割
6. VectorStore がチャンクをEmbedding → ChromaDBに保存
7. 結果サマリーをSlackに返答
```

### 出力例

```
bot: クロール完了しました。
     取り込みページ数: 15
     チャンク数: 128
     エラー: 2件（タイムアウト）

bot: ナレッジベース統計:
     総チャンク数: 342
     ソースURL数: 20

bot: 削除しました: https://example.com/guide/getting-started (8チャンク)
```

### チャット応答（自動統合）

```
ユーザー: @bot Pythonのasync/awaitについて教えて

（RAGが有効で、関連知識がある場合）
→ システムプロンプトに関連チャンクが自動注入される
→ LLMが取り込み済み知識を踏まえて応答

（RAGが無効、または関連知識がない場合）
→ 従来通りLLMの学習済み知識のみで応答
```

## 技術仕様

### 依存パッケージ

```toml
# pyproject.toml に追加
dependencies = [
    "chromadb>=0.5,<1",
    "beautifulsoup4>=4.12,<5",
]
```

### ディレクトリ構成

```
ai-assistant/
├── src/
│   ├── embedding/                  # Embeddingプロバイダー（新規）
│   │   ├── __init__.py
│   │   ├── base.py                 # EmbeddingProvider 抽象基底クラス
│   │   ├── lmstudio_embedding.py   # LM Studio経由
│   │   ├── openai_embedding.py     # OpenAI Embeddings API
│   │   └── factory.py              # get_embedding_provider()
│   ├── rag/                        # RAGインフラ（新規）
│   │   ├── __init__.py
│   │   ├── chunker.py              # テキストチャンキング
│   │   └── vector_store.py         # ChromaDBラッパー
│   ├── services/
│   │   ├── web_crawler.py          # Webクローラー（新規）
│   │   └── rag_knowledge.py        # RAGナレッジサービス（新規）
│   ├── config/
│   │   └── settings.py             # RAG設定追加
│   └── slack/
│       └── handlers.py             # ragコマンドハンドラ追加
├── tests/
│   ├── test_embedding.py
│   ├── test_chunker.py
│   ├── test_vector_store.py
│   ├── test_web_crawler.py
│   └── test_rag_knowledge.py
└── .env.example                    # RAG設定項目追加
```

### Embeddingプロバイダー (`src/embedding/`)

既存の `LLMProvider` とは入出力が異なるため、独立した `EmbeddingProvider` 階層として実装する。

#### 抽象基底クラス (`src/embedding/base.py`)

```python
class EmbeddingProvider(abc.ABC):
    """Embedding生成の抽象基底クラス.

    仕様: docs/specs/f9-rag-knowledge.md
    """

    @abc.abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """テキストリストをベクトルリストに変換する."""

    @abc.abstractmethod
    async def is_available(self) -> bool:
        """プロバイダーが利用可能かチェックする."""
```

**`LLMProvider` と別階層にする理由**:
- chat completionとembeddingは入出力が根本的に異なる（`Message→str` vs `str→float[]`）
- モデルも別（chat用モデルとembedding用モデル）
- 既存の `LLMProvider` 実装を変更不要

#### LM Studio Embedding (`src/embedding/lmstudio_embedding.py`)

```python
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
        response = await self._client.embeddings.create(
            model=self._model, input=texts,
        )
        return [item.embedding for item in response.data]

    async def is_available(self) -> bool:
        # モデル一覧取得で疎通確認
        ...
```

#### OpenAI Embedding (`src/embedding/openai_embedding.py`)

`AsyncOpenAI(api_key=...)` を使用し、同じインターフェースで OpenAI Embeddings API を呼び出す。

#### ファクトリ関数 (`src/embedding/factory.py`)

```python
def get_embedding_provider(
    settings: Settings,
    provider_setting: Literal["local", "online"],
) -> EmbeddingProvider:
    """設定に応じたEmbeddingプロバイダーを返す.

    - "local": LMStudioEmbedding
    - "online": OpenAIEmbedding
    """
```

既存の `src/llm/factory.py` の `get_provider_for_service()` と同じパターン。

### テキストチャンキング (`src/rag/chunker.py`)

```python
def chunk_text(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> list[str]:
    """テキストをオーバーラップ付きチャンクに分割する.

    仕様: docs/specs/f9-rag-knowledge.md

    分割優先順: 段落 → 文 → 文字数
    外部依存なし（LangChain不要）。
    """
```

- 段落（空行区切り）でまず分割
- 段落が `chunk_size` を超える場合は文（句点区切り）で分割
- それでも超える場合は文字数で分割
- 各チャンクは `chunk_overlap` 文字分オーバーラップさせ、文脈の断絶を軽減

### ChromaDB ベクトルストア (`src/rag/vector_store.py`)

#### データ型

```python
@dataclass
class DocumentChunk:
    """ベクトルストアに格納するチャンク."""
    id: str                           # ユニークID（URLハッシュ + chunk_index）
    text: str                         # チャンク本文
    metadata: dict[str, str | int]    # source_url, title, chunk_index, crawled_at

@dataclass
class RetrievalResult:
    """検索結果."""
    text: str
    metadata: dict[str, str | int]
    distance: float                   # 小さいほど類似度が高い
```

#### VectorStoreクラス

```python
class VectorStore:
    """ChromaDBベースのベクトルストア.

    仕様: docs/specs/f9-rag-knowledge.md
    """

    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        persist_directory: str = "./chroma_db",
        collection_name: str = "knowledge",
    ) -> None:
        self._embedding = embedding_provider
        self._client = chromadb.PersistentClient(path=persist_directory)
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    async def add_documents(self, chunks: list[DocumentChunk]) -> int:
        """チャンクをEmbedding→ベクトルストアに追加. Returns: 追加件数."""

    async def search(self, query: str, n_results: int = 5) -> list[RetrievalResult]:
        """クエリに類似するチャンクを検索する."""

    async def delete_by_source(self, source_url: str) -> int:
        """ソースURL指定でチャンクを削除. Returns: 削除件数."""

    def get_stats(self) -> dict[str, int]:
        """ナレッジベース統計（総チャンク数等）を返す."""
```

**設計ポイント**:
- ChromaDBは同期APIのため `asyncio.to_thread()` でラップ（`feed_collector.py` の `feedparser.parse` と同パターン）
- SQLAlchemyモデルは追加しない（ChromaDB自身がSQLiteに永続化するため）
- Embeddingは `VectorStore` 内で呼び出す（外部から渡す必要なし）

### Webクローラー (`src/services/web_crawler.py`)

```python
@dataclass
class CrawledPage:
    """クロール結果."""
    url: str
    title: str
    text: str          # 抽出済みプレーンテキスト
    crawled_at: str    # ISO 8601 タイムスタンプ

class WebCrawler:
    """Webページクローラー.

    仕様: docs/specs/f9-rag-knowledge.md
    """

    def __init__(self, timeout: float = 30.0) -> None:
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def crawl_index_page(
        self, index_url: str, url_pattern: str = "",
    ) -> list[str]:
        """リンク集ページ内の <a> タグからURLリストを抽出する（深度1のみ、再帰クロールは行わない）.

        Args:
            index_url: リンク集ページのURL
            url_pattern: 正規表現パターンでリンクをフィルタリング（任意）
        """

    async def crawl_page(self, url: str) -> CrawledPage | None:
        """単一ページの本文テキストを取得する. 失敗時は None."""

    async def crawl_pages(self, urls: list[str]) -> list[CrawledPage]:
        """複数ページを並行クロールする."""
```

**HTML本文抽出ロジック（BeautifulSoup4使用）**:
1. `<script>`, `<style>`, `<nav>`, `<header>`, `<footer>` タグを除去
2. `<article>` → `<main>` → `<body>` の優先順で本文領域を特定
3. テキストを抽出してクリーンアップ

**並行制御**:
- `asyncio.Semaphore` で同時接続数を制限（デフォルト: 5）
- 対象サーバーへの負荷を配慮

**エラー耐性**:
- ページ単位で失敗を隔離し、他のページの処理は継続
- 失敗時は `None` を返す（`OgpExtractor` と同パターン）

**既存パターンの再利用**:

| 参照元 | 用途 |
|--------|------|
| `src/services/ogp_extractor.py` — aiohttp + タイムアウト | HTTPクライアントパターン |
| `src/services/ogp_extractor.py` — `errors="replace"` | エラー耐性のあるテキストデコード |
| `src/services/feed_collector.py` — エラー隔離 | ページ単位の try/except + continue |

### RAGナレッジサービス (`src/services/rag_knowledge.py`)

各コンポーネントを統合するオーケストレーションサービス。

```python
class RAGKnowledgeService:
    """RAGナレッジ管理サービス.

    仕様: docs/specs/f9-rag-knowledge.md
    """

    def __init__(
        self,
        vector_store: VectorStore,
        web_crawler: WebCrawler,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ) -> None: ...

    async def ingest_from_index(
        self, index_url: str, url_pattern: str = "",
    ) -> dict[str, int]:
        """リンク集ページから一括取り込み.

        Returns:
            {"pages_crawled": N, "chunks_stored": M, "errors": E}
        """

    async def ingest_page(self, url: str) -> int:
        """単一ページ取り込み.

        同一URLの再取り込み時は、既存チャンクを delete_by_source() で
        削除してから新規追加する（upsert動作）。
        Returns: チャンク数.
        """

    async def retrieve(self, query: str, n_results: int = 5) -> str:
        """関連知識を検索し、フォーマット済みテキストとして返す.

        ChatService から呼ばれる。結果なしの場合は空文字列。
        """

    async def delete_source(self, source_url: str) -> int:
        """ソースURL指定で知識を削除. Returns: 削除チャンク数."""

    async def get_stats(self) -> dict[str, int]:
        """ナレッジベース統計."""
```

**`retrieve()` の出力フォーマット**:

検索結果のチャンクを以下の形式で連結し、1つの文字列として返す:

```
--- 参考情報 1 ---
出典: https://example.com/article1
{chunk_text}

--- 参考情報 2 ---
出典: https://example.com/article2
{chunk_text}
```

結果が0件の場合は空文字列を返す。

**同一URLの再取り込み**:

`ingest_page()` および `ingest_from_index()` で同一URLを再取り込みする場合、既存チャンクを `VectorStore.delete_by_source()` で削除してから新規チャンクを追加する（upsert動作）。これにより、ページ内容の更新に追従できる。

### ChatServiceへの自動統合 (`src/services/chat.py`)

`ThreadHistoryService` や `MCPClientManager` と同じオプショナル注入パターンで統合する。

**変更点**:

```python
class ChatService:
    def __init__(
        self,
        llm: LLMProvider,
        session_factory: async_sessionmaker[AsyncSession],
        system_prompt: str = "",
        thread_history_service: ThreadHistoryService | None = None,
        mcp_manager: MCPClientManager | None = None,
        rag_service: RAGKnowledgeService | None = None,  # 追加
    ) -> None: ...
```

**respond() 内のRAGコンテキスト注入**:

```python
async def respond(self, ...) -> str:
    # RAGコンテキスト取得（オプショナル）
    rag_context = ""
    if self._rag_service:
        try:
            rag_context = await self._rag_service.retrieve(text)
        except Exception:
            logger.exception("Failed to retrieve RAG context")

    # メッセージリスト構築
    messages: list[Message] = []
    if self._system_prompt:
        system_content = self._system_prompt
        if rag_context:
            system_content += (
                "\n\n以下は質問に関連する参考情報です。"
                "回答に役立つ場合は活用してください:\n" + rag_context
            )
        messages.append(Message(role="system", content=system_content))
    # ... 以降は既存フローと同じ
```

- `rag_service=None` 時は既存動作と完全同一（後方互換性）
- RAG検索に失敗した場合は例外をキャッチしてログ出力し、通常応答を継続

### Slackコマンドハンドラ (`src/slack/handlers.py`)

```python
_RAG_KEYWORDS = ("rag",)
```

既存の `feed` コマンドと同じルーティングパターンで `rag` コマンドを追加する。

**コマンド処理**:
- `rag crawl <URL> [パターン]`: `RAGKnowledgeService.ingest_from_index()` を呼び出し
- `rag add <URL>`: `RAGKnowledgeService.ingest_page()` を呼び出し
- `rag status`: `RAGKnowledgeService.get_stats()` を呼び出し
- `rag delete <URL>`: `RAGKnowledgeService.delete_source()` を呼び出し

`register_handlers()` に `rag_service: RAGKnowledgeService | None = None` 引数を追加。

### サービス初期化 (`src/main.py`)

```python
# RAG初期化（有効時のみ） — MCP初期化と同パターン
rag_service: RAGKnowledgeService | None = None
if settings.rag_enabled:
    embedding = get_embedding_provider(settings, settings.embedding_provider)
    vector_store = VectorStore(embedding, settings.chromadb_persist_dir)
    web_crawler = WebCrawler()
    rag_service = RAGKnowledgeService(
        vector_store, web_crawler,
        chunk_size=settings.rag_chunk_size,
        chunk_overlap=settings.rag_chunk_overlap,
    )

# ChatService に注入
chat_service = ChatService(..., rag_service=rag_service)

# register_handlers に注入
handlers_module.register_handlers(..., rag_service=rag_service)
```

### 設定 (`src/config/settings.py`)

```python
class Settings(BaseSettings):
    # ... 既存の設定 ...

    # RAG
    rag_enabled: bool = False
    embedding_provider: Literal["local", "online"] = "local"
    embedding_model_local: str = "nomic-embed-text"
    embedding_model_online: str = "text-embedding-3-small"
    chromadb_persist_dir: str = "./chroma_db"
    rag_chunk_size: int = 500
    rag_chunk_overlap: int = 50
    rag_retrieval_count: int = 5
```

### 環境変数 (`.env`)

```env
# RAG Knowledge
RAG_ENABLED=false
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL_LOCAL=nomic-embed-text
EMBEDDING_MODEL_ONLINE=text-embedding-3-small
CHROMADB_PERSIST_DIR=./chroma_db
RAG_CHUNK_SIZE=500
RAG_CHUNK_OVERLAP=50
RAG_RETRIEVAL_COUNT=5
```

## 受け入れ条件

### Embeddingプロバイダー

- [ ] **AC1**: `EmbeddingProvider` 抽象基底クラスが `embed()` と `is_available()` メソッドを定義すること
- [ ] **AC2**: `LMStudioEmbedding` が LM Studio 経由でテキストをベクトルに変換できること
- [ ] **AC3**: `OpenAIEmbedding` が OpenAI Embeddings API でテキストをベクトルに変換できること
- [ ] **AC4**: `get_embedding_provider()` が `EMBEDDING_PROVIDER` 設定に応じたプロバイダーを返すこと

### テキストチャンキング

- [ ] **AC5**: `chunk_text()` がテキストを指定サイズのチャンクに分割できること
- [ ] **AC6**: チャンク間にオーバーラップが適用されること（`RAG_CHUNK_OVERLAP` で設定可能）
- [ ] **AC7**: 空文字列や短いテキストに対しても正常に動作すること

### ChromaDB ベクトルストア

- [ ] **AC8**: `VectorStore.add_documents()` でチャンクをEmbedding→ChromaDBに保存できること
- [ ] **AC9**: `VectorStore.search()` でクエリに類似するチャンクを検索できること
- [ ] **AC10**: `VectorStore.delete_by_source()` でソースURL指定のチャンクを削除できること
- [ ] **AC11**: `VectorStore.get_stats()` でナレッジベースの統計情報を取得できること

### Webクローラー

- [ ] **AC12**: `WebCrawler.crawl_index_page()` がリンク集ページからURLリストを抽出できること
- [ ] **AC13**: URLパターン（正規表現）によるフィルタリングが機能すること
- [ ] **AC14**: `WebCrawler.crawl_page()` が単一ページの本文テキストを取得できること
- [ ] **AC15**: `WebCrawler.crawl_pages()` が複数ページを並行クロールし、ページ単位のエラーを隔離すること

### RAGナレッジサービス（オーケストレーション）

- [ ] **AC16**: `ingest_from_index()` がリンク集ページから記事を一括クロール→チャンキング→ベクトル保存できること
- [ ] **AC17**: `ingest_page()` が単一ページをクロール→チャンキング→ベクトル保存できること
- [ ] **AC18**: `retrieve()` がクエリに関連するチャンクを検索し、フォーマット済みテキストを返すこと
- [ ] **AC19**: `retrieve()` で結果がない場合は空文字列を返すこと

### ChatServiceへの自動統合

- [ ] **AC20**: RAG有効時、チャット応答に関連知識がシステムプロンプトとして自動注入されること
- [ ] **AC21**: RAG無効時（`rag_enabled=False`）は従来通りの動作をすること（後方互換性）
- [ ] **AC22**: RAG検索に失敗した場合、エラーログを出力し通常応答を継続すること

### Slackコマンド

- [ ] **AC23**: `rag crawl <URL> [パターン]` でリンク集ページからの一括取り込みができること
- [ ] **AC24**: `rag add <URL>` で単一ページの取り込みができること
- [ ] **AC25**: `rag status` でナレッジベースの統計が表示されること
- [ ] **AC26**: `rag delete <URL>` でソースURL指定の削除ができること

### 設定

- [ ] **AC27**: `RAG_ENABLED` 環境変数でRAG機能のON/OFFを制御できること
- [ ] **AC28**: `EMBEDDING_PROVIDER` で `local` / `online` を切り替えられること
- [ ] **AC29**: チャンクサイズ・オーバーラップ・検索件数が環境変数で設定可能であること

## 使用LLMプロバイダー

| タスク | プロバイダー | 理由 |
|--------|-------------|------|
| Embedding生成 | ローカル (LM Studio + `nomic-embed-text`) またはオンライン (OpenAI `text-embedding-3-small`) | `EMBEDDING_PROVIDER` で切替 |
| チャット応答生成 | 既存の `ChatService` 設定に従う | RAG固有のLLM設定は不要 |
| Webクロール・チャンキング | なし | LLM不要（テキスト処理のみ） |

## 新規ファイル一覧

| ファイル | 用途 |
|---------|------|
| `src/embedding/__init__.py` | Embeddingモジュール |
| `src/embedding/base.py` | `EmbeddingProvider` 抽象基底クラス |
| `src/embedding/lmstudio_embedding.py` | LM Studio Embedding |
| `src/embedding/openai_embedding.py` | OpenAI Embedding |
| `src/embedding/factory.py` | Embeddingファクトリ関数 |
| `src/rag/__init__.py` | RAGモジュール |
| `src/rag/chunker.py` | テキストチャンキング |
| `src/rag/vector_store.py` | ChromaDBベクトルストア |
| `src/services/web_crawler.py` | Webクローラー |
| `src/services/rag_knowledge.py` | RAGナレッジサービス |
| `tests/test_embedding.py` | Embeddingテスト |
| `tests/test_chunker.py` | チャンキングテスト |
| `tests/test_vector_store.py` | ベクトルストアテスト |
| `tests/test_web_crawler.py` | Webクローラーテスト |
| `tests/test_rag_knowledge.py` | RAGナレッジサービステスト |

## 変更ファイル一覧

| ファイル | 変更内容 |
|---------|---------|
| `pyproject.toml` | `chromadb`, `beautifulsoup4` 依存追加 |
| `src/config/settings.py` | RAG設定項目追加 |
| `src/services/chat.py` | `rag_service` オプショナル注入、RAGコンテキスト注入 |
| `src/slack/handlers.py` | `rag` コマンドハンドラ追加 |
| `src/main.py` | RAGサービス初期化・注入 |
| `.env.example` | RAG関連環境変数追加 |
| `.gitignore` | `chroma_db/` ディレクトリを除外対象に追加 |

## テスト方針

### ユニットテスト

| テストファイル | テスト | 対応AC |
|--------------|--------|--------|
| `tests/test_embedding.py` | `test_ac1_embedding_provider_interface` | AC1 |
| `tests/test_embedding.py` | `test_ac2_lmstudio_embedding_converts_text` | AC2 |
| `tests/test_embedding.py` | `test_ac3_openai_embedding_converts_text` | AC3 |
| `tests/test_embedding.py` | `test_ac4_factory_returns_correct_provider` | AC4 |
| `tests/test_chunker.py` | `test_ac5_chunk_text_splits_by_size` | AC5 |
| `tests/test_chunker.py` | `test_ac6_chunk_overlap_applied` | AC6 |
| `tests/test_chunker.py` | `test_ac7_empty_and_short_text` | AC7 |
| `tests/test_vector_store.py` | `test_ac8_add_documents` | AC8 |
| `tests/test_vector_store.py` | `test_ac9_search_similar_chunks` | AC9 |
| `tests/test_vector_store.py` | `test_ac10_delete_by_source` | AC10 |
| `tests/test_vector_store.py` | `test_ac11_get_stats` | AC11 |
| `tests/test_web_crawler.py` | `test_ac12_crawl_index_page_extracts_urls` | AC12 |
| `tests/test_web_crawler.py` | `test_ac13_url_pattern_filtering` | AC13 |
| `tests/test_web_crawler.py` | `test_ac14_crawl_page_extracts_text` | AC14 |
| `tests/test_web_crawler.py` | `test_ac15_crawl_pages_isolates_errors` | AC15 |

### 統合テスト

| テストファイル | テスト | 対応AC |
|--------------|--------|--------|
| `tests/test_rag_knowledge.py` | `test_ac16_ingest_from_index` | AC16 |
| `tests/test_rag_knowledge.py` | `test_ac17_ingest_page` | AC17 |
| `tests/test_rag_knowledge.py` | `test_ac18_retrieve_returns_formatted_text` | AC18 |
| `tests/test_rag_knowledge.py` | `test_ac19_retrieve_returns_empty_when_no_results` | AC19 |
| `tests/test_rag_knowledge.py` | `test_ac20_chat_injects_rag_context` | AC20 |
| `tests/test_rag_knowledge.py` | `test_ac21_chat_backward_compatible` | AC21 |
| `tests/test_rag_knowledge.py` | `test_ac22_rag_failure_graceful` | AC22 |
| `tests/test_rag_knowledge.py` | `test_ac23_rag_crawl_command` | AC23 |
| `tests/test_rag_knowledge.py` | `test_ac24_rag_add_command` | AC24 |
| `tests/test_rag_knowledge.py` | `test_ac25_rag_status_command` | AC25 |
| `tests/test_rag_knowledge.py` | `test_ac26_rag_delete_command` | AC26 |
| `tests/test_rag_knowledge.py` | `test_ac27_rag_enabled_toggle` | AC27 |
| `tests/test_rag_knowledge.py` | `test_ac28_embedding_provider_switch` | AC28 |
| `tests/test_rag_knowledge.py` | `test_ac29_configurable_parameters` | AC29 |

### テスト戦略

- **Embeddingプロバイダー**: `AsyncOpenAI` クライアントを `AsyncMock` でモック
- **VectorStore**: `chromadb.EphemeralClient()`（インメモリ）を使用し、ファイルシステム副作用を回避
- **Webクローラー**: `aiohttp.ClientSession` を `AsyncMock` でモック、HTMLサンプルで本文抽出を検証
- **RAGナレッジサービス**: VectorStore・WebCrawler をモック化してオーケストレーションを検証
- **ChatService統合**: RAGKnowledgeService をモック化してコンテキスト注入を検証

## 実装ステップ

### Step 1: Embeddingプロバイダー (#115)
1. `src/embedding/base.py` に `EmbeddingProvider` 抽象基底クラスを作成
2. `src/embedding/lmstudio_embedding.py` を実装
3. `src/embedding/openai_embedding.py` を実装
4. `src/embedding/factory.py` を実装
5. テスト作成

### Step 2: RAGインフラ (#116)
1. `src/rag/chunker.py` — テキストチャンキング実装
2. `src/rag/vector_store.py` — ChromaDBラッパー実装
3. `pyproject.toml` に `chromadb` 追加
4. テスト作成

### Step 3: Webクローラー (#117)
1. `src/services/web_crawler.py` を作成
2. `pyproject.toml` に `beautifulsoup4` 追加
3. テスト作成

### Step 4: RAGナレッジサービス＆既存コード統合 (#118)
1. `src/services/rag_knowledge.py` — オーケストレーションサービス実装
2. `src/config/settings.py` — RAG設定追加
3. `src/services/chat.py` — RAGコンテキスト注入
4. `src/slack/handlers.py` — `rag` コマンドハンドラ追加
5. `src/main.py` — RAGサービス初期化・注入
6. `.env.example` — RAG設定項目追加
7. 統合テスト作成

## 注意事項

1. **RAG_ENABLED のデフォルト**: `false`。明示的に有効化しない限り、既存の動作に一切影響しない
2. **ChromaDBの永続化**: `CHROMADB_PERSIST_DIR` で指定したディレクトリにSQLiteファイルが作成される。`.gitignore` に追加すること
3. **Embeddingモデルの整合性**: ベクトルストア内のデータは特定のEmbeddingモデルで生成されている。モデルを変更した場合、既存データとの類似度計算が不正確になるため、コレクションの再構築が必要
4. **Webクローラーの負荷配慮**: `asyncio.Semaphore` で同時接続数を制限し、対象サーバーへの過負荷を防ぐ
5. **LLMコンテキストウィンドウ**: 多数のチャンクが注入されるとトークン上限に近づく可能性がある。`RAG_RETRIEVAL_COUNT` で検索件数を制限し、対応する
6. **既存テストへの影響**: RAGサービスはオプショナル注入のため、既存テストに変更は不要
7. **robots.txt**: 初期実装では `robots.txt` のチェックは行わない。将来的に対応を検討する
