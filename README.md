# ボーテスキンクリニック 料金管理システム

## 概要

Googleスプレッドシートで管理している料金データを自動取得・Web公開するシステムです。

## ファイル構成

```
BEAUTE/
├── data/
│   ├── prices.json          ← 管理者用データ（コスト・利益情報含む）
│   └── prices_public.json   ← 公開用データ（コスト情報なし）
├── scripts/
│   ├── fetch_and_merge.py   ← スプレッドシートからデータ取得・マージ
│   └── build_public.py      ← 公開用JSON生成（コスト情報除去）
├── web/
│   ├── index.html           ← スタッフ・お客様用ページ（公開）
│   └── admin/
│       └── index.html       ← 管理者用ページ（パスワード保護）
└── .github/
    └── workflows/
        └── update-prices.yml ← 自動更新ワークフロー
```

## データソース

| スプレッドシート | 用途 |
|-----------------|------|
| コストなし版 | 最新・正の価格データ |
| コストあり版 | コスト・利益情報（P列・Q列） |

## 操作方法

### 料金を変更したい場合
1. Googleスプレッドシート（コストあり版）を編集する
2. GitHubの「Actions」タブを開く
3. 「料金データ自動更新」を選択
4. 「Run workflow」ボタンをクリック
5. 約1分後にWebページに反映される

※毎朝6時に自動更新も実行されます

### 管理者ページのパスワード変更
`web/admin/index.html` の以下の行を変更:
```javascript
const ADMIN_PASSWORD = "beaute2024";  // ← ここを変更
```

## GitHub Pages 設定（初回のみ）

1. GitHubリポジトリの「Settings」→「Pages」を開く
2. Source: 「Deploy from a branch」を選択
3. Branch: `main` / Folder: `/web` を選択
4. 「Save」をクリック

公開URL（例）:
- スタッフ・お客様用: `https://[username].github.io/BEAUTE/`
- 管理者用: `https://[username].github.io/BEAUTE/admin/`

## 権限管理

| ユーザー | アクセス先 | 閲覧できる内容 |
|---------|-----------|--------------|
| お客様・スタッフ | 公開ページ | 価格・キャンペーン情報 |
| 管理者（2〜3名） | 管理者ページ（要パスワード） | 全データ＋コスト・利益率 |
