# AI Assistant — 開発ガイドライン

> プロジェクトの概要・技術スタック・セットアップ手順・プロジェクト構造は [README.md](README.md) を参照してください。

## LLM使い分けルール

- **デフォルト**: 全サービスでローカルLLM（LM Studio）を使用
- **設定変更**: `.env` で各サービスごとにLLMを変更可能
  - `CHAT_LLM_PROVIDER` — ChatService用
  - `PROFILER_LLM_PROVIDER` — UserProfiler用
  - `TOPIC_LLM_PROVIDER` — TopicRecommender用
  - `SUMMARIZER_LLM_PROVIDER` — Summarizer用
- 各設定は `"local"` または `"online"` を指定（デフォルト: `"local"`）

### MCP設定

- `MCP_ENABLED` — MCP機能の有効/無効（`true` / `false`、デフォルト: `false`）
- `MCP_SERVERS_CONFIG` — MCPサーバー設定ファイルのパス（デフォルト: `config/mcp_servers.json`）
- MCPサーバーの追加・変更は `config/mcp_servers.json` で行う
- MCPサーバー（`mcp-servers/` 配下）は `src/` のモジュールを import しないこと（将来のリポジトリ分離制約）

### RAG設定

- `RAG_ENABLED` — RAG機能の有効/無効（`true` / `false`、デフォルト: `false`）
- `EMBEDDING_PROVIDER` — Embeddingプロバイダー（`"local"` / `"online"`、デフォルト: `"local"`）
- `RAG_ALLOWED_DOMAINS` — クロール許可ドメインのカンマ区切りリスト（SSRF対策、未設定時はクロール拒否）
- 詳細設定は `docs/specs/f9-rag-knowledge.md` を参照

## 開発ルール

### 仕様駆動開発

- **実装前に必ず `docs/specs/` の仕様書を読むこと**。仕様書が実装の根拠。
- **実装前に既存コードを必ず読むこと**。仕様書の「関連ファイル」に記載された実装ファイルを確認し、既存の構造・パターン・抽象化を把握してから設計する。
- **既存コードの拡張を優先する**。新しいメソッドやクラスを作る前に、既存のメソッドにパラメータ（フラグ）を追加して対応できないか検討する。やむを得ず類似ロジックが重複する場合は、その理由と設計判断を仕様書に記載する。
- 仕様書にない機能追加・リファクタリングは別Issueに切り出す。
- 仕様変更が必要な場合は、先に仕様書を更新してから実装する。

### コーディング規約

- 各サービスクラスのdocstringに対応する仕様書パスを記載する:

  ```python
  class FeedCollector:
      """RSS/Webからの情報収集サービス
      仕様: docs/specs/f2-feed-collection.md
      """
  ```

- テスト名は仕様書の受け入れ条件(AC)番号と対応させる:

  ```python
  def test_ac1_rss_feed_is_fetched_and_parsed():
  def test_ac2_articles_are_summarized_by_local_llm():
  ```

- ruff でリント、mypy (strict) で型チェック
- markdownlint でMarkdownチェック（`npx markdownlint-cli2@0.20.0` を使用、Node.js環境が必要）

### 作業開始時の手順

1. **Issue・Milestoneの確認**: 作業前に必ず現状を把握する

   ```bash
   gh milestone list                  # Milestone一覧と進捗確認
   gh issue list --milestone "Step N: ..."  # 該当Stepのissue一覧
   gh issue list --state open         # 未着手Issue一覧
   gh issue view <番号>               # Issue詳細の確認
   ```

2. **対象Issueの仕様書を読む**: Issueに記載された仕様書パスを確認し、`docs/specs/` の該当ファイルを読む
3. **既存実装コードの確認**: 仕様書の「関連ファイル」セクションに記載されたソースファイルを読み、既存の処理フロー・メソッド構成・抽象化パターンを把握する。**新規メソッド作成前に、既存メソッドのパラメータ追加で対応できないか必ず検討する**
4. **ブランチ作成→実装→PR** の流れで進める

