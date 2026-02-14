# PR body テンプレート

## 概要

PR作成時の body を `.github/pull_request_template.md` で標準化し、記載内容の統一と prt 自動レビューツールへのコンテキスト提供を改善する。

## 背景

- PR #338 で設計書先行更新のPRに対し、prt ツールが「設計書とコードの不整合」として4件の誤検知を出した
- 原因: PR body に「設計書の先行更新であり、コードとの不整合は意図的」と明記されていなかった
- CLAUDE.md に暫定ルールを追記したが、自由記述では記載漏れが発生しやすい
- テンプレートとして構造化することで、記載漏れを防止する
- ただし、prt が PR body を直接参照する仕組みは現状ないため、pr-review.yml の prompt にも PR body の Change type を参照する指示を追加する必要がある

## ユーザーストーリー

- 開発者として、PR作成時に何を書くべきか迷わずに済むテンプレートが欲しい
- 開発者として、設計書先行更新PRで prt 自動レビューの誤検知を防ぎたい
- 開発者として、小さな修正でも過剰な記載を求められないテンプレートが欲しい

## 設計方針

| # | 方針 | 根拠 |
|---|------|------|
| 1 | セクション数は4つに制限 | 5-7を超えると形骸化（N/A で埋められる）するリスクが高い |
| 2 | テンプレートを SSOT（Single Source of Truth）とする | CLAUDE.md・auto-finalize スキルはテンプレート参照に正規化 |
| 3 | prt 誤検知防止が最優先目的 | 変更種別の明示 + pr-review.yml の prompt 更新で実現 |
| 4 | AI・人間の両方に使いやすく | CLI（`gh pr create --body`）では自動適用されないため、CLAUDE.md にもルールを記載 |

## 技術仕様

### テンプレートファイル

**ファイル: `.github/pull_request_template.md`**

```markdown
## Change type

<!-- 該当するものにチェック（複数可、主な種別に ★ を付記） -->

- [ ] feat: 新機能実装
- [ ] fix: バグ修正
- [ ] docs: ドキュメント更新
- [ ] docs(pre-impl): 設計書先行更新（実装は後続フェーズ）
- [ ] refactor: リファクタリング
- [ ] ci: CI/CD改善
- [ ] test: テスト追加・修正

<!-- docs(pre-impl) を選択した場合: 現在のコードとの不整合は意図的です -->

## Summary

<!-- 変更内容を箇条書きで -->

-

## Test plan

<!-- テスト計画（省略可: typo修正等の軽微な変更時） -->

- [ ]

## Related issues

Closes #
```

### セクション仕様

| セクション | 必須/任意 | 形式 | 説明 |
|-----------|----------|------|------|
| Change type | 必須 | チェックボックス（複数可） | 変更の性質を明示。prt の判断コンテキストとなる |
| Summary | 必須 | 箇条書き | 変更内容の概要 |
| Test plan | 推奨（省略可） | チェックリスト | typo修正・軽微な変更時は省略可 |
| Related issues | 必須 | `Closes #N` | Issue 紐付け |

### Change type の選択肢

コミットメッセージの prefix と一致させ、一貫性を保つ。

| 種別 | 対応するコミット prefix | 説明 |
|------|----------------------|------|
| `feat` | `feat(fN):` | 新機能実装（`src/` の変更を含む） |
| `fix` | `fix:` | バグ修正 |
| `docs` | `docs:` | ドキュメント更新（仕様書・README等） |
| `docs(pre-impl)` | `docs:` | 設計書先行更新。実装は後続フェーズで行う |
| `refactor` | `refactor:` | リファクタリング（機能変更なし） |
| `ci` | `ci:` | CI/CD・GitHub Actions の改善 |
| `test` | `test:` | テスト追加・修正 |

### `docs(pre-impl)` の特別扱い

`docs(pre-impl)` を選択した場合、以下が暗黙的に宣言される:

- 現在のコードとの不整合は意図的である
- 実装は後続フェーズ（別PR）で行う
- prt 自動レビューはコードとの不整合を検出対象外とすべき

テンプレート内の HTML コメント（`<!-- docs(pre-impl) を選択した場合: ... -->`）でこの注記を表示し、記載漏れを防止する。

### テンプレートの適用範囲

本テンプレートは PR body（description）のみに適用する。PR コメント（prt レビューサマリー等）には適用しない。

### 複数種別の選択

複合的な変更（例: バグ修正 + リファクタリング）の場合:

- 複数のチェックボックスにチェックを入れる
- 主な種別に `★` を付記する（例: `- [x] fix: バグ修正 ★`）
- コミットメッセージの prefix は主な種別に合わせる

### 不採用としたセクション

| セクション | 不採用理由 |
|-----------|-----------|
| 変更ファイル一覧 | PR の Files changed タブで確認可能。小さな修正で列挙する手間が過剰 |
| Breaking changes | 内部ツールであり外部 API を公開していない。現時点で不要 |
| Screenshots | UI コンポーネントがない（Discord bot + CLI）。不要 |
| Reviewer 指定 | prt ツールが自動レビューするため不要 |
| Context（背景） | Summary に含められる。セクション数制限のため独立セクションとしない |

## CLI からの利用

