"""配信カードの表示テスト用スクリプト.

ダミー記事5件をDBに挿入し、Slackに配信する。
テスト後にダミーデータは自動でクリーンアップされる。

使い方:
    uv run python scripts/test_delivery.py              # デフォルト (.env の設定)
    uv run python scripts/test_delivery.py horizontal   # 横長形式
    uv run python scripts/test_delivery.py vertical     # 縦長形式
"""

from __future__ import annotations

import asyncio
import random
import sys
import uuid

from slack_sdk.web.async_client import AsyncWebClient

from src.config.settings import get_settings
from src.db.models import Article, Feed
from src.db.session import get_session_factory, init_db
from src.scheduler.jobs import format_daily_digest

# --- テスト用ダミー記事データ ---
DUMMY_ARTICLES = [
    {
        "category": "Python",
        "title": "Python 3.14 で追加された新しいパターンマッチング構文",
        "url": f"https://example.com/python-pattern-matching-{uuid.uuid4().hex[:8]}",
        "summary": (
            "Python 3.14 では match-case 文がさらに強化され、"
            "ガード式やネストパターンの記述が簡潔になりました。"
            "特に型チェックとの組み合わせが便利です。"
        ),
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c3/Python-logo-notext.svg/1200px-Python-logo-notext.svg.png",
    },
    {
        "category": "Python",
        "title": "asyncio 完全ガイド：非同期処理のベストプラクティス",
        "url": f"https://example.com/asyncio-guide-{uuid.uuid4().hex[:8]}",
        "summary": (
            "asyncio の TaskGroup や timeout を活用した実践的なパターン集。"
            "並行処理のエラーハンドリングやキャンセル処理の正しい書き方を解説します。"
        ),
        "image_url": None,  # 画像なしのケース
    },
    {
        "category": "機械学習",
        "title": "Transformer アーキテクチャの最新動向 2026",
        "url": f"https://example.com/transformer-2026-{uuid.uuid4().hex[:8]}",
        "summary": (
            "Attention 機構の改善により推論速度が 3 倍に向上。"
            "Mixture of Experts (MoE) と組み合わせた新手法が注目を集めています。"
            "特にエッジデバイスでの動作が現実的になりました。"
        ),
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/8/8a/Dall-e_3_%28jan_%2724%29_artificial_intelligence_702489.png/1200px-Dall-e_3_%28jan_%2724%29_artificial_intelligence_702489.png",
    },
    {
        "category": "機械学習",
        "title": "ローカルLLMの性能比較：Llama 4 vs Mistral 3",
        "url": f"https://example.com/local-llm-compare-{uuid.uuid4().hex[:8]}",
        "summary": (
            "ローカル環境で動作する主要LLMのベンチマーク結果。"
            "コーディングタスクでは Llama 4 が優勢、"
            "日本語対応では Mistral 3 が高精度を示しました。"
        ),
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/0/04/ChatGPT_logo.svg/1200px-ChatGPT_logo.svg.png",
    },
    {
        "category": "Web開発",
        "title": "Slack Block Kit デザインパターン集",
        "url": f"https://example.com/slack-blockkit-{uuid.uuid4().hex[:8]}",
        "summary": (
            "Slack Block Kit を使ったリッチなメッセージの構築パターンをまとめました。"
            "accessory 画像の活用法、セクションの組み立て方、"
            "インタラクティブ要素の配置など実践的なノウハウを紹介します。"
        ),
        "image_url": None,  # 画像なしのケース
    },
]


