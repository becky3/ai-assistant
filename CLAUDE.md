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
- 詳細設定は `docs/specs/f9-rag.md` を参照

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
- ドキュメント内の図表（フローチャート、シーケンス図、ER図等）はmermaid形式を使用する
  - ASCII図表は使用しない
  - 参考: <https://mermaid.js.org/>

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

### Git運用（git-flow）

本プロジェクトは git-flow ベースのブランチ戦略を採用している。詳細は `docs/specs/git-flow.md` を参照。

- **常設ブランチ**: `main`（安定版）/ `develop`（開発統合）
- **作業ブランチ**:
  - `feature/f{N}-{機能名}-#{Issue番号}` — 新機能開発（`develop` から分岐 → `develop` にマージ）
  - `bugfix/{修正内容}-#{Issue番号}` — バグ修正（`develop` から分岐 → `develop` にマージ）
  - `hotfix/{修正内容}-#{Issue番号}` — 本番緊急修正（`main` から分岐 → `main` + `develop` にマージ）
  - `claude/issue-{N}-{date}-{id}` — Claude Code Action 自動生成（命名はシステム依存）
- コミット: `feat(f{N}): 説明 (#{Issue番号})`
- PR作成時に `Closes #{Issue番号}` で紐付け
- **PRのbaseブランチ**: 通常は `develop`、hotfix は `main`
- GitHub Milestones で Step 単位の進捗管理
- `gh` コマンドで Issue/PR を操作

**Claudeによる実装完了時の必須手順**:

1. **ファイル作成の確認**: 作成したと報告したファイルが実際に存在するか `ls -la` で確認
2. **テスト実行**: **test-runner サブエージェント** または `/test-run` スキルで全テスト（pytest / mypy / ruff / markdownlint）が通過することを確認
3. **コードレビュー**: **code-reviewer サブエージェント** または `/code-review` スキルで変更コードのセルフレビューを実施し、Critical/Warning の指摘があれば修正する
4. **ドキュメントレビュー**: ドキュメント（`docs/specs/`、`README.md`、`CLAUDE.md` 等）に変更がある場合、**doc-reviewer サブエージェント** または `/doc-review` スキルで品質レビューを実施し、指摘があれば修正する。実装のみのPRでも、対応する仕様書との整合性チェックのため実施すること。
   - **スキップ基準**: 誤字脱字のみの修正はスキップ可
   - **差分レビュー推奨**: PRレビュー指摘対応、軽微な補足追加は「差分レビュー」を使用
   - **フルレビュー必須**: 新規仕様書作成、大幅改訂時
5. **レトロスペクティブ**: 機能実装のPRの場合、`/doc-gen retro <feature-name>` でレトロを生成・更新する（PRに含めて自動レビュー対象にするため、コミット前に作成する）
6. **変更のステージング**: `git status` で変更を確認し、`git add` で全てステージング
7. **コミット**: 変更内容を明確に記述したコミットメッセージでコミット
8. **プッシュ**: `git push origin <ブランチ名>` でリモートにプッシュ
9. **PR作成**: `gh pr create` コマンドで実際にPRを作成（手動リンクではなく実際に作成）

   ```bash
   # 通常開発（feature/bugfix → develop）
   gh pr create --title "タイトル" --body "説明\n\nCloses #Issue番号" --base develop

   # hotfix（hotfix → main）
   gh pr create --title "タイトル" --body "説明\n\nCloses #Issue番号" --base main
   ```

10. **作成確認**: `gh pr view` でPRが正しく作成されたことを確認し、URLをユーザーに提示

### レビュー指摘対応

PRに対するレビュー指摘（自動レビューツール、人間問わず）への対応は `/check-pr` スキルを使用する。
ユーザーが以下のような表現でレビュー対応を依頼した場合、自律的に `/check-pr` スキルを呼び出すこと:

- 「指摘をチェックして」「レビューを確認して」「レビュー指摘に対応して」
- 「コメントを修正して」「レビューコメントを直して」
- 「レビューの指摘を見て」「PRのフィードバックに対応して」

手動対応する場合は以下を確認すること:

