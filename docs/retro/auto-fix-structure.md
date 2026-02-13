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

## 次に活かすこと

1. **外部アクションのパラメータは `action.yml` の `inputs` で確認する**: `with:` に渡すパラメータが実際に定義されているか、利用前に `action.yml` を確認する。IDE の schema validation 警告も見逃さない
2. **設計書を先に固めることで実装がスムーズになる**: 入出力・エラー方針・環境変数マッピングを事前に定義しておくと、実装時の判断コストが大幅に下がり、並行作業の分担も容易になる
3. **セルフレビューで `require_env` の網羅性を確認する**: スクリプト内で明示的に参照する環境変数は全て `require_env` に含める。`gh` CLI が暗黙参照するもの（`GH_TOKEN`, `GH_REPO`）と、URL パス等に明示的に埋め込むものを区別する
4. **YAML内のインラインスクリプトは30行を超えたら外部化を検討する**: shellcheck 適用、エディタのシンタックスハイライト、テスト可能性の全てが改善される
