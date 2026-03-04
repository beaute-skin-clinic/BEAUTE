#!/usr/bin/env python3
"""
ボーテスキンクリニック 料金データ取得スクリプト

⚠️  このスクリプトは現在 **参照用バックアップ** です。
    マスターデータは web/data/prices.json (git管理) に移行済み。
    管理画面 (web/admin/) から直接編集 → GitHubコミットが正規フローです。

    スプレッドシートからの再取得は、データ復旧など緊急時のみ
    --force フラグ付きで実行してください。

使用方法:
  python3 scripts/fetch_from_master.py --force   # 緊急時のみ
"""
from __future__ import annotations

import csv
import json
import math
import re
import urllib.request
import urllib.error
import io
import os
import sys
from datetime import datetime

# ============================================================
# 安全ガード: --force なしでの実行を禁止
# マスターデータは prices.json (git) に移行済みのため、
# スプレッドシートからの再取得は緊急時のみ
# ============================================================
if "--force" not in sys.argv:
    print("=" * 60)
    print("⚠️  このスクリプトは現在無効化されています。")
    print()
    print("マスターデータは web/data/prices.json (git管理) です。")
    print("料金の更新は管理画面 (web/admin/) から行ってください。")
    print()
    print("緊急時（データ復旧等）のみ:")
    print("  python3 scripts/fetch_from_master.py --force")
    print("=" * 60)
    sys.exit(1)

# ============================================================
# マスタースプレッドシート設定（緊急時の参照用）
# ============================================================
MASTER_SPREADSHEET_ID = "1aoRw1sc5Jw1S2RwP4EoTztzQHKGf2SWYoRAAbSScmZU"

# 旧スプレッドシート（参照用・読み取り専用のバックアップ）
OLD_NO_COST = "1Nw-myLLojzdm0FZJMkwb3n2QHcXnvhFw"
OLD_WITH_COST = "1jv43DpLm-d0awOV-rxD4ACCaszg2IPFK"

# カテゴリの表示順序
CATEGORY_ORDER = [
    "肌質改善／肌育",
    "ヒアルロン酸",
    "ボトックス",
    "毛穴・ニキビ・肌の凹凸ケア",
    "しわ・たるみ・小顔",
    "美肌・肌質改善（シミ・くすみ・透明感）",
    "ピーリング",
    "スレッド（糸リフト）",
    "目元のクマたるみ治療（オペ）",
    "目元の形成（オペ）",
    "医療痩身",
    "医療脱毛",
    "点滴・注射",
    "麻酔",
    "診察料",
    "エステフェイシャル",
    "リラクゼーション",
    "エステボディ",
    "エステブライダル",
    "エステマタニティ",
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
    "イオン導入", "ピーリング", "ダーマペン", "ヴェルヴェットスキン", "ハイドラフェイシャル",
]

# 30万/50万: 施術別の割引率オーバーライド（通常10%→5%）
PP_REDUCED_RATE_TREATMENTS = [
    {"keywords": ["ヒアルロン酸"], "provider": "Dr.", "rate": 5},
    {"keywords": ["サーマニードルアイ"], "provider": "Dr.", "rate": 5},
]

# 30万/50万: 対象外の施術キーワード
PP_EXCLUDED_30_50 = ["ボトックス", "ヒアルローニターゼ", "ヒアルロニダーゼ"]

# ============================================================
# エステパス割引率テーブル
# ============================================================
ESTEPASS_RATES = {"5万": 5, "10万": 10, "20万": 20}
ESTEPASS_EXCLUDED_CATEGORIES = ["エステマタニティ", "エステブライダル"]
ESTEPASS_EXCLUDED_KEYWORDS = [
    "ベーシックフェイシャル", "ボディ&フェイシャル", "ボディ＆フェイシャル",
    "ホワイトニング", "アートメイク",
]