1. **コード修正**: 指摘に対する修正を実施
2. **テスト実行**: **test-runner サブエージェント** で**差分テスト**を実行（`test-runnerサブエージェントで差分テストを実行してください`）
3. **ドキュメント整合性チェック**: 修正内容が以下のドキュメントに影響しないか確認し、必要なら更新する
   - `docs/specs/` — 仕様・受け入れ条件に影響する変更の場合
   - `CLAUDE.md` — 開発ルール・プロジェクト構造に影響する場合
4. **ドキュメントレビュー**: ドキュメント（`docs/specs/`、`README.md`、`CLAUDE.md` 等）に変更がある場合、**doc-reviewer サブエージェント** で**差分レビュー**を実施（軽微な修正のためフルレビューは不要）
5. **対応コメント投稿**: PRに対応状況を説明するコメントを投稿する（`gh pr comment`）
   - 各指摘に対して「対応済み ✅」「別Issue化 ⏸️」「対応不要（理由）❌」を明記
   - 対応内容の簡潔な説明を含める
   - レビュアーが再確認しやすいよう、変更箇所や判断理由を記載
6. **コミット**: `fix: レビュー指摘対応 (PR #番号)` の形式でコミット

### レトロスペクティブ

- **機能の実装完了時（PRマージ後）に必ず** `/doc-gen retro <feature-name>` でレトロを生成する
- 運用テストで問題が見つかった場合も、修正完了後にレトロを更新する
- **ファイル命名**: 機能番号がある場合は `docs/retro/f{N}-{機能名}.md`、ない場合は `docs/retro/{機能名}.md`
- **記載内容**: 実装の概要、うまくいったこと、ハマったこと・改善点、次に活かすこと
- 既存レトロがある場合は追記・更新する（新規作成ではなく）
- テンプレート・運用ルール自体の改善も行う
- 新機能の仕様策定時は、関連する既存レトロの「次に活かすこと」を参照する

## 自動進行ルール（auto-progress）

`auto-implement` ラベルによりIssueが自動実装トリガーされた場合、
以下のルールに従って実装を進める。
仕様: docs/specs/auto-progress.md

### 起動時の判断フロー

1. Issueの内容を読む（タイトル、本文、全コメント）
2. 仕様書の存在確認（`docs/specs/` に対応する仕様書があるか）
   - あり + AC定義済み: 仕様書に従って実装を開始
   - あり + AC未定義: ACを追加してから実装を開始
   - なし + Issue具体的: `/doc-gen spec` で仕様書を自動生成し、そのまま実装（事後拒否権モデル）
   - なし + Issue曖昧: `auto:failed` 付与、不明点をIssueにコメントして停止
3. 通常の開発ルール（仕様駆動開発）に従って実装
4. 実装完了後、通常の手順でPR作成まで行う（ベースブランチは `develop`）
5. ラベル更新:
   - 実装開始時: `auto-implement` ラベルを除去
   - 失敗時: `auto:failed` 付与

### Git運用（auto-progress）

- PRのベースブランチは `develop`（`gh pr create --base develop`）
- `main` への直接PRは作成しない（リリースPR以外）
- ブランチ命名規則は既存ルールを踏襲

### Issue具体性の判定

具体的と見なす: 入出力例あり、具体的な変更指示、バグ再現手順あり
曖昧と見なす: 「検討」「改善」のみ、複数要求混在、外部仕様未確定

### `auto:failed` ラベル

`auto:failed` ラベルが付いたIssue/PRは自動処理を一切行わない。
自動処理の失敗時に自動付与されるほか、管理者が手動で付与して緊急停止にも使う。
再開するには `auto:failed` を除去し、`auto-implement` を再付与する。

### 品質チェック（GitHub Actions 環境）

GitHub Actions 環境（claude-code-action）ではサブエージェント（Task tool）が安定しないため、品質チェックにはスキルを直接使用する:

1. `/test-run` — pytest / ruff / mypy / markdownlint を実行
2. `/code-review` — 変更差分のセルフコードレビュー
3. `/doc-review` — ドキュメント変更がある場合の品質レビュー

**重要**: 品質チェックは中間ステップであり、ここで停止しないこと。通過後は「Claudeによる実装完了時の必須手順」のステップ6以降（ステージング → コミット → プッシュ → PR作成）まで必ず実行する。

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
| `/check-pr` | PRの内容確認・レビュー指摘対応・実装継続 | `/check-pr 123` |
| `/topic` | 学びトピックの自動抽出・Zenn記事生成 | `/topic`, `/topic 3` |
| `/test-run` | テスト実行（pytest/ruff/mypy/markdownlint） | `/test-run`, `/test-run diff` |
| `/code-review` | コードレビュー（code-reviewer相当） | `/code-review` |
| `/doc-review` | ドキュメントレビュー（doc-reviewer相当） | `/doc-review docs/specs/f1-chat.md` |

