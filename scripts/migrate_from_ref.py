from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CSV_PATH = BASE_DIR / "scripts" / "ref_cost.csv"
PRICES_PATH = BASE_DIR / "web" / "data" / "prices.json"
PUBLIC_PATH = BASE_DIR / "web" / "data" / "prices_public.json"

# ---------- helpers ----------

def parse_price(s: str | int | None) -> int | None:
    """Parse a price string like '27,500' or '¥32,000' into int."""
    if isinstance(s, (int, float)):
        return int(s)
    if not s:
        return None
    s = s.replace(",", "").replace("¥", "").replace("￥", "").strip()
    if isinstance(s, (int, float)):
        return int(s)
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def clean_str(s: str | None) -> str:
    """Return stripped string, or empty string for None."""
    if s is None:
        return ""
    return s.strip()


# ---------- load data ----------

def load_csv() -> list[dict]:
    """Load ref_cost.csv (header row index 2, data from row 3)."""
    with open(CSV_PATH, encoding="utf-8") as f:
        raw = list(csv.reader(f))

    headers = raw[2]  # row index 2 = header
    rows = []
    for i, r in enumerate(raw[3:], start=3):
        if len(r) < 6:
            continue
        treatment = clean_str(r[1])
        seizai = clean_str(r[2])
        tani = clean_str(r[3])
        new_price_str = clean_str(r[5])
        cost_note = clean_str(r[16]) if len(r) > 16 else ""
        profit_note = clean_str(r[17]) if len(r) > 17 else ""
        rows.append({
            "csv_row": i,
            "treatment": treatment,
            "seizai": seizai,
            "tani": tani,
            "new_price": parse_price(new_price_str),
            "new_price_str": new_price_str,
            "cost_note": cost_note,
            "profit_note": profit_note,
        })
    return rows


def load_prices() -> dict:
    with open(PRICES_PATH, encoding="utf-8") as f:
        return json.load(f)


# ---------- matching logic ----------

def match_botox(csv_rows: list[dict], json_treatments: list) -> list[tuple]:
    """
    Match CSV ボトックス rows to JSON ボトックス（アラガン/ニューロノックス）
    and ボトックスリフト rows.

    CSV seizai mapping:
      - ニューロノックス -> JSON ボトックス（ニューロノックス）  1-3部位
      - ニューロノックスまとめ買い -> JSON ボトックス（ニューロノックス）  50/100単位
      - ニューロノックスボトックスリフト -> JSON ボトックスリフト（ニューロノックス）
      - ボトックスビスタ -> JSON ボトックス（アラガン）  1-3部位
      - ビスタまとめ買い -> JSON ボトックス（アラガン）  50/100単位
      - ビスタボトックスリフト -> JSON ボトックスリフト（アラガン）
    """
    # Classify CSV rows
    neuro_buirows = []  # 1-3部位
    neuro_matome = []   # まとめ買い (50/100単位)
    neuro_lift = []     # ボトックスリフト
    allergan_buirows = []
    allergan_matome = []
    allergan_lift = []

    for cr in csv_rows:
        sz = cr["seizai"]
        if "ニューロノックスボトックスリフト" in sz:
            neuro_lift.append(cr)
        elif "ニューロノックスまとめ買い" in sz:
            neuro_matome.append(cr)
        elif "ニューロノックス" in sz:
            neuro_buirows.append(cr)
        elif "ビスタボトックスリフト" in sz:
            allergan_lift.append(cr)
        elif "ビスタまとめ買い" in sz:
            allergan_matome.append(cr)
        elif "ボトックスビスタ" in sz:
            allergan_buirows.append(cr)
        else:
            print(f"  [WARN] ボトックス CSV row {cr['csv_row']} seizai=[{sz}] not classified, skipping")

    # Classify JSON rows
    json_neuro = [j for j in json_treatments if j["treatment"] == "ボトックス（ニューロノックス）"]
    json_allergan = [j for j in json_treatments if j["treatment"] == "ボトックス（アラガン）"]
    json_neuro_lift = [j for j in json_treatments if j["treatment"] == "ボトックスリフト（ニューロノックス）"]
    json_allergan_lift = [j for j in json_treatments if j["treatment"] == "ボトックスリフト（アラガン）"]

    # Split JSON neuro/allergan into 部位 and まとめ買い
    json_neuro_bui = [j for j in json_neuro if j.get("sessions") not in ("50単位", "100単位")]
    json_neuro_mat = [j for j in json_neuro if j.get("sessions") in ("50単位", "100単位")]
    json_allergan_bui = [j for j in json_allergan if j.get("sessions") not in ("50単位", "100単位")]
    json_allergan_mat = [j for j in json_allergan if j.get("sessions") in ("50単位", "100単位")]

    pairs = []

    def pair_by_order(csv_list, json_list, label):
        if len(csv_list) != len(json_list):
            print(f"  [WARN] {label}: CSV has {len(csv_list)} rows, JSON has {len(json_list)} rows - matching by order anyway")
        for k in range(min(len(csv_list), len(json_list))):
            pairs.append((csv_list[k], json_list[k]))

    pair_by_order(neuro_buirows, json_neuro_bui, "ニューロノックス部位")
    pair_by_order(neuro_matome, json_neuro_mat, "ニューロノックスまとめ買い")
    pair_by_order(neuro_lift, json_neuro_lift, "ニューロノックスリフト")
    pair_by_order(allergan_buirows, json_allergan_bui, "アラガン部位")
    pair_by_order(allergan_matome, json_allergan_mat, "アラガンまとめ買い")
    pair_by_order(allergan_lift, json_allergan_lift, "アラガンリフト")

    return pairs


