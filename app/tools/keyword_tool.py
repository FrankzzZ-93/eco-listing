from __future__ import annotations

import io
import re
from typing import Union

import openpyxl

from app.config import settings

# Amazon ASIN: 10-char alphanumeric token; product ASINs start with "B0".
# Used to strip ASIN-like tokens out of keyword libraries and generated ST,
# and to flag them during compliance validation. Shared across tools.
ASIN_RE = re.compile(r"\bB0[A-Z0-9]{8}\b", re.IGNORECASE)

# Function words that carry no search value in backend Search Terms. Amazon
# ignores them anyway, so spending bytes on them is pure waste.
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "for", "with", "of", "to", "in", "on",
        "at", "by", "is", "are", "be", "as", "it", "its", "this", "that",
        "from", "your", "you", "&",
    }
)


def parse_xlsx_keywords(content: bytes) -> list[dict]:
    """Parse keyword xlsx files from 西柚 or 鸥鹭 into a unified format.

    西柚 header signature: first column is '关键词 (数据来源于西柚找词)'
      - keyword col: '关键词 (数据来源于西柚找词)'
      - search_volume col: '周搜索量'
      - competition col: '竞争难度档位'

    鸥鹭 header signature: first column is '流量关键词'
      - keyword col: '流量关键词'
      - search_volume col: '月搜索量'
      - competition col: (derived from '机会指数')
    """
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not rows:
        return []

    header = [str(c or "").strip() for c in rows[0]]
    col_map = {name: idx for idx, name in enumerate(header)}

    def _get(row: tuple, col_name: str, default=""):
        idx = col_map.get(col_name)
        if idx is None or idx >= len(row):
            return default
        val = row[idx]
        return default if val is None else val

    # Optional source-library columns (西柚 export). Matched by substring so
    # minor header variations (e.g. "CPC建议竞价($)" vs "CPC竞价") still resolve.
    # These ride along into the keyword library purely as review-time reference
    # data (translation / CPC / click-through conversion rate).
    def _find_col(*needles: str) -> int | None:
        for idx, name in enumerate(header):
            if any(n in name for n in needles):
                return idx
        return None

    translation_idx = _find_col("翻译")
    cpc_idx = _find_col("CPC", "建议竞价", "建议出价")
    conv_idx = _find_col("转化率")

    def _opt(row: tuple, idx: int | None, default=""):
        if idx is None or idx >= len(row):
            return default
        val = row[idx]
        return default if val is None else val

    def _num(val) -> float:
        try:
            return float(str(val).replace("$", "").replace("%", "").strip())
        except (ValueError, TypeError):
            return 0.0

    def _source_extras(row: tuple) -> dict:
        extras: dict = {}
        if translation_idx is not None:
            extras["translation"] = str(_opt(row, translation_idx, "")).strip()
        if cpc_idx is not None:
            extras["bid_price"] = _num(_opt(row, cpc_idx, 0))
        if conv_idx is not None:
            extras["conversion_rate"] = _num(_opt(row, conv_idx, 0))
        return extras

    results: list[dict] = []
    first_col = header[0] if header else ""

    if "西柚" in first_col or "关键词" == first_col.split("(")[0].strip().split("（")[0].strip():
        kw_col = header[0]
        sv_col = "周搜索量"
        comp_col = "竞争难度档位"
        for row in rows[1:]:
            kw = str(_get(row, kw_col, "")).strip()
            if not kw:
                continue
            sv = _get(row, sv_col, 0)
            try:
                sv = int(float(sv))
            except (ValueError, TypeError):
                sv = 0
            results.append({
                "keyword": kw,
                "search_volume": sv,
                "competition": str(_get(row, comp_col, "")),
                **_source_extras(row),
            })
    elif first_col == "流量关键词":
        for row in rows[1:]:
            kw = str(_get(row, "流量关键词", "")).strip()
            if not kw:
                continue
            sv = _get(row, "月搜索量", 0)
            try:
                sv = int(float(sv))
            except (ValueError, TypeError):
                sv = 0
            opp = _get(row, "机会指数", 0)
            try:
                opp = float(opp)
            except (ValueError, TypeError):
                opp = 0
            if opp >= 0.5:
                comp = "低"
            elif opp >= 0.2:
                comp = "中等"
            else:
                comp = "高"
            results.append({
                "keyword": kw,
                "search_volume": sv,
                "competition": comp,
                **_source_extras(row),
            })
    else:
        for row in rows[1:]:
            kw = str(row[0] or "").strip() if row else ""
            if not kw:
                continue
            sv = 0
            for i, h in enumerate(header):
                if "搜索量" in h and i < len(row):
                    try:
                        sv = int(float(row[i]))
                    except (ValueError, TypeError):
                        pass
                    break
            results.append({
                "keyword": kw,
                "search_volume": sv,
                "competition": "",
                **_source_extras(row),
            })

    return results


