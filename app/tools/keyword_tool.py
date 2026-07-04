from __future__ import annotations

import io
import logging
import re
from typing import Union

import openpyxl

from app.config import settings

logger = logging.getLogger(__name__)

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


def _best_integer_column(rows: list[tuple], header: list[str], exclude: set[int]) -> int | None:
    """Pick the column that most looks like a search-volume column.

    Used to repair a parse where every ``search_volume`` came out 0. Search
    volumes are positive integers, while CPC ($1.23) and conversion (0.09) are
    fractional — so the column with the most positive *whole-number* cells is
    the search-volume column. Columns in ``exclude`` (keyword / CPC / conversion
    / translation) are skipped.
    """
    best_idx, best_score = None, 0
    for idx in range(len(header)):
        if idx in exclude:
            continue
        score = 0
        for row in rows[1:]:
            if idx >= len(row):
                continue
            v = row[idx]
            if isinstance(v, bool):
                continue
            if isinstance(v, int) and v > 0:
                score += 1
            elif isinstance(v, float) and v > 0 and v.is_integer():
                score += 1
        if score > best_score:
            best_idx, best_score = idx, score
    return best_idx


def parse_xlsx_keywords(content: bytes) -> list[dict]:
    """Parse keyword xlsx files from 西柚 or 鸥鹭 into a unified format.

    西柚 header signature: first column starts with '关键词' (e.g.
    '关键词 (数据来源于西柚找词)' or '关键词 (数据来源于西柚洞察)')
      - keyword col: first column
      - search_volume col: any header containing '搜索量' — the exact name
        varies across 西柚 exports ('周搜索量', '周平均搜索量', …)
      - competition col: '竞争难度档位' if present (optional)

    鸥鹭 header signature: first column is '流量关键词'
      - keyword col: '流量关键词'
      - search_volume col: '月搜索量'
      - competition col: (derived from '机会指数')

    Robustness: the search-volume column is resolved by substring/known-name
    matching (not a hardcoded name), and a post-parse validation repairs the
    common failure where every ``search_volume`` came out 0 because the volume
    column wasn't recognized (see ``_repair_zero_search_volume``).
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

    def _int(val) -> int:
        try:
            return int(float(str(val).replace(",", "").strip()))
        except (ValueError, TypeError):
            return 0

    # Resolve the weekly/monthly search-volume column robustly. 西柚 exports use
    # different names across versions ('周搜索量' vs '周平均搜索量'), so match
    # known names first, then any header containing '搜索量'. Excludes the CPC /
    # conversion / translation columns from later numeric repair.
    _sv_exclude = {i for i in (translation_idx, cpc_idx, conv_idx) if i is not None}

    def _resolve_sv_col() -> int | None:
        for exact in ("周搜索量", "周平均搜索量", "月搜索量", "月平均搜索量", "搜索量"):
            for idx, name in enumerate(header):
                if name == exact:
                    return idx
        for idx, name in enumerate(header):
            if "搜索量" in name:
                return idx
        return None

    sv_idx = _resolve_sv_col()

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
    kw_idx = 0  # column holding the keyword text; used by the repair pass

    if "西柚" in first_col or "关键词" == first_col.split("(")[0].strip().split("（")[0].strip():
        kw_col = header[0]
        comp_idx = _find_col("竞争难度", "难度档位", "竞争度")
        for row in rows[1:]:
            kw = str(_get(row, kw_col, "")).strip()
            if not kw:
                continue
            results.append({
                "keyword": kw,
                "search_volume": _int(_opt(row, sv_idx, 0)),
                "competition": str(_opt(row, comp_idx, "")).strip(),
                **_source_extras(row),
            })
    elif first_col == "流量关键词":
        kw_idx = col_map.get("流量关键词", 0)
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

    # Post-parse validation + repair. If EVERY search_volume is 0, the volume
    # column almost certainly wasn't recognized (e.g. a 西柚 variant naming it
    # '周平均搜索量'). Find the most search-volume-like numeric column and
    # backfill by row order (results mirror rows[1:] with a non-empty keyword).
    if results and all(int(r.get("search_volume", 0) or 0) == 0 for r in results):
        repair_idx = _best_integer_column(rows, header, _sv_exclude | {kw_idx})
        if repair_idx is not None:
            res_iter = iter(results)
            filled = 0
            for row in rows[1:]:
                kw_cell = row[kw_idx] if kw_idx < len(row) else None
                if not str(kw_cell or "").strip():
                    continue
                entry = next(res_iter, None)
                if entry is None:
                    break
                entry["search_volume"] = _int(row[repair_idx] if repair_idx < len(row) else 0)
                if entry["search_volume"] > 0:
                    filled += 1
            logger.warning(
                "keyword parse: all search_volume=0; repaired from column '%s' (idx=%d), %d/%d rows now non-zero. header=%s",
                header[repair_idx] if repair_idx < len(header) else "?",
                repair_idx, filled, len(results), header,
            )
        else:
            logger.warning(
                "keyword parse: all search_volume=0 and no numeric column to repair from. header=%s",
                header,
            )

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