### Git運用

- ブランチ: `feature/f{N}-{機能名}-#{Issue番号}`
- コミット: `feat(f{N}): 説明 (#{Issue番号})`
- PR作成時に `Closes #{Issue番号}` で紐付け
- GitHub Milestones で Step 単位の進捗管理
- `gh` コマンドで Issue/PR を操作

**Claudeによる実装完了時の必須手順**:

1. **ファイル作成の確認**: 作成したと報告したファイルが実際に存在するか `ls -la` で確認
2. **テスト実行**: **test-runner サブエージェント** で全テスト（pytest / mypy / ruff / markdownlint）が通過することを確認
3. **コードレビュー**: **code-reviewer サブエージェント** で変更コードのセルフレビューを実施し、Critical/Warning の指摘があれば修正する
4. **ドキュメントレビュー**: `docs/specs/` に変更・新規追加がある場合、**doc-reviewer サブエージェント** で品質レビューを実施し、指摘があれば修正する。実装のみのPRでも、対応する仕様書との整合性チェックのため実施すること。
   - **スキップ基準**: 誤字脱字のみの修正はスキップ可
   - **差分レビュー推奨**: PRレビュー指摘対応、軽微な補足追加は「差分レビュー」を使用
   - **フルレビュー必須**: 新規仕様書作成、大幅改訂時
5. **変更のステージング**: `git status` で変更を確認し、`git add` で全てステージング
6. **コミット**: 変更内容を明確に記述したコミットメッセージでコミット
7. **プッシュ**: `git push origin <ブランチ名>` でリモートにプッシュ
8. **PR作成**: `gh pr create` コマンドで実際にPRを作成（手動リンクではなく実際に作成）

   ```bash
   gh pr create --title "タイトル" --body "説明\n\nCloses #Issue番号" --base main
   ```

9. **作成確認**: `gh pr view` でPRが正しく作成されたことを確認し、URLをユーザーに提示
10. **レトロスペクティブ**: 機能実装のPRの場合、`/doc-gen retro <feature-name>` でレトロを生成・更新する

### レビュー指摘対応

PRに対するレビュー指摘（Copilot、人間問わず）への対応は `/fix-reviews` スキルを使用する。
ユーザーが以下のような表現でレビュー対応を依頼した場合、自律的に `/fix-reviews` スキルを呼び出すこと:

- 「指摘をチェックして」「レビューを確認して」「レビュー指摘に対応して」
- 「コメントを修正して」「レビューコメントを直して」
- 「Copilotの指摘を見て」「PRのフィードバックに対応して」

手動対応する場合は以下を確認すること:

1. **コード修正**: 指摘に対する修正を実施
2. **テスト実行**: **test-runner サブエージェント** で**差分テスト**を実行（`test-runnerサブエージェントで差分テストを実行してください`）
3. **ドキュメント整合性チェック**: 修正内容が以下のドキュメントに影響しないか確認し、必要なら更新する
   - `docs/specs/` — 仕様・受け入れ条件に影響する変更の場合
   - `CLAUDE.md` — 開発ルール・プロジェクト構造に影響する場合
4. **ドキュメントレビュー**: `docs/specs/` に変更がある場合、**doc-reviewer サブエージェント** で**差分レビュー**を実施（軽微な修正のためフルレビューは不要）
5. **コミット**: `fix: レビュー指摘対応 (PR #番号)` の形式でコミット

### レトロスペクティブ

- **機能の実装完了時（PRマージ後）に必ず** `/doc-gen retro <feature-name>` でレトロを生成する
- 運用テストで問題が見つかった場合も、修正完了後にレトロを更新する
- **ファイル命名**: `docs/retro/f{N}-{機能名}.md`
- **記載内容**: 実装の概要、うまくいったこと、ハマったこと・改善点、次に活かすこと
- 既存レトロがある場合は追記・更新する（新規作成ではなく）
- テンプレート・運用ルール自体の改善も行う
- 新機能の仕様策定時は、関連する既存レトロの「次に活かすこと」を参照する