# ============================================================
# カテゴリ分割ルール
# ============================================================
# 「注入系」→ 施術名ベースで個別カテゴリに分割
CATEGORY_SPLIT_RULES = {
    "注入系": {
        "ボトックス":           "ボトックス",
        "ヒアルロン酸":         "ヒアルロン酸",
        "ヒアルローニターゼ":    "ヒアルロン酸",
        "水光注射（ハイコックス）": "水光注射",
        "Dr.手打ち注射":        "Dr.手打ち注射",
        "脂肪溶解注射":         "肌質改善注射",
    },
}

# 回数券: 固定列としてベース行に統合する有効な回数券タイプ
VALID_TICKET_TYPES = {"3回券", "5回券", "8回券"}
TICKET_FIELD_MAP = {"3回券": "ticket_3", "5回券": "ticket_5", "8回券": "ticket_8"}


def merge_ticket_rows(records):
    # type: (list) -> list
    """回数券行をベース行に統合し、回数券行を削除する"""
    from collections import defaultdict

    # (treatment, area) でグルーピング
    grouped = defaultdict(lambda: {"base": [], "tickets": []})
    for i, r in enumerate(records):
        key = (r["treatment"], r["area"])
        sessions = r.get("sessions", "")
        if sessions in VALID_TICKET_TYPES:
            grouped[key]["tickets"].append((i, sessions, r))
        else:
            grouped[key]["base"].append((i, r))

    # 削除対象のインデックス
    remove_indices = set()

    merged_count = 0
    for key, group in grouped.items():
        base_rows = group["base"]
        ticket_rows = group["tickets"]

        if not ticket_rows:
            continue

        if not base_rows:
            # ベース行なし → 回数券行を削除
            for idx, _, _ in ticket_rows:
                remove_indices.add(idx)
            continue

        # 最初のベース行にマージ
        _, base_record = base_rows[0]
        for idx, ticket_type, ticket_record in ticket_rows:
            field = TICKET_FIELD_MAP.get(ticket_type)
            if field:
                base_record[field] = ticket_record["price"]
                merged_count += 1
            remove_indices.add(idx)

    # 2回券/4回券/6回券 等の無効な回数券行も削除
    for i, r in enumerate(records):
        sessions = r.get("sessions", "")
        if sessions and "回券" in sessions and sessions not in VALID_TICKET_TYPES:
            remove_indices.add(i)

    # 削除対象を除外し、ticket フィールドのデフォルト値を設定
    new_records = []
    for i, r in enumerate(records):
        if i not in remove_indices:
            r.setdefault("ticket_3", None)
            r.setdefault("ticket_5", None)
            r.setdefault("ticket_8", None)
            new_records.append(r)

    print(f"  → 回数券マージ: {merged_count}件統合, {len(remove_indices)}行削除")
    return new_records


# 価格倍率マージの対象カテゴリ（回数券が明確なカテゴリのみ）
RATIO_MERGE_CATEGORIES = {
    "医療脱毛",
    "ピーリング",
    "しわ・たるみ",
}
# 倍率 → チケットフィールドのマッピング
RATIO_TICKET_MAP = {3: "ticket_3", 5: "ticket_5", 8: "ticket_8"}


