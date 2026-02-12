# リーダーガードフック — レトロスペクティブ

## 概要

エージェントチームのリーダー管理専任ルール（Edit/Write使用禁止）を、PreToolUseフック（`.claude/scripts/leader-guard.sh`）で技術的に制約する機能を実装した。

- Issue: #248
- PR: #249

## 実装の概要

- `.claude/scripts/leader-guard.sh` を新規作成
- PreToolUseフックとして Edit/Write ツール使用時に実行される
- stdin から JSON を読み取り、`permission_mode` でリーダー/メンバーを判別
- リーダーかつチーム稼働中（`~/.claude/teams/` 配下にディレクトリが存在）の場合、deny 応答でブロック
- メンバー（`bypassPermissions`）やチーム非稼働時は素通り
- `.claude/settings.json` に PreToolUse フック設定を追加
- 仕様書3つ（`agent-teams.md`, `agent-teams-operations.md`, `claude-code-hooks.md`）を更新

## うまくいったこと

### 1. permission_mode によるリーダー/メンバー判別

PreToolUse フックの stdin に含まれる `permission_mode` フィールドを活用し、`bypassPermissions`（メンバー）と `default`（リーダー）を区別できた。これにより、メンバーの作業を妨げずにリーダーのみを制約する仕組みが実現した。

### 2. jq / grep フォールバック

jq がインストールされていない環境でも grep/sed で `permission_mode` を抽出するフォールバックを実装。環境依存を最小化した。

### 3. deny 応答によるブロック

PreToolUse フックの `permissionDecision: "deny"` を活用し、警告ではなく実際にツール実行をブロックする強い制約を実現した。

## ハマったこと・改善点

### 1. permissions.allow からの除外がメンバーにも影響する問題

**問題**: 当初、`.claude/settings.json` の `permissions.allow` から Edit/Write を除外する方針で実装した。しかし、permissions はプロジェクト全体に適用されるため、`bypassPermissions` でスポーンしたメンバーにも影響が及ぶことが判明した。

**対応**: permissions.allow からの除外は見送り、PreToolUse フックのみで対応する方針に変更した。

**教訓**: `settings.json` の設定はセッション単位ではなくプロジェクト全体に適用される。リーダーだけを制約したい場合、permissions は使えない。

### 2. 作業中の settings.json 変更が即座に反映される

**問題**: permissions.allow から Edit/Write を除外した状態で作業を進めると、メンバーを含む全セッションで Edit/Write 使用時にユーザーへの承認ダイアログが出てしまう。

**対応**: 一旦 Edit/Write を復元し、コミット直前に再適用する方針に変更。最終的には permissions.allow からの除外自体を見送った。

**教訓**: settings.json の変更は即座に全セッションに影響する。チーム作業中の変更は特に慎重に行う必要がある。

### 3. 方針が二転三転した

**経緯**:

1. 最初の方針: PreToolUse フックで警告 + permissions.allow から除外の二段構え
2. 方針変更1: permissions.allow からの除外がメンバーに影響するため見送り、フックによる警告のみに
3. 方針変更2: 警告のみでは弱い → stdin の permission_mode を使って deny 応答でブロックする方式に

**教訓**: 設計段階で「プロジェクト全体の設定」と「セッション固有の設定」の区別を意識していれば、permissions.allow の除外は最初から検討対象外にできた。

### 4. 自動レビューで10件の指摘

**問題**: 初回実装では fail-open 未対応、chmod +x 漏れ、エラーメッセージの具体性不足、nullglob 未対応、例外運用と技術的制約の不整合など、10件の指摘を受けた。

**対応**: fail-open 設計を全面的に導入（stdin 空、permission_mode 取得失敗、HOME 未定義、ディレクトリ読み取り権限なし）。エラーメッセージを具体化し、nullglob 対応を追加。仕様書の例外運用記載を整合させた。

**教訓**: フックスクリプトは「正常系が動く」だけでは不十分。エラー時の挙動（fail-open / fail-closed）を最初から設計に含めるべき。

### 5. 実装担当1名への負荷集中

**問題**: 実装担当が1名で、スクリプト実装、settings.json 更新、仕様書3つの更新、方針変更への対応2回、レビュー指摘10件への対応、レトロ作成、追加ルール追記を全て担った。特に方針変更のたびに仕様書3つの該当箇所を追跡して書き直す必要があり、負荷が高かった。

**対応**: 実装タスク時は2名以上配置を推奨するルールを新設した。

**教訓**: 複数ファイルにまたがる修正では、方針変更1回あたりの修正コストが高い。分担することで追跡コストを分散できる。

## 次に活かすこと

1. **settings.json の変更は即座に全セッションに影響する**: 作業中の変更は慎重に。特にチーム運用中は全メンバーに影響が及ぶ

2. **bypassPermissions でスポーンしたエージェントも settings.json の permissions.allow の影響を受ける**: permissions による制約はリーダーだけに限定できない

3. **PreToolUse フックの stdin に permission_mode が含まれ、リーダー/メンバー判別に使える**: `"bypassPermissions"` はメンバー、`"default"` はリーダー

4. **設計時に「プロジェクト全体の設定」と「セッション固有の設定」の区別を意識する**: settings.json はプロジェクト全体、stdin の permission_mode はセッション固有

5. **フックスクリプトは fail-open 設計にする**: 運用支援ツールはユーザーの作業を止めないことを優先。エラー時の挙動を最初から設計に含める

6. **実装タスク時は2名以上配置を推奨**: 分量に応じて柔軟に分担し、方針変更時の修正コストを分散する

7. **方針変更時はリーダーが変更箇所をファイル名・行番号レベルで具体的に指示する**: 複数ファイルにまたがる修正では、変更箇所の追跡コストが高い

8. **リーダーはキャラクターとして一貫して振る舞う**: 特に事務的な応答（「待ちます」「確認します」等）でキャラクターが抜けやすい。メンバーへの指示・ユーザーへの報告ともにキャラクター口調を維持する

## 参考

- エージェントチーム仕様: [docs/specs/agent-teams.md](../specs/agent-teams.md)
- エージェントチーム運用詳細: [docs/specs/agent-teams-operations.md](../specs/agent-teams-operations.md)
- Claude Code Hooks 仕様: [docs/specs/claude-code-hooks.md](../specs/claude-code-hooks.md)
- 関連Issue: #248
- 関連PR: #249
