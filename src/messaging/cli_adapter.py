"""CLI用メッセージングアダプター.

仕様: docs/specs/features/cli-adapter.md
"""

from __future__ import annotations

from pathlib import Path

from src.llm.base import Message
from src.messaging.port import ArticleCard, IncomingFile, MessagingPort, ThreadRef


class CliAdapter(MessagingPort):
    """CLI（stdout/ローカルファイル）向けアダプター.

    仕様: docs/specs/features/cli-adapter.md
    """

    def __init__(self, user_id: str = "cli-user") -> None:
        self._user_id = user_id

    async def send_message(self, text: str, thread_id: str, channel: str) -> None:
        """テキストを標準出力に表示する."""
        print(f"\n{text}\n")

    async def upload_file(
        self,
        content: str,
        filename: str,
        thread_id: str,
        channel: str,
        comment: str,
    ) -> None:
        """ファイルをローカルに保存する."""
        path = Path(".tmp/cli_exports") / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"\n{comment}\nファイル保存先: {path}\n")

    async def read_file(self, file: IncomingFile) -> bytes:
        """CLI ではローカルパス（download_url）からファイルを読み込む."""
        return Path(file.download_url).read_bytes()

    async def post_header(self, channel: str, text: str) -> None:
        """配信見出しを標準出力に表示する."""
        print(f"\n=== {text} ===\n")

    async def start_feed_thread(self, channel: str, feed_name: str) -> ThreadRef:
        """フィード名を表示し、スレッド参照（CLI ではチャンネル）を返す."""
        print(f"\n[{feed_name}]")
        return ThreadRef(channel=channel, thread_key=channel)

    async def post_article_card(self, thread: ThreadRef, card: ArticleCard) -> None:
        """記事カードを標準出力に表示する."""
        print(f"- {card.title} ({card.datetime_str})\n  {card.url}\n  {card.summary}\n")

    async def post_footer(self, channel: str, text: str) -> None:
        """配信フッターを標準出力に表示する."""
        print(f"\n{text}\n")

    async def fetch_thread_history(
        self, channel: str, thread_id: str, current_message_id: str
    ) -> list[Message] | None:
        """CLI ではスレッド履歴なし（DBフォールバックを使用）."""
        return None

    def get_format_instruction(self) -> str:
        """CLI ではフォーマット指示なし（プレーンテキスト）."""
        return ""

    def get_bot_user_id(self) -> str:
        """CLI ボットのユーザーID."""
        return "cli-bot"