def merge_ticket_by_ratio(records):
    # type: (list) -> list
    """同一施術+部位で価格が3/5/8倍の行を回数券列に自動統合する"""
    from collections import defaultdict

    # 対象カテゴリの行だけをグルーピング
    grouped = defaultdict(list)
    for i, r in enumerate(records):
        if r["category"] in RATIO_MERGE_CATEGORIES:
            key = (r["category"], r.get("treatment", ""), r.get("area", ""))
            grouped[key].append((i, r))

    remove_indices = set()
    merged_count = 0

    for key, items in grouped.items():
        if len(items) < 2:
            continue
        # 最小価格をベース（1回価格）とみなす
        items_sorted = sorted(items, key=lambda x: int(x[1]["price"]))
        base_idx, base_rec = items_sorted[0]
        base_price = int(base_rec["price"])
        if base_price <= 0:
            continue

        for idx, rec in items_sorted[1:]:
            p = int(rec["price"])
            ratio = p / base_price
            # 整数倍率（3/5/8）に合致するかチェック
            for mult, field in RATIO_TICKET_MAP.items():
                if abs(ratio - mult) < 0.01:
                    # 既にticket列に値がなければマージ
                    if not base_rec.get(field):
                        base_rec[field] = rec["price"]
                        remove_indices.add(idx)
                        merged_count += 1
                    break

    if not remove_indices:
        return records

    new_records = [r for i, r in enumerate(records) if i not in remove_indices]
    print(f"  → 倍率マージ: {merged_count}件統合, {len(remove_indices)}行削除"
          f" (対象: {', '.join(RATIO_MERGE_CATEGORIES)})")
    return new_records


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
    if v in ["0", "-", "—", "―", "", "なし", "設定なし"]:
        return ""
    return v


# 有効な sessions パターン: 数字 + 単位（1回, 1本, 1部位, 1cc, 30錠, 90包 等）
VALID_SESSION_PATTERN = re.compile(
    r'^\d+(回|本|部位|cc|CC|ml|ML|g|mg|箇所|枚|個|単位|錠|カプセル|包)$'
)


def clean_sessions(value):
    # type: (str) -> str | None
    """sessionsフィールドのクリーニング: 有効な単位のみ残し、不正値はNoneに"""
    if not value or not value.strip():
        return None
    v = value.strip()
    # % を含む値は旧回数券行の割引率の残骸 → 無効
    if '%' in v or '％' in v:
        return None
    # 純粋な数値・金額（カンマ付き含む）は流出データ → 無効
    digits_only = v.replace(',', '').replace('¥', '').replace(' ', '').replace('　', '')
    try:
        float(digits_only)
        return None
    except ValueError:
        pass
    # 有効な単位パターン（1回, 1本, 1部位, 1cc 等）のみ残す
    if VALID_SESSION_PATTERN.match(v):
        return v
    # それ以外（不明な文字列）も無効
    return None


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

    # 30万/50万: 施術別の対象外チェック
    t_name = treatment or ""
    is_excluded_30_50 = any(kw in t_name for kw in PP_EXCLUDED_30_50)

    # 30万/50万: 施術別の割引率オーバーライド判定
    def get_effective_rate(tier):
        base_rate = rates.get(tier, 0)
        if base_rate == 0:
            return 0
        for rule in PP_REDUCED_RATE_TREATMENTS:
            if provider_type == rule["provider"] and any(kw in t_name for kw in rule["keywords"]):
                return rule["rate"]
        return base_rate

    # 30万ティア
    if not is_excluded_30_50:
        rate_30 = get_effective_rate("30万")
        if rate_30 > 0:
            result["prepaid_30"] = str(math.floor(price * (100 - rate_30) / 100))

    # 50万ティア
    if not is_excluded_30_50:
        rate_50 = get_effective_rate("50万")
        if rate_50 > 0:
            result["prepaid_50"] = str(math.floor(price * (100 - rate_50) / 100))

    return result