GitHub の `.github/pull_request_template.md` は Web UI からの PR 作成時のみ自動適用される。CLI（`gh pr create --body`）では自動適用されない。

### CLAUDE.md への反映

テンプレート導入後、CLAUDE.md の PR 作成指示を以下のように更新する:

**変更前**:

```bash
gh pr create --title "タイトル" --body "説明\n\nCloses #Issue番号" --base develop
```

**変更後**:

```bash
gh pr create --title "タイトル" --body "$(cat <<'EOF'
## Change type

- [x] 該当する種別

## Summary

- 変更内容

## Test plan

- [ ] テスト項目

## Related issues

Closes #Issue番号
EOF
)" --base develop
```

PR body は `.github/pull_request_template.md` の形式に従うこと。

### auto-finalize スキルへの反映

`.claude/skills/auto-finalize/SKILL.md` の手順6（PR作成）で生成する body をテンプレート形式に更新する。Change type は変更内容から自動判定する（既存の種別判定ロジック `fix > feat > docs > ci` を流用）。

> **注記**: 現在の auto-finalize の種別判定ロジックは `fix > feat > docs > ci` の4種のみ。テンプレートの `refactor` / `test` は自動判定の対象外。これらの種別判定の拡張は別 Issue で対応する。

### pr-review.yml の prompt 更新

prt 自動レビューが PR body の Change type を参照して判断精度を向上させるためには、`pr-review.yml` の prompt に以下の指示を追加する必要がある:

- PR body の Change type を確認すること
- `docs(pre-impl)` が選択されている場合、コードとの不整合を検出対象外とすること

現状の `pr-review.yml` は PR body を prt の prompt に明示的に渡していない。テンプレート導入と合わせて prompt を更新することで、prt 誤検知防止の目的を達成する。

## 移行時の注意事項

- テンプレート導入 PR のマージ後、以降の PR から適用される
- マージ前に作成されたオープン PR には自動適用されない（手動でテンプレート形式に修正するかは任意）

## 更新が必要なファイル

| ファイル | 変更内容 | 優先度 |
|---------|---------|--------|
| `.github/pull_request_template.md` | 新規作成（テンプレート本体） | 必須 |
| `CLAUDE.md` | PR body の `--body` 例を**全箇所**テンプレート形式に更新（通常開発・hotfix・auto-progress ステップ4/4） | 必須 |
| `.claude/skills/auto-finalize/SKILL.md` | 手順6の body 生成をテンプレート形式に更新 | 必須 |
| `.github/workflows/pr-review.yml` | prt prompt に PR body の Change type 参照指示を追加 | 必須 |
| `docs/specs/git-flow.md` | 「PRテンプレートは現行を維持」の記述を更新 | 必須 |

### CLAUDE.md の更新方針

- PR body の具体例を**全箇所**（通常開発・hotfix・auto-progress ステップ4/4）テンプレート形式に差し替え
- 「PR body は `.github/pull_request_template.md` の形式に従うこと」と明記
- 設計書先行更新時は「Change type で `docs(pre-impl)` を選択すること」と簡潔に記載（具体的な注記文言はテンプレート側のみに記載し、二重管理を回避）

## 受け入れ条件

- [ ] AC1: `.github/pull_request_template.md` が作成されている
- [ ] AC2: Web UI から PR を作成するとテンプレートが自動適用される
- [ ] AC3: Change type に `docs(pre-impl)` が選択肢として含まれている
- [ ] AC4: CLAUDE.md の PR body 指示がテンプレート形式に更新されている
- [ ] AC5: auto-finalize スキルの body 生成がテンプレート形式に更新されている
- [ ] AC6: テンプレートのセクション数が5個以下である
- [ ] AC7: docs(pre-impl) 選択時に不整合が意図的である旨の注記がテンプレート内に表示される
- [ ] AC8: pr-review.yml の prompt が PR body の Change type を参照し、`docs(pre-impl)` 時にコードとの不整合を検出対象外とする
- [ ] AC9: git-flow.md の「PRテンプレートは現行を維持」の記述が更新されている

## テスト方針

本仕様はテンプレートファイルの追加とドキュメント更新が主であり、以下の手動検証で確認する:

- markdownlint でテンプレートファイルのエラーがないこと
- Web UI での PR 作成時にテンプレートが表示されること（マージ後に確認）
- CLAUDE.md 内の**全ての** `gh pr create --body` 記述がテンプレート形式に更新されていること（通常開発・hotfix・auto-progress ステップ4/4）
- pr-review.yml の prompt に Change type 参照の指示が含まれていること

## 関連ファイル

| ファイル | 役割 |
|---------|------|
| `.github/pull_request_template.md` | テンプレート本体（新規作成） |
| `CLAUDE.md` | PR body ルール・`gh pr create` の例 |
| `.claude/skills/auto-finalize/SKILL.md` | auto-finalize スキルの PR 作成手順 |
| `docs/specs/git-flow.md` | git-flow 運用仕様（PR テンプレートの参照あり） |
| `.github/workflows/pr-review.yml` | prt 自動レビュー（prompt に Change type 参照指示を追加） |

## 参考

- [Issue #341](https://github.com/becky3/ai-assistant/issues/341): PR body テンプレートの導入
- PR #338: 設計書先行更新で prt 誤検知が発生した事例