**定義ファイル**: `.claude/skills/` 配下
**仕様書**: `docs/specs/doc-gen-skill.md`（`/doc-gen`, `/doc-edit` 用）、`docs/specs/topic-skill.md`（`/topic` 用）
**補足**: `/check-pr` は `.claude/skills/check-pr/SKILL.md` の定義のみで、`docs/specs/` 配下に専用の仕様書はありません。

### サブエージェント（自動委譲タスク）

サブエージェントは Claude が内部的に専門タスクを委譲する仕組みです。ユーザーから呼び出すこともできます。

| サブエージェント | 用途 | 使用例 |
|-----------------|------|--------|
| **planner** | Issue・提案内容から実装計画を立案 | `plannerサブエージェントでIssue #42 の実装計画を立ててください` |
| **code-reviewer** | コミット前のセルフコードレビュー（内部で `/code-review` スキルを参照） | `code-reviewerサブエージェントで変更差分をレビューしてください` |
| **doc-reviewer** | 仕様書・README.md の品質レビュー（内部で `/doc-review` スキルを参照） | `doc-reviewerサブエージェントで docs/specs/f1-chat.md をレビューしてください` |
| **test-runner** | pytest によるテスト実行・分析・修正提案（内部で `/test-run` スキルを参照） | `test-runnerサブエージェントで全テストを実行してください` |

**定義ファイル**: `.claude/agents/` 配下
**仕様書**: `docs/specs/planner-agent.md`, `docs/specs/code-review-agent.md`, `docs/specs/doc-review-agent.md`, `docs/specs/test-runner-agent.md`

### PR Review Toolkit（プラグイン）

Anthropic 公式の PR レビュー専門エージェント群です。既存のサブエージェントを補完し、より専門的な観点でのレビューを提供します。

| エージェント | 用途 | 特徴 |
|-------------|------|------|
| **prt-code-reviewer** | CLAUDE.md準拠・バグ検出 | 信頼度スコア(0-100)付き、80以上のみ報告 |
| **prt-test-analyzer** | テストカバレッジ品質分析 | 振る舞いカバレッジに焦点、1-10スケール評価 |
| **prt-silent-failure-hunter** | サイレント障害検出 | try-catch/except の品質分析 |
| **prt-type-design-analyzer** | 型設計・不変条件評価 | 4観点で1-10スケール評価 |
| **prt-comment-analyzer** | コメント正確性分析 | コメント腐敗・誤解を招く記述の検出 |
| **prt-code-simplifier** | コード簡素化 | 機能保持しつつ可読性向上 |

**統合コマンド**: `/review-pr`

```bash
/review-pr              # 全観点でレビュー
/review-pr tests errors # テストとエラー処理のみ
/review-pr simplify     # コード簡素化のみ
```

**既存サブエージェントとの使い分け**:

| 目的 | 既存サブエージェント | PR Review Toolkit |
|------|---------------------|-------------------|
| テスト実行・修正 | test-runner | - |
| テスト品質分析 | - | prt-test-analyzer |
| 汎用コードレビュー | code-reviewer | prt-code-reviewer（スコア付き） |
| ドキュメント品質 | doc-reviewer | prt-comment-analyzer（コメント特化） |
| エラー処理分析 | - | prt-silent-failure-hunter |
| 型設計評価 | - | prt-type-design-analyzer |

**定義ファイル**: `.claude/agents/prt-*.md`, `.claude/commands/review-pr.md`

**GitHub Actions 自動レビュー**: PR作成時に自動実行（`becky3` ユーザーのPRのみ対象、コスト制御のため）

**GitHub Actions の意図的設定**（レビューツールへの注記）:

- `--dangerously-skip-permissions`: 自動化のため意図的に使用。GitHub Actions環境は隔離されており、セキュリティリスクは許容範囲
- `pr-review.yml` の Slack 通知は `if: failure()`: 成功時の通知は冗長なため意図的に失敗時のみ
- シークレット未設定時のエラー: 初回セットアップ時のみの問題であり、バリデーションステップは不要

