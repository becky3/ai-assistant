# F8: ボットのスレッド対応（Slack スレッド履歴取得）

## 概要

Slackスレッドでの会話の連続性を保つため、スレッド内の過去メッセージを Slack API から取得し、
プロンプトにやり取りの履歴として渡す。遡る件数は環境変数で変更可能（デフォルト: 20件）。

## 背景・課題

### 現状

- `ChatService._load_history()` は **DB（conversations テーブル）** からのみ履歴を取得している
- DB に保存されるのは **ボットが処理したメッセージのみ**（ユーザーの発言 + ボットの応答）
- スレッド内で他のユーザーが発言した内容や、ボットが処理する前の発言は DB に存在しない

### 課題

1. **スレッド途中参加**: ボットがスレッドの途中から呼ばれた場合、それ以前のやり取りのコンテキストがない
2. **複数ユーザーの会話**: スレッド内で複数ユーザーが会話している場合、ボットは自分が関わった部分しか把握できない
3. **コンテキスト不足**: スレッド全体の流れを把握せずに応答するため、的外れな回答になることがある

## ユーザーストーリー

- ユーザーとして、スレッド内でボットにメンションしたとき、スレッドの過去のやり取りを踏まえた応答が欲しい
- ユーザーとして、スレッドの途中からボットを呼んでも、それまでの文脈を理解した応答が欲しい
- 管理者として、コスト・パフォーマンスのバランスを取るため、履歴取得件数を設定で調整したい

## 入出力仕様

### 入力

- Slack の `app_mention` / `message` イベント
  - `event.thread_ts`: スレッドのタイムスタンプ（スレッド内の場合）
  - `event.ts`: メッセージのタイムスタンプ（トリガーメッセージの識別、およびスレッド外時の thread_ts 代替に使用）
- Slack API `conversations.replies` で取得するスレッド内メッセージ

### 出力

- LLM に渡すメッセージリストにスレッド履歴が含まれる（変更なし: スレッド内にテキストで応答）

### 具体例

```
スレッドの状態:
  User A: "Pythonの非同期処理について議論しよう"
  User B: "asyncioがいいと思う"
  User A: "awaitの使い方がよくわからない"
  User A: "@bot ここまでの議論を踏まえて、asyncioの使い方を教えて"

ボットに渡されるコンテキスト:
  [system] アシスタントの性格設定
  [user] User A: "Pythonの非同期処理について議論しよう"
  [user] User B: "asyncioがいいと思う"
  [user] User A: "awaitの使い方がよくわからない"
  [user] User A: "ここまでの議論を踏まえて、asyncioの使い方を教えて"

→ ボットはスレッド全体の文脈を踏まえて応答
```

## 受け入れ条件

- [ ] AC1: スレッド内でメンションされた場合、Slack API からスレッドの過去メッセージを取得してプロンプトに含める
- [ ] AC2: 取得件数は環境変数 `THREAD_HISTORY_LIMIT` で変更可能（デフォルト: 20件）
- [ ] AC3: ボット自身の過去メッセージは `assistant` ロール、他ユーザーのメッセージは `user` ロールとして渡す（複数ユーザーの発言を区別するためユーザーIDを付与）
- [ ] AC4: スレッド外（トップレベルメッセージ）からの呼び出し時は従来どおり DB 履歴を使用する
- [ ] AC5: Slack API 呼び出し失敗時は DB 履歴にフォールバックし、エラーログを出力する
- [ ] AC6: 自動返信チャンネル（F6）でのスレッド内メッセージにも同様に対応する
- [ ] AC7: 既存テストが壊れないこと

## 技術設計

### 1. 設定追加

**`src/config/settings.py`**

```python
class Settings(BaseSettings):
    # ... 既存の設定 ...

    # Thread History
    thread_history_limit: int = Field(default=20, ge=1, le=100)
```

**`.env.example`**

```bash
# Thread History (max messages to fetch from Slack thread)
THREAD_HISTORY_LIMIT=20
```

