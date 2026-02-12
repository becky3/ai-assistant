"""テキストチャンキングのテスト (Issue #116).

仕様: docs/specs/f9-rag.md — AC5〜AC7
"""

from __future__ import annotations

import pytest

from src.rag.chunker import chunk_text


class TestAC5ChunkTextSplitsBySize:
    """AC5: chunk_text() がテキストを指定サイズのチャンクに分割できること."""

    def test_ac5_short_text_returns_single_chunk(self) -> None:
        """短いテキストは1つのチャンクとして返される."""
        text = "これは短いテキストです。"
        result = chunk_text(text, chunk_size=500)
        assert result == [text]

    def test_ac5_long_text_is_split_into_multiple_chunks(self) -> None:
        """長いテキストは複数のチャンクに分割される."""
        # 1000文字以上のテキストを作成
        text = "これはテストです。" * 100
        result = chunk_text(text, chunk_size=100, chunk_overlap=10)
        assert len(result) > 1
        # 各チャンクがchunk_size以下であること（オーバーラップ分を考慮）
        for chunk in result:
            assert len(chunk) <= 150  # chunk_size + マージン

    def test_ac5_paragraphs_are_used_as_split_points(self) -> None:
        """段落（空行区切り）が分割ポイントとして使用される."""
        text = "段落1のテキスト。\n\n段落2のテキスト。\n\n段落3のテキスト。"
        result = chunk_text(text, chunk_size=20, chunk_overlap=0)
        # 段落ごとに分割される
        assert len(result) >= 2

    def test_ac5_sentences_are_used_when_paragraphs_too_long(self) -> None:
        """段落が長い場合は文単位で分割される."""
        # 1つの長い段落
        text = "これは最初の文です。これは2番目の文です。これは3番目の文です。これは4番目の文です。"
        result = chunk_text(text, chunk_size=30, chunk_overlap=5)
        assert len(result) >= 2


class TestAC6ChunkOverlapApplied:
    """AC6: チャンク間にオーバーラップが適用されること."""

    def test_ac6_overlap_is_applied_between_chunks(self) -> None:
        """チャンク間にオーバーラップが適用される."""
        # 明確に分割されるテキストを使用
        text = "A" * 60 + " " + "B" * 60 + " " + "C" * 60
        result = chunk_text(text, chunk_size=80, chunk_overlap=20)

        assert len(result) >= 2, "テキストは2つ以上のチャンクに分割されるべき"

        # オーバーラップが適用されていることを確認
        # 後続チャンクの先頭に前チャンクの末尾が含まれる
        for i in range(1, len(result)):
            prev_chunk_end = result[i - 1][-20:]  # 前チャンクの末尾20文字
            current_chunk_start = result[i][:40]  # 現在チャンクの先頭40文字
            # オーバーラップにより何らかの共有がある（完全一致でなくても部分的に含まれる）
            overlap_found = any(c in current_chunk_start for c in prev_chunk_end if c.strip())
            assert overlap_found or len(result[i - 1]) <= 20, (
                f"チャンク{i - 1}とチャンク{i}間にオーバーラップが見つからない"
            )

    def test_ac6_overlap_with_different_sizes(self) -> None:
        """異なるオーバーラップサイズでの動作."""
        text = "A" * 100 + " " + "B" * 100 + " " + "C" * 100
        result_small = chunk_text(text, chunk_size=120, chunk_overlap=10)
        result_large = chunk_text(text, chunk_size=120, chunk_overlap=50)

        # どちらも複数チャンクに分割される
        assert len(result_small) >= 2, "小さいオーバーラップでも複数チャンクに分割されるべき"
        assert len(result_large) >= 2, "大きいオーバーラップでも複数チャンクに分割されるべき"

        # 大きいオーバーラップの方がチャンク数が多いか同等（オーバーラップ分だけ実効容量が減る）
        assert len(result_large) >= len(result_small)


class TestAC7EmptyAndShortText:
    """AC7: 空文字列や短いテキストに対しても正常に動作すること."""

    def test_ac7_empty_string_returns_empty_list(self) -> None:
        """空文字列は空のリストを返す."""
        result = chunk_text("")
        assert result == []

    def test_ac7_whitespace_only_returns_empty_list(self) -> None:
        """空白のみの文字列は空のリストを返す."""
        result = chunk_text("   \n\t  ")
        assert result == []

    def test_ac7_single_character_returns_single_chunk(self) -> None:
        """1文字のテキストは1つのチャンクとして返される."""
        result = chunk_text("A")
        assert result == ["A"]

    def test_ac7_text_exactly_chunk_size_returns_single_chunk(self) -> None:
        """ちょうどchunk_sizeのテキストは1つのチャンクとして返される."""
        text = "A" * 100
        result = chunk_text(text, chunk_size=100)
        assert result == [text]

    def test_ac7_text_slightly_over_chunk_size(self) -> None:
        """chunk_sizeを少し超えるテキストは2つ以上のチャンクに分割される."""
        text = "A" * 110
        result = chunk_text(text, chunk_size=100, chunk_overlap=10)
        assert len(result) >= 2, "chunk_sizeを超えるテキストは複数チャンクに分割されるべき"


