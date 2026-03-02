#!/usr/bin/env python3
"""
ボーテスキンクリニック 料金データ取得・マージスクリプト

コストなし版（最新価格）とコストあり版（P・Q列にコスト情報）を
Googleスプレッドシートから取得し、マージしてJSONを生成する。

使用方法:
  python3 scripts/fetch_and_merge.py
"""
from __future__ import annotations

import csv
import json
import urllib.request
import urllib.error
import io
import os
import sys
from datetime import datetime
from typing import Optional, List, Dict

# ============================================================
# スプレッドシート設定
# ============================================================
SPREADSHEET_NO_COST = "1Nw-myLLojzdm0FZJMkwb3n2QHcXnvhFw"   # コストなし版（最新価格・正）
SPREADSHEET_WITH_COST = "1jv43DpLm-d0awOV-rxD4ACCaszg2IPFK"  # コストあり版（コスト情報付き）

# コストあり版 カテゴリ別シートID
# （施術カテゴリ, GID, P列名, Q列名）
WITH_COST_SHEETS = [
    # GID,          カテゴリ名称,                   P列の意味,    Q列の意味
    ("250922401",   "シミ取り（そばかす・肝斑・ほくろ）", "コスト",      "コスト2"),
    ("101442597",   "しわ・たるみ",                    None,         None),
    ("1231424483",  "注入系",                          None,         "備考コスト"),
    ("1691956801",  "スレッド（糸リフト）",              "利益",        None),
    ("136097638",   "美肌治療",                         "備考コスト",  "利益"),
    ("1137041870",  "美容整形・外科",                   None,         None),
    ("111708255",   "ピーリング",                       "利益",        None),
    ("1194063261",  "医療ボディ（痩身）",                None,         None),
    ("61927464",    "医療脱毛",                         None,         None),
    ("1656805005",  "点滴・注射",                       None,         None),
    ("289561760",   "内服・外用薬",                     None,         None),
    ("540577641",   "フェイシャル",                     None,         None),
    ("999905790",   "リラクゼーション",                  None,         None),
    ("1896636903",  "ボディ",                           None,         None),
    ("772650460",   "エステその他",                     None,         None),
]

# コストなし版の最新価格シート（公開ページ形式）
NO_COST_MAIN_GID = "1150979074"


def fetch_csv(spreadsheet_id: str, gid: str) -> list[list[str]]:
    """GoogleスプレッドシートのシートをCSVとして取得する"""
    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            content = response.read().decode("utf-8")
            reader = csv.reader(io.StringIO(content))
            return list(reader)
    except urllib.error.URLError as e:
        print(f"  エラー: GID {gid} の取得に失敗しました - {e}", file=sys.stderr)
        return []


def clean_price(value: str) -> str | None:
    """価格文字列をクリーニング（¥マーク・カンマ除去）"""
    if not value:
        return None
    v = value.strip().replace("¥", "").replace(",", "").replace(" ", "")
    if not v or v in ["0", "-", "—", "―"]:
        return None
    # 数値かどうか確認
    try:
        int(v)
        return v
    except ValueError:
        # 数値でない場合はそのまま返す（「1s4.5円」などのコスト注記）
        if v:
            return v
        return None


