#!/usr/bin/env python3
"""
ボーテスキンクリニック 料金データ取得スクリプト（新マスター版）

新しい整理済みGoogleスプレッドシート（1シート・フラットテーブル）から
料金データを取得し、Web表示用のJSONを生成する。

使用方法:
  python3 scripts/fetch_from_master.py
"""
from __future__ import annotations

import csv
import json
import math
import urllib.request
import urllib.error
import io
import os
import sys
from datetime import datetime

# ============================================================
# マスタースプレッドシート設定
# ============================================================
MASTER_SPREADSHEET_ID = "1aoRw1sc5Jw1S2RwP4EoTztzQHKGf2SWYoRAAbSScmZU"

# 旧スプレッドシート（参照用・読み取り専用のバックアップ）
OLD_NO_COST = "1Nw-myLLojzdm0FZJMkwb3n2QHcXnvhFw"
OLD_WITH_COST = "1jv43DpLm-d0awOV-rxD4ACCaszg2IPFK"

# カテゴリの表示順序
CATEGORY_ORDER = [
    "シミ取り（そばかす・肝斑・ほくろ）",
    "しわ・たるみ",
    "注入系",
    "スレッド（糸リフト）",
    "美肌治療",
    "美容整形・外科",
    "ピーリング",
    "医療ボディ（痩身）",
    "医療脱毛",
    "点滴・注射",
    "内服・外用薬",
    "フェイシャル",
    "リラクゼーション",
    "ボディ",
    "エステその他",
]

# ============================================================
# プリペイド割引率テーブル
# ============================================================
# 施術者区分 → { ティア → 割引率(%) }
PREPAID_RATES = {
    "看護師": {"10万": 10, "30万": 20, "50万": 25},
    "Dr.":    {"10万": 0,  "30万": 10, "50万": 10},
    "Dr.オペ": {"10万": 0,  "30万": 0,  "50万": 10},
    "エステ":  {"10万": 10, "30万": 20, "50万": 20},
}

# 10万円プリペイド対象施術キーワード（看護師・エステの場合のみ適用）
PP10_ELIGIBLE_KEYWORDS = [
    "フォトナ", "ピコトーニング", "ピコフラクショナル", "フォトフェイシャル",
    "イオン導入", "ピーリング", "ダーマペン", "ヴェルヴェット", "ハイドラ", "オプション",
]


def fetch_csv(spreadsheet_id: str) -> list[list[str]]:
    """GoogleスプレッドシートをCSVとして取得"""
    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            content = response.read().decode("utf-8")
            reader = csv.reader(io.StringIO(content))
            return list(reader)
    except urllib.error.URLError as e:
        print(f"エラー: スプレッドシートの取得に失敗しました - {e}", file=sys.stderr)
        sys.exit(1)


def clean_price(value: str) -> str:
    """価格文字列のクリーニング"""
    if not value or not value.strip():
        return ""
    v = value.strip().replace("¥", "").replace(",", "").replace(" ", "").replace("　", "")
    if v in ["0", "-", "—", "―", ""]:
        return ""
    return v


def calc_prepaid_prices(price_str: str, provider_type: str, treatment: str, categories: list) -> dict:
    """プリペイド3ティア価格を自動計算"""
    result = {"prepaid_10": None, "prepaid_30": None, "prepaid_50": None}

    if not price_str or not provider_type:
        return result

    try:
        price = int(price_str)
    except ValueError:
        return result

    rates = PREPAID_RATES.get(provider_type)
    if not rates:
        return result

    # 10万ティア: 対象施術かチェック
    rate_10 = rates.get("10万", 0)
    if rate_10 > 0:
        cat_str = " ".join(categories) if categories else ""
        is_eligible = any(kw in (treatment or "") or kw in cat_str
                         for kw in PP10_ELIGIBLE_KEYWORDS)
        if is_eligible:
            result["prepaid_10"] = str(math.floor(price * (100 - rate_10) / 100))

    # 30万ティア
    rate_30 = rates.get("30万", 0)
    if rate_30 > 0:
        result["prepaid_30"] = str(math.floor(price * (100 - rate_30) / 100))

    # 50万ティア
    rate_50 = rates.get("50万", 0)
    if rate_50 > 0:
        result["prepaid_50"] = str(math.floor(price * (100 - rate_50) / 100))

    return result


