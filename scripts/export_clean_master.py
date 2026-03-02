#!/usr/bin/env python3
"""
整理済みマスターCSVを生成するスクリプト
prices.json → クリーンなフラットテーブル形式のCSV

オーナーがGoogleスプレッドシートで直感的に編集できる形式で出力する。
"""
from __future__ import annotations
import csv
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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


def sort_key(record):
    cat = record.get("category", "")
    try:
        idx = CATEGORY_ORDER.index(cat)
    except ValueError:
        idx = 999
    return (idx, cat, record.get("treatment", ""), record.get("area", ""), record.get("sessions", ""))


def fmt_price(val):
    """数値文字列をそのまま返す（¥なし・カンマなし）"""
    if not val:
        return ""
    v = str(val).replace("¥", "").replace(",", "").replace(" ", "").strip()
    try:
        return str(int(v))
    except ValueError:
        return v  # "1s4.5円" のような注記はそのまま


def main():
    src = os.path.join(BASE, "web", "data", "prices.json")
    with open(src, encoding="utf-8") as f:
        data = json.load(f)

    records = sorted(data["treatments"], key=sort_key)

    # ===== CSV 1: 公開用（コストなし）=====
    public_csv = os.path.join(BASE, "web", "data", "master_public.csv")
    with open(public_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "施術カテゴリ", "施術名", "対象部位", "回数",
            "通常価格（税込）", "初回価格", "回数券価格", "キャンペーン価格", "プリペイド割価格",
        ])
        for r in records:
            writer.writerow([
                r.get("category", ""),
                r.get("treatment", ""),
                r.get("area", ""),
                r.get("sessions", ""),
                fmt_price(r.get("price")),
                fmt_price(r.get("first_price")),
                fmt_price(r.get("bundle_price")),
                fmt_price(r.get("campaign_price")),
                fmt_price(r.get("prepaid_price")),
            ])
    print(f"✅ 公開用マスターCSV: {public_csv} ({len(records)}行)")

    # ===== CSV 2: 管理者用（コストあり）=====
    admin_csv = os.path.join(BASE, "web", "data", "master_admin.csv")
    with open(admin_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "施術カテゴリ", "施術名", "対象部位", "回数",
            "通常価格（税込）", "初回価格", "回数券価格", "キャンペーン価格", "プリペイド割価格",
            "【管理者】コスト", "【管理者】利益メモ",
        ])
        for r in records:
            writer.writerow([
                r.get("category", ""),
                r.get("treatment", ""),
                r.get("area", ""),
                r.get("sessions", ""),
                fmt_price(r.get("price")),
                fmt_price(r.get("first_price")),
                fmt_price(r.get("bundle_price")),
                fmt_price(r.get("campaign_price")),
                fmt_price(r.get("prepaid_price")),
                r.get("cost_note", "") or "",
                r.get("profit_note", "") or "",
            ])
    print(f"✅ 管理者用マスターCSV: {admin_csv} ({len(records)}行)")

    # ===== サマリー =====
    print()
    print("【構造】")
    print("  1行 = 1施術メニュー（フラットテーブル・結合セルなし）")
    print("  オーナーはセルを書き換えるだけで価格変更OK")
    print()
    print("【次のステップ】")
    print("  1. master_admin.csv をGoogleスプレッドシートにインポート")
    print("  2. オーナーに確認してもらう")
    print("  3. 確認済みのスプレッドシートを新マスターとして運用開始")


if __name__ == "__main__":
    main()
