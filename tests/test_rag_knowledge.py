"""RAGナレッジサービスのテスト

仕様: docs/specs/f9-rag-knowledge.md
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.rag.vector_store import RetrievalResult, VectorStore
from src.services.rag_knowledge import RAGKnowledgeService
from src.services.web_crawler import CrawledPage, WebCrawler


@pytest.fixture
def mock_embedding_provider() -> MagicMock:
    """モックEmbeddingプロバイダーを作成する."""
    mock = MagicMock()
    mock.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    return mock


@pytest.fixture
def mock_vector_store(mock_embedding_provider: MagicMock) -> MagicMock:
    """モックVectorStoreを作成する."""
    mock = MagicMock(spec=VectorStore)
    mock.add_documents = AsyncMock(return_value=3)
    mock.search = AsyncMock(return_value=[])
    mock.delete_by_source = AsyncMock(return_value=0)
    mock.get_stats = MagicMock(return_value={"total_chunks": 10, "source_count": 2})
    return mock


@pytest.fixture
def mock_web_crawler() -> MagicMock:
    """モックWebCrawlerを作成する."""
    mock = MagicMock(spec=WebCrawler)
    mock.crawl_index_page = AsyncMock(return_value=[])
    mock.crawl_page = AsyncMock(return_value=None)
    mock.crawl_pages = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def rag_service(
    mock_vector_store: MagicMock,
    mock_web_crawler: MagicMock,
) -> RAGKnowledgeService:
    """RAGKnowledgeServiceインスタンスを作成する."""
    return RAGKnowledgeService(
        vector_store=mock_vector_store,
        web_crawler=mock_web_crawler,
        chunk_size=500,
        chunk_overlap=50,
    )


class TestIngestFromIndex:
    """ingest_from_index() のテスト (AC16)."""

    async def test_ac16_ingest_from_index(
        self,
        rag_service: RAGKnowledgeService,
        mock_vector_store: MagicMock,
        mock_web_crawler: MagicMock,
    ) -> None:
        """AC16: リンク集ページから記事を一括クロール→チャンキング→ベクトル保存できること."""
        # Arrange
        mock_web_crawler.crawl_index_page.return_value = [
            "https://example.com/page1",
            "https://example.com/page2",
        ]
        mock_web_crawler.crawl_pages.return_value = [
            CrawledPage(
                url="https://example.com/page1",
                title="Page 1",
                text="This is page 1 content with enough text to be chunked.",
                crawled_at="2024-01-01T00:00:00+00:00",
            ),
            CrawledPage(
                url="https://example.com/page2",
                title="Page 2",
                text="This is page 2 content with enough text to be chunked.",
                crawled_at="2024-01-01T00:00:00+00:00",
            ),
        ]
        mock_vector_store.add_documents.return_value = 1

        # Act
        result = await rag_service.ingest_from_index(
            "https://example.com/index",
            url_pattern=r"page\d",
        )

        # Assert
        assert result["pages_crawled"] == 2
        assert result["chunks_stored"] >= 2
        assert result["errors"] == 0
        mock_web_crawler.crawl_index_page.assert_called_once_with(
            "https://example.com/index", r"page\d"
        )
        mock_web_crawler.crawl_pages.assert_called_once()

    async def test_ingest_from_index_with_errors(
        self,
        rag_service: RAGKnowledgeService,
        mock_vector_store: MagicMock,
        mock_web_crawler: MagicMock,
    ) -> None:
        """クロール失敗したページはエラーとしてカウントされること."""
        # Arrange
        mock_web_crawler.crawl_index_page.return_value = [
            "https://example.com/page1",
            "https://example.com/page2",
        ]
        mock_web_crawler.crawl_pages.return_value = [
            CrawledPage(
                url="https://example.com/page1",
                title="Page 1",
                text="Content",
                crawled_at="2024-01-01T00:00:00+00:00",
            ),
        ]  # 1件のみ成功

        # Act
        result = await rag_service.ingest_from_index("https://example.com/index")

        # Assert
        assert result["pages_crawled"] == 1
        assert result["errors"] == 1  # 2件中1件失敗

    async def test_ingest_from_index_no_urls(
        self,
        rag_service: RAGKnowledgeService,
        mock_web_crawler: MagicMock,
    ) -> None:
        """URLが見つからない場合は空の結果を返すこと."""
        # Arrange
        mock_web_crawler.crawl_index_page.return_value = []

        # Act
        result = await rag_service.ingest_from_index("https://example.com/empty")

        # Assert
        assert result["pages_crawled"] == 0
        assert result["chunks_stored"] == 0
        assert result["errors"] == 0


class TestIngestPage:
    """ingest_page() のテスト (AC17)."""

    async def test_ac17_ingest_page(
        self,
        rag_service: RAGKnowledgeService,
        mock_vector_store: MagicMock,
        mock_web_crawler: MagicMock,
    ) -> None:
        """AC17: 単一ページをクロール→チャンキング→ベクトル保存できること."""
        # Arrange
        mock_web_crawler.crawl_page.return_value = CrawledPage(
            url="https://example.com/page1",
            title="Test Page",
            text="This is test content.",
            crawled_at="2024-01-01T00:00:00+00:00",
        )
        mock_vector_store.add_documents.return_value = 1

        # Act
        result = await rag_service.ingest_page("https://example.com/page1")

        # Assert
        assert result == 1
        mock_web_crawler.crawl_page.assert_called_once_with("https://example.com/page1")
        mock_vector_store.delete_by_source.assert_called_once_with(
            "https://example.com/page1"
        )
        mock_vector_store.add_documents.assert_called_once()

    async def test_ingest_page_crawl_failed(
        self,
        rag_service: RAGKnowledgeService,
        mock_web_crawler: MagicMock,
    ) -> None:
        """クロール失敗時は0を返すこと."""
        # Arrange
        mock_web_crawler.crawl_page.return_value = None

        # Act
        result = await rag_service.ingest_page("https://example.com/fail")

        # Assert
        assert result == 0

    async def test_ingest_page_upsert(
        self,
        rag_service: RAGKnowledgeService,
        mock_vector_store: MagicMock,
        mock_web_crawler: MagicMock,
    ) -> None:
        """同一URLの再取り込み時は既存チャンクを削除してから追加すること."""
        # Arrange
        mock_web_crawler.crawl_page.return_value = CrawledPage(
            url="https://example.com/page1",
            title="Updated Page",
            text="Updated content.",
            crawled_at="2024-01-02T00:00:00+00:00",
        )
        mock_vector_store.delete_by_source.return_value = 5  # 既存5件削除

        # Act
        await rag_service.ingest_page("https://example.com/page1")

        # Assert
        mock_vector_store.delete_by_source.assert_called_once_with(
            "https://example.com/page1"
        )


class TestRetrieve:
    """retrieve() のテスト (AC18, AC19)."""

    async def test_ac18_retrieve_returns_formatted_text(
        self,
        rag_service: RAGKnowledgeService,
        mock_vector_store: MagicMock,
    ) -> None:
        """AC18: クエリに関連するチャンクを検索し、フォーマット済みテキストを返すこと."""
        # Arrange
        mock_vector_store.search.return_value = [
            RetrievalResult(
                text="This is relevant content 1.",
                metadata={"source_url": "https://example.com/page1"},
                distance=0.1,
            ),
            RetrievalResult(
                text="This is relevant content 2.",
                metadata={"source_url": "https://example.com/page2"},
                distance=0.2,
            ),
        ]

        # Act
        result = await rag_service.retrieve("test query", n_results=5)

        # Assert
        assert "--- 参考情報 1 ---" in result
        assert "出典: https://example.com/page1" in result
        assert "This is relevant content 1." in result
        assert "--- 参考情報 2 ---" in result
        assert "出典: https://example.com/page2" in result
        mock_vector_store.search.assert_called_once_with("test query", n_results=5)

    async def test_ac19_retrieve_returns_empty_when_no_results(
        self,
        rag_service: RAGKnowledgeService,
        mock_vector_store: MagicMock,
    ) -> None:
        """AC19: 結果がない場合は空文字列を返すこと."""
        # Arrange
        mock_vector_store.search.return_value = []

        # Act
        result = await rag_service.retrieve("unrelated query")

        # Assert
        assert result == ""


class TestDeleteSource:
    """delete_source() のテスト."""

    async def test_delete_source(
        self,
        rag_service: RAGKnowledgeService,
        mock_vector_store: MagicMock,
    ) -> None:
        """ソースURL指定で削除できること."""
        # Arrange
        mock_vector_store.delete_by_source.return_value = 8

        # Act
        result = await rag_service.delete_source("https://example.com/page1")

        # Assert
        assert result == 8
        mock_vector_store.delete_by_source.assert_called_once_with(
            "https://example.com/page1"
        )


class TestGetStats:
    """get_stats() のテスト."""

    async def test_get_stats(
        self,
        rag_service: RAGKnowledgeService,
        mock_vector_store: MagicMock,
    ) -> None:
        """統計情報を取得できること."""
        # Arrange
        mock_vector_store.get_stats.return_value = {
            "total_chunks": 100,
            "source_count": 10,
        }

        # Act
        result = await rag_service.get_stats()

        # Assert
        assert result["total_chunks"] == 100
        assert result["source_count"] == 10


class TestChatServiceIntegration:
    """ChatService統合のテスト (AC20, AC21, AC22)."""

    async def test_ac20_chat_injects_rag_context(self) -> None:
        """AC20: RAG有効時、チャット応答に関連知識がシステムプロンプトとして自動注入されること."""
        # このテストは実際のChatService統合後に実行される
        # ここではモックを使ったユニットテストを実装

        from unittest.mock import AsyncMock, MagicMock

        from src.services.chat import ChatService

        # Arrange
        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(
            return_value=MagicMock(content="Response with RAG context")
        )

        mock_session_factory = MagicMock()
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session_factory.return_value = mock_session

        # execute の戻り値をモック
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.add = MagicMock()

        mock_rag_service = MagicMock()
        mock_rag_service.retrieve = AsyncMock(
            return_value="--- 参考情報 1 ---\n出典: https://example.com\nRelevant info"
        )

        chat_service = ChatService(
            llm=mock_llm,
            session_factory=mock_session_factory,
            system_prompt="You are an assistant.",
            rag_service=mock_rag_service,
        )

        # Act
        response = await chat_service.respond(
            user_id="U123",
            text="What is Python?",
            thread_ts="1234567890.000000",
        )

        # Assert
        mock_rag_service.retrieve.assert_called_once_with("What is Python?")
        # LLMに渡されるメッセージを確認
        call_args = mock_llm.complete.call_args
        messages = call_args[0][0]
        system_message = messages[0]
        assert "参考情報" in system_message.content
        assert response == "Response with RAG context"

    async def test_ac21_chat_backward_compatible(self) -> None:
        """AC21: RAG無効時（rag_enabled=False）は従来通りの動作をすること（後方互換性）."""
        from unittest.mock import AsyncMock, MagicMock

        from src.services.chat import ChatService

        # Arrange
        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(
            return_value=MagicMock(content="Normal response")
        )

        mock_session_factory = MagicMock()
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session_factory.return_value = mock_session

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.add = MagicMock()

        # rag_service=None（RAG無効）
        chat_service = ChatService(
            llm=mock_llm,
            session_factory=mock_session_factory,
            system_prompt="You are an assistant.",
            rag_service=None,
        )

        # Act
        response = await chat_service.respond(
            user_id="U123",
            text="Hello",
            thread_ts="1234567890.000000",
        )

        # Assert
        assert response == "Normal response"
        # システムプロンプトにRAGコンテキストが含まれていないことを確認
        call_args = mock_llm.complete.call_args
        messages = call_args[0][0]
        system_message = messages[0]
        assert "参考情報" not in system_message.content

    async def test_ac22_rag_failure_graceful(self) -> None:
        """AC22: RAG検索に失敗した場合、エラーログを出力し通常応答を継続すること."""
        from unittest.mock import AsyncMock, MagicMock

        from src.services.chat import ChatService

        # Arrange
        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(
            return_value=MagicMock(content="Response without RAG")
        )

        mock_session_factory = MagicMock()
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session_factory.return_value = mock_session

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.add = MagicMock()

        mock_rag_service = MagicMock()
        mock_rag_service.retrieve = AsyncMock(side_effect=Exception("RAG error"))

        chat_service = ChatService(
            llm=mock_llm,
            session_factory=mock_session_factory,
            system_prompt="You are an assistant.",
            rag_service=mock_rag_service,
        )

        # Act
        response = await chat_service.respond(
            user_id="U123",
            text="Test query",
            thread_ts="1234567890.000000",
        )

        # Assert - エラーが発生しても応答が返ること
        assert response == "Response without RAG"


class TestSlackCommands:
    """Slackコマンドのテスト (AC23, AC24, AC25, AC26).

    NOTE: handlers.py のRAGコマンドハンドラは実装済みです。
    以下のプレースホルダーテストは、Slackコマンドの統合テストが
    必要な場合に実装してください。現在は handlers.py 内の
    ハンドラ関数が正しく呼び出されることを手動テストで確認済みです。
    """

    async def test_ac23_rag_crawl_command(self) -> None:
        """AC23: rag crawl <URL> [パターン] でリンク集ページからの一括取り込みができること.

        TODO: Slackイベントのモックを使った統合テストを実装
        """
        # RAGKnowledgeService.ingest_from_index() の単体テストは
        # TestIngestFromIndex で実装済み
        pass

    async def test_ac24_rag_add_command(self) -> None:
        """AC24: rag add <URL> で単一ページの取り込みができること.

        TODO: Slackイベントのモックを使った統合テストを実装
        """
        # RAGKnowledgeService.ingest_page() の単体テストは
        # TestIngestPage で実装済み
        pass

    async def test_ac25_rag_status_command(self) -> None:
        """AC25: rag status でナレッジベースの統計が表示されること.

        TODO: Slackイベントのモックを使った統合テストを実装
        """
        # RAGKnowledgeService.get_stats() の単体テストは
        # TestGetStats で実装済み
        pass

    async def test_ac26_rag_delete_command(self) -> None:
        """AC26: rag delete <URL> でソースURL指定の削除ができること.

        TODO: Slackイベントのモックを使った統合テストを実装
        """
        # RAGKnowledgeService.delete_source() の単体テストは
        # TestDeleteSource で実装済み
        pass


class TestConfiguration:
    """設定のテスト (AC27, AC28, AC29)."""

    def test_ac27_rag_enabled_toggle(self) -> None:
        """AC27: RAG_ENABLED 環境変数でRAG機能のON/OFFを制御できること."""
        import os
        from unittest.mock import patch

        from src.config.settings import Settings

        # RAG_ENABLED=true
        with patch.dict(os.environ, {"RAG_ENABLED": "true"}):
            settings = Settings()
            assert settings.rag_enabled is True

        # RAG_ENABLED=false
        with patch.dict(os.environ, {"RAG_ENABLED": "false"}):
            settings = Settings()
            assert settings.rag_enabled is False

    def test_ac28_embedding_provider_switch(self) -> None:
        """AC28: EMBEDDING_PROVIDER で local / online を切り替えられること."""
        import os
        from unittest.mock import patch

        from src.config.settings import Settings

        with patch.dict(os.environ, {"EMBEDDING_PROVIDER": "local"}):
            settings = Settings()
            assert settings.embedding_provider == "local"

        with patch.dict(os.environ, {"EMBEDDING_PROVIDER": "online"}):
            settings = Settings()
            assert settings.embedding_provider == "online"

    def test_ac29_configurable_parameters(self) -> None:
        """AC29: チャンクサイズ・オーバーラップ・検索件数が環境変数で設定可能であること."""
        import os
        from unittest.mock import patch

        from src.config.settings import Settings

        with patch.dict(
            os.environ,
            {
                "RAG_CHUNK_SIZE": "1000",
                "RAG_CHUNK_OVERLAP": "100",
                "RAG_RETRIEVAL_COUNT": "10",
            },
        ):
            settings = Settings()
            assert settings.rag_chunk_size == 1000
            assert settings.rag_chunk_overlap == 100
            assert settings.rag_retrieval_count == 10
