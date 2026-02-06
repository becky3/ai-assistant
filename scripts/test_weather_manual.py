"""天気予報MCPサーバーの手動動作確認スクリプト.

使い方: python scripts/test_weather_manual.py
"""

import asyncio
import sys
sys.path.insert(0, ".")

from importlib import import_module

mod = import_module("mcp-servers.weather.server")
get_weather = mod.get_weather


async def main() -> None:
    print("=== 天気予報MCPサーバー 手動テスト (気象庁API) ===\n")

    tests = [
        ("東京", "today", "今日の天気"),
        ("大阪", "tomorrow", "明日の天気"),
        ("札幌", "week", "週間予報"),
        ("福岡", "today", "今日の天気"),
        ("沖縄", "today", "今日の天気（部分一致テスト）"),
        ("存在しない場所XYZ", "today", "エラーケース"),
    ]

    for i, (location, date, desc) in enumerate(tests, 1):
        print(f"{i}. {location}の{desc}:")
        result = await get_weather(location, date)
        for line in result.split("\n"):
            print(f"   {line}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