### 2. Slack スレッド履歴取得

**新規: `src/services/thread_history.py`**

```python
"""Slackスレッド履歴取得サービス
仕様: docs/specs/f8-thread-support.md
"""

from __future__ import annotations

import logging
from typing import Any

from slack_sdk.web.async_client import AsyncWebClient

from src.llm.base import Message

logger = logging.getLogger(__name__)


class ThreadHistoryService:
    """Slackスレッドから会話履歴を取得するサービス.

    仕様: docs/specs/f8-thread-support.md
    """

    def __init__(
        self,
        slack_client: AsyncWebClient,
        bot_user_id: str,
        limit: int = 20,
    ) -> None:
        self._client = slack_client
        self._bot_user_id = bot_user_id
        self._limit = limit

    async def fetch_thread_messages(
        self,
        channel: str,
        thread_ts: str,
        current_ts: str,
    ) -> list[Message] | None:
        """スレッドのメッセージ履歴を取得し、LLM用のMessageリストに変換する.

        Args:
            channel: チャンネルID
            thread_ts: スレッドの親メッセージのタイムスタンプ
            current_ts: 今回のトリガーメッセージのタイムスタンプ（除外用）

        Returns:
            Message のリスト。取得失敗時は None（呼び出し元でフォールバック判定）。
        """
        try:
            result = await self._client.conversations_replies(
                channel=channel,
                ts=thread_ts,
                limit=self._limit,
            )
            raw_messages: list[dict[str, Any]] = result.get("messages", [])
        except Exception:
            logger.exception(
                "Failed to fetch thread replies: channel=%s, thread_ts=%s",
                channel,
                thread_ts,
            )
            return None

        if not raw_messages:
            return []

        # 今回のトリガーメッセージを除外（ChatService 側で追加されるため）
        history_messages = [m for m in raw_messages if m.get("ts") != current_ts]

        # limit 件に絞る（古い方から切り捨て）
        if len(history_messages) > self._limit:
            history_messages = history_messages[-self._limit:]

        messages: list[Message] = []
        for msg in history_messages:
            # サブタイプ付き（編集通知等）やテキストなしのメッセージはスキップ
            text = msg.get("text", "")
            if not text or msg.get("subtype"):
                continue

            user_id = msg.get("user", "")
            if user_id == self._bot_user_id:
                role = "assistant"
                content = text
            else:
                role = "user"
                # 複数ユーザーの発言を区別するためユーザーIDを付与
                content = f"<@{user_id}>: {text}" if user_id else text

            messages.append(Message(role=role, content=content))

        return messages
```

### 3. ChatService の変更

**`src/services/chat.py`**

```python
class ChatService:
    def __init__(
        self,
        llm: LLMProvider,
        session_factory: async_sessionmaker[AsyncSession],
        system_prompt: str = "",
        thread_history_service: ThreadHistoryService | None = None,  # 追加
    ) -> None:
        self._llm = llm
        self._session_factory = session_factory
        self._system_prompt = system_prompt
        self._thread_history = thread_history_service  # 追加

    async def respond(
        self,
        user_id: str,
        text: str,
        thread_ts: str,
        channel: str = "",          # 追加
        is_in_thread: bool = False,  # 追加
        current_ts: str = "",        # 追加: トリガーメッセージの ts
    ) -> str:
        """ユーザーメッセージに対する応答を生成し、履歴を保存する."""
        async with self._session_factory() as session:
            # スレッド内かつ ThreadHistoryService が利用可能な場合は Slack API から取得
            history: list[Message] | None = None
            if is_in_thread and self._thread_history and channel:
                history = await self._thread_history.fetch_thread_messages(
                    channel=channel,
                    thread_ts=thread_ts,
                    current_ts=current_ts,
                )

            # Slack API から取得できなかった場合は DB フォールバック
            if history is None:
                history = await self._load_history(session, thread_ts)

            # メッセージリストを構築
            messages: list[Message] = []
            if self._system_prompt:
                messages.append(Message(role="system", content=self._system_prompt))
            messages.extend(history)
            messages.append(Message(role="user", content=text))

            # LLM 応答生成
            response = await self._llm.complete(messages)

            # 履歴を保存（DB への保存は従来どおり維持）
            session.add(Conversation(
                slack_user_id=user_id,
                thread_ts=thread_ts,
                role="user",
                content=text,
            ))
            session.add(Conversation(
                slack_user_id=user_id,
                thread_ts=thread_ts,
                role="assistant",
                content=response.content,
            ))
            await session.commit()

            return response.content
```

