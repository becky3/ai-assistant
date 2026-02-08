"""テキストチャンキングモジュール

仕様: docs/specs/f9-rag-knowledge.md
"""

from __future__ import annotations

import re


def chunk_text(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> list[str]:
    """テキストをオーバーラップ付きチャンクに分割する.

    仕様: docs/specs/f9-rag-knowledge.md

    分割優先順: 段落 → 文 → 文字数
    外部依存なし（LangChain不要）。

    Args:
        text: 分割対象のテキスト
        chunk_size: 各チャンクの最大文字数（デフォルト: 500）
        chunk_overlap: チャンク間のオーバーラップ文字数（デフォルト: 50）

    Returns:
        分割されたチャンクのリスト
    """
    if not text or not text.strip():
        return []

    text = text.strip()

    if len(text) <= chunk_size:
        return [text]

    # 段落で分割を試みる
    paragraphs = _split_by_paragraphs(text)
    chunks = _merge_into_chunks(paragraphs, chunk_size, chunk_overlap)

    return chunks


def _split_by_paragraphs(text: str) -> list[str]:
    """テキストを段落（空行区切り）で分割する."""
    # 空行（2つ以上の連続改行）で分割
    paragraphs = re.split(r"\n\s*\n", text)
    return [p.strip() for p in paragraphs if p.strip()]


def _split_by_sentences(text: str) -> list[str]:
    """テキストを文（句点区切り）で分割する."""
    # 日本語の句点（。）と英語のピリオド（.）で分割
    # ただし、ピリオド後にスペースまたは改行がある場合のみ
    sentences = re.split(r"(?<=[。.!?])\s*", text)
    return [s.strip() for s in sentences if s.strip()]


def _split_by_characters(text: str, chunk_size: int) -> list[str]:
    """テキストを指定文字数で分割する."""
    chunks = []
    for i in range(0, len(text), chunk_size):
        chunks.append(text[i : i + chunk_size])
    return chunks


def _merge_into_chunks(
    segments: list[str],
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    """セグメントをチャンクサイズに収まるようにマージする.

    大きすぎるセグメントは文単位で分割し、それでも大きい場合は文字数で分割する。
    """
    chunks: list[str] = []
    current_chunk = ""
    overlap_buffer = ""

    for segment in segments:
        # セグメントがチャンクサイズより大きい場合は分割
        if len(segment) > chunk_size:
            # 現在のチャンクを確定
            if current_chunk:
                chunks.append(current_chunk)
                overlap_buffer = _get_overlap(current_chunk, chunk_overlap)
                current_chunk = ""

            # セグメントを文単位で分割
            sub_segments = _split_by_sentences(segment)
            if len(sub_segments) == 1 and len(sub_segments[0]) > chunk_size:
                # 文単位で分割できない場合は文字数で分割
                sub_segments = _split_by_characters(segment, chunk_size - chunk_overlap)

            # 分割したセグメントを再帰的に処理
            sub_chunks = _merge_into_chunks(sub_segments, chunk_size, chunk_overlap)
            for i, sub_chunk in enumerate(sub_chunks):
                if i == 0 and overlap_buffer:
                    # 最初のサブチャンクにオーバーラップを付与
                    combined = overlap_buffer + " " + sub_chunk
                    if len(combined) <= chunk_size:
                        chunks.append(combined)
                    else:
                        chunks.append(sub_chunk)
                else:
                    chunks.append(sub_chunk)
            if sub_chunks:
                overlap_buffer = _get_overlap(sub_chunks[-1], chunk_overlap)
            continue

        # 現在のチャンクにセグメントを追加
        if current_chunk:
            combined = current_chunk + "\n\n" + segment
        else:
            combined = overlap_buffer + " " + segment if overlap_buffer else segment
            combined = combined.strip()

        if len(combined) <= chunk_size:
            current_chunk = combined
        else:
            # チャンクを確定して新しいチャンクを開始
            if current_chunk:
                chunks.append(current_chunk)
                overlap_buffer = _get_overlap(current_chunk, chunk_overlap)
            current_chunk = overlap_buffer + " " + segment if overlap_buffer else segment
            current_chunk = current_chunk.strip()

            # それでもチャンクサイズを超える場合は強制分割
            if len(current_chunk) > chunk_size:
                sub_chunks = _split_by_characters(current_chunk, chunk_size - chunk_overlap)
                for sub_chunk in sub_chunks[:-1]:
                    chunks.append(sub_chunk)
                current_chunk = sub_chunks[-1] if sub_chunks else ""
                overlap_buffer = ""

    # 残りのチャンクを追加
    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def _get_overlap(text: str, overlap_size: int) -> str:
    """テキストの末尾からオーバーラップ用の文字列を取得する."""
    if len(text) <= overlap_size:
        return text
    return text[-overlap_size:]
