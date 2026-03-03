#!/usr/bin/env python3
"""
Integrate web pricing data from beau-te.jp into master prices.json and prices_public.json.

Steps:
1. Fetch & parse HTML from https://beau-te.jp/priceinfo/clinicmedicalsalonprice/
2. Extract all treatment + area + price data
3. Match to existing master data by treatment name + area
4. Update old_price, first_price, repeat_price, campaign_price, monitor prices
5. Only update 'price' (通常価格) if web price differs from master price
6. Write updated prices.json and prices_public.json
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from html.parser import HTMLParser

# ── Config ──
WEB_URL = "https://beau-te.jp/priceinfo/clinicmedicalsalonprice/"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRICES_JSON = os.path.join(BASE_DIR, "web", "data", "prices.json")
PRICES_PUBLIC_JSON = os.path.join(BASE_DIR, "web", "data", "prices_public.json")

# Fields that should NOT appear in public JSON
PRIVATE_FIELDS = {"cost_note", "profit_note", "prepaid_10", "prepaid_30",
                  "prepaid_50", "prepaid_manual"}

# ── Treatment name aliases: web name → master name(s) ──
# When the web uses a different name than the master spreadsheet
TREATMENT_ALIASES = {
    # シミ治療
    "ピコスポット": ["ピコレーザー・ピコスポット"],
    "ピコW（ピコダブル）": ["ピコW"],
    "ピコW(ピコダブル)": ["ピコW"],
    "フォトフェイシャル": ["フォトフェイシャル", "フォトフェイシャル（フォトダブル）",
                     "フォトフェイシャル(フォトダブル)"],
    # しわ・たるみ・小顔
    "フェイシャルハイフ（ウルトラフォーマーMPT）": [
        "フェイシャルハイフ（ウルトラフォーマーMPT）", "ウルトラフォーマーMPT"],
    "ボルフォーマー（ボルニューマ＋ウルトラフォーマーMPT）": [
        "ボルフォーマーライト（ボルニューマ＋ウルトラフォーマーMPT）",
        "ボルフォーマースタンダード（ボルニューマ＋ウルトラフォーマーMPT）",
        "ボルフォーマープレミアム（ボルニューマ＋ウルトラフォーマーMPT）"],
    "脂肪溶解注射（顔）": ["脂肪溶解注射（FatX core）"],
    "顔の脂肪吸引": ["顔の脂肪吸引", "脂肪吸引（頬）"],
    # 美容整形・外科
    "二重術（自然癒着法）": ["二重 自然癒着法"],
    "二重術（埋没法）": ["二重埋没法"],
    "二重術（埋没法）※1年間保証付き": ["二重埋没法（1年間保証付）"],
    "目元のクマ・たるみ治療": ["目の下のくま・たるみ取り"],
    "タレ目形成": ["タレ目形成"],
    # スレッド
    "糸リフト（ショートスレッド）": ["ショートスレッド", "アイスレッド"],
    "ボーテ式糸リフト（PDO）ロングスレッド": ["ロングスレッドPDO"],
    "ボーテ式糸リフト（PCL）ロングスレッド": ["ロングスレッドPCL"],
    "バーティカルリフト（PCL）": ["バーティカルリフト(PCL)"],
    # ピーリング
    "ヴェルベットスキン": ["ヴェルヴェットスキン", "ヴェルヴェットスキン（美容液オプション）"],
    "マッサージピール（ハリ・弾力）": ["マッサージピール"],
    "リバースピール（シミ・肝斑）": ["リバースピール"],
    "ミラノリピール（肌質改善・ニキビ跡・色素沈着）": ["ミラノリピール"],
    # 医療ボディ
    "脂肪冷却（クラツーαアルファ）": ["脂肪冷却", "脂肪冷却（クラツーα）"],
    "脂肪溶解注射（BodyContour）": ["脂肪溶解注射（BodyContour）"],
    "脂肪溶解注射（FatXCore）": ["脂肪溶解注射（FatX core）"],
    "ハイフ（ウルトラフォーマーMPT）": ["ウルトラフォーマーMPT"],
    # 医療脱毛
    "脱毛（女性）": ["レディース脱毛"],
    "脱毛（男性）": ["メンズ脱毛"],
    "脱毛（キッズ）": ["キッズ脱毛"],
    # エステ
    "氣内臓（チネイザン）": ["チネイザン20分"],
    "キャビゼロ痩身": ["キャビゼロ瘦身60分", "キャビゼロ瘦身＋発汗付き90分",
                   "キャビゼロ瘦身＋発汗付き120分"],
    "HAAB LA SERRA（ハーブ ラ セール）": [
        "ラセールボディアロマリンパマッサージ60分",
        "ラセールボディアロマリンパマッサージ90分"],
    # フォトナ sub-treatments (web groups under フォトナレーザー)
    "フォトナレーザー": ["フォトナ2d", "フォトナ4d", "フォトナ6d",
                    "フォトナアイ2d", "フォトナアイ粘膜無し表面のみ"],
}

# Areas that are really "header" areas (not real body parts)
# The actual area is in the 'detail' field
HEADER_AREAS = {"1回の範囲", "通常価格"}


# ── HTML Parser ──
class PricePageParser(HTMLParser):
    """Parse the pricing page HTML and extract treatment data."""

    def __init__(self):
        super().__init__()
        self.results = []
        self.current_section = ""
        self.current_treatment = ""

        # State tracking
        self._in_h2 = False
        self._in_h3 = False
        self._in_h4 = False
        self._in_th = False
        self._in_count = False
        self._in_price = False
        self._in_price_label = False
        self._in_price_detail_span = False

        self._current_area = ""
        self._current_count = ""
        self._current_price_label = ""
        self._current_price_value = ""

        # For complex rows (price-detail--list)
        self._in_detail_list = False
        self._in_detail_row = False
        self._in_detail_main = False
        self._in_detail_price_div = False
        self._detail_prices = []
        self._detail_count = ""
        self._detail_subitem = ""

        self._text_buffer = ""
        self._tag_stack = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        cls = attrs_dict.get("class", "")

        self._tag_stack.append(tag)

        if tag == "h2":
            self._in_h2 = True
            self._text_buffer = ""
        elif tag == "h3":
            self._in_h3 = True
            self._text_buffer = ""
        elif tag == "h4" and "price-box__head" in cls:
            self._in_h4 = True
            self._text_buffer = ""
        elif tag == "th" and "head" in cls:
            self._in_th = True
            self._text_buffer = ""
        elif tag == "td":
            if "price-detail--list" in cls or "price-detail" in cls:
                self._in_detail_list = True
            elif "count" in cls:
                self._in_count = True
                self._text_buffer = ""
            elif "price" in cls.split() or cls == "price":
                self._in_price = True
                self._text_buffer = ""
        elif tag == "div":
            if "price-detail__row" in cls:
                self._in_detail_row = True
                self._detail_count = ""
                self._detail_subitem = ""
                self._detail_prices = []
            elif "price-detail__main" in cls:
                self._in_detail_main = True
            elif "price-detail__price" in cls:
                self._in_detail_price_div = True
                self._current_price_label = ""
                self._current_price_value = ""
        elif tag == "span":
            if "count" in cls and self._in_detail_row:
                self._in_count = True
                self._text_buffer = ""
            elif "price-detail" == cls and self._in_detail_list:
                self._in_price_detail_span = True
                self._text_buffer = ""
            elif "price" in cls.split() or cls == "price":
                self._in_price = True
                self._text_buffer = ""
            elif cls in ("normal", "first", "repeat", "campaign") or \
                 any(c in cls for c in ("normal", "first")):
                self._in_price_label = True
                self._text_buffer = ""

    def handle_endtag(self, tag):
        if self._tag_stack and self._tag_stack[-1] == tag:
            self._tag_stack.pop()

        if tag == "h2" and self._in_h2:
            self._in_h2 = False
            text = _clean_ws(self._text_buffer)
            if text:
                self.current_section = text
        elif tag == "h3" and self._in_h3:
            self._in_h3 = False
            text = _clean_ws(self._text_buffer)
            if text and not text.startswith("メニュー"):
                self.current_section = text
        elif tag == "h4" and self._in_h4:
            self._in_h4 = False
            text = _clean_ws(self._text_buffer)
            if text:
                self.current_treatment = text
        elif tag == "th" and self._in_th:
            self._in_th = False
            self._current_area = _clean_ws(self._text_buffer)
        elif tag == "td":
            if self._in_count:
                self._in_count = False
                count_text = _clean_ws(self._text_buffer)
                if not self._in_detail_row:
                    self._current_count = count_text
            if self._in_price and not self._in_detail_row:
                self._in_price = False
                price_text = _clean_ws(self._text_buffer)
                self._current_price_value = price_text
                if self.current_treatment and self._current_area:
                    self._emit_simple_row()
            if self._in_detail_list and tag == "td":
                self._in_detail_list = False
        elif tag == "span":
            if self._in_count and self._in_detail_row:
                self._in_count = False
                self._detail_count = _clean_ws(self._text_buffer)
            elif self._in_price_detail_span:
                self._in_price_detail_span = False
                self._detail_subitem = _clean_ws(self._text_buffer)
            elif self._in_price:
                self._in_price = False
                self._current_price_value = _clean_ws(self._text_buffer)
            elif self._in_price_label:
                self._in_price_label = False
                self._current_price_label = _clean_ws(self._text_buffer)
        elif tag == "div":
            if self._in_detail_price_div:
                self._in_detail_price_div = False
                if self._current_price_label and self._current_price_value:
                    self._detail_prices.append(
                        (self._current_price_label, self._current_price_value))
                elif self._current_price_value and not self._current_price_label:
                    self._detail_prices.append(
                        ("通常価格", self._current_price_value))
                self._current_price_label = ""
                self._current_price_value = ""
            elif self._in_detail_main:
                self._in_detail_main = False
            elif self._in_detail_row:
                self._in_detail_row = False
                if self.current_treatment:
                    self._emit_detail_row()

    def handle_data(self, data):
        if any([self._in_h2, self._in_h3, self._in_h4, self._in_th,
                self._in_count, self._in_price, self._in_price_label,
                self._in_price_detail_span]):
            self._text_buffer += data

    def _parse_price(self, text):
        if not text:
            return None
        text = text.replace(",", "").replace("，", "").replace("円", "")
        text = text.replace("¥", "").replace("\u00a5", "").strip()
        text = re.sub(r'[^\d]', '', text)
        if text:
            try:
                return int(text)
            except ValueError:
                return None
        return None

    def _emit_simple_row(self):
        price = self._parse_price(self._current_price_value)
        if price is not None:
            self.results.append({
                "section": self.current_section,
                "treatment": self.current_treatment,
                "area": self._current_area,
                "detail": "",
                "sessions": self._current_count,
                "regular_price": price,
                "first_price": None,
                "repeat_price": None,
                "campaign_price": None,
                "monitor_full_price": None,
                "monitor_eye_price": None,
            })

    def _emit_detail_row(self):
        if not self._detail_prices:
            if self._detail_subitem and self._current_price_value:
                price = self._parse_price(self._current_price_value)
                if price is not None:
                    area = self._current_area or self._detail_subitem
                    detail = self._detail_subitem if self._current_area else ""
                    self.results.append({
                        "section": self.current_section,
                        "treatment": self.current_treatment,
                        "area": area,
                        "detail": detail,
                        "sessions": self._detail_count,
                        "regular_price": price,
                        "first_price": None, "repeat_price": None,
                        "campaign_price": None,
                        "monitor_full_price": None, "monitor_eye_price": None,
                    })
            return

        row = {
            "section": self.current_section,
            "treatment": self.current_treatment,
            "area": self._current_area or self._detail_subitem,
            "detail": self._detail_subitem if self._current_area else "",
            "sessions": self._detail_count,
            "regular_price": None, "first_price": None,
            "repeat_price": None, "campaign_price": None,
            "monitor_full_price": None, "monitor_eye_price": None,
        }

        for label, price_text in self._detail_prices:
            price = self._parse_price(price_text)
            if price is None:
                continue
            label = label.strip()
            if "通常" in label:
                row["regular_price"] = price
            elif "初回" in label:
                row["first_price"] = price
            elif "リピーター" in label:
                row["repeat_price"] = price
            elif "キャンペーン" in label or "まとめ買い" in label:
                row["campaign_price"] = price
            elif "全顔出しモニター" in label:
                row["monitor_full_price"] = price
            elif "目隠しありモニター" in label or "目元のみモニター" in label:
                row["monitor_eye_price"] = price
            elif "上顔面のみモニター" in label:
                row["monitor_eye_price"] = price
            elif "チケット" in label:
                row["campaign_price"] = price

        has_price = any(row[k] is not None for k in [
            "regular_price", "first_price", "repeat_price",
            "campaign_price", "monitor_full_price", "monitor_eye_price"])
        if has_price:
            self.results.append(row)


def _clean_ws(s):
    """Clean whitespace from parsed HTML text."""
    if not s:
        return ""
    # Replace all whitespace (newlines, tabs, spaces) with single space
    s = re.sub(r'[\r\n\t]+', ' ', s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip()


# ── Normalization ──
def norm(s):
    """Normalize text for matching: lowercase, strip, remove extra chars."""
    if not s:
        return ""
    s = str(s).strip()
    # Whitespace normalization
    s = re.sub(r'[\r\n\t\u3000]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    # Full-width to half-width
    s = s.replace("（", "(").replace("）", ")").replace("＋", "+")
    s = s.replace("〜", "~").replace("～", "~")
    s = s.replace("㎜", "mm").replace("ｍｍ", "mm")
    s = s.replace("㎝", "cm").replace("ｃｍ", "cm")
    s = s.replace("ｃｃ", "cc").replace("㏄", "cc")
    # Common character variations
    s = s.replace("ヴェルベット", "ヴェルヴェット")  # normalize to master form
    s = s.replace("α", "α")  # keep consistent
    s = s.replace("➕", "+")
    # Normalize 瘦/痩 (different kanji for same meaning)
    s = s.replace("痩", "瘦")
    # Lowercase for case-insensitive matching (for things like 2D/2d)
    s = s.lower()
    return s


def norm_compact(s):
    """Even more aggressive normalization for loose matching."""
    s = norm(s)
    # Remove all whitespace and common punctuation
    s = re.sub(r'[\s・\-–—/／]', '', s)
    return s


# ── Fetch & Parse ──
def fetch_web_data():
    print(f"Fetching {WEB_URL} ...")
    req = urllib.request.Request(WEB_URL, headers={"User-Agent": "Mozilla/5.0"})
    resp = urllib.request.urlopen(req, timeout=30)
    html = resp.read().decode("utf-8")
    print(f"  Received {len(html):,} bytes")

    parser = PricePageParser()
    parser.feed(html)

    # Post-process: clean areas and split header areas
    processed = []
    for w in parser.results:
        w["area"] = _clean_ws(w["area"])
        w["detail"] = _clean_ws(w.get("detail", ""))
        w["sessions"] = _clean_ws(w.get("sessions", ""))
        w["treatment"] = _clean_ws(w["treatment"])

        # If area is a "header area", use detail as real area
        if w["area"] in HEADER_AREAS and w["detail"]:
            w["area"] = w["detail"]
            w["detail"] = ""

        processed.append(w)

    print(f"  Parsed {len(processed)} web price entries (raw)")

    # ── Deduplicate: merge bundle entries into single-session entries ──
    # Many treatments have both 1回 and 3回券/5回 entries for the same area.
    # The bundle entry's regular_price is a TOTAL (e.g., 137,500 for 5 sessions),
    # not a per-session price, so it must not be used as old_price.
    # Strategy: group by (treatment, area), keep single-session entry,
    #           merge campaign/repeat/monitor prices from bundle entries.
    BUNDLE_PATTERN = re.compile(r'^[2-9]\d*回|^\d{2,}回')  # 2回以上, 10回, etc.
    from collections import defaultdict
    groups = defaultdict(list)
    for w in processed:
        key = (w["treatment"], w["area"])
        groups[key].append(w)

    deduplicated = []
    skipped_bundles = 0
    for key, entries in groups.items():
        if len(entries) == 1:
            deduplicated.append(entries[0])
            continue

        # Separate single-session and bundle entries
        singles = []
        bundles = []
        for e in entries:
            sess = e.get("sessions", "").strip()
            if BUNDLE_PATTERN.match(sess) or "回券" in sess:
                bundles.append(e)
            else:
                singles.append(e)

        if not singles:
            # No single-session entry; keep bundles as-is (rare)
            deduplicated.extend(bundles)
            continue

        # Keep only single-session entries; discard bundle entries.
        # Bundle entries have total prices (e.g., 3回券 ¥47,520 = 3×¥15,840/回)
        # which would be incorrectly applied as per-session old_price.

        # Additional dedup: when multiple singles share the same (treatment, area)
        # with empty sessions but different prices (e.g., 脱毛 1回/5回/8回 all parsed
        # as sessions=""), keep only the CHEAPEST (= 1回 per-session price).
        empty_sess_singles = [s for s in singles if not s.get("sessions", "").strip()]
        named_sess_singles = [s for s in singles if s.get("sessions", "").strip()]

        if len(empty_sess_singles) > 1:
            # Multiple entries with empty sessions — keep cheapest as single-session
            priced = [s for s in empty_sess_singles if s.get("regular_price") is not None]
            no_price = [s for s in empty_sess_singles if s.get("regular_price") is None]
            if priced:
                priced.sort(key=lambda s: s["regular_price"])
                deduplicated.append(priced[0])  # cheapest = single-session
                skipped_bundles += len(priced) - 1
            # Keep entries with no regular_price (may have first/campaign/monitor)
            for np in no_price:
                deduplicated.append(np)
        else:
            for s in empty_sess_singles:
                deduplicated.append(s)

        # Always keep entries with named sessions (e.g., "1回", "60分", "1cc")
        for s in named_sess_singles:
            deduplicated.append(s)
        skipped_bundles += len(bundles)

    print(f"  After dedup: {len(deduplicated)} entries "
          f"({skipped_bundles} bundle entries merged/skipped)")
    return deduplicated


# ── Matching Logic ──
def match_and_update(master_data, web_data):
    treatments = master_data["treatments"]

    # Build master indices
    # 1. Exact key: (norm_treatment, norm_area) → [indices]
    master_exact = {}
    for i, t in enumerate(treatments):
        key = (norm(t.get("treatment", "")), norm(t.get("area", "")))
        master_exact.setdefault(key, []).append(i)

    # 2. By treatment name only: norm_treatment → [indices]
    master_by_name = {}
    for i, t in enumerate(treatments):
        name = norm(t.get("treatment", ""))
        master_by_name.setdefault(name, []).append(i)

    # 3. By compact name: norm_compact(treatment) → [indices]
    master_by_compact = {}
    for i, t in enumerate(treatments):
        name = norm_compact(t.get("treatment", ""))
        master_by_compact.setdefault(name, []).append(i)

    # 4. Build alias map: for each web name, what master names to try
    alias_map = {}
    for web_name, master_names in TREATMENT_ALIASES.items():
        alias_map[norm(web_name)] = [norm(mn) for mn in master_names]

    matched = 0
    unmatched_web = []
    stats = {
        "old_price": 0, "first_price": 0, "repeat_price": 0,
        "campaign_price": 0, "monitor_full_price": 0, "monitor_eye_price": 0,
        "price_changed": 0,
    }

    for w in web_data:
        w_name = norm(w["treatment"])
        w_area = norm(w["area"])
        w_detail = norm(w.get("detail", ""))
        w_sessions = norm(w.get("sessions", ""))

        indices = _find_match(
            w_name, w_area, w_detail, w_sessions, w,
            master_exact, master_by_name, master_by_compact,
            alias_map, treatments
        )

        if not indices:
            unmatched_web.append(w)
            continue

        for idx in indices:
            matched += 1
            _update_treatment(treatments[idx], w, stats)

    return matched, unmatched_web, stats


def _find_match(w_name, w_area, w_detail, w_sessions, w,
                master_exact, master_by_name, master_by_compact,
                alias_map, treatments):
    """Multi-strategy matching."""
    indices = []

    # ── Pass 1: Exact (name, area) match ──
    key = (w_name, w_area)
    if key in master_exact:
        return master_exact[key]

    # ── Pass 2: Alias name + area match ──
    if w_name in alias_map:
        for alias_name in alias_map[w_name]:
            key = (alias_name, w_area)
            if key in master_exact:
                return master_exact[key]
            # Also try with detail as area for alias
            if w_detail:
                key2 = (alias_name, norm(w_detail))
                if key2 in master_exact:
                    return master_exact[key2]

    # ── Pass 3: Same name, fuzzy area ──
    if w_name in master_by_name:
        for idx in master_by_name[w_name]:
            m_area = norm(treatments[idx].get("area", ""))
            if _area_match(w_area, m_area, w_detail):
                indices.append(idx)
        if indices:
            return indices

    # ── Pass 4: Alias name, EXACT area (after normalization) ──
    # Using alias already loosens the name constraint, so be strict on area
    if w_name in alias_map:
        for alias_name in alias_map[w_name]:
            if alias_name in master_by_name:
                for idx in master_by_name[alias_name]:
                    m_area = norm(treatments[idx].get("area", ""))
                    # Strict: exact match after normalization, or detail match
                    if w_area == m_area or (w_detail and w_detail == m_area):
                        indices.append(idx)
                    # Also allow compact exact match
                    elif norm_compact(w_area) == norm_compact(m_area):
                        indices.append(idx)
                if indices:
                    return indices

    # ── Pass 5: Treatment name substring match + EXACT area ──
    for m_name, m_indices in master_by_name.items():
        if not m_name or not w_name:
            continue
        if len(w_name) < 3 or len(m_name) < 3:
            continue
        if w_name in m_name or m_name in w_name:
            for idx in m_indices:
                m_area = norm(treatments[idx].get("area", ""))
                # Strict area match when treatment names are only partial matches
                if w_area == m_area or norm_compact(w_area) == norm_compact(m_area):
                    indices.append(idx)
                elif w_detail and (w_detail == m_area or norm_compact(w_detail) == norm_compact(m_area)):
                    indices.append(idx)
            if indices:
                return indices

    # ── Pass 6: Web area IS a master treatment name ──
    # e.g., web: フォトナレーザー area="フォトナ2D ..." → master: "フォトナ2d"
    # Only when the web treatment is a known parent that groups sub-treatments
    PARENT_TREATMENTS = {norm(x) for x in [
        "フォトナレーザー", "ボルフォーマー（ボルニューマ＋ウルトラフォーマーMPT）",
    ]}
    if w_name in PARENT_TREATMENTS and w_area:
        area_first = w_area.split()[0] if " " in w_area else w_area
        area_clean = re.sub(r'\(.*\)', '', area_first).strip()
        for lookup in [norm(area_first), norm(area_clean)]:
            if lookup in master_by_name:
                return master_by_name[lookup]
        # Try compact
        for lookup in [norm_compact(area_first), norm_compact(area_clean)]:
            if lookup in master_by_compact:
                return master_by_compact[lookup]

    # ── Pass 7: Web area STARTS WITH master treatment name (ADM case) ──
    # e.g., web: treatment=ピコスポット area=ADM(後天性...) → master treatment=ADM
    # STRICT: Require area to START with the treatment name, and w_name != m_name.
    # This prevents false positives like "ボトックス" in "スキンボトックス".
    for m_name, m_indices in master_by_name.items():
        if not m_name or len(m_name) < 2:
            continue
        if m_name == w_name:
            continue  # Same treatment — already handled by earlier passes
        area_compact = norm_compact(w_area)
        if area_compact.startswith(m_name):
            for idx in m_indices:
                m_area = norm(treatments[idx].get("area", ""))
                if not m_area or _area_match(w_detail, m_area, ""):
                    indices.append(idx)
            if indices:
                return indices

    # ── Pass 8: Price-based confirmation for same-name matches ──
    # Only use when there's exactly one price match (to avoid ambiguity)
    # IMPORTANT: Only use when the web entry has an area AND the master has an area.
    # Without area, price matches are too unreliable (e.g., ボトックス variants
    # all have different web areas but master entries have no area).
    if w_name in master_by_name and w.get("regular_price") is not None and w_area:
        wp = w["regular_price"]
        price_matches = []
        for idx in master_by_name[w_name]:
            m_area = norm(treatments[idx].get("area", ""))
            m_price = treatments[idx].get("price")
            if m_price and m_area:  # Both need area for reliable matching
                try:
                    mp = int(str(m_price).replace(",", ""))
                    if mp == wp:
                        price_matches.append(idx)
                except (ValueError, TypeError):
                    pass
        # Only use if exactly one match (unique price match)
        if len(price_matches) == 1:
            return price_matches

    # Same for aliases - only unique matches
    if w_name in alias_map and w.get("regular_price") is not None:
        wp = w["regular_price"]
        price_matches = []
        for alias_name in alias_map[w_name]:
            if alias_name in master_by_name:
                for idx in master_by_name[alias_name]:
                    m_price = treatments[idx].get("price")
                    if m_price:
                        try:
                            mp = int(str(m_price).replace(",", ""))
                            if mp == wp:
                                price_matches.append(idx)
                        except (ValueError, TypeError):
                            pass
        if len(price_matches) == 1:
            return price_matches

    return []


def _area_match(w_area, m_area, w_detail=""):
    """Check if web area matches master area."""
    if not w_area and not m_area:
        return True
    if not w_area or not m_area:
        if w_detail and m_area:
            return _area_match(w_detail, m_area, "")
        # Web has no area, master has no area
        if not w_area and not m_area:
            return True
        return False

    # Exact
    if w_area == m_area:
        return True

    # Compact comparison
    wa = norm_compact(w_area)
    ma = norm_compact(m_area)
    if wa == ma:
        return True

    # Contains - but require reasonable length similarity to avoid false matches
    # e.g., "VIO" should not match "全身パーフェクト(顔うなじVIO付き)"
    if len(wa) >= 2 and len(ma) >= 2:
        shorter = min(len(wa), len(ma))
        longer = max(len(wa), len(ma))
        if (wa in ma or ma in wa) and shorter >= longer * 0.4:
            return True

    # 全顔 / 顔全体 equivalence — ONLY when both areas are exactly the face word
    # e.g., "全顔" ↔ "顔全体", but NOT "顔全体(HA+...)" ↔ "顔全体"
    face_words = {"全顔", "顔全体"}
    if w_area in face_words and m_area in face_words:
        return True

    # Number-based matching for mm/cm sizes (only when treatment context suggests size-based)
    wa_nums = re.findall(r'(\d+)\s*(?:mm|cm)', wa)
    ma_nums = re.findall(r'(\d+)\s*(?:mm|cm)', ma)
    if wa_nums and ma_nums and set(wa_nums) == set(ma_nums):
        # Only match if both are primarily size descriptions
        if len(wa) < 15 and len(ma) < 15:
            return True

    # N部位/N単位 prefix matching (for remapped ボトックス entries etc.)
    # "1部位" matches "1部位(眉間・額・...)"
    # "2部位" matches "2部位"
    # Skip "per unit" descriptions like "3部位以上なら..."
    unit_pat = re.compile(r'^(\d+(?:部位|単位))')
    wa_unit = unit_pat.match(wa)
    ma_unit = unit_pat.match(ma)
    if wa_unit and ma_unit and wa_unit.group(1) == ma_unit.group(1):
        # Ensure not a "per unit" bulk pricing description
        if "以上" not in wa and "あたり" not in wa:
            return True

    return False


# ── ボトックス Pre-processing ──
def _preprocess_botox(web_data):
    """Remap ボトックス web entries to match master naming convention.

    Web structure:   treatment=ボトックス, area=アラガン/ニューロノックス, sessions=N部位
    Master structure: treatment=ボトックス（アラガン）, area=N部位（眉間・額・...）

    Also handles:
    - area=アラガンボトックスリフト → treatment=ボトックスリフト（アラガン）
    - area=アラガンまとめ買い → treatment=ボトックス（アラガン）, area=100単位
    - area=アラガンオーダーメイド → treatment=ボトックス（アラガン）, area=オーダーメイド...
    """
    DRUG_NAMES = ["アラガン", "ニューロノックス"]
    remapped = 0

    for w in web_data:
        if w["treatment"] != "ボトックス":
            continue

        area = w["area"]
        matched_drug = None
        for drug in DRUG_NAMES:
            if area.startswith(drug):
                matched_drug = drug
                break

        if not matched_drug:
            continue

        suffix = area[len(matched_drug):]

        if "ボトックスリフト" in suffix:
            # ボトックスリフト（アラガン）/ ボトックスリフト（ニューロノックス）
            w["treatment"] = f"ボトックスリフト（{matched_drug}）"
            w["area"] = ""
        elif "まとめ買い" in suffix:
            # ボトックス（アラガン）with sessions (e.g., 100単位) as area
            w["treatment"] = f"ボトックス（{matched_drug}）"
            w["area"] = w.get("sessions", "")
            w["sessions"] = ""
        elif "オーダーメイド" in suffix:
            # Special product — remap treatment but keep distinctive area
            w["treatment"] = f"ボトックス（{matched_drug}）"
            w["area"] = f"オーダーメイド {w.get('sessions', '')}"
            w["sessions"] = ""
        elif suffix == "":
            # Plain drug name: area=アラガン → treatment=ボトックス（アラガン）
            # Move sessions (1部位, 2部位) to area for matching
            w["treatment"] = f"ボトックス（{matched_drug}）"
            w["area"] = w.get("sessions", "")
            w["sessions"] = ""

        remapped += 1

    if remapped:
        print(f"  Pre-processed {remapped} ボトックス entries (remapped to master naming)")

    return web_data


# ── Update Logic ──
def _update_treatment(t, w, stats):
    """Update a master treatment record with web price data."""
    # Map web regular_price → old_price
    if w.get("regular_price") is not None:
        new_val = str(w["regular_price"])
        if t.get("old_price") != new_val:
            t["old_price"] = new_val
            stats["old_price"] += 1

        # Check if master price differs from web regular_price
        master_price = t.get("price")
        if master_price:
            try:
                mp = int(str(master_price).replace(",", ""))
                if mp != w["regular_price"]:
                    stats["price_changed"] += 1
            except (ValueError, TypeError):
                pass

    # Map web first_price → first_price
    if w.get("first_price") is not None:
        new_val = str(w["first_price"])
        if t.get("first_price") != new_val:
            t["first_price"] = new_val
            stats["first_price"] += 1

    # Map web repeat_price → repeat_price
    if w.get("repeat_price") is not None:
        new_val = str(w["repeat_price"])
        if t.get("repeat_price") != new_val:
            t["repeat_price"] = new_val
            stats["repeat_price"] += 1

    # Map web campaign_price → campaign_price
    if w.get("campaign_price") is not None:
        new_val = str(w["campaign_price"])
        if t.get("campaign_price") != new_val:
            t["campaign_price"] = new_val
            stats["campaign_price"] += 1

    # Map web monitor_full_price → monitor_full_price
    if w.get("monitor_full_price") is not None:
        new_val = str(w["monitor_full_price"])
        if t.get("monitor_full_price") != new_val:
            t["monitor_full_price"] = new_val
            stats["monitor_full_price"] += 1

    # Map web monitor_eye_price → monitor_eye_price
    if w.get("monitor_eye_price") is not None:
        new_val = str(w["monitor_eye_price"])
        if t.get("monitor_eye_price") != new_val:
            t["monitor_eye_price"] = new_val
            stats["monitor_eye_price"] += 1


# ── Build public JSON ──
def build_public_data(master_data):
    public = {
        "metadata": dict(master_data["metadata"]),
        "treatments": []
    }
    for t in master_data["treatments"]:
        pub_t = {k: v for k, v in t.items() if k not in PRIVATE_FIELDS}
        public["treatments"].append(pub_t)
    return public


# ── Main ──
def main():
    # Step 1: Fetch web data
    web_data = fetch_web_data()

    # Save web data for reference
    web_json_path = os.path.join(BASE_DIR, "scripts", "web_prices_scraped.json")
    with open(web_json_path, "w", encoding="utf-8") as f:
        json.dump(web_data, f, ensure_ascii=False, indent=2)
    print(f"  Saved scraped data to {web_json_path}")

    # Step 1.5: Pre-process special cases for matching
    web_data = _preprocess_botox(web_data)

    # Step 2: Read master data
    print(f"\nReading {PRICES_JSON} ...")
    with open(PRICES_JSON, "r", encoding="utf-8") as f:
        master = json.load(f)
    print(f"  {len(master['treatments'])} treatments in master")

    # Step 2.5: Clear all web-derived fields before re-matching
    # This ensures stale data from previous runs doesn't persist
    WEB_DERIVED_FIELDS = ["old_price", "first_price", "repeat_price",
                          "campaign_price", "monitor_full_price", "monitor_eye_price"]
    cleared = 0
    for t in master["treatments"]:
        for field in WEB_DERIVED_FIELDS:
            if t.get(field):
                t[field] = ""
                cleared += 1
    print(f"  Cleared {cleared} web-derived fields from {len(master['treatments'])} treatments")

    # Step 3: Match and update
    print("\nMatching web data to master ...")
    matched, unmatched, stats = match_and_update(master, web_data)
    print(f"  Matched: {matched} web entries → master treatments")
    print(f"  Unmatched web entries: {len(unmatched)}")
    print(f"  Updates:")
    for field, count in sorted(stats.items()):
        if count > 0:
            print(f"    {field}: {count}")

    # Show unmatched for debugging
    if unmatched:
        print(f"\n  Unmatched web entries ({len(unmatched)}):")
        for w in unmatched[:30]:
            p = w.get('regular_price', '?')
            print(f"    [{w['section'][:10]}] {w['treatment'][:25]} | "
                  f"A={w['area'][:25]} | D={w.get('detail','')[:20]} | ¥{p}")

    # Step 4: Write updated files
    print(f"\nWriting {PRICES_JSON} ...")
    with open(PRICES_JSON, "w", encoding="utf-8") as f:
        json.dump(master, f, ensure_ascii=False, indent=2)
    print("  Done")

    print(f"Writing {PRICES_PUBLIC_JSON} ...")
    public = build_public_data(master)
    with open(PRICES_PUBLIC_JSON, "w", encoding="utf-8") as f:
        json.dump(public, f, ensure_ascii=False, indent=2)
    print("  Done")

    total_updates = sum(v for v in stats.values())
    print(f"\n✅ Integration complete!")
    print(f"   {matched} web entries matched to master treatments")
    print(f"   {total_updates} fields updated")
    print(f"   {len(unmatched)} web entries had no match in master")


if __name__ == "__main__":
    main()