def match_hyaluronidase(csv_rows: list[dict], json_rows: list) -> list[tuple]:
    """Match ヒアルローニターゼ by area keyword."""
    pairs = []
    used_json = set()

    for cr in csv_rows:
        seizai = cr["seizai"]
        if not seizai:
            continue
        for ji, jr in enumerate(json_rows):
            if ji in used_json:
                continue
            area = clean_str(jr.get("area", ""))
            if seizai in area or area in seizai:
                pairs.append((cr, jr))
                used_json.add(ji)
                break
    return pairs


def match_hyaluronic(csv_rows: list[dict], json_rows: list) -> list[tuple]:
    """Match ヒアルロン酸 by 製剤 keyword in area."""
    pairs = []
    used_json = set()

    for cr in csv_rows:
        seizai = cr["seizai"]
        if not seizai:
            continue
        # Extract the key part of seizai for matching
        # CSV: ボリフト【アラガン社】, JSON area: ボリフト(アラガン）
        key = seizai.split("【")[0].split("（")[0].split("(")[0]
        for ji, jr in enumerate(json_rows):
            if ji in used_json:
                continue
            area = clean_str(jr.get("area", ""))
            if key in area:
                pairs.append((cr, jr))
                used_json.add(ji)
                break
        else:
            print(f"  [WARN] ヒアルロン酸 CSV row {cr['csv_row']} seizai=[{seizai}] not matched")
    return pairs


def match_by_price_and_profit(csv_rows: list[dict], json_rows: list, treatment_name: str) -> list[tuple]:
    """
    Generic matching: match by price, using existing profit_note (which contains
    cost from a prior import) to disambiguate when prices are duplicated.
    """
    pairs = []
    used_json = set()

    # Group JSON by price for quick lookup
    json_by_price: dict[int, list[tuple[int, dict]]] = defaultdict(list)
    for ji, jr in enumerate(json_rows):
        p = parse_price(jr.get("price"))
        if p is not None:
            json_by_price[p].append((ji, jr))

    for cr in csv_rows:
        csv_price = cr["new_price"]
        if csv_price is None:
            continue

        candidates = [(ji, jr) for ji, jr in json_by_price.get(csv_price, []) if ji not in used_json]

        if len(candidates) == 0:
            print(f"  [WARN] {treatment_name} CSV row {cr['csv_row']} price={csv_price} no JSON match")
            continue

        if len(candidates) == 1:
            ji, jr = candidates[0]
            pairs.append((cr, jr))
            used_json.add(ji)
            continue

        # Multiple candidates with same price - disambiguate using existing profit_note vs csv cost_note
        matched = False
        csv_cost = cr["cost_note"]
        if csv_cost:
            for ji, jr in candidates:
                existing_profit = clean_str(jr.get("profit_note"))
                if existing_profit == csv_cost:
                    pairs.append((cr, jr))
                    used_json.add(ji)
                    matched = True
                    break

        if not matched:
            # Try numeric comparison
            csv_cost_num = parse_price(csv_cost) if csv_cost else None
            if csv_cost_num is not None:
                for ji, jr in candidates:
                    existing_profit_num = parse_price(clean_str(jr.get("profit_note")))
                    if existing_profit_num == csv_cost_num:
                        pairs.append((cr, jr))
                        used_json.add(ji)
                        matched = True
                        break

        if not matched:
            # Last resort: take first available
            ji, jr = candidates[0]
            pairs.append((cr, jr))
            used_json.add(ji)
            print(f"  [WARN] {treatment_name} CSV row {cr['csv_row']} price={csv_price} matched by first-available (ambiguous)")

    return pairs