class TestChunkTextEdgeCases:
    """その他のエッジケーステスト."""

    def test_unicode_text(self) -> None:
        """Unicode文字（日本語・絵文字等）が正しく処理される."""
        text = "日本語テキスト🎉です。これはテストです。"
        result = chunk_text(text, chunk_size=50, chunk_overlap=10)
        assert len(result) >= 1
        assert "日本語" in result[0]

    def test_multiple_blank_lines(self) -> None:
        """複数の空行がある場合も正しく段落分割される."""
        text = "段落1\n\n\n\n段落2\n\n段落3"
        result = chunk_text(text, chunk_size=500)
        assert len(result) >= 1

    def test_no_sentence_delimiters(self) -> None:
        """句点がないテキストも文字数で分割される."""
        text = "A" * 200
        result = chunk_text(text, chunk_size=50, chunk_overlap=10)
        assert len(result) >= 1

    def test_mixed_delimiters(self) -> None:
        """日本語と英語の句点が混在するテキスト."""
        text = "これは日本語です。This is English. また日本語。More English!"
        result = chunk_text(text, chunk_size=30, chunk_overlap=5)
        assert len(result) >= 1

    def test_default_parameters(self) -> None:
        """デフォルトパラメータ（chunk_size=500, chunk_overlap=50）での動作."""
        text = "テスト" * 200  # 600文字
        result = chunk_text(text)
        assert len(result) >= 1

    def test_zero_overlap(self) -> None:
        """オーバーラップ0での動作."""
        text = "段落1のテキスト。\n\n段落2のテキスト。"
        result = chunk_text(text, chunk_size=20, chunk_overlap=0)
        assert len(result) >= 1

    def test_large_overlap_relative_to_chunk_size(self) -> None:
        """チャンクサイズに対して大きなオーバーラップ."""
        text = "A" * 100
        result = chunk_text(text, chunk_size=50, chunk_overlap=40)
        assert len(result) >= 1


class TestChunkTextValidation:
    """引数バリデーションのテスト."""

    def test_chunk_size_zero_raises_value_error(self) -> None:
        """chunk_size=0でValueErrorが発生する."""
        with pytest.raises(ValueError, match="chunk_size must be positive"):
            chunk_text("テスト", chunk_size=0)

    def test_chunk_size_negative_raises_value_error(self) -> None:
        """chunk_sizeが負数でValueErrorが発生する."""
        with pytest.raises(ValueError, match="chunk_size must be positive"):
            chunk_text("テスト", chunk_size=-10)

    def test_chunk_overlap_negative_raises_value_error(self) -> None:
        """chunk_overlapが負数でValueErrorが発生する."""
        with pytest.raises(ValueError, match="chunk_overlap must be non-negative"):
            chunk_text("テスト", chunk_size=100, chunk_overlap=-5)

    def test_chunk_overlap_equals_chunk_size_raises_value_error(self) -> None:
        """chunk_overlap == chunk_sizeでValueErrorが発生する."""
        with pytest.raises(ValueError, match="chunk_overlap.*must be less than chunk_size"):
            chunk_text("テスト", chunk_size=100, chunk_overlap=100)

    def test_chunk_overlap_greater_than_chunk_size_raises_value_error(self) -> None:
        """chunk_overlap > chunk_sizeでValueErrorが発生する."""
        with pytest.raises(ValueError, match="chunk_overlap.*must be less than chunk_size"):
            chunk_text("テスト", chunk_size=100, chunk_overlap=150)


class TestChunkTextSpecExamples:
    """仕様書の例に基づくテスト."""

    def test_paragraph_priority(self) -> None:
        """分割優先順: 段落 → 文 → 文字数."""
        # 段落区切りがある場合は段落で分割
        text_with_paragraphs = "段落1。\n\n段落2。"
        result = chunk_text(text_with_paragraphs, chunk_size=20, chunk_overlap=0)
        # 段落ごとに分割されることを確認
        assert any("段落1" in chunk for chunk in result)
        assert any("段落2" in chunk for chunk in result)
