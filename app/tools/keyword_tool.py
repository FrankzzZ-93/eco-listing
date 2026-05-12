from __future__ import annotations

import re

from app.config import settings


class KeywordTool:
    def clean(self, raw_data: list[dict]) -> list[dict]:
        cleaned: list[dict] = []
        seen: set[str] = set()
        for row in raw_data:
            kw = row.get("keyword", "").strip().lower()
            if not kw or kw in seen:
                continue
            seen.add(kw)
            cleaned.append(
                {
                    "keyword": kw,
                    "search_volume": int(row.get("search_volume", 0)),
                    "competition": row.get("competition", ""),
                }
            )
        cleaned.sort(key=lambda x: x["search_volume"], reverse=True)
        return cleaned

    def optimize_st(
        self,
        listing: dict,
        st_v3: list[str],
        classified_keywords: dict,
    ) -> dict:
        listing_text = " ".join(
            [
                listing.get("title", ""),
                " ".join(listing.get("bullet_points", [])),
                listing.get("description", ""),
            ]
        ).lower()
        w_listing = set(re.findall(r"[a-zA-Z0-9]+", listing_text))

        w_st = [w.lower().strip() for w in st_v3 if w.strip()]
        w_st_deduped = [w for w in w_st if w not in w_listing]

        all_kw = self._flatten(classified_keywords)
        covered = w_listing | set(w_st_deduped)
        supplement = [kw for kw in all_kw if kw["keyword"].lower() not in covered]
        supplement.sort(key=lambda x: x["search_volume"], reverse=True)

        current_st = list(w_st_deduped)
        current_bytes = len(" ".join(current_st).encode("utf-8"))

        for kw in supplement:
            word = kw["keyword"].lower()
            added = len(word.encode("utf-8")) + (1 if current_st else 0)
            if current_bytes + added > settings.st_max_bytes:
                continue
            current_st.append(word)
            current_bytes += added

        return {
            "final_st": current_st,
            "word_frequency_report": {
                "total_keywords": len(all_kw),
                "used_in_listing": len(
                    w_listing & {k["keyword"].lower() for k in all_kw}
                ),
                "added_to_st": len(current_st) - len(w_st_deduped),
                "total_bytes": len(" ".join(current_st).encode("utf-8")),
            },
        }

    @staticmethod
    def _flatten(classified: dict) -> list[dict]:
        result: list[dict] = []
        for entries in classified.values():
            if isinstance(entries, list):
                for e in entries:
                    result.append(
                        e
                        if isinstance(e, dict)
                        else {"keyword": e, "search_volume": 0}
                    )
        return result