def parse_flat_sheet(rows: list[list[str]], gid: str, category: str,
                     p_label: str | None, q_label: str | None) -> list[dict]:
    """
    フラットテーブル形式のシートを解析してデータリストを返す
    フォーマット: 複数行ヘッダー + データ行
    """
    records = []

    # ヘッダー行を探す（施術カテゴリを含む行）
    header_row_idx = None
    for i, row in enumerate(rows[:8]):
        if row and "施術カテゴリ" in row[0]:
            header_row_idx = i
            break

    if header_row_idx is None:
        return records

    # ヘッダー行の構築（複数行にまたがるヘッダーを結合）
    headers = []
    for col_idx in range(len(rows[header_row_idx])):
        parts = []
        # 最大3行のヘッダーを結合
        for row_offset in range(3):
            row_i = header_row_idx + row_offset
            if row_i >= len(rows):
                break
            cell = rows[row_i][col_idx].strip().replace("\n", "") if col_idx < len(rows[row_i]) else ""
            if cell:
                parts.append(cell)
        headers.append("".join(parts[:2]))  # 最初の2パーツまで結合

    # データ開始行を探す
    data_start = header_row_idx + 1
    # 空行やヘッダー継続行をスキップ
    for i in range(header_row_idx + 1, min(header_row_idx + 5, len(rows))):
        row = rows[i]
        if row and row[0].strip() and row[0].strip() not in ["施術カテゴリ", ""] and not row[0].strip().startswith("式"):
            # 施術カテゴリっぽいデータが始まった
            # でも「式入ってます」行はスキップ
            if "式入ってます" not in row[0]:
                data_start = i
                break

    # 列インデックスを決定
    col_map = {}
    for i, h in enumerate(headers):
        h_norm = h.replace("\n", "").strip()
        if "施術カテゴリ" in h_norm:
            col_map["category"] = i
        elif "施術名" in h_norm:
            col_map["treatment"] = i
        elif "対象部位" in h_norm:
            col_map["area"] = i
        elif "回数" in h_norm or "本数" in h_norm:
            col_map["sessions"] = i
        elif "新価格" in h_norm or ("通常" in h_norm and "価格" in h_norm):
            if "price" not in col_map:
                col_map["price"] = i
        elif "現価格" in h_norm and "price" not in col_map:
            col_map["old_price"] = i
        elif "旧価格" in h_norm and "old_price" not in col_map:
            col_map["old_price"] = i
        elif "初回" in h_norm and "割引" not in h_norm:
            col_map["first_price"] = i
        elif "初回" in h_norm and ("割引" in h_norm or "率" in h_norm):
            col_map["first_discount"] = i
        elif "回数券" in h_norm and "率" not in h_norm and "割引" not in h_norm:
            col_map["bundle_price"] = i
        elif "回数券" in h_norm and ("率" in h_norm or "割引" in h_norm):
            col_map["bundle_discount"] = i
        elif "キャンペーン" in h_norm and "率" not in h_norm and "割引" not in h_norm:
            col_map["campaign_price"] = i
        elif "キャンペーン" in h_norm and ("率" in h_norm or "割引" in h_norm):
            col_map["campaign_discount"] = i
        elif "プリ割" in h_norm or ("プリペイド" in h_norm and "割" in h_norm):
            col_map["prepaid_price"] = i

    # P列(16)・Q列(17)のコスト情報
    # Excelのカラム番号: P=16番目(0-indexed:15), Q=17番目(0-indexed:16)
    P_IDX = 15
    Q_IDX = 16

    # データを解析
    current_category = category  # カテゴリデフォルト
    for row in rows[data_start:]:
        if not row or not any(cell.strip() for cell in row):
            continue  # 空行スキップ

        # 施術カテゴリ列の値
        cat_val = row[col_map.get("category", 0)].strip() if col_map.get("category", 0) < len(row) else ""
        if cat_val and cat_val != "施術カテゴリ":
            current_category = cat_val

        # 施術名
        treatment = row[col_map.get("treatment", 1)].strip() if col_map.get("treatment", 1) < len(row) else ""

        # 価格
        price_idx = col_map.get("price")
        new_price = clean_price(row[price_idx]) if price_idx is not None and price_idx < len(row) else None
        old_price = clean_price(row[col_map.get("old_price", -1)]) if col_map.get("old_price") is not None and col_map["old_price"] < len(row) else None

        # 最終価格: new_price優先、なければold_price
        final_price = new_price or old_price

        if not final_price:
            continue  # 価格がない行はスキップ

        record = {
            "category": current_category,
            "treatment": treatment,
            "area": row[col_map.get("area", 2)].strip() if col_map.get("area") is not None and col_map["area"] < len(row) else "",
            "sessions": row[col_map.get("sessions", 3)].strip() if col_map.get("sessions") is not None and col_map["sessions"] < len(row) else "",
            "price": final_price,
            "first_price": clean_price(row[col_map["first_price"]]) if col_map.get("first_price") and col_map["first_price"] < len(row) else None,
            "bundle_price": clean_price(row[col_map["bundle_price"]]) if col_map.get("bundle_price") and col_map["bundle_price"] < len(row) else None,
            "campaign_price": clean_price(row[col_map["campaign_price"]]) if col_map.get("campaign_price") and col_map["campaign_price"] < len(row) else None,
            "prepaid_price": clean_price(row[col_map["prepaid_price"]]) if col_map.get("prepaid_price") and col_map["prepaid_price"] < len(row) else None,
            # コスト情報（管理者のみ）
            "cost_note": row[P_IDX].strip() if P_IDX < len(row) and p_label else None,
            "profit_note": row[Q_IDX].strip() if Q_IDX < len(row) and q_label else None,
            "source_gid": gid,
        }

        # 空のコスト値はNoneに
        if record["cost_note"] in ["", "0", "-", p_label]:
            record["cost_note"] = None
        if record["profit_note"] in ["", "0", "-", q_label]:
            record["profit_note"] = None

        records.append(record)

    return records