def calc_estepass_prices(price_str, provider_type, treatment, categories):
    # type: (str, str, str, list) -> dict
    """エステパス3ティア価格を自動計算（エステ区分のみ）"""
    result = {"estepass_5": None, "estepass_10": None, "estepass_20": None}

    if not price_str or provider_type != "エステ":
        return result

    # カテゴリ除外チェック（マタニティ・ブライダル全て対象外）
    for cat in categories:
        if cat in ESTEPASS_EXCLUDED_CATEGORIES:
            return result

    # 施術名キーワード除外チェック
    t_name = treatment or ""
    for kw in ESTEPASS_EXCLUDED_KEYWORDS:
        if kw in t_name:
            return result

    try:
        price = int(price_str)
    except ValueError:
        return result

    for tier, rate in ESTEPASS_RATES.items():
        field = "estepass_" + str(rate)
        result[field] = str(math.floor(price * (100 - rate) / 100))

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

        # カテゴリ分割ルール適用（施術名ベースでサブカテゴリ化）
        if category in CATEGORY_SPLIT_RULES:
            split_map = CATEGORY_SPLIT_RULES[category]
            if treatment in split_map:
                category = split_map[treatment]
                categories = [category]

        # 回数券行はPP計算をスキップ（回数券とPPは並列の割引体系で併用不可）
        sessions = get(row, "sessions")
        is_ticket_row = sessions and "回券" in sessions
        if is_ticket_row:
            pp = {"prepaid_10": None, "prepaid_30": None, "prepaid_50": None}
            ep = {"estepass_5": None, "estepass_10": None, "estepass_20": None}
        else:
            # プリペイド3ティア自動計算
            pp = calc_prepaid_prices(price, provider_type, treatment, categories)
            # エステパス3ティア自動計算
            ep = calc_estepass_prices(price, provider_type, treatment, categories)

        # スプレッドシートの手動プリペイド価格があればオーバーライド用に保持
        manual_pp = clean_price(get(row, "prepaid_price")) or None

        record = {
            "category": category,
            "categories": categories,
            "provider_type": provider_type or None,
            "treatment": treatment,
            "area": get(row, "area"),
            "sessions": sessions,
            "old_price": clean_price(get(row, "old_price")) or None,
            "price": price,
            "first_price": clean_price(get(row, "first_price")) or None,
            "repeat_price": clean_price(get(row, "repeat_price")) or None,
            "campaign_price": clean_price(get(row, "campaign_price")) or None,
            "monitor_full_price": clean_price(get(row, "monitor_full_price")) or None,
            "monitor_eye_price": clean_price(get(row, "monitor_eye_price")) or None,
            "prepaid_10": pp["prepaid_10"],
            "prepaid_30": pp["prepaid_30"],
            "prepaid_50": pp["prepaid_50"],
            "prepaid_manual": manual_pp,
            "estepass_5": ep["estepass_5"],
            "estepass_10": ep["estepass_10"],
            "estepass_20": ep["estepass_20"],
            "cost_note": get(row, "cost_note") or None,
            "profit_note": get(row, "profit_note") or None,
        }
        records.append(record)

    print(f"  → {len(records)}件の施術データ（マージ前）")

    # 回数券行をベース行に統合（sessions列ベース）
    records = merge_ticket_rows(records)
    print(f"  → {len(records)}件の施術データ（マージ後）")

    # 価格倍率ベースの回数券マージ（対象カテゴリのみ）
    records = merge_ticket_by_ratio(records)

    # sessionsフィールドのクリーニング（%値・金額流出データを除去）
    cleaned_count = 0
    for r in records:
        raw = r.get("sessions", "")
        cleaned = clean_sessions(raw)
        if raw and raw.strip() and cleaned is None:
            cleaned_count += 1
        r["sessions"] = cleaned
    if cleaned_count:
        print(f"  → sessions クリーンアップ: {cleaned_count}件の不正値を除去")

    # areaに入っている単位らしき値をsessionsに移動（sessionsが空の場合のみ）
    # パターン1: 数字+単位（30錠, 4本 等）
    # パターン2: 単価基準（1㎜ごと, 1mmにつき 等）
    AREA_UNIT_PATTERN = re.compile(
        r'^\d+(㎜|mm|cm)?(ごと|毎|あたり|につき)$'
    )
    moved_count = 0
    for r in records:
        area = (r.get("area") or "").strip()
        if area and not r.get("sessions"):
            if VALID_SESSION_PATTERN.match(area) or AREA_UNIT_PATTERN.match(area):
                r["sessions"] = area
                r["area"] = ""
                moved_count += 1
    if moved_count:
        print(f"  → 部位→単位 移動: {moved_count}件")

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
