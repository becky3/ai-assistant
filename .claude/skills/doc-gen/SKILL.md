---
name: doc-gen
description: プロジェクトドキュメント（仕様書・レトロ）の新規作成
user-invocable: true
allowed-tools: Bash, Read, Edit, Write, Grep, Glob
argument-hint: "[spec|retro] [feature-name]"
---

## タスク

プロジェクトドキュメントを自動生成する。Issue/PR/コミット履歴から情報を収集し、CLAUDE.mdのルールに従ったフォーマットで出力する。

## 引数

`$ARGUMENTS` の形式:
- `spec <feature-name>`: 仕様書生成（例: `spec feed-collection`）
- `retro <feature-name>`: レトロスペクティブ生成（例: `retro chat`）

## 処理手順

### 共通フロー

1. **引数解析**
   ```bash
   ARGS=($ARGUMENTS)
   DOC_TYPE="${ARGS[0]}"  # spec, retro
   FEATURE_NAME="${ARGS[1]}"  # 機能名
   ```

2. **既存ドキュメントの参照**
   - 同種のドキュメントを1-2件読み込み、フォーマットを理解する

3. **出力ファイル名の決定**
   - CLAUDE.mdの命名規則に従う
   - 既存ファイルがある場合は警告を表示し、上書き確認

4. **ドキュメント生成**
   - テンプレートに従って各セクションを作成
   - 関連情報（Issue/PR/コミット）を調査・反映

5. **ファイル保存**
   - Writeツールでファイルを作成
   - 生成結果を表示

### A. 仕様書生成 (`spec <feature-name>`)

**出力先**: `docs/specs/f{N}-{feature-name}.md`

**手順**:

1. 機能番号の決定
   - 既存の仕様書一覧から最大のf{N}を取得
   - 新規機能は次の番号を割り当て（例: f5, f6, ...）
   - 既存機能を指定された場合はその番号を使用

2. Issue情報の収集
   ```bash
   # 該当機能のIssueを検索
   gh issue list --search "in:title $FEATURE_NAME" --json number,title,body
   ```
   - Issue本文から要件を抽出
   - コメントから議論内容を収集

3. 関連コードの調査
   ```bash
   # 機能に関連するファイルを検索
   find src/ -name "*${FEATURE_NAME}*"
   ```

4. 仕様書生成（以下のセクションを含む）:
   - **概要**: 機能の簡潔な説明
   - **背景**: なぜこの機能が必要か
   - **ユーザーストーリー**: ユーザー視点での要求
   - **技術仕様**: 入出力、処理フロー
   - **受け入れ条件 (AC)**: チェックボックス形式
   - **使用LLMプロバイダー**: オンライン/ローカル
   - **関連ファイル**: テーブル形式
   - **テスト方針**: テスト戦略

**参考**: `docs/specs/f1-chat.md` のフォーマットを踏襲

### B. レトロスペクティブ生成 (`retro <feature-name>`)

**出力先**: `docs/retro/f{N}-{feature-name}.md`

**手順**:

1. 機能番号の決定
   - 仕様書と同じ番号を使用

2. 実装情報の収集
   ```bash
   # 該当機能のPR
   gh pr list --search "in:title $FEATURE_NAME" --state all --json number,title,body

   # 関連コミット
   gh pr view <pr-number> --json commits
   ```

3. Issue/PRコメントから学びを抽出
   - 実装時の議論
   - 技術的な判断
   - ハマったポイント

4. レトロ生成（以下のセクションを含む）:
   - **何を実装したか**: 機能の概要
   - **うまくいったこと**: 良かったアプローチ、効率的だった点
   - **改善点**: 時間がかかった部分、難しかった点
   - **次に活かすこと**: 今後の開発に役立つ知見

## エラーハンドリング

- 引数が不正な場合:
  ```
  エラー: 引数が不正です。
  使用方法:
    /doc-gen spec <feature-name>
    /doc-gen retro <feature-name>
  ```

- 既存ファイルがある場合:
  ```
  警告: ファイル {path} は既に存在します。
  上書きしますか？ (y/n)
  ```

- Issue/PRが見つからない場合:
  ```
  警告: {feature-name} に関連するIssue/PRが見つかりませんでした。
  手動で情報を入力してドキュメントを作成します。
  ```

## 出力例

```
✓ 仕様書を生成しました: docs/specs/f5-notification.md

内容:
- Issue #42 の要件を反映
- 関連ファイル 3件を特定
- 受け入れ条件 5項目を定義

次のステップ:
1. 仕様書をレビュー
2. 実装を開始
3. 完了後に `/doc-gen retro notification` でレトロを作成
```

## 注意事項

- 生成されたドキュメントは必ず人間がレビューし、必要に応じて修正する
- Issue/PRから自動収集できない情報は「TODO」として明示する
- 既存ファイルを上書きする前に必ず確認する
