# auto-fix.yml 構造リファクタリング — レトロスペクティブ

## 概要

auto-fix.yml の構造リファクタリング（#295）と、その前提調査である direct_prompt 問題の修正（#297）を実施した。

- Issue: #295, #297
- 設計書: `docs/specs/auto-fix-structure.md`

## 実装の概要

### Issue #297: direct_prompt 調査・修正

- `claude-code-action` v1.0 のソースコード（action.yml, collect-inputs.ts, context.ts, create-prompt/index.ts 等）を精査
- `direct_prompt` は v0.x の旧パラメータで、v1.0 で `prompt` に置き換えられた（DEPRECATED）ことを確認
- `direct_prompt` で渡した値は `PROMPT` 環境変数にマッピングされず、プロンプトとして Claude に到達していなかった
- auto-fix.yml の `direct_prompt:` を `prompt:` に変更、設計書の注記も更新

### Issue #295: 構造リファクタリング

- 937行の auto-fix.yml から 8本のシェルスクリプトを `.github/scripts/auto-fix/` に外部化
- prompt テンプレートを `.github/prompts/auto-fix-check-pr.md` に分離
- `_common.sh` に `require_env`、`output` 関数を追加
- YAML は「オーケストレーションのみ」に簡素化（`${{ }}` 式を `env:` ブロックで環境変数に変換）
- `.shellcheckrc` を追加し、shellcheck による静的解析を有効化
- 変更結果: 4ファイル変更 + 10ファイル新規作成、net -519行の削減

## うまくいったこと

### 1. 設計書が事前に固まっていた効果

設計書（`docs/specs/auto-fix-structure.md`）が PR #296 のレビューを経て詳細に固まっていたため、実装時に判断に迷う場面がほとんどなかった。具体的に役立った箇所:

- 各スクリプトの入出力・エラー方針が明確に定義されていた
- 環境変数一覧（`GH_REPO` vs `GITHUB_REPOSITORY` の使い分け等）が事前に整理されていた
- `_common.sh` の追加関数（`require_env`, `output`）の実装案がコード付きで記載されていた
- 外部化する/しないの判断基準（30行以上 or 複雑な制御構造）が明確だった

### 2. 並行作業の分担が効果的だった

前半4スクリプト（get-pr-number, remove-label, check-loop-count, check-review-result）と後半4スクリプト + YAML書き換え + prompt外部化を分担し、並行して作業できた。設計書で各スクリプトの責務が独立していたため、分担がスムーズだった。

### 3. #297 の調査で潜在的な問題を発見できた

\#295 の構造リファクタリング着手前に #297 の調査を行ったことで、`direct_prompt` がプロンプトとして機能していなかった潜在的な問題を発見・修正できた。リファクタリングと同時に修正することで、変更のまとまりが良くなった。

## ハマったこと・改善点

### 1. direct_prompt が実はプロンプト未到達だった

auto-fix.yml で `with: direct_prompt: |` でプロンプトを渡していたが、`action.yml` の `inputs` に `direct_prompt` が定義されていないため、`${{ inputs.prompt }}` にマッピングされず、`PROMPT` 環境変数は空のままだった。

ワークフローが「動作しているように見えた」のは、Claude がリポジトリの CLAUDE.md やコンテキストから自律的に動作していたためと推測される。つまり、プロンプトの 8 ステップ手順が Claude に渡っていない状態で運用されていた可能性がある。

**教訓**: 外部アクションの `with:` パラメータは `action.yml` の `inputs` に定義されているものだけが有効。未定義のパラメータはサイレントに無視される（エラーにならない）。VS Code の schema validation が警告を出していたが見落としていた。

### 2. `GH_REPO` と `GITHUB_REPOSITORY` の使い分けに注意が必要

設計書で明確に定義されていたが、セルフレビューで `check-loop-count.sh` の `require_env` に `GH_REPO` を含め忘れていた箇所を発見した。`gh api` の URL パスに `${GH_REPO}` を明示的に埋め込む場合は、`require_env` でのチェックが必要。`gh` CLI が暗黙的に使う場合（`gh pr view` 等）とは扱いが異なる。

### 3. `validate_numeric` の活用で手動正規表現チェックを共通化

元コードでは `if ! [[ "$VALUE" =~ ^[0-9]+$ ]]` を各所に手書きしていたが、`_common.sh` の `validate_numeric` を活用することでコードの重複を削減できた。ただし、`get-pr-number.sh` では `^[1-9][0-9]*$`（先頭0を許容しない）パターンを使用しており、これは `validate_numeric`（`^[0-9]+$`）とは異なるため、スクリプト内で個別にバリデーションしている。

## 検証結果（PR #298 マージ後）

### prompt 修正の効果確認

