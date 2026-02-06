# F1: チャット応答

## 概要

Slackで @bot メンションされた際に、アシスタントの性格設定に基づいてスレッド内で会話応答を行う。

## ユーザーストーリー

- ユーザーとして、Slackでボットにメンションして質問したい。ボットはスレッド内で回答する。
- ユーザーとして、同じスレッド内で続けて質問し、文脈を保持した会話をしたい。
- 管理者として、アシスタントの性格・口調をYAML設定で変更したい。

## 入出力仕様

### 入力
- Slackの `app_mention` イベント
  - `event.text`: メンションを含むメッセージ本文
  - `event.user`: 送信者のSlack User ID
  - `event.channel`: チャンネルID
  - `event.thread_ts`: スレッドのタイムスタンプ（スレッド内の場合）

### 出力
- スレッド内にテキストメッセージで応答

### 具体例

```
入力: "@bot Pythonの非同期処理について教えて"
出力: "Pythonの非同期処理は、asyncioモジュールを使って実現できます。
      async/awaitキーワードを使うことで、I/O待ち時間を有効活用できます。..."
      (アシスタントの性格設定に応じた口調で応答)
```

```
入力: (同一スレッド内) "具体的なコード例は？"
出力: (前の会話の文脈を踏まえて、非同期処理のコード例を提示)
```

## 受け入れ条件

- [ ] AC1: @bot メンションに対してスレッド内で応答する
- [ ] AC2: 同一スレッド内の会話履歴を保持し、文脈を踏まえた応答ができる（スレッド履歴取得の詳細は [f8-thread-support.md](f8-thread-support.md) を参照）
- [ ] AC3: `config/assistant.yaml` の性格設定がシステムプロンプトに反映される
- [ ] AC4: メンション部分（`<@BOT_ID>`）を除去してからLLMに送信する
- [ ] AC5: オンラインLLM（OpenAI or Anthropic、設定で切替）で応答を生成する
- [ ] AC6: 会話履歴をDBに保存する（conversations テーブル）
- [ ] AC7: LLM API呼び出し失敗時にユーザーへエラーメッセージを返す

## 使用LLMプロバイダー

**オンライン**（OpenAI or Anthropic）— 質の高い応答が必要なため

## 関連ファイル

| ファイル | 役割 |
|---------|------|
| `src/slack/app.py` | Slack Bolt AsyncApp初期化 |
| `src/slack/handlers.py` | app_mentionイベントハンドラ |
| `src/services/chat.py` | チャットオーケストレーション、会話履歴管理（F8 でスレッド履歴統合を追加） |
| `src/llm/base.py` | LLMProvider抽象インターフェース |
| `src/llm/openai_provider.py` | OpenAIプロバイダー |
| `src/llm/anthropic_provider.py` | Anthropicプロバイダー |
| `src/llm/lmstudio_provider.py` | LM Studioプロバイダー |
| `src/llm/factory.py` | プロバイダーファクトリ |
| `src/db/models.py` | conversationsモデル |
| `config/assistant.yaml` | 性格設定 |

## テスト方針

- LLM APIをモックしてハンドラの動作をテスト
- 会話履歴の保持・取得をDBレベルでテスト
- assistant.yamlの読み込みとシステムプロンプト反映をテスト
- メンション除去ロジックのユニットテスト