def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    print("=" * 60)
    print("ボーテスキンクリニック 料金データ取得（新マスター版）")
    print("=" * 60)
    print(f"実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"マスター: https://docs.google.com/spreadsheets/d/{MASTER_SPREADSHEET_ID}")
    print()

    # マスタースプレッドシートを取得
    print("マスタースプレッドシートを取得中...")
    rows = fetch_csv(MASTER_SPREADSHEET_ID)
    print(f"  → {len(rows)}行 取得")

    if len(rows) < 2:
        print("エラー: データが空です", file=sys.stderr)
        sys.exit(1)

    # ヘッダー行を解析
    headers = [h.replace("\n", "").strip() for h in rows[0]]
    print(f"  → 列: {headers}")

    # 列インデックスのマッピング
    col = {}
    for i, h in enumerate(headers):
        if "施術カテゴリ" in h:
            col["category"] = i
        elif "施術者" in h or "区分" in h:
            col["provider_type"] = i
        elif "施術名" in h:
            col["treatment"] = i
        elif "対象部位" in h:
            col["area"] = i
        elif "回数" in h and "回数券" not in h:
            col["sessions"] = i
        elif "旧価格" in h:
            col["old_price"] = i
        elif "通常価格" in h:
            col["price"] = i
        elif "初回価格" in h:
            col["first_price"] = i
        elif "リピート" in h:
            col["repeat_price"] = i
        elif "回数券" in h:
            col["bundle_price"] = i
        elif "キャンペーン" in h:
            col["campaign_price"] = i
        elif "モニター" in h and "全顔" in h:
            col["monitor_full_price"] = i
        elif "モニター" in h and "目元" in h:
            col["monitor_eye_price"] = i
        elif "プリペイド" in h:
            col["prepaid_price"] = i
        elif "コスト" in h:
            col["cost_note"] = i
        elif "利益" in h:
            col["profit_note"] = i

    print(f"  → マッピング: {list(col.keys())}")

    def get(row, key):
        idx = col.get(key)
        if idx is None or idx >= len(row):
            return ""
        return row[idx].strip()

    # データ行を解析
    records = []
    for row in rows[1:]:
        if not row or not any(cell.strip() for cell in row):
            continue

        price = clean_price(get(row, "price"))
        if not price:
            continue  # 価格がない行はスキップ

        provider_type = get(row, "provider_type")
        treatment = get(row, "treatment")
        category_raw = get(row, "category")
        # カンマ区切りで複数カテゴリ対応
        categories = [c.strip() for c in category_raw.split(",") if c.strip()] if category_raw else []
        category = categories[0] if categories else ""

        # プリペイド3ティア自動計算
        pp = calc_prepaid_prices(price, provider_type, treatment, categories)

        # スプレッドシートの手動プリペイド価格があればオーバーライド用に保持
        manual_pp = clean_price(get(row, "prepaid_price")) or None

        record = {
            "category": category,
            "categories": categories,
            "provider_type": provider_type or None,
            "treatment": treatment,
            "area": get(row, "area"),
            "sessions": get(row, "sessions"),
            "old_price": clean_price(get(row, "old_price")) or None,
            "price": price,
            "first_price": clean_price(get(row, "first_price")) or None,
            "repeat_price": clean_price(get(row, "repeat_price")) or None,
            "bundle_price": clean_price(get(row, "bundle_price")) or None,
            "campaign_price": clean_price(get(row, "campaign_price")) or None,
            "monitor_full_price": clean_price(get(row, "monitor_full_price")) or None,
            "monitor_eye_price": clean_price(get(row, "monitor_eye_price")) or None,
            "prepaid_10": pp["prepaid_10"],
            "prepaid_30": pp["prepaid_30"],
            "prepaid_50": pp["prepaid_50"],
            "prepaid_manual": manual_pp,
            "cost_note": get(row, "cost_note") or None,
            "profit_note": get(row, "profit_note") or None,
        }
        records.append(record)

    print(f"  → {len(records)}件の施術データ")
    with_cost = sum(1 for r in records if r.get("cost_note") or r.get("profit_note"))
    with_provider = sum(1 for r in records if r.get("provider_type"))
    print(f"  → うちコスト情報付き: {with_cost}件")
    print(f"  → うち施術者区分あり: {with_provider}件")

    # 出力データ
    now = datetime.now()
    output = {
        "metadata": {
            "generated_at": now.isoformat(),
            "master_spreadsheet": f"https://docs.google.com/spreadsheets/d/{MASTER_SPREADSHEET_ID}",
            "total_records": len(records),
            "records_with_cost": with_cost,
        },
        "treatments": records,
        "prepaid_discount_rates": {
            "10万円": {
                "nurse": "10%オフ",
                "doctor": "なし",
                "estethic": "10%オフ",
                "applicable": ["フォトナ・ピコトーニング", "ピコフラクショナル・フォトフェイシャル",
                               "イオン導入・ピーリング", "ダーマペン・ヴェルヴェット", "ハイドラ・オプション"],
                "note": "以下の施術限定・それ以外は対象外"
            },
            "30万円": {
                "nurse": "20%オフ",
                "doctor": "10%オフ",
                "estethic": "20%オフ",
                "applicable": "全ての施術で使える",
            },
            "50万円": {
                "nurse": "25%オフ",
                "doctor": "10%オフ",
                "estethic": "20%オフ",
                "applicable": "全ての施術で使える",
            },
            "紹介": {
                "nurse": "30%オフ",
                "doctor": "15%オフ",
                "estethic": "30%オフ",
                "note": "除外：オペ・ピコスポット・CO2・ボトックス麻酔・オプション・点滴",
                "expiry": "2026年3月末まで（無期限配布分）",
            }
        }
    }

    # ===== 管理者用JSON（コスト情報あり）=====
    admin_path = os.path.join(base_dir, "web", "data", "prices.json")
    os.makedirs(os.path.dirname(admin_path), exist_ok=True)
    with open(admin_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # ===== 公開用JSON（コスト情報なし）=====
    ADMIN_ONLY_FIELDS = {"cost_note", "profit_note"}
    public_treatments = []
    for r in records:
        pub = {k: v for k, v in r.items() if k not in ADMIN_ONLY_FIELDS}
        public_treatments.append(pub)

    public_output = {
        "metadata": {
            **output["metadata"],
            "note": "公開用データ（コスト情報除去済み）",
        },
        "treatments": public_treatments,
        "prepaid_discount_rates": output["prepaid_discount_rates"],
    }

    public_path = os.path.join(base_dir, "web", "data", "prices_public.json")
    with open(public_path, "w", encoding="utf-8") as f:
        json.dump(public_output, f, ensure_ascii=False, indent=2)

    # ===== バージョン管理用スナップショット =====
    snapshot_dir = os.path.join(base_dir, "web", "data", "history")
    os.makedirs(snapshot_dir, exist_ok=True)
    snapshot_file = os.path.join(snapshot_dir, f"{now.strftime('%Y%m%d')}.json")
    with open(snapshot_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print()
    print(f"✅ 管理者用JSON: {admin_path}")
    print(f"✅ 公開用JSON:   {public_path}")
    print(f"✅ 履歴スナップ:  {snapshot_file}")

    # カテゴリ別サマリー
    print()
    print("【カテゴリ別件数】")
    from collections import Counter
    cat_counter = Counter()
    for r in records:
        for cat in r.get("categories", [r["category"]]):
            cat_counter[cat] += 1
    for cat, n in sorted(cat_counter.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {n}件")


if __name__ == "__main__":
    main()
