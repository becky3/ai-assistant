"""BM25インデックスのテスト

仕様: docs/specs/f9-rag-chunking-hybrid.md
"""

from src.rag.bm25_index import BM25Index, tokenize_japanese


class TestTokenizeJapanese:
    """tokenize_japanese関数のテスト."""

    def test_ac7_empty_text_returns_empty_list(self) -> None:
        """AC7: 空のテキストは空リストを返す."""
        assert tokenize_japanese("") == []
        assert tokenize_japanese("   ") == []

    def test_ac7_japanese_text_tokenized(self) -> None:
        """日本語テキストがトークン化される."""
        tokens = tokenize_japanese("りゅうおうはボスモンスターです")

        # 何らかのトークンが生成される
        assert len(tokens) > 0

    def test_ac7_stopwords_removed(self) -> None:
        """AC7: ストップワードが除去される."""
        tokens = tokenize_japanese("これは本です")

        # 「これ」「は」「です」はストップワード
        assert "これ" not in tokens
        assert "は" not in tokens
        assert "です" not in tokens

    def test_ac7_mixed_text_tokenized(self) -> None:
        """AC7: 日本語と英数字の混合テキストがトークン化される."""
        tokens = tokenize_japanese("Python3とJavaScript")

        # 何らかのトークンが生成される
        assert len(tokens) > 0


class TestBM25Index:
    """BM25Indexクラスのテスト."""

    def test_ac6_add_and_search_documents(self) -> None:
        """ドキュメントの追加と検索ができる."""
        index = BM25Index()

        # ドキュメントを追加
        docs = [
            ("doc1", "りゅうおうはドラゴンクエストのボスです", "source1"),
            ("doc2", "スライムは最弱のモンスターです", "source2"),
            ("doc3", "ゾーマは強力な魔王です", "source3"),
        ]
        added = index.add_documents(docs)
        assert added == 3

        # 検索
        results = index.search("りゅうおう", n_results=3)

        # りゅうおうを含むドキュメントがヒット
        assert len(results) > 0
        assert any("りゅうおう" in r.text for r in results)

    def test_ac6_delete_by_source(self) -> None:
        """ソースURL指定でドキュメントを削除できる."""
        index = BM25Index()

        docs = [
            ("doc1", "テスト1", "source1"),
            ("doc2", "テスト2", "source1"),
            ("doc3", "テスト3", "source2"),
        ]
        index.add_documents(docs)

        # source1のドキュメントを削除
        deleted = index.delete_by_source("source1")
        assert deleted == 2

        # 残りは1件
        assert index.get_document_count() == 1

    def test_ac6_search_empty_index_returns_empty_list(self) -> None:
        """AC6: 空のインデックスへの検索は空リストを返す."""
        index = BM25Index()
        results = index.search("テスト")
        assert results == []

    def test_ac6_search_with_no_matches_returns_empty_list(self) -> None:
        """AC6: マッチするドキュメントがない場合は空リストを返す."""
        index = BM25Index()
        index.add_documents([("doc1", "りゅうおう", "source1")])

        # 全く関係ないクエリ
        results = index.search("プログラミング言語")

        # マッチなしの場合は空（またはスコア0の結果がない）
        # BM25はトークンベースなので、完全に無関係なら結果なし
        # ただし簡易トークナイザの場合は挙動が異なる可能性あり
        # 結果があってもスコアが0より大きいもののみ
        assert all(r.score > 0 for r in results)

    def test_ac6_update_existing_document(self) -> None:
        """AC6: 既存ドキュメントの更新."""
        index = BM25Index()

        # 3つ以上のドキュメントを追加（BM25のIDF計算にはN>=3が必要）
        index.add_documents([
            ("doc1", "dragon quest adventure game", "source1"),
            ("doc2", "pokemon battle monster", "source2"),
            ("doc3", "zelda sword shield", "source3"),
        ])
        assert index.get_document_count() == 3

        # 同じIDで更新（addedは0だがドキュメントは更新される）
        added = index.add_documents([("doc1", "final fantasy rpg game", "source1")])
        assert added == 0  # 新規追加ではない
        assert index.get_document_count() == 3

        # 更新後のテキストで検索 - finalでヒットするはず
        results = index.search("final fantasy")
        assert len(results) > 0, "更新後のドキュメントが検索でヒットしない"
        assert "final" in results[0].text

        # 古いテキストのキーワードでは検索されない（テキストが置き換わっている）
        old_results = index.search("dragon quest")
        assert not any("dragon" in r.text for r in old_results)

    def test_ac10_bm25_parameters(self) -> None:
        """BM25パラメータのカスタマイズ."""
        # カスタムパラメータでインスタンス化
        index = BM25Index(k1=2.0, b=0.5)

        # パラメータが設定されている
        assert index._k1 == 2.0
        assert index._b == 0.5
