"""Feed要約の速度・品質計測スクリプト.

reasoning_effort あり/なしの比較ができる。

使い方:
    # config.toml の設定値で実行
    uv run python scripts/test_summarize_speed.py

    # reasoning_effort を明示指定（none / low / medium / high）
    uv run python scripts/test_summarize_speed.py none
    uv run python scripts/test_summarize_speed.py high

    # あり/なし比較モード
    uv run python scripts/test_summarize_speed.py --compare
"""

from __future__ import annotations

import asyncio
import sys
import time

from src.compat import configure_stdio_encoding

from src.config.settings import get_settings
from src.llm.factory import create_local_provider
from src.services.summarizer import Summarizer

# テスト用の記事データ（実際のRSS記事を模擬）
TEST_ARTICLES = [
    {
        "title": "Python 3.13 introduces new features for async programming",
        "url": "https://example.com/python-3.13",
        "description": (
            "Python 3.13 brings significant improvements to async programming, "
            "including TaskGroup enhancements, better error handling in asyncio, "
            "and new APIs for structured concurrency."
        ),
    },
    {
        "title": "Understanding Vector Databases for AI Applications",
        "url": "https://example.com/vector-db",
        "description": (
            "This article explains how vector databases work, their role in AI "
            "applications like RAG, and compares popular options such as ChromaDB, "
            "Pinecone, and Weaviate."
        ),
    },
    {
        "title": "Best Practices for Building Slack Bots with Python",
        "url": "https://example.com/slack-bots",
        "description": (
            "A comprehensive guide on building production-ready Slack bots using "
            "Python and slack-bolt, covering event handling, rate limiting, and "
            "deployment strategies."
        ),
    },
]


async def run_test(reasoning_effort: str | None) -> list[tuple[str, str, float]]:
    """指定した reasoning_effort で要約を実行し、結果を返す."""
    settings = get_settings()
    llm = create_local_provider(settings)
    summarizer = Summarizer(llm=llm, reasoning_effort=reasoning_effort)

    available = await llm.is_available()
    if not available:
        print("ERROR: LM Studio is not available")
        sys.exit(1)

    results: list[tuple[str, str, float]] = []
    for article in TEST_ARTICLES:
        start = time.perf_counter()
        summary = await summarizer.summarize(
            title=article["title"],
            url=article["url"],
            description=article["description"],
        )
        elapsed = time.perf_counter() - start
        results.append((article["title"], summary, elapsed))
    return results


def print_results(label: str, results: list[tuple[str, str, float]]) -> None:
    """結果を表示する."""
    print(f"\n{'=' * 70}")
    print(f"  {label}")
    print(f"{'=' * 70}")
    total = 0.0
    for i, (title, summary, elapsed) in enumerate(results, 1):
        total += elapsed
        print(f"\n[{i}] {elapsed:.1f}s — {title[:60]}")
        print(f"    {summary}")
    avg = total / len(results)
    print(f"\n  Total: {total:.1f}s | Avg: {avg:.1f}s/article")


async def main() -> None:
    settings = get_settings()
    print(f"Model: {settings.lmstudio_model}")
    print(f"LM Studio URL: {settings.lmstudio_base_url}")

    args = sys.argv[1:]

    if "--compare" in args:
        # 比較モード: reasoning あり(デフォルト=None) と なし(none) を比較
        print("\n--- Compare mode: default vs none ---")

        results_default = await run_test(reasoning_effort=None)
        print_results("reasoning_effort = (default/未指定)", results_default)

        results_none = await run_test(reasoning_effort="none")
        print_results("reasoning_effort = none", results_none)

        # サマリー比較
        total_default = sum(e for _, _, e in results_default)
        total_none = sum(e for _, _, e in results_none)
        speedup = total_default / total_none if total_none > 0 else 0
        print(f"\n{'=' * 70}")
        print(f"  Speedup: {speedup:.1f}x faster with reasoning_effort=none")
        print(f"  ({total_default:.1f}s -> {total_none:.1f}s)")
        print(f"{'=' * 70}")
    else:
        # 単発モード
        valid_efforts = {"none", "low", "medium", "high"}
        if args:
            if args[0] not in valid_efforts:
                print(f"ERROR: invalid reasoning_effort '{args[0]}'")
                print(f"Valid values: {', '.join(sorted(valid_efforts))}")
                sys.exit(1)
            effort: str | None = args[0]
        else:
            effort = settings.feed_summarize_reasoning_effort
        print(f"reasoning_effort: {effort}")

        results = await run_test(reasoning_effort=effort)
        print_results(f"reasoning_effort = {effort}", results)


if __name__ == "__main__":
    configure_stdio_encoding()
    asyncio.run(main())