class KeywordTool:
    def clean(self, raw_data: Union[list[dict], bytes]) -> list[dict]:
        if isinstance(raw_data, bytes):
            raw_data = parse_xlsx_keywords(raw_data)
        cleaned: list[dict] = []
        seen: set[str] = set()
        for row in raw_data:
            kw = row.get("keyword", "").strip().lower()
            if not kw or kw in seen:
                continue
            if ASIN_RE.search(kw):
                # Drop ASIN-like tokens (e.g. accidental ASIN rows in the
                # 鸥鹭/西柚 export) so they never reach classification or ST.
                continue
            seen.add(kw)
            entry = {
                "keyword": kw,
                "search_volume": int(row.get("search_volume", 0)),
                "competition": row.get("competition", ""),
            }
            # Preserve optional source-library reference fields when present so
            # they can be surfaced during keyword-classification review.
            for opt_key in ("translation", "bid_price", "conversion_rate"):
                if opt_key in row and row.get(opt_key) not in (None, ""):
                    entry[opt_key] = row[opt_key]
            cleaned.append(entry)
        cleaned.sort(key=lambda x: x["search_volume"], reverse=True)
        return cleaned

    def optimize_st(
        self,
        listing: dict,
        st_v3: list[str],
        classified_keywords: dict,
    ) -> dict:
        """Build backend Search Terms as a bag of unique single words.

        Amazon indexes ST word-by-word and gives no extra weight to repeats,
        so the optimal strategy is: tokenize every candidate phrase into
        individual words, drop words already indexed elsewhere in the listing,
        drop stopwords/ASIN/noise, dedupe, rank by source value, then pack
        unique words up to the byte budget. This eliminates the phrase-level
        duplication (e.g. "closet organizer" + "closet organization" both
        re-spending bytes on "closet").
        """
        st_byte_budget = settings.st_max_bytes

        listing_text = " ".join(
            [
                listing.get("title", ""),
                " ".join(listing.get("bullet_points", [])),
                listing.get("description", ""),
            ]
        ).lower()
        used_words = set(self._tokenize(listing_text))

        # Candidate words with their best (priority, search_volume) score.
        # Lower priority number = higher value (A > B > C); st_v3 inherits the
        # highest priority since the copywriter already curated it.
        CLASS_PRIORITY = {"A": 0, "B": 1, "C": 2}
        best: dict[str, tuple[int, int]] = {}
        order: list[str] = []
        raw_word_count = 0

        def _consider(word: str, priority: int, volume: int) -> None:
            nonlocal raw_word_count
            raw_word_count += 1
            if word in best:
                # Keep the strongest score seen for this word.
                if (priority, -volume) < (best[word][0], -best[word][1]):
                    best[word] = (priority, volume)
                return
            best[word] = (priority, volume)
            order.append(word)

        # st_v3 phrases first (curated), priority 0.
        for phrase in st_v3 or []:
            for word in self._tokenize(str(phrase)):
                _consider(word, 0, 0)

        # Classified A/B/C keywords (D and meta keys are skipped in _flatten).
        for kw in self._flatten(classified_keywords):
            priority = CLASS_PRIORITY.get(kw.get("_class", ""), 2)
            volume = int(kw.get("search_volume", 0) or 0)
            for word in self._tokenize(kw.get("keyword", "")):
                _consider(word, priority, volume)

        unique_candidate_words = len(order)

        # Filter: already-indexed words, stopwords, ASIN tokens, noise, and
        # single-character fragments. The tokenizer splits phrases on non-
        # alphanumerics, so contractions/hyphenations leak stray 1-char tokens
        # ("women's" -> "women","s"; "t-shirt" -> "t","shirt"). Single letters/
        # digits carry zero search value and must never reach Search Terms.
        candidates = [
            w
            for w in order
            if len(w) >= 2
            and w not in used_words
            and w not in _STOPWORDS
            and not ASIN_RE.match(w)
        ]

        # Rank by (priority asc, search_volume desc), stable on insertion order.
        candidates.sort(key=lambda w: (best[w][0], -best[w][1]))

        final_st: list[str] = []
        current_bytes = 0
        for word in candidates:
            added = len(word.encode("utf-8")) + (1 if final_st else 0)
            if current_bytes + added > st_byte_budget:
                continue
            final_st.append(word)
            current_bytes += added

        return {
            "final_st": final_st,
            "word_frequency_report": {
                "total_candidate_words": raw_word_count,
                "unique_candidate_words": unique_candidate_words,
                "duplicates_removed": raw_word_count - unique_candidate_words,
                "final_word_count": len(final_st),
                "total_bytes": current_bytes,
            },
        }

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Lowercase word tokens (letters/digits), order-preserving."""
        return re.findall(r"[a-z0-9]+", (text or "").lower())

    # Keys in the classify output that are NOT keyword buckets (metadata), and
    # the exclusion bucket (D) whose words must never reach the listing/ST.
    _META_KEYS = frozenset({"semantic_map", "summary"})
    _EXCLUSION_KEYS = frozenset({"D", "d", "排除词", "exclusion"})

    @classmethod
    def _flatten(cls, classified: dict) -> list[dict]:
        """Flatten keyword buckets, skipping metadata and the D/exclusion class.

        Works with both the production A/B/C/D schema and arbitrary class names
        (e.g. "functional"). Each returned dict carries a `_class` key for
        downstream ranking.
        """
        result: list[dict] = []
        for class_name, entries in classified.items():
            if class_name in cls._META_KEYS or class_name in cls._EXCLUSION_KEYS:
                continue
            if not isinstance(entries, list):
                continue
            for e in entries:
                if isinstance(e, dict):
                    item = dict(e)
                else:
                    item = {"keyword": e, "search_volume": 0}
                item["_class"] = class_name
                result.append(item)
        return result