**変更ポイント**:
- `thread_history_service` をオプショナル引数として追加（後方互換性を維持）
- `channel` と `is_in_thread` を `respond()` に追加
- Slack API 取得 → 失敗時は DB フォールバックの 2段構え
- DB への保存は従来どおり維持（将来のフォールバック用）

### 4. ハンドラの変更

**`src/slack/handlers.py`**

```python
async def _process_message(
    user_id: str,
    cleaned_text: str,
    thread_ts: str,
    say: object,
    files: list[dict[str, object]] | None = None,
    channel: str = "",           # 追加
    is_in_thread: bool = False,  # 追加
    current_ts: str = "",        # 追加: トリガーメッセージの ts
) -> None:
    # ... 既存のコマンド処理 ...

    # デフォルト: ChatService で応答
    try:
        response = await chat_service.respond(
            user_id=user_id,
            text=cleaned_text,
            thread_ts=thread_ts,
            channel=channel,           # 追加
            is_in_thread=is_in_thread,  # 追加
            current_ts=current_ts,      # 追加
        )
        # ...
```

```python
@app.event("app_mention")
async def handle_mention(event: dict, say: object) -> None:
    user_id: str = event.get("user", "")
    text: str = event.get("text", "")
    raw_thread_ts: str | None = event.get("thread_ts")
    event_ts: str = event.get("ts", "")      # 追加
    thread_ts: str = raw_thread_ts or event_ts
    files: list[dict[str, object]] | None = event.get("files")
    channel: str = event.get("channel", "")  # 追加

    cleaned_text = strip_mention(text)
    if not cleaned_text:
        return

    await _process_message(
        user_id, cleaned_text, thread_ts, say, files,
        channel=channel,                          # 追加
        is_in_thread=raw_thread_ts is not None,   # 追加
        current_ts=event_ts,                      # 追加
    )
```

```python
@app.event("message")
async def handle_message(event: dict, say: object) -> None:
    # ... 既存のフィルタリング処理 ...

    raw_thread_ts: str | None = event.get("thread_ts")
    event_ts: str = event.get("ts", "")      # 追加
    thread_ts: str = raw_thread_ts or event_ts
    channel: str = event.get("channel", "")

    await _process_message(
        user_id, cleaned_text, thread_ts, say, files,
        channel=channel,                          # 追加
        is_in_thread=raw_thread_ts is not None,   # 追加
        current_ts=event_ts,                      # 追加
    )
```

### 5. main.py の変更

```python
from src.services.thread_history import ThreadHistoryService

async def main() -> None:
    # ... 既存の初期化 ...

    # Slack アプリ
    app = create_app(settings)
    slack_client = app.client

    # Bot User ID を取得（エラーハンドリング付き）
    try:
        auth_result = await slack_client.auth_test()
    except Exception as e:
        raise RuntimeError(f"Failed to call Slack auth_test: {e}") from e

    bot_user_id: str | None = auth_result.get("user_id") if isinstance(auth_result, dict) else None
    if not bot_user_id:
        raise RuntimeError("Slack auth_test response does not contain 'user_id'.")

    # スレッド履歴サービス
    thread_history_service = ThreadHistoryService(
        slack_client=slack_client,
        bot_user_id=bot_user_id,
        limit=settings.thread_history_limit,
    )

    # チャットサービス（thread_history_service を追加）
    chat_service = ChatService(
        llm=chat_llm,
        session_factory=session_factory,
        system_prompt=system_prompt,
        thread_history_service=thread_history_service,  # 追加
    )

    # ...
```

