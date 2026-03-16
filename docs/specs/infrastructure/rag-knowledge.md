# RAG ナレッジ

## 概要

RAG（Retrieval-Augmented Generation）基盤との連携仕様。
RAG 機能は独立リポジトリ（rag-knowledge）で実装・運用しており、ai-assistant からは MCP サーバーとして HTTP 接続する。

## 背景

- LLM の学習済み知識とリアルタイムの会話コンテキストのみでは、特定 Web サイトの情報に基づいた回答ができない
- 知識ベースの蓄積・検索を MCP サーバーとして独立させ、本体アプリケーションとの疎結合を維持する

## 制約

- RAG の実装・設定・テストは rag-knowledge リポジトリで管理する。ツールの詳細仕様は rag-knowledge 側の仕様書を参照
- ai-assistant からは MCP サーバー設定（`config/mcp_servers.json`）で RAG サーバーに HTTP 接続する
- RAG サーバーは別プロセスとして事前に起動しておく必要がある
- RAG の利用可否は MCP 基盤の有効化（`MCP_ENABLED`）と MCP サーバー設定への登録で決まる

## インターフェース

### チャット統合

LLM がツールループ内で `rag_search` を呼ぶかどうかを自律的に判断する。
MCP サーバー設定の `system_instruction` / `response_instruction` により、ナレッジベース関連の質問時に検索を促す。

MCP ツールの定義・振る舞いは rag-knowledge リポジトリ側の仕様書で管理する。

## コンポーネント構成

本仕様書固有のコンポーネントはない。接続構成は [MCP 統合](mcp-integration.md) のコンポーネント構成図を参照。

## 外部連携

| 連携先 | 用途 | 接続方式 |
| --- | --- | --- |
| rag-knowledge リポジトリ | RAG MCP サーバー | HTTP（Streamable HTTP） |

## 関連ドキュメント

- [MCP 統合](mcp-integration.md) — MCP サーバーの接続管理・ツール呼び出し基盤
- [chat-response](../features/chat-response.md) — チャット応答（ソース URL 付与）