## Bot プロセスガード

- Bot起動時に `bot.pid` ファイルで重複起動を検知する（仕様: `docs/specs/bot-process-guard.md`）
- 既に起動中の場合は警告メッセージを表示して `sys.exit(1)` で終了する（自動killはしない）
- シャットダウン時に子プロセス（MCPサーバー等）をクリーンアップする
- プラットフォーム分岐: Windows は `tasklist`/`wmic`/`taskkill`、Unix は `os.kill`/`pgrep`/`SIGTERM`

## Claude Code 拡張機能

### Hooks

プロジェクトには Claude Code の hooks 機能を使った通知システムが設定されています。

- **仕様**: `docs/specs/claude-code-hooks.md`
- **設定ファイル**: `.claude/settings.json`
- **通知スクリプト**: `.claude/scripts/notify.sh`

**Windows環境での注意点**:

- シェルスクリプト（`.sh`）は **LF 改行コード** で保存すること（CRLF だとエラー）
- 改行コード変換: `cat file.sh | tr -d '\r' > file_tmp.sh && mv file_tmp.sh file.sh`
- **出力の破棄には必ず `/dev/null` を使うこと。`> nul` は禁止。**
  - Git Bash 環境では `> nul` と書くと `nul` という名前のファイルが作成されてしまう（Windows の予約デバイス名が正しく解釈されない）
  - 正: `command > /dev/null 2>&1`
  - 誤: `command > nul 2>&1`

### スキル（ユーザー実行コマンド）

スキルは `/スキル名` 形式でユーザーが直接呼び出すコマンドです。

| スキル | 用途 | 使用例 |
|--------|------|--------|
| `/doc-gen` | ドキュメント新規作成（仕様書・レトロ） | `/doc-gen spec feed-collection` |
| `/doc-edit` | 既存ドキュメントの更新・修正 | `/doc-edit docs/specs/f2-feed-collection.md` |
| `/fix-reviews` | PRレビュー指摘の確認・修正対応 | `/fix-reviews` |

**定義ファイル**: `.claude/skills/` 配下
**仕様書**: `docs/specs/doc-gen-skill.md`（`/doc-gen`, `/doc-edit` 用）
**補足**: `/fix-reviews` は `.claude/skills/fix-reviews/SKILL.md` の定義のみで、`docs/specs/` 配下に専用の仕様書はありません。

### サブエージェント（自動委譲タスク）

サブエージェントは Claude が内部的に専門タスクを委譲する仕組みです。ユーザーから呼び出すこともできます。

| サブエージェント | 用途 | 使用例 |
|-----------------|------|--------|
| **planner** | Issue・提案内容から実装計画を立案 | `plannerサブエージェントでIssue #42 の実装計画を立ててください` |
| **code-reviewer** | コミット前のセルフコードレビュー | `code-reviewerサブエージェントで変更差分をレビューしてください` |
| **doc-reviewer** | 仕様書・README.md の品質レビュー | `doc-reviewerサブエージェントで docs/specs/f1-chat.md をレビューしてください` |
| **test-runner** | pytest によるテスト実行・分析・修正提案 | `test-runnerサブエージェントで全テストを実行してください` |

**定義ファイル**: `.claude/agents/` 配下
**仕様書**: `docs/specs/planner-agent.md`, `docs/specs/code-review-agent.md`, `docs/specs/doc-review-agent.md`, `docs/specs/test-runner-agent.md`

### スキルとサブエージェントの使い分け

- **スキル**: ユーザーが `/コマンド名` で明示的に実行するワークフロー（ドキュメント生成、レビュー対応など）
- **サブエージェント**: 実装作業中に Claude が自律的に呼び出す専門家（テスト実行、計画立案、品質レビューなど）

例: レビュー指摘対応では `/fix-reviews` スキルが起動し、その中で **test-runner** や **doc-reviewer** サブエージェントが自動的に呼び出されます。
