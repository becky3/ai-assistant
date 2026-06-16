"""MessagingPort / CliAdapter / IncomingMessage のテスト (Issue #496)."""

from __future__ import annotations

from pathlib import Path

from src.messaging.cli_adapter import CliAdapter
from src.messaging.port import IncomingFile, IncomingMessage, MessagingPort


def test_incoming_message_fields() -> None:
    """IncomingMessage のフィールドが正しく構築される."""
    msg = IncomingMessage(
        user_id="U1",
        text="hello",
        thread_id="t1",
        channel="C1",
        is_in_thread=False,
        message_id="m1",
    )
    assert msg.user_id == "U1"
    assert msg.text == "hello"
    assert msg.thread_id == "t1"
    assert msg.channel == "C1"
    assert msg.is_in_thread is False
    assert msg.message_id == "m1"
    assert msg.files is None


def test_incoming_message_with_files() -> None:
    """IncomingMessage にファイル情報（IncomingFile）を付与できる."""
    files = [
        IncomingFile(
            name="test.csv",
            mimetype="text/csv",
            download_url="https://example.com/test.csv",
        )
    ]
    msg = IncomingMessage(
        user_id="U1",
        text="feed import",
        thread_id="t1",
        channel="C1",
        is_in_thread=False,
        message_id="m1",
        files=files,
    )
    assert msg.files is not None
    assert len(msg.files) == 1


async def test_cli_adapter_read_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """CliAdapter の read_file はローカルパスからバイト列を読む."""
    target = tmp_path / "data.csv"
    target.write_text("url,name\nhttps://x,y", encoding="utf-8")
    adapter = CliAdapter()
    content = await adapter.read_file(
        IncomingFile(name="data.csv", mimetype="text/csv", download_url=str(target))
    )
    assert content.decode("utf-8").startswith("url,name")


def test_cli_adapter_is_messaging_port() -> None:
    """CliAdapter は MessagingPort のサブクラスである."""
    adapter = CliAdapter(user_id="test-user")
    assert isinstance(adapter, MessagingPort)


def test_cli_adapter_get_format_instruction() -> None:
    """CliAdapter のフォーマット指示は空文字列."""
    adapter = CliAdapter()
    assert adapter.get_format_instruction() == ""


def test_cli_adapter_get_bot_user_id() -> None:
    """CliAdapter の bot user id は 'cli-bot'."""
    adapter = CliAdapter()
    assert adapter.get_bot_user_id() == "cli-bot"


async def test_cli_adapter_fetch_thread_history_returns_none() -> None:
    """CliAdapter のスレッド履歴取得は None を返す."""
    adapter = CliAdapter()
    result = await adapter.fetch_thread_history("cli", "t1", "m1")
    assert result is None


async def test_cli_adapter_send_message(capsys) -> None:  # type: ignore[no-untyped-def]
    """CliAdapter の send_message は stdout に出力する."""
    adapter = CliAdapter()
    await adapter.send_message("テスト出力", "t1", "cli")
    captured = capsys.readouterr()
    assert "テスト出力" in captured.out


async def test_cli_adapter_upload_file(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """CliAdapter の upload_file はローカルファイルに保存する."""
    monkeypatch.chdir(tmp_path)

    adapter = CliAdapter()
    await adapter.upload_file(
        content="url,name\nhttp://example.com,test",
        filename="feeds.csv",
        thread_id="t1",
        channel="cli",
        comment="エクスポート完了",
    )

    saved = Path(".tmp/cli_exports/feeds.csv")
    assert saved.exists()
    assert "url,name" in saved.read_text(encoding="utf-8")