PR #298 マージ後、Issue #284（チーム編成履歴上限40件）で auto-fix ワークフローをテストした結果:

- **PR #299 が自動生成され、レビュー指摘0件で自動マージに成功**
- auto-fix ワークフロー史上初の「指摘なし完全自動マージ」
- `prompt` が正しく渡されるようになったことで、Claude が仕様書・レトロの両方を正しく更新
- 従来は CLAUDE.md のみを頼りに自律動作していたため、指示の意図が伝わらないケースがあった

この結果により、`direct_prompt` → `prompt` 修正の効果が実戦で証明された。

## 次に活かすこと

1. **外部アクションのパラメータは `action.yml` の `inputs` で確認する**: `with:` に渡すパラメータが実際に定義されているか、利用前に `action.yml` を確認する。IDE の schema validation 警告も見逃さない
2. **設計書を先に固めることで実装がスムーズになる**: 入出力・エラー方針・環境変数マッピングを事前に定義しておくと、実装時の判断コストが大幅に下がり、並行作業の分担も容易になる
3. **セルフレビューで `require_env` の網羅性を確認する**: スクリプト内で明示的に参照する環境変数は全て `require_env` に含める。`gh` CLI が暗黙参照するもの（`GH_TOKEN`, `GH_REPO`）と、URL パス等に明示的に埋め込むものを区別する
4. **YAML内のインラインスクリプトは30行を超えたら外部化を検討する**: shellcheck 適用、エディタのシンタックスハイライト、テスト可能性の全てが改善される

---

## Phase 2: ワークフロー簡素化（#337）

### 概要

Issue #335（親）の Phase 2 として、Phase 1（#336）で更新された設計書に基づいてワークフローの簡素化を実装した。

- Issue: #335, #337
- 設計書: `docs/specs/auto-fix-structure.md`, `docs/specs/auto-progress.md`

### 実装の概要

#### コマンド体系の整理

- `/review`: レビューのみ実行。auto-fix は起動しない
- `/fix`（新設）: レビュー実行後に `auto:fix-requested` ラベルを付与し、auto-fix を起動

#### ラベル体系の整理

| 旧ラベル | 新ラベル | 用途 |
|---------|---------|------|
| `auto-progress`（PR） | `auto:pipeline` | 自動パイプラインで作成されたPRのマーカー |
| `auto-implement`（PR、auto-fix トリガー） | `auto:fix-requested` | auto-fix 起動トリガー |
| `auto-merged` | `auto:merged` | 自動マージ済みマーカー |

命名規則: `auto-implement` = Issue側（手動付与）、`auto:*` = PR側（ワークフロー自動管理）

#### workflow_run トリガーの廃止

- `auto-fix.yml` から `workflow_run` トリガーを完全削除
- `pull_request[labeled]`（`auto:fix-requested`）に一本化
- PR番号の取得を `github.event.pull_request.number` の直接参照に簡素化
- `get-pr-number.sh` を削除（デッドコード除去）
- スコープチェックステップを最小化（ラベル付与自体がスコープ制御）
- concurrency グループを `auto-fix-pr-{pr_number}` に簡素化

#### merge-or-dryrun.sh の拡張

- マージ直前に `auto:merged` ラベルを付与（`post-merge.yml` の発火条件）

### うまくいったこと

#### 1. Phase 1 で設計書が完成していた効果

Phase 1（#336）で設計書が更新済みだったため、実装は「設計書を忠実に再現する」だけで済んだ。ラベル名・色・付与条件・ガード条件が全て定義済みで、判断に迷う場面がなかった。

#### 2. コードレビューで案内メッセージの不整合を検出

セルフレビューで、PRコメントの案内メッセージが旧コマンド（`/review`）のままになっていた箇所を4つ検出できた（auto-fix.yml 3箇所 + handle-errors.sh 1箇所）。`/fix` コマンドの導入で `/review` はレビュー専用になったため、auto-fix 再開の案内は `/fix` であるべき。

#### 3. 変更の波及範囲を網羅的にチェックできた

`grep` で旧ラベル名（`auto-progress`、`auto-merged`）の残存を横断検索し、漏れがないことを確認できた。

### ハマったこと・改善点

#### 1. 設計書と Issue のラベル色情報の不一致

Issue #337 では `auto:fix-requested` の色が `#0E8A16`（緑）と記載されていたが、設計書 `auto-progress.md` では `#FBCA04`（黄）と定義されていた。設計書を正とした。設計書の情報を常に信頼する判断は正しかったが、Issue 作成時に設計書と一致させておくべきだった。

### 次に活かすこと

