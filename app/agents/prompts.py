import json
import os
import re


class PromptRegistry:
    def __init__(self, prompts_dir: str = "prompts"):
        self._dir = prompts_dir

    def render(self, agent_name: str, template_name: str, variables: dict) -> str:
        meta_path = os.path.join(self._dir, agent_name, "meta.json")
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)

        version = (
            meta.get("templates", {}).get(template_name, {}).get("active", "v1")
        )
        tpl_path = os.path.join(self._dir, agent_name, f"{template_name}_{version}.md")
        with open(tpl_path, encoding="utf-8") as f:
            template = f.read()

        def replacer(m: re.Match) -> str:
            key = m.group(1).strip()
            val = variables.get(key, "")
            return val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)

        return re.sub(r"\{\{(.+?)\}\}", replacer, template)

    def get_model(self, agent_name: str, template_name: str) -> str:
        meta_path = os.path.join(self._dir, agent_name, "meta.json")
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        return (
            meta.get("templates", {}).get(template_name, {}).get("model", "gemini-pro")
        )