def parse_public_price_sheet(rows: list[list[str]]) -> dict:
    """
    公開ページ形式の価格シートを解析して (カテゴリ, 施術名, 部位, 回数) → 価格 のマップを返す
    コストなし版の最新価格を取得するために使用
    """
    price_map = {}
    current_category = ""
    current_treatment = ""

    i = 0
    while i < len(rows):
        row = rows[i]
        if not row:
            i += 1
            continue

        first_cell = row[0].strip()

        # カテゴリ行（値が1列目だけで長い）
        if first_cell and not any(c.strip() for c in row[1:4] if row[1:4]):
            # カテゴリっぽい行
            if len(first_cell) > 3 and "対象部位" not in first_cell and "通常価格" not in first_cell:
                # サブカテゴリか施術名か判断
                next_row = rows[i + 1] if i + 1 < len(rows) else []
                if next_row and "対象部位" in str(next_row):
                    # 次がヘッダー行なら、これは施術名
                    current_treatment = first_cell
                else:
                    current_category = first_cell

        # ヘッダー行
        elif "対象部位" in str(row) or "通常価格" in str(row):
            # ヘッダー行はスキップ
            pass

        # データ行
        elif first_cell and any(cell.strip() for cell in row[1:5] if row[1:5]):
            # 価格データっぽい行
            area = first_cell
            # 回数と価格を探す
            for j, cell in enumerate(row[1:], 1):
                if "回" in cell or "本" in cell:
                    sessions = cell.strip()
                    price_raw = row[j + 1].strip() if j + 1 < len(row) else ""
                    price = clean_price(price_raw)
                    if price:
                        key = f"{current_category}|{current_treatment}|{area}|{sessions}"
                        price_map[key] = price
                    break

        i += 1

    return price_map


def main():
    print("=" * 60)
    print("ボーテスキンクリニック 料金データ取得・マージ")
    print("=" * 60)
    print(f"実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    all_records = []
    total_with_cost = 0

    # コストあり版の各シートを取得・解析
    print("【コストあり版】フラットテーブルシートを取得中...")
    for gid, category, p_label, q_label in WITH_COST_SHEETS:
        print(f"  取得中: {category} (GID: {gid})")
        rows = fetch_csv(SPREADSHEET_WITH_COST, gid)
        if not rows:
            print(f"    → スキップ（取得失敗）")
            continue

        records = parse_flat_sheet(rows, gid, category, p_label, q_label)
        print(f"    → {len(records)}件 取得")

        # コスト情報があるものをカウント
        with_cost = sum(1 for r in records if r.get("cost_note") or r.get("profit_note"))
        if with_cost > 0:
            print(f"    → うちコスト情報付き: {with_cost}件")
            total_with_cost += with_cost

        all_records.extend(records)

    print()
    print(f"合計: {len(all_records)}件 (うちコスト情報付き: {total_with_cost}件)")

    # 出力データ構造
    output = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "source_no_cost": f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_NO_COST}",
            "source_with_cost": f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_WITH_COST}",
            "total_records": len(all_records),
            "records_with_cost": total_with_cost,
        },
        "treatments": all_records,
        # プリペイド割引率設定
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

    # JSONファイルに出力（web/data/ と data/ の両方に出力）
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_path = os.path.join(base_dir, "web", "data", "prices.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print()
    print(f"✅ 出力完了: {output_path}")
    print(f"   ファイルサイズ: {os.path.getsize(output_path):,} bytes")

    # サマリー表示
    print()
    print("【カテゴリ別件数】")
    from collections import Counter
    cat_counts = Counter(r["category"] for r in all_records)
    for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count}件")


if __name__ == "__main__":
    main()
