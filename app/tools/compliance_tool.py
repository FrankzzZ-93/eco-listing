from __future__ import annotations

import glob
import os
import re

from app.tools.keyword_tool import ASIN_RE


class ComplianceTool:
    FORBIDDEN_WORDS = [
        "best",
        "cheapest",
        "#1",
        "guaranteed",
        "number one",
        "top rated",
        "best seller",
        "free",
        "bonus",
        "limited time",
    ]
    MAX_TITLE = 200
    MAX_BULLET = 500
    MAX_BULLETS_TOTAL_BYTES = 1000
    MAX_DESCRIPTION = 2000
    MAX_ST_BYTES = 249
    # Soft minimums (encourage fuller content; never block a run).
    MIN_TITLE = 120
    MIN_BULLETS_TOTAL_BYTES = 700
    MIN_DESCRIPTION = 1500

    def __init__(self, rules_dir: str = "compliance_rules"):
        self._rules_dir = rules_dir

    def load_rules(self, category: str | None = None) -> str:
        parts: list[str] = []
        for md in sorted(
            glob.glob(os.path.join(self._rules_dir, "**/*.md"), recursive=True)
        ):
            with open(md, "r", encoding="utf-8") as f:
                parts.append(f.read())
        return "\n\n---\n\n".join(parts)

    def validate(self, listing: dict, limits: dict | None = None) -> list[str]:
        limits = limits or {}
        max_title = limits.get("title_max_chars", self.MAX_TITLE)
        max_bullet = limits.get("bullet_max_chars", self.MAX_BULLET)
        max_bullets_total = limits.get(
            "bullets_total_max_bytes", self.MAX_BULLETS_TOTAL_BYTES
        )
        max_desc = limits.get("description_max_chars", self.MAX_DESCRIPTION)
        max_st_bytes = limits.get("st_max_bytes", self.MAX_ST_BYTES)
        min_title = limits.get("title_min_chars", self.MIN_TITLE)
        min_bullets_total = limits.get(
            "bullets_total_min_bytes", self.MIN_BULLETS_TOTAL_BYTES
        )
        min_desc = limits.get("description_min_chars", self.MIN_DESCRIPTION)

        violations: list[str] = []
        title = listing.get("title", "")
        bullets = listing.get("bullet_points", [])
        desc = listing.get("description", "")
        search_terms = listing.get("search_terms", [])

        if len(title) > max_title:
            violations.append(f"标题超长: {len(title)} > {max_title} 字符")
        elif len(title) < min_title:
            violations.append(
                f"标题过短: {len(title)} < {min_title} 字符（请丰富标题至接近上限 {max_title}）"
            )
        for i, bp in enumerate(bullets):
            if len(bp) > max_bullet:
                violations.append(f"Bullet #{i + 1} 超长: {len(bp)} > {max_bullet} 字符")
        # Total bullets byte budget (binding UI constraint). Match the UI's
        # measurement: join the five bullets with newlines, count UTF-8 bytes.
        bullets_bytes = len("\n".join(str(b) for b in bullets).encode("utf-8"))
        if bullets_bytes > max_bullets_total:
            violations.append(
                f"五点描述总长超限: {bullets_bytes} > {max_bullets_total} 字节"
                f"（需精简五点，使合计不超过 {max_bullets_total} 字节）"
            )
        elif bullets_bytes < min_bullets_total:
            violations.append(
                f"五点描述过短: {bullets_bytes} < {min_bullets_total} 字节"
                f"（请充实五点内容，使合计接近上限 {max_bullets_total} 字节）"
            )
        if len(desc) > max_desc:
            violations.append(f"Description 超长: {len(desc)} > {max_desc} 字符")
        elif len(desc) < min_desc:
            violations.append(
                f"Description 过短: {len(desc)} < {min_desc} 字符"
                f"（请扩充描述至接近上限 {max_desc} 字符）"
            )

        if isinstance(search_terms, list):
            st_str = " ".join(str(w) for w in search_terms)
        else:
            st_str = str(search_terms)
        st_bytes = len(st_str.encode("utf-8"))
        if st_bytes > max_st_bytes:
            violations.append(f"Search Terms 超长: {st_bytes} > {max_st_bytes} bytes")

        all_text = f"{title} {' '.join(bullets)} {desc} {st_str}"
        for word in self.FORBIDDEN_WORDS:
            if re.search(rf"\b{re.escape(word)}\b", all_text.lower()):
                violations.append(f'禁用词: "{word}"')

        asin_hits = sorted(set(ASIN_RE.findall(all_text)))
        for hit in asin_hits:
            violations.append(f"ASIN 字符串不应出现在 Listing 中: {hit}")

        return violations