### スキルとサブエージェントの使い分け

- **スキル**: ユーザーが `/コマンド名` で明示的に実行するワークフロー（ドキュメント生成、レビュー対応など）
- **サブエージェント**: 実装作業中に Claude が自律的に呼び出す専門家（テスト実行、計画立案、品質レビューなど）

例: PR確認・レビュー対応では `/check-pr` スキルが起動し、その中で **test-runner** や **doc-reviewer** サブエージェントが自動的に呼び出されます。

### エージェントチーム（実験的機能）

リーダー1名とチームメンバー（独立したClaude Codeインスタンス）で構成される協調作業システム。

**有効化**: `.claude/settings.json` で `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS: "1"` を設定

**起動**: 「チームで開発して」でキャラクターテーマがランダム選択される（特定テーマ指定も可）

**必須ルール**:

- **品質担当（1名以上）**: code-reviewer / doc-reviewer / test-runner を使う担当。**3つ全て明示**すること
- **ストーリーテラー（1名）**: プロセス全体を俯瞰し、問題を早期発見する語り部
- **リーダーもキャラクターとして振る舞う**: 無個性な応答（「待ちます」「確認します」等）は禁止。メンバーへの指示・ユーザーへの報告ともにキャラクター口調を維持する
- **外部成果物は素で**: コミットメッセージ、PR/Issue本文、成果物（コード・コメント・仕様書等）にはキャラクター要素を含めない（※運用ガイド: CLAUDE.md、`docs/specs/agent-teams*.md`、`.claude/team-themes/` は演出ルール記載のため例外）
- **リーダー管理専任**: リーダーは管理・調整・判断に専念し、実装・テスト・レビュー等の作業は行わない。
  作業が必要な場合は既存メンバーに割り振るか新メンバーをspawnする。
  Edit / Write ツールの使用は原則禁止（例外: dashboard.md の更新、CLAUDE.md 等の運用ルール更新、
  チーム管理に直接必要なファイル操作のみ）。
  全メンバーがブロックされている場合のみ、リーダーが一時的に作業を代行可
- **実装担当2名以上推奨**: 実装タスク時は2名以上配置し、分量に応じて柔軟に分担する（少量の場合はリーダー判断で1名も可）
- **メンバー自律行動**: タスク完了後にTaskListを確認し、自分の担当領域で未割り当てタスクがあればリーダーに着手意思を報告してから着手する。該当タスクがなければリーダーに完了報告と待機を伝える

**チーム構築前に必読**:

- `docs/specs/agent-teams.md` — 仕様・ルール
- `docs/specs/agent-teams-operations.md` — 運用詳細・プロンプトテンプレート
- `.claude/team-themes/GUIDELINES.md` — キャラクター演出ガイドライン

### GitHub Actions 環境（claude-code-action）

GitHub Actions で `anthropics/claude-code-action` を使用する場合の制約事項。

**対話不可の制約**:

- `AskUserQuestion` ツールは使用不可（`permission_denials` で拒否される）
- 不明点があっても質問せずに、以下の原則で自分で判断して進めること:
  - 情報不足で判断できない場合は、最も妥当な選択を行い、その判断理由をコメントに明記する
  - 曖昧な指示は、CLAUDE.md のルールに基づいて解釈する
  - 完璧を求めず、まず動くものを作ることを優先する

**Issueから実装する際の注意点**:

- **Issue本文だけでなく、コメントも必ず確認すること**
  - コメントに追加の要件・制約・補足情報が書かれていることがある
  - コメントの要件が仕様書のACに反映されていない場合は、ACに追加してから実装する
  - 過去の教訓: コメントで「外部サイトにアクセスしない」と明言されていたが、見落としてセキュリティ脆弱性が発生した

**タスク完了時の必須アクション**:

- PRを作成したら、必ず対応したIssueに「新規コメント」として完了報告を投稿すること
- 既存コメントの編集ではなく、新しいコメントを追加する（編集では通知が飛ばないため）
- コマンド: `gh issue comment <Issue番号> --body "対応が完了しました。PR #<PR番号> をご確認ください。"`

**設定ファイル**: `.github/workflows/claude.yml`
**レトロスペクティブ**: `docs/retro/claude-code-action.md`
