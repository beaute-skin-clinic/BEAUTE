#!/usr/bin/env python3
"""
公開用JSONを生成するスクリプト
prices.json からコスト・利益情報を除いた prices_public.json を生成する
"""
from __future__ import annotations

import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    src = os.path.join(BASE, "web", "data", "prices.json")
    dst = os.path.join(BASE, "web", "data", "prices_public.json")

    with open(src, encoding="utf-8") as f:
        data = json.load(f)

    # コスト・利益情報を除去
    public_treatments = []
    for record in data["treatments"]:
        pub = {k: v for k, v in record.items()
               if k not in ("cost_note", "profit_note", "source_gid")}
        public_treatments.append(pub)

    public_data = {
        "metadata": {
            **data["metadata"],
            "note": "公開用データ（コスト情報除去済み）"
        },
        "treatments": public_treatments,
        "prepaid_discount_rates": data.get("prepaid_discount_rates", {}),
    }

    with open(dst, "w", encoding="utf-8") as f:
        json.dump(public_data, f, ensure_ascii=False, indent=2)

    print(f"✅ 公開用JSON生成完了: {dst}")
    print(f"   レコード数: {len(public_treatments)}件")


if __name__ == "__main__":
    main()
