# 引き継ぎ: F2 Block Kit配信 + OGP画像表示

## 完了済み作業

- Block Kit形式でのカテゴリ別配信メッセージ (#23)
  - `format_daily_digest` をテキスト形式からBlock Kit辞書形式に変更
  - ヘッダー・カテゴリ別・フッターを別メッセージとして投稿
  - `_build_category_blocks` でカテゴリごとのBlock Kit構築
  - `FEED_ARTICLES_PER_CATEGORY` 設定でカテゴリあたりの表示件数制御
- 記事カードにOGP画像表示 (#25, PR #30)
  - `src/services/ogp_extractor.py` を新規作成（OGP画像URL抽出サービス）
  - 取得元: og:imageメタタグ、media_content、media_thumbnail、enclosure、summary内imgタグ
  - `Article` モデルに `image_url` カラム追加
  - Block Kitで独立imageブロックとして画像表示
  - 画像取得失敗・Slackダウンロード失敗時は画像なしでフォールバック配信
  - タイトルにリンク付与、要約を全文表示、カテゴリヘッダーの視認性向上
  - HTMLエンティティのデコード対応（Qiitaの`&amp;`問題）
- 手動配信キーワードを `deliver` のみに統一（`配信テスト`/`テスト配信` 廃止）
- 仕様書更新: `docs/specs/f2-feed-collection.md` にAC10（OGP画像取得・表示）追加
- テスト: 全66件パス

## 未着手・作業中

- Issue #22: Slackからフィードの追加・削除・管理
- Issue #24: 定型メッセージをローカルLLMでアシスタント性格に合わせた表現に変換
- Issue #20: 実環境での動作確認
- Issue #27: Slackスラッシュコマンド対応（コマンド体系が固まってから着手）
- Issue #28: APScheduler廃止・Slackリマインダー運用への移行
- Issue #29: 配信済み記事の重複配信防止（deliveredフラグ）

## 注意事項・判断メモ

- `daily_collect_and_deliver` のインポートはハンドラ内でローカルインポートしている（循環参照回避のため）
- 手動配信は `SLACK_NEWS_CHANNEL_ID` に投稿される（メンションしたチャンネルではない）
- `collector`, `session_factory`, `slack_client`, `channel_id` の4つが全て渡されていない場合、配信テストキーワードは無視される（静かにフォールスルーしてチャット応答になる）
- MediumはCloudflare保護(403)でHTMLアクセス不可。RSSのsummary内imgタグからフォールバック取得している
- Redditは `media_thumbnail` フィールドから画像取得
- QiitaのOGP画像URLにはHTMLエンティティ(`&amp;`等)が含まれるため `html.unescape` でデコードしている
- 既存DBに `image_url` カラムがない場合は `ALTER TABLE articles ADD COLUMN image_url VARCHAR(2048)` が必要（またはDB再作成）
- `deliver` を何度実行しても同じ記事が表示される問題あり → Issue #29 で対応予定

## 環境メモ

- LM Studioは `src/config/settings.py` の `lmstudio_base_url`（デフォルト `http://localhost:1234/v1`）で接続
- `.env` に `SLACK_NEWS_CHANNEL_ID` の設定が必要
