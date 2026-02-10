---
name: topic
description: 学びトピックの自動抽出・Zenn記事生成
user-invocable: true
allowed-tools: Bash, Read, Edit, Write, Grep, Glob
argument-hint: "[番号]"
---

## タスク

レトロスペクティブ（`docs/retro/`）やMEMORY.mdから学びトピックを自動抽出し、Zenn形式の記事を生成する。

## 引数

`$ARGUMENTS` の形式:

- 引数なし: トピック候補を自動抽出・表示
- `<番号>`: 選んだトピックの記事を生成

## 処理手順

### A. トピック候補表示（引数なし）

1. **抽出対象のスキャン**
   - `docs/retro/*.md` — レトロスペクティブ
   - `~/.claude/projects/*/memory/MEMORY.md` — Claude Code開発知見

2. **トピック抽出ルール**
   - `## 改善点` `## ハマったこと` セクションを検出
   - 配下の `###` 見出しをトピック候補として抽出
   - 「教訓」「対応」キーワードがあれば優先度UP
   - `docs/zenn-drafts/published.txt` に記載済みのソースは候補から除外

3. **候補表示**

   ```text
   📚 学びトピック候補（未記事化）

   1. [★★] RSS 1.0形式での日付取得失敗（docs/retro/f2.md#3）
   2. [★★] skip-summary実装時のコード重複（docs/retro/f2.md#1）
   3. [★] Bot重複起動問題（docs/retro/f2.md#6）
   ...

   👉 記事化するには: /topic <番号>
   ```

### B. 記事生成（`/topic <番号>`）

1. **トピック情報の取得**
   - 指定番号のトピックをスキャン結果から取得
   - ソースファイルの該当セクションを読み込み

2. **LLMで記事生成**
   - Zennフロントマター形式で生成
   - ソースセクションの内容を元に構造化

3. **ファイル出力**
   - `docs/zenn-drafts/{topic-slug}.md` に保存
   - `docs/zenn-drafts/published.txt` にソース参照を追記

4. **結果表示**

   ```text
   ✅ 記事を生成しました: docs/zenn-drafts/rss-date-parsing.md
   ```

## Zenn記事テンプレート

```markdown
---
title: "{タイトル}"
emoji: "{自動選択}"
type: "tech"
topics: ["{tag1}", "{tag2}"]
published: false
---

## TL;DR

{3行で要約}

## 背景

{なぜこの問題に遭遇したか}

## 問題

{何が起きたか}

## 解決策

{どう解決したか、コード例}

## まとめ

{学びのポイント}
```

## 抽出ロジック詳細

### 優先度スコアリング

| 条件 | スコア加算 |
|------|-----------|
| セクションに「教訓」が含まれる | +2 |
| セクションに「対応」が含まれる | +1 |
| コードブロックが含まれる | +1 |
| 「問題」「原因」キーワードがある | +1 |

### ソース参照形式

`{相対パス}#{セクション番号}`

例: `docs/retro/f2.md#3` は f2.md の3番目の `###` 見出し

## エラーハンドリング

- 番号が範囲外:

  ```text
  エラー: 番号 {N} は候補にありません。`/topic` で候補を確認してください。
  ```

- レトロファイルが見つからない:

  ```text
  ⚠️ レトロスペクティブが見つかりませんでした。
  先に機能を実装し、`/doc-gen retro <feature>` でレトロを作成してください。
  ```

## 注意事項

- 生成された記事は必ずレビューしてから公開する
- `published: false` で生成されるため、Zenn上で確認後に `true` に変更