async def main() -> None:
    settings = get_settings()

    if not settings.slack_bot_token or not settings.slack_news_channel_id:
        print("エラー: .env に SLACK_BOT_TOKEN と SLACK_NEWS_CHANNEL_ID を設定してください")
        return

    # 引数があればそれを使う、なければ .env の設定
    layout = settings.feed_card_layout
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg not in ("horizontal", "vertical"):
            print(f"エラー: レイアウトは 'horizontal' または 'vertical' を指定してください (got: {arg})")
            return
        layout = arg

    print(f"カードレイアウト: {layout}")
    print(f"配信先チャンネル: {settings.slack_news_channel_id}")
    print()

    await init_db()
    session_factory = get_session_factory()

    # テスト用フィードとダミー記事を作成
    test_feed_ids: dict[str, int] = {}
    test_article_ids: list[int] = []

    async with session_factory() as session:
        # カテゴリごとにテスト用フィードを作成
        categories = {a["category"] for a in DUMMY_ARTICLES}
        for cat in categories:
            test_url = f"https://test-feed-{uuid.uuid4().hex[:8]}.example.com/rss"
            feed = Feed(url=test_url, name=f"テスト ({cat})", category=cat, enabled=True)
            session.add(feed)
            await session.flush()
            test_feed_ids[cat] = feed.id

        # ダミー記事をランダム順で追加
        shuffled = random.sample(DUMMY_ARTICLES, len(DUMMY_ARTICLES))
        for data in shuffled:
            article = Article(
                feed_id=test_feed_ids[data["category"]],
                title=data["title"],
                url=data["url"],
                summary=data["summary"],
                image_url=data["image_url"],
                delivered=False,
            )
            session.add(article)
            await session.flush()
            test_article_ids.append(article.id)

        await session.commit()
        print(f"ダミー記事 {len(test_article_ids)} 件を作成しました")

    # Block Kit を生成して Slack に投稿
    async with session_factory() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(Article).where(Article.id.in_(test_article_ids))
        )
        articles = list(result.scalars().all())

        feed_result = await session.execute(
            select(Feed).where(Feed.id.in_(list(test_feed_ids.values())))
        )
        feeds = {f.id: f for f in feed_result.scalars().all()}

    digest = format_daily_digest(
        articles, feeds, layout=layout,
    )

    if not digest:
        print("配信する記事がありません")
        return

    client = AsyncWebClient(token=settings.slack_bot_token)
    channel = settings.slack_news_channel_id

    # ヘッダー
    await client.chat_postMessage(
        channel=channel,
        text=f":test_tube: 配信カードテスト (layout={layout})",
        blocks=[
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f":test_tube: 配信カードテスト (layout={layout})",
                },
            },
        ],
    )

    # カテゴリごと
    for category, blocks in digest.items():
        try:
            await client.chat_postMessage(
                channel=channel,
                text=f"【{category}】",
                blocks=blocks,
                unfurl_links=False,
                unfurl_media=False,
            )
            print(f"  投稿完了: {category}")
        except Exception as exc:
            error_msg = str(exc)
            if "invalid_blocks" in error_msg or "downloading image" in error_msg:
                # accessory付きsectionは accessory を除去して再投稿
                clean_blocks = []
                for b in blocks:
                    if b.get("type") == "image":
                        continue
                    if "accessory" in b:
                        b = {k: v for k, v in b.items() if k != "accessory"}
                    clean_blocks.append(b)

                print(f"  画像エラー、画像なしで再投稿: {category}")
                await client.chat_postMessage(
                    channel=channel,
                    text=f"【{category}】",
                    blocks=clean_blocks,
                    unfurl_links=False,
                    unfurl_media=False,
                )
            else:
                print(f"  投稿エラー: {category} - {error_msg}")

    # フッター
    await client.chat_postMessage(
        channel=channel,
        text=":bulb: これはテスト配信です",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": ":bulb: これはテスト配信です（ダミー記事のため実際のリンクは無効です）",
                },
            },
        ],
    )

    print()
    print("投稿完了！Slack を確認してください")

    # クリーンアップ: テスト用フィード・記事を削除
    async with session_factory() as session:
        from sqlalchemy import delete

        await session.execute(
            delete(Article).where(Article.id.in_(test_article_ids))
        )
        await session.execute(
            delete(Feed).where(Feed.id.in_(list(test_feed_ids.values())))
        )
        await session.commit()
    print("テスト用データをクリーンアップしました")


if __name__ == "__main__":
    asyncio.run(main())