# ---------- main ----------

def main():
    csv_rows = load_csv()
    prices_data = load_prices()
    treatments = prices_data["treatments"]

    print(f"Loaded {len(csv_rows)} CSV data rows")
    print(f"Loaded {len(treatments)} JSON treatment rows")
    print()

    # Filter out empty CSV rows (no treatment name AND no seizai AND no price)
    csv_rows = [r for r in csv_rows if r["treatment"] or r["seizai"] or r["new_price"] is not None]
    # Skip rows where treatment is empty per instructions, except handle special continuation rows
    # Row 23 (empty treatment, ジュベルック 2㏄) belongs to Dr.手打ち注射 - but not in JSON, so skip
    # Row 28 (CGスタイラー) - not in JSON, so skip
    # Row 32 (completely empty) - skip
    # Row 45 (リタッチ) - not in JSON, skip

    # Group CSV rows by treatment name
    csv_groups: dict[str, list[dict]] = defaultdict(list)
    for r in csv_rows:
        if r["treatment"]:
            csv_groups[r["treatment"]].append(r)

    # Group JSON by treatment name
    json_groups: dict[str, list] = defaultdict(list)
    for t in treatments:
        json_groups[t["treatment"]].append(t)

    # Build match pairs
    all_pairs: list[tuple[dict, dict]] = []

    # 1. ボトックス special case
    if "ボトックス" in csv_groups:
        botox_csv = csv_groups.pop("ボトックス")
        botox_json = []
        for key in ["ボトックス（アラガン）", "ボトックス（ニューロノックス）",
                     "ボトックスリフト（アラガン）", "ボトックスリフト（ニューロノックス）"]:
            botox_json.extend(json_groups.get(key, []))
        print("=== ボトックス matching ===")
        pairs = match_botox(botox_csv, botox_json)
        all_pairs.extend(pairs)
        print(f"  Matched {len(pairs)} pairs")
        print()

    # 2. ヒアルローニターゼ special case
    if "ヒアルローニターゼ" in csv_groups:
        hyrd_csv = csv_groups.pop("ヒアルローニターゼ")
        hyrd_json = json_groups.get("ヒアルローニターゼ", [])
        print("=== ヒアルローニターゼ matching ===")
        pairs = match_hyaluronidase(hyrd_csv, hyrd_json)
        all_pairs.extend(pairs)
        print(f"  Matched {len(pairs)} pairs")
        print()

    # 3. ヒアルロン酸 special case
    if "ヒアルロン酸" in csv_groups:
        ha_csv = csv_groups.pop("ヒアルロン酸")
        ha_json = json_groups.get("ヒアルロン酸", [])
        print("=== ヒアルロン酸 matching ===")
        pairs = match_hyaluronic(ha_csv, ha_json)
        all_pairs.extend(pairs)
        print(f"  Matched {len(pairs)} pairs")
        print()

    # 4. Generic matching for remaining treatments
    for csv_treatment, csv_list in csv_groups.items():
        if not csv_treatment:
            continue
        # Find matching JSON treatment name
        json_name = csv_treatment
        json_list = json_groups.get(json_name, [])
        if not json_list:
            # Try partial match
            for jn in json_groups:
                if csv_treatment in jn or jn in csv_treatment:
                    json_list = json_groups[jn]
                    json_name = jn
                    break
        if not json_list:
            print(f"=== {csv_treatment}: NO JSON MATCH FOUND ===")
            continue

        print(f"=== {csv_treatment} -> {json_name} matching ===")
        pairs = match_by_price_and_profit(csv_list, json_list, csv_treatment)
        all_pairs.extend(pairs)
        print(f"  Matched {len(pairs)} pairs")
        print()

    # ---------- apply updates ----------
    print("=" * 60)
    print("APPLYING UPDATES")
    print("=" * 60)

    area_updated = 0
    sessions_updated = 0
    cost_updated = 0
    profit_updated = 0
    price_mismatches = []

    for csv_row, json_row in all_pairs:
        treatment_label = f"{json_row['treatment']} (csv row {csv_row['csv_row']})"

        # a) area: if JSON area is empty and CSV has seizai
        json_area = clean_str(json_row.get("area"))
        csv_seizai = csv_row["seizai"]
        if not json_area and csv_seizai:
            json_row["area"] = csv_seizai
            area_updated += 1
            print(f"  [AREA] {treatment_label}: set area = '{csv_seizai}'")

        # b) sessions: if JSON sessions is empty/null and CSV has tani
        json_sessions = json_row.get("sessions")
        csv_tani = csv_row["tani"]
        if (json_sessions is None or clean_str(json_sessions) == "") and csv_tani:
            json_row["sessions"] = csv_tani
            sessions_updated += 1
            print(f"  [SESSIONS] {treatment_label}: set sessions = '{csv_tani}'")

        # c) cost_note from CSV col 16 (備考コスト)
        csv_cost = csv_row["cost_note"]
        if csv_cost:
            old_cost = json_row.get("cost_note")
            json_row["cost_note"] = csv_cost
            cost_updated += 1
            if old_cost and clean_str(old_cost) != csv_cost:
                print(f"  [COST] {treatment_label}: updated cost_note '{old_cost}' -> '{csv_cost}'")
            else:
                print(f"  [COST] {treatment_label}: set cost_note = '{csv_cost}'")

        # d) profit_note from CSV col 17 (定価利益)
        csv_profit = csv_row["profit_note"]
        if csv_profit:
            old_profit = json_row.get("profit_note")
            json_row["profit_note"] = csv_profit
            profit_updated += 1
            if old_profit and clean_str(old_profit) != csv_profit:
                print(f"  [PROFIT] {treatment_label}: updated profit_note '{old_profit}' -> '{csv_profit}'")
            else:
                print(f"  [PROFIT] {treatment_label}: set profit_note = '{csv_profit}'")

        # e) Price mismatch check (DO NOT change price)
        csv_price = csv_row["new_price"]
        json_price = parse_price(json_row.get("price"))
        if csv_price is not None and json_price is not None and csv_price != json_price:
            price_mismatches.append({
                "treatment": json_row["treatment"],
                "csv_row": csv_row["csv_row"],
                "csv_price": csv_price,
                "json_price": json_price,
                "seizai": csv_row["seizai"],
                "tani": csv_row["tani"],
            })

    # ---------- summary ----------
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Total matched pairs: {len(all_pairs)}")
    print(f"  Area updated:     {area_updated}")
    print(f"  Sessions updated: {sessions_updated}")
    print(f"  Cost notes set:   {cost_updated}")
    print(f"  Profit notes set: {profit_updated}")
    print()

    if price_mismatches:
        print(f"  PRICE MISMATCHES ({len(price_mismatches)}):")
        for pm in price_mismatches:
            print(f"    {pm['treatment']} csv_row={pm['csv_row']} "
                  f"seizai=[{pm['seizai']}] tani=[{pm['tani']}] "
                  f"CSV={pm['csv_price']:,} vs JSON={pm['json_price']:,}")
    else:
        print("  No price mismatches found.")

    # ---------- save ----------
    print()
    print("Saving updated prices.json ...")
    with open(PRICES_PATH, "w", encoding="utf-8") as f:
        json.dump(prices_data, f, ensure_ascii=False, indent=2)
    print(f"  -> {PRICES_PATH}")

    # Regenerate prices_public.json (same data minus cost_note and profit_note)
    print("Regenerating prices_public.json ...")
    public_data = {
        "metadata": prices_data["metadata"],
        "treatments": [],
        "prepaid_discount_rates": prices_data["prepaid_discount_rates"],
    }
    private_fields = {"cost_note", "profit_note"}
    for t in prices_data["treatments"]:
        public_t = {k: v for k, v in t.items() if k not in private_fields}
        public_data["treatments"].append(public_t)

    with open(PUBLIC_PATH, "w", encoding="utf-8") as f:
        json.dump(public_data, f, ensure_ascii=False, indent=2)
    print(f"  -> {PUBLIC_PATH}")

    print()
    print("Done.")


if __name__ == "__main__":
    main()
