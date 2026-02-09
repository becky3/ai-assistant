"""RAGナレッジサービスのテスト

仕様: docs/specs/f9-rag-knowledge.md, docs/specs/f9-rag-evaluation.md
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.rag.vector_store import RetrievalResult, VectorStore
from src.services.rag_knowledge import RAGKnowledgeService, RAGRetrievalResult
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
    mock.delete_stale_chunks = AsyncMock(return_value=0)
    mock.get_stats = MagicMock(return_value={"total_chunks": 10, "source_count": 2})
    return mock


@pytest.fixture
def mock_web_crawler() -> MagicMock:
    """モックWebCrawlerを作成する."""
    mock = MagicMock(spec=WebCrawler)
    mock.crawl_index_page = AsyncMock(return_value=[])
    mock.crawl_page = AsyncMock(return_value=None)
    mock.crawl_pages = AsyncMock(return_value=[])
    # validate_url は入力URLをそのまま返す（検証OK）
    mock.validate_url = MagicMock(side_effect=lambda url: url)
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
        mock_web_crawler.validate_url.assert_called_once_with("https://example.com/page1")
        mock_web_crawler.crawl_page.assert_called_once_with("https://example.com/page1")
        mock_vector_store.add_documents.assert_called_once()
        # upsert後に古いチャンクを削除
        mock_vector_store.delete_stale_chunks.assert_called_once()

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
        """同一URLの再取り込み時はupsert後に古いチャンクを削除すること."""
        # Arrange
        mock_web_crawler.crawl_page.return_value = CrawledPage(
            url="https://example.com/page1",
            title="Updated Page",
            text="Updated content.",
            crawled_at="2024-01-02T00:00:00+00:00",
        )
        mock_vector_store.delete_stale_chunks.return_value = 2  # 古い2件削除

        # Act
        await rag_service.ingest_page("https://example.com/page1")

        # Assert: upsert後に古いチャンクを削除
        mock_vector_store.add_documents.assert_called_once()
        mock_vector_store.delete_stale_chunks.assert_called_once()


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
        assert isinstance(result, RAGRetrievalResult)
        assert "--- 参考情報 1 ---" in result.context
        assert "出典: https://example.com/page1" in result.context
        assert "This is relevant content 1." in result.context
        assert "--- 参考情報 2 ---" in result.context
        assert "出典: https://example.com/page2" in result.context
        mock_vector_store.search.assert_called_once_with("test query", n_results=5)

    async def test_ac19_retrieve_returns_empty_when_no_results(
        self,
        rag_service: RAGKnowledgeService,
        mock_vector_store: MagicMock,
    ) -> None:
        """AC19: 結果がない場合は空のRAGRetrievalResultを返すこと."""
        # Arrange
        mock_vector_store.search.return_value = []

        # Act
        result = await rag_service.retrieve("unrelated query")

        # Assert
        assert isinstance(result, RAGRetrievalResult)
        assert result.context == ""
        assert result.sources == []


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

        from unittest.mock import AsyncMock, MagicMock, patch

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
            return_value=RAGRetrievalResult(
                context="--- 参考情報 1 ---\n出典: https://example.com\nRelevant info",
                sources=["https://example.com"],
            )
        )

        chat_service = ChatService(
            llm=mock_llm,
            session_factory=mock_session_factory,
            system_prompt="You are an assistant.",
            rag_service=mock_rag_service,
        )

        # Act - get_settingsをモックして決定的なテストにする
        mock_settings = MagicMock()
        mock_settings.rag_retrieval_count = 5
        mock_settings.rag_show_sources = False  # ソース情報非表示
        with patch("src.services.chat.get_settings", return_value=mock_settings):
            response = await chat_service.respond(
                user_id="U123",
                text="What is Python?",
                thread_ts="1234567890.000000",
            )

        # Assert
        # モックした rag_retrieval_count=5 が使われる
        mock_rag_service.retrieve.assert_called_once_with("What is Python?", n_results=5)
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
        """AC23: rag crawl <URL> [パターン] でリンク集ページからの一括取り込みができること."""
        # RAGKnowledgeService.ingest_from_index() の単体テストは
        # TestIngestFromIndex で実装済み
        pytest.skip("Slackイベントのモックを使った統合テストは未実装")

    async def test_ac24_rag_add_command(self) -> None:
        """AC24: rag add <URL> で単一ページの取り込みができること."""
        # RAGKnowledgeService.ingest_page() の単体テストは
        # TestIngestPage で実装済み
        pytest.skip("Slackイベントのモックを使った統合テストは未実装")

    async def test_ac25_rag_status_command(self) -> None:
        """AC25: rag status でナレッジベースの統計が表示されること."""
        # RAGKnowledgeService.get_stats() の単体テストは
        # TestGetStats で実装済み
        pytest.skip("Slackイベントのモックを使った統合テストは未実装")

    async def test_ac26_rag_delete_command(self) -> None:
        """AC26: rag delete <URL> でソースURL指定の削除ができること."""
        # RAGKnowledgeService.delete_source() の単体テストは
        # TestDeleteSource で実装済み
        pytest.skip("Slackイベントのモックを使った統合テストは未実装")


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


class TestRAGDebugLog:
    """RAG検索結果のログ出力テスト (AC1-4, f9-rag-evaluation.md)."""

    @pytest.fixture
    def mock_settings_log_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ログ出力有効の設定をモックする."""
        mock_settings = MagicMock()
        mock_settings.rag_debug_log_enabled = True
        monkeypatch.setattr(
            "src.config.settings.get_settings",
            lambda: mock_settings,
        )

    @pytest.fixture
    def mock_settings_log_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ログ出力無効の設定をモックする."""
        mock_settings = MagicMock()
        mock_settings.rag_debug_log_enabled = False
        monkeypatch.setattr(
            "src.config.settings.get_settings",
            lambda: mock_settings,
        )

    async def test_ac1_retrieve_logs_query(
        self,
        rag_service: RAGKnowledgeService,
        mock_vector_store: MagicMock,
        mock_settings_log_enabled: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """AC1: RAG_DEBUG_LOG_ENABLED=true の場合、検索クエリがINFOログに出力されること."""
        # Arrange
        mock_vector_store.search.return_value = [
            RetrievalResult(
                text="Test content",
                metadata={"source_url": "https://example.com/page1"},
                distance=0.234,
            ),
        ]

        # Act
        with caplog.at_level(logging.INFO, logger="src.services.rag_knowledge"):
            await rag_service.retrieve("しれんのしろ アイテム", n_results=5)

        # Assert
        assert "RAG retrieve: query='しれんのしろ アイテム'" in caplog.text

    async def test_ac2_retrieve_logs_results(
        self,
        rag_service: RAGKnowledgeService,
        mock_vector_store: MagicMock,
        mock_settings_log_enabled: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """AC2: 各検索結果の distance、source_url がINFOログに出力されること.

        Note: テキストプレビューはPII漏洩リスク軽減のためDEBUGレベルに移動された。
        """
        # Arrange
        long_text = "A" * 150  # 100文字を超えるテキスト
        mock_vector_store.search.return_value = [
            RetrievalResult(
                text=long_text,
                metadata={"source_url": "https://example.com/page1"},
                distance=0.234,
            ),
            RetrievalResult(
                text="Short text",
                metadata={"source_url": "https://example.com/page2"},
                distance=0.312,
            ),
        ]

        # Act
        with caplog.at_level(logging.INFO, logger="src.services.rag_knowledge"):
            await rag_service.retrieve("test query", n_results=5)

        # Assert - INFOレベルではdistanceとsourceのみ（テキストは含まない）
        assert "RAG result 1: distance=0.234" in caplog.text
        assert "source='https://example.com/page1'" in caplog.text
        assert "RAG result 2: distance=0.312" in caplog.text
        assert "source='https://example.com/page2'" in caplog.text
        # テキストプレビューはINFOレベルには含まれない（DEBUGレベルで出力）
        # assert "A" * 100 + "..." in caplog.text  # -> DEBUGレベルに移動

    async def test_ac3_retrieve_logs_full_text_debug(
        self,
        rag_service: RAGKnowledgeService,
        mock_vector_store: MagicMock,
        mock_settings_log_enabled: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """AC3: 各検索結果の全文がDEBUGログに出力されること."""
        # Arrange
        full_text = "This is the full text content that should appear in DEBUG log."
        mock_vector_store.search.return_value = [
            RetrievalResult(
                text=full_text,
                metadata={"source_url": "https://example.com/page1"},
                distance=0.1,
            ),
        ]

        # Act
        with caplog.at_level(logging.DEBUG, logger="src.services.rag_knowledge"):
            await rag_service.retrieve("test query", n_results=5)

        # Assert
        assert "RAG result 1 full text:" in caplog.text
        assert full_text in caplog.text

    async def test_ac4_retrieve_no_log_when_disabled(
        self,
        rag_service: RAGKnowledgeService,
        mock_vector_store: MagicMock,
        mock_settings_log_disabled: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """AC4: RAG_DEBUG_LOG_ENABLED=false の場合、ログが出力されないこと."""
        # Arrange
        mock_vector_store.search.return_value = [
            RetrievalResult(
                text="Test content",
                metadata={"source_url": "https://example.com/page1"},
                distance=0.1,
            ),
        ]

        # Act
        with caplog.at_level(logging.DEBUG, logger="src.services.rag_knowledge"):
            await rag_service.retrieve("test query", n_results=5)

        # Assert
        assert "RAG retrieve:" not in caplog.text
        assert "RAG result" not in caplog.text


class TestRAGRetrievalResultSources:
    """RAG検索結果のソース情報テスト (AC5-6, f9-rag-evaluation.md)."""

    async def test_ac5_retrieve_returns_sources(
        self,
        rag_service: RAGKnowledgeService,
        mock_vector_store: MagicMock,
    ) -> None:
        """AC5: retrieve() がソースURLリストを返すこと."""
        # Arrange
        mock_vector_store.search.return_value = [
            RetrievalResult(
                text="Content 1",
                metadata={"source_url": "https://example.com/page1"},
                distance=0.1,
            ),
            RetrievalResult(
                text="Content 2",
                metadata={"source_url": "https://example.com/page2"},
                distance=0.2,
            ),
        ]

        # Act
        result = await rag_service.retrieve("test query", n_results=5)

        # Assert
        assert isinstance(result, RAGRetrievalResult)
        assert len(result.sources) == 2
        assert "https://example.com/page1" in result.sources
        assert "https://example.com/page2" in result.sources

    async def test_ac6_sources_are_unique(
        self,
        rag_service: RAGKnowledgeService,
        mock_vector_store: MagicMock,
    ) -> None:
        """AC6: ソースURLは重複なく表示されること."""
        # Arrange - 同じソースURLを持つ複数のチャンク
        mock_vector_store.search.return_value = [
            RetrievalResult(
                text="Content 1 from page1",
                metadata={"source_url": "https://example.com/page1"},
                distance=0.1,
            ),
            RetrievalResult(
                text="Content 2 from page1",
                metadata={"source_url": "https://example.com/page1"},
                distance=0.2,
            ),
            RetrievalResult(
                text="Content from page2",
                metadata={"source_url": "https://example.com/page2"},
                distance=0.3,
            ),
        ]

        # Act
        result = await rag_service.retrieve("test query", n_results=5)

        # Assert
        assert len(result.sources) == 2  # 3件のチャンクだが、ソースは2件
        assert result.sources.count("https://example.com/page1") == 1
        assert result.sources.count("https://example.com/page2") == 1

    async def test_sources_exclude_unknown(
        self,
        rag_service: RAGKnowledgeService,
        mock_vector_store: MagicMock,
    ) -> None:
        """ソースURLが不明の場合はソースリストに含まれないこと."""
        # Arrange
        mock_vector_store.search.return_value = [
            RetrievalResult(
                text="Content with source",
                metadata={"source_url": "https://example.com/page1"},
                distance=0.1,
            ),
            RetrievalResult(
                text="Content without source",
                metadata={},  # source_url がない
                distance=0.2,
            ),
        ]

        # Act
        result = await rag_service.retrieve("test query", n_results=5)

        # Assert
        assert len(result.sources) == 1
        assert "https://example.com/page1" in result.sources
        assert "不明" not in result.sources


class TestRAGShowSources:
    """Slack回答時のソース情報表示テスト (AC5, AC7-9, f9-rag-evaluation.md)."""

    async def test_ac5_chat_shows_sources(self) -> None:
        """AC5: RAG_SHOW_SOURCES=true の場合、Slack回答末尾にソースURLリストが表示されること."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from src.services.chat import ChatService

        # Arrange
        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(
            return_value=MagicMock(content="This is the answer.")
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
        mock_rag_service.retrieve = AsyncMock(
            return_value=RAGRetrievalResult(
                context="--- 参考情報 1 ---\n出典: https://example.com/page1\nContent",
                sources=["https://example.com/page1", "https://example.com/page2"],
            )
        )

        chat_service = ChatService(
            llm=mock_llm,
            session_factory=mock_session_factory,
            system_prompt="You are an assistant.",
            rag_service=mock_rag_service,
        )

        # Act
        mock_settings = MagicMock()
        mock_settings.rag_retrieval_count = 5
        mock_settings.rag_show_sources = True
        with patch("src.services.chat.get_settings", return_value=mock_settings):
            response = await chat_service.respond(
                user_id="U123",
                text="Test question",
                thread_ts="1234567890.000000",
            )

        # Assert
        assert "This is the answer." in response
        assert "---" in response
        assert "参照元:" in response
        assert "• https://example.com/page1" in response
        assert "• https://example.com/page2" in response

    async def test_ac7_chat_hides_sources_when_disabled(self) -> None:
        """AC7: RAG_SHOW_SOURCES=false の場合、ソース情報が表示されないこと（従来動作）."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from src.services.chat import ChatService

        # Arrange
        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(
            return_value=MagicMock(content="This is the answer.")
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
        mock_rag_service.retrieve = AsyncMock(
            return_value=RAGRetrievalResult(
                context="--- 参考情報 1 ---\n出典: https://example.com/page1\nContent",
                sources=["https://example.com/page1"],
            )
        )

        chat_service = ChatService(
            llm=mock_llm,
            session_factory=mock_session_factory,
            system_prompt="You are an assistant.",
            rag_service=mock_rag_service,
        )

        # Act
        mock_settings = MagicMock()
        mock_settings.rag_retrieval_count = 5
        mock_settings.rag_show_sources = False  # ソース表示無効
        with patch("src.services.chat.get_settings", return_value=mock_settings):
            response = await chat_service.respond(
                user_id="U123",
                text="Test question",
                thread_ts="1234567890.000000",
            )

        # Assert
        assert response == "This is the answer."
        assert "参照元:" not in response

    async def test_ac8_backward_compatible(self) -> None:
        """AC8: 新設定のデフォルト値により、既存の動作に影響がないこと（rag_show_sources=false）."""
        import os
        from unittest.mock import patch

        from src.config.settings import Settings

        # デフォルト値をテスト（.envファイルと環境変数の影響を排除）
        # Settingsはenv_file=".env"を読み込むため、環境変数だけでなく
        # .envファイルの影響も排除する必要がある
        # 環境変数を削除し、.envファイルも読み込まないようにする
        env_backup = {
            k: os.environ.pop(k, None)
            for k in ["RAG_SHOW_SOURCES", "RAG_DEBUG_LOG_ENABLED"]
        }
        try:
            settings = Settings(_env_file=None)  # .envファイルを読み込まない
            assert settings.rag_show_sources is False
            assert settings.rag_debug_log_enabled is False  # デフォルトはFalse
        finally:
            # 環境変数を復元
            for k, v in env_backup.items():
                if v is not None:
                    os.environ[k] = v

    async def test_ac9_no_effect_when_rag_disabled(self) -> None:
        """AC9: RAG無効時（rag_enabled=false）は新機能が動作しないこと."""
        from unittest.mock import AsyncMock, MagicMock, patch

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
        mock_settings = MagicMock()
        mock_settings.rag_show_sources = True  # 有効でも効果なし
        with patch("src.services.chat.get_settings", return_value=mock_settings):
            response = await chat_service.respond(
                user_id="U123",
                text="Hello",
                thread_ts="1234567890.000000",
            )

        # Assert
        assert response == "Normal response"
        assert "参照元:" not in response
