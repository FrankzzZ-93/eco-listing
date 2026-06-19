import json
import os

from app.config import settings


def to_artifact_url(image_path: str) -> str:
    """Map an on-disk path under ``artifacts_dir`` to its ``/artifacts`` URL.

    Single source of truth shared by the research node and the account-session
    manager (both surface captcha screenshots to the frontend).
    """
    if not image_path:
        return ""
    try:
        rel = os.path.relpath(image_path, settings.artifacts_dir)
        return f"/artifacts/{rel}"
    except ValueError:
        return ""


class FileStoreTool:
    def __init__(self, base_dir: str):
        self._base = base_dir

    def run_dir(self, run_id: str) -> str:
        d = os.path.join(self._base, run_id)
        os.makedirs(d, exist_ok=True)
        return d

    def write_json(self, run_id: str, filename: str, data) -> str:
        path = os.path.join(self.run_dir(run_id), filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return path

    def read_json(self, run_id: str, filename: str) -> dict:
        path = os.path.join(self.run_dir(run_id), filename)
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def write_text(self, run_id: str, filename: str, content: str) -> str:
        path = os.path.join(self.run_dir(run_id), filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def export_final(self, run_id: str, listing: dict, st: list[str]) -> dict:
        d = os.path.join(self.run_dir(run_id), "final")
        os.makedirs(d, exist_ok=True)

        jp = os.path.join(d, "final_listing.json")
        with open(jp, "w", encoding="utf-8") as f:
            json.dump(
                {"final_listing": listing, "final_st": st},
                f,
                ensure_ascii=False,
                indent=2,
            )

        mp = os.path.join(d, "final_listing.md")
        with open(mp, "w", encoding="utf-8") as f:
            f.write(self._listing_to_md(listing, st))

        sp = os.path.join(d, "final_st.json")
        with open(sp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)

        return {"json": jp, "markdown": mp, "st": sp}

    @staticmethod
    def _listing_to_md(listing: dict, st: list[str]) -> str:
        lines = [
            "# Amazon Listing\n",
            "## Title\n",
            listing.get("title", ""),
            "\n## Bullet Points\n",
        ]
        for i, bp in enumerate(listing.get("bullet_points", []), 1):
            lines.append(f"{i}. {bp}")
        lines += [
            "\n## Description\n",
            listing.get("description", ""),
            "\n## Search Terms\n",
            " ".join(st),
        ]
        return "\n".join(lines)
