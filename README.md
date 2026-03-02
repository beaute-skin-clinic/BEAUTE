# ボーテスキンクリニック 料金管理システム

## 概要

Googleスプレッドシートで管理している料金データを自動取得・Web公開するシステムです。

## マスタースプレッドシート

https://docs.google.com/spreadsheets/d/1aoRw1sc5Jw1S2RwP4EoTztzQHKGf2SWYoRAAbSScmZU/edit

**オーナーはこのスプレッドシートのセルを書き換えるだけで料金変更できます。**

| 列 | 内容 | 編集頻度 |
|----|------|---------|
| 施術カテゴリ | シミ取り、脱毛等 | まれに |
| 施術名 | ピコトーニング等 | まれに |
| 対象部位 | 顔全体、VIO等 | まれに |
| 回数 | 1回、5回等 | ほぼなし |
| **通常価格（税込）** | **メイン価格** | **よく編集** |
| 初回価格 | 初回お試し | 時々 |
| 回数券価格 | セット割 | 時々 |
| キャンペーン価格 | 期間限定 | 時々 |
| プリペイド割価格 | プリカ割 | 時々 |
| 【管理者】コスト | 原価情報 | 管理者のみ |
| 【管理者】利益メモ | 利益情報 | 管理者のみ |

## ファイル構成

```
BEAUTE/
├── scripts/
│   ├── fetch_from_master.py  ← マスターから取得・JSON生成（メイン）
│   ├── fetch_and_merge.py    ← 旧版：2シートマージ（バックアップ用）
│   ├── build_public.py       ← 旧版：公開用JSON生成
│   └── export_clean_master.py ← マスターCSV生成ツール
├── web/
│   ├── index.html            ← スタッフ・お客様用ページ
│   ├── admin/index.html      ← 管理者用ページ（パスワード保護）
│   └── data/
│       ├── prices.json       ← 管理者用データ（コストあり）
│       ├── prices_public.json ← 公開用データ（コストなし）
│       └── history/          ← 日次スナップショット（バージョン管理）
└── .github/workflows/
    └── update-prices.yml     ← 毎朝6時 自動更新
```

## 操作方法

### 料金を変更したい場合
1. マスタースプレッドシートのセルを書き換える
2. GitHubの「Actions」タブ →「料金データ自動更新」→「Run workflow」
3. 約1分後にWebページに反映

※毎朝6時にも自動で反映されます

### バージョン管理（「先週いくらだった？」に対応）
- **スプレッドシート**: ファイル → 変更履歴 で過去の状態を確認
- **Git**: `web/data/history/` に日付別のスナップショットが自動保存される

### 管理者ページのパスワード変更
`web/admin/index.html` の以下の行を変更:
```javascript
const ADMIN_PASSWORD = "beaute2024";  // ← ここを変更
```

## GitHub Pages 設定（初回のみ）

1. GitHubリポジトリの Settings → Pages
2. Source: Deploy from a branch
3. Branch: `main` / Folder: `/web`
4. Save

## 旧スプレッドシート（参照用・編集しない）

| スプレッドシート | 用途 |
|-----------------|------|
| コストなし版 (1Nw-) | 旧マスター・最新価格 |
| コストあり版 (1jv4-) | 旧版・コスト情報元 |