### 6. スレッド判定ロジック

| 条件 | `thread_ts` | `is_in_thread` | 履歴ソース |
|------|------------|----------------|-----------|
| トップレベルメッセージ | `event.ts` | `False` | DB |
| スレッド内メッセージ | `event.thread_ts` | `True` | Slack API → DB フォールバック |

**判定方法**: `event.thread_ts` が存在する場合 = スレッド内メッセージ

## 関連ファイル

| ファイル | 役割 |
|---------|---------|
| `src/config/settings.py` | `thread_history_limit` 設定追加 |
| `src/services/thread_history.py` | **新規** スレッド履歴取得サービス |
| `src/services/chat.py` | `thread_history_service` 引数追加、Slack API 優先ロジック |
| `src/slack/handlers.py` | `channel` と `is_in_thread` をイベントから抽出して伝搬 |
| `src/main.py` | `ThreadHistoryService` 初期化、`auth_test()` で Bot User ID 取得 |
| `.env.example` | `THREAD_HISTORY_LIMIT` 追加 |
| `tests/test_thread_history.py` | **新規** ThreadHistoryService のテスト |
| `tests/test_chat_service.py` | スレッド履歴関連テスト追加 |
| `docs/specs/f1-chat.md` | スレッド履歴関連の AC 追加・更新（実装PRで更新予定） |

## テスト方針

### 新規テスト (`tests/test_thread_history.py`)

```python
# AC1: Slack API からスレッドメッセージを取得できる
def test_ac1_fetch_thread_messages_from_slack_api():

# AC2: limit 設定に従って件数が制限される
def test_ac2_thread_history_respects_limit():

# AC3: ボットのメッセージは assistant ロール、他は user ロール
def test_ac3_bot_messages_mapped_to_assistant_role():

# AC5: Slack API 失敗時に None を返す（フォールバック用）
def test_ac5_returns_none_on_api_failure():

# サブタイプ付きメッセージはスキップされる
def test_subtype_messages_are_skipped():
```

### 既存テスト更新 (`tests/test_chat_service.py`)

```python
# AC4: スレッド外ではDB履歴を使用する（既存テストが壊れないことの確認）
def test_ac4_non_thread_uses_db_history():

# AC5: Slack API 失敗時に DB フォールバック
def test_ac5_fallback_to_db_on_api_failure():

# AC6: 自動返信チャンネルのスレッド内でもスレッド履歴が使用される
def test_ac6_auto_reply_channel_thread_uses_slack_api_history():

# スレッド内で Slack API 履歴が使用される
def test_thread_uses_slack_api_history():

# AC7: 既存テストが壊れないこと（CI での全テスト実行で確認）
```

## 注意事項

1. **Slack API レートリミット**: `conversations.replies` は Tier 3（50 req/min）。通常利用では問題ないが、高頻度利用時は注意
2. **`conversations.replies` の `limit` 挙動**: API の `limit` パラメータは最大取得件数を指定するが、スレッド全件が `limit` 以下の場合はすべて返される。取得後にアプリケーション側でも件数制限を行い、`limit` を超えた場合は最新 `limit` 件を使用する（古いメッセージを切り捨て）
3. **メンションの除去**: Slack API から取得したメッセージ内の `<@BOT_ID>` は除去不要（文脈理解に有用）
4. **DB 保存の維持**: Slack API から履歴を取得する場合でも、DB への保存は従来どおり行う。これにより API 失敗時のフォールバックが機能する
5. **後方互換性**: `ThreadHistoryService` はオプショナルなので、設定しない場合は従来どおり DB のみで動作する
6. **Bot User ID**: `auth_test()` で取得するため、起動時に Slack API 呼び出しが1回追加される
7. **トークン上限**: スレッド内のメッセージが長文の場合、LLM のコンテキストウィンドウを圧迫する可能性がある。現段階では件数制限のみとし、トークン上限によるメッセージ切り捨ては将来課題とする