1. **コマンド名変更時は案内メッセージを横断検索する**: コマンド名やラベル名を変更した場合、ユーザー向けメッセージ内の旧名が残りやすい。`grep` で全参照箇所を洗い出す
2. **Phase 分割の設計書先行パターンは効果的**: Phase 1 で設計書を固め、Phase 2 で実装する方式は判断コストを最小化できる。大きなリファクタリングではこのパターンを踏襲する
3. **デッドコードは即座に削除する**: ワークフローの参照を外しただけでファイルを残すと混乱を招く。参照を外したら同時にファイルも削除する

---

## Phase 3: Copilot ベース方式への移行（#353）

### 概要

PRKit ベースの自動レビュー（pr-review.yml → auto-fix.yml ループ）のレビュー収束問題（#351）を解決するため、Copilot ネイティブレビューベースの新ワークフロー copilot-auto-fix.yml を実装した。

- Issue: #351（問題分析）, #353（実装）
- 設計書: `docs/specs/copilot-auto-fix.md`（新規）, `docs/specs/auto-progress.md`（更新）
- 検証PR: #352（Copilot レビューイベント検証）

### 実装の概要

#### 新ワークフロー copilot-auto-fix.yml

- トリガー: `pull_request_review[submitted]`（Copilot レビュー完了時）
- 再レビューループなしの単方向フロー: レビュー → 修正 → マージ
- 既存スクリプト群（`check-review-result.sh`, `check-forbidden.sh`, `merge-check.sh`, `merge-or-dryrun.sh`）を流用
- CI 完了待機ステップ追加（修正 push 後、30秒間隔で最大10分ポーリング）

#### 既存ワークフローの無効化

- `pr-review.yml`: トリガーを `workflow_dispatch` に変更（削除せず切り戻し容易に）
- `auto-fix.yml`: 同上

#### merge-check.sh の拡張

- PR OPEN 状態チェックを条件1として追加（4条件 → 5条件）
- Copilot が複数回レビューを投稿するケースのガード

#### handle-errors.sh の更新

- エラーメッセージ内の再開手順を `/fix` コメント → `auto:failed` 除去 + Copilot 再レビューに変更

### うまくいったこと

#### 1. 既存スクリプトの高い再利用率

Phase 1-2 で外部化した 8 スクリプトのうち 5 つ（`_common.sh`, `check-review-result.sh`, `check-forbidden.sh`, `merge-check.sh`, `merge-or-dryrun.sh`）をそのまま copilot-auto-fix.yml から流用できた。構造リファクタリングの投資が回収された形。修正が必要だったのは `merge-check.sh`（条件追加）と `handle-errors.sh`（メッセージ変更）のみ。

#### 2. PR #352 の事前検証データが判断根拠として有効だった

Copilot のレビューイベント名が取得元で異なる問題（イベントペイロード: `"Copilot"` vs REST API: `"copilot-pull-request-reviewer[bot]"`）を事前検証で把握できていたため、if 条件で両方を OR 判定する設計をスムーズに反映できた。

#### 3. 設計書先行パターンの3回目の成功

Phase 1（設計書整備） → Phase 2（ワークフロー簡素化） → Phase 3（Copilot 移行）と、常に設計書を先行させるパターンを踏襲した。今回は前セッションで copilot-auto-fix.md 新規作成 + auto-progress.md 更新を完了させ、今セッションで実装のみに集中できた。

### ハマったこと・改善点

#### 1. 設計書が2ファイルに分散している管理コスト

copilot-auto-fix.yml の仕様は `copilot-auto-fix.md`（詳細設計）と `auto-progress.md`（全体パイプライン）の2ファイルに分散している。整合性維持のコストが生じるが、「全体フロー ↔ 個別ワークフロー」の粒度の違いを考えると妥当な構成。

#### 2. 再レビューループ廃止の意思決定プロセス

Issue #351 のコメント3件で「再レビューループ自体が問題の温床」という根本原因を特定し、方針決定できた。PRKit の正答率データ（17%、CRITICAL 20%）と PR #350 の4ラウンド実績が判断の裏付けになった。データに基づく意思決定が効果的だった。

### 次に活かすこと

1. **構造リファクタリングは長期投資**: スクリプト外部化は単体では「見た目の改善」に見えるが、ワークフロー切り替え時に再利用性として回収できる。「コンセプト: YAMLはオーケストレーションのみ、ロジックはスクリプトに」の方針は正しかった
2. **事前検証PRは判断根拠として残す**: PR #352 のようなマージしない検証PRでも、データを Issue コメントに記録しておくことで後続の設計判断に活用できる
3. **無効化は削除より安全**: ワークフローのトリガーを `workflow_dispatch` に変更する無効化方式は、切り戻しが容易で、PRKit 精度改善時に再有効化できる。Phase 2 のレトロで「デッドコードは即座に削除」と書いたが、ワークフロー全体の無効化は例外として「残す」判断が適切なケースもある
