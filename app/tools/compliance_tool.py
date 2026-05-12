from __future__ import annotations

import glob
import os
import re


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

    def validate(self, listing: dict) -> list[str]:
        violations: list[str] = []
        title = listing.get("title", "")
        bullets = listing.get("bullet_points", [])
        desc = listing.get("description", "")

        if len(title) > self.MAX_TITLE:
            violations.append(f"标题超长: {len(title)} > {self.MAX_TITLE}")
        for i, bp in enumerate(bullets):
            if len(bp) > self.MAX_BULLET:
                violations.append(f"Bullet #{i + 1} 超长: {len(bp)} > {self.MAX_BULLET}")

        all_text = f"{title} {' '.join(bullets)} {desc}".lower()
        for word in self.FORBIDDEN_WORDS:
            if re.search(rf"\b{re.escape(word)}\b", all_text):
                violations.append(f'禁用词: "{word}"')

        return violations
