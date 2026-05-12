# 亚马逊 Listing 自动化创作系统 — Low Level Design（Agent 架构）

本文档基于 `high_level_design.md` 中的 Agent 架构（MVP 版本），给出每个组件的类/函数级实现设计、LangGraph 图定义、详细接口契约、错误处理策略和测试方案。

---

## 1. 配置模块 (`app/config.py`)

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # LLM
    gemini_api_key: str
    claude_api_key: str
    openai_api_key: str = ""

    llm_retry_max: int = 3
    llm_retry_backoff_base: float = 2.0
    llm_timeout: int = 60

    # ST
    st_max_bytes: int = 249

    # Storage
    artifacts_dir: str = "artifacts/runs"
    checkpoint_db: str = "checkpoints.db"  # LangGraph 内置 checkpoint

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    class Config:
        env_file = ".env"

settings = Settings()
```

---

## 2. Shared Memory (`app/memory/`)

### 2.1 State 定义 (`app/memory/schemas.py`)

LangGraph 的核心是一个 TypedDict 作为 State，所有 Agent 节点读写同一份 State。

```python
from typing import TypedDict, Annotated
from langgraph.graph import add_messages

class ListingState(TypedDict):
    # 输入
    run_id: str
    competitor_asins: list[str]

    # Phase 1: 认知层
    competitor_listings: list[dict]
    review_summary: dict
    rufus_questions: list[str]
    rufus_screenshots: list[str]
    product_attributes_draft: dict
    product_attributes_confidence: float
    product_attributes_notes: str
    approved_product_attributes: dict

    # Phase 2: 语义层
    keyword_library: list[dict]
    classified_keywords: dict

    # Phase 3: 表达层
    draft_listing_v1: dict
    st_v1: list[str]
    draft_listing_v2: dict
    st_v2: list[str]
    final_listing: dict
    st_v3: list[str]
    final_st: list[str]
    word_frequency_report: dict

    # 控制
    status: str                         # running | waiting_human | completed | failed
    pending_action: dict                # 当前需要人工操作的信息
    agent_log: Annotated[list, add_messages]  # 追加式日志
    error: str
```

### 2.2 State 辅助函数 (`app/memory/shared_memory.py`)

```python
import json, os, datetime

class MemoryHelper:
    """封装 State 的常用读写操作。"""

    @staticmethod
    def has(state: dict, key: str) -> bool:
        val = state.get(key)
        if val is None:
            return False
        if isinstance(val, (list, dict, str)) and len(val) == 0:
            return False
        return True

    @staticmethod
    def log_action(agent: str, action: str, **kwargs) -> dict:
        return {
            "agent": agent,
            "action": action,
            "timestamp": datetime.datetime.utcnow().isoformat(),
            **kwargs,
        }

    @staticmethod
    def save_snapshot(state: dict, artifacts_dir: str) -> str:
        """将当前 State 持久化为 JSON 快照。"""
        run_dir = os.path.join(artifacts_dir, state["run_id"])
        os.makedirs(run_dir, exist_ok=True)
        path = os.path.join(run_dir, "memory_snapshot.json")
        serializable = {k: v for k, v in state.items()}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(serializable, f, ensure_ascii=False, indent=2, default=str)
        return path
```

---

## 3. Tool Layer (`app/tools/`)

### 3.1 LLM Tool (`app/tools/llm_tool.py`)

```python
import litellm, json, base64
from tenacity import retry, stop_after_attempt, wait_exponential
from langchain_core.tools import tool

MODEL_MAP = {
    "gemini-pro": "gemini/gemini-1.5-pro",
    "claude-sonnet": "anthropic/claude-sonnet-4-20250514",
    "gpt-4o": "gpt-4o",
}

FALLBACK = {
    "gemini-pro": "gpt-4o",
    "claude-sonnet": "gpt-4o",
}

class LLMTool:
    def __init__(self):
        self.total_tokens = 0

    async def call(
        self,
        model: str,
        prompt: str,
        attachments: list[str] | None = None,
        response_format: str = "json",
    ) -> dict:
        try:
            return await self._invoke(model, prompt, attachments, response_format)
        except Exception:
            fallback = FALLBACK.get(model)
            if fallback:
                return await self._invoke(fallback, prompt, attachments, response_format)
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    async def _invoke(self, model, prompt, attachments, response_format) -> dict:
        messages = self._build_messages(prompt, attachments)
        response = await litellm.acompletion(
            model=MODEL_MAP[model],
            messages=messages,
            timeout=settings.llm_timeout,
            response_format={"type": "json_object"} if response_format == "json" else None,
        )
        content = response.choices[0].message.content
        self.total_tokens += response.usage.total_tokens

        if response_format == "json":
            return json.loads(content)
        return {"text": content}

    def _build_messages(self, prompt, attachments):
        parts = [{"type": "text", "text": prompt}]
        for path in (attachments or []):
            parts.append({
                "type": "image_url",
                "image_url": {"url": self._encode_image(path)},
            })
        return [{"role": "user", "content": parts}]

    def _encode_image(self, path: str) -> str:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        ext = path.rsplit(".", 1)[-1].lower()
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(ext, "image/png")
        return f"data:{mime};base64,{b64}"
```

### 3.2 Keyword Tool (`app/tools/keyword_tool.py`)

```python
import re

class KeywordTool:
    def clean(self, raw_data: list[dict]) -> list[dict]:
        cleaned, seen = [], set()
        for row in raw_data:
            kw = row.get("keyword", "").strip().lower()
            if not kw or kw in seen:
                continue
            seen.add(kw)
            cleaned.append({
                "keyword": kw,
                "search_volume": int(row.get("search_volume", 0)),
                "competition": row.get("competition", ""),
            })
        cleaned.sort(key=lambda x: x["search_volume"], reverse=True)
        return cleaned

    def optimize_st(self, listing: dict, st_v3: list[str], classified_keywords: dict) -> dict:
        listing_text = " ".join([
            listing.get("title", ""),
            " ".join(listing.get("bullet_points", [])),
            listing.get("description", ""),
        ]).lower()
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
                "used_in_listing": len(w_listing & {k["keyword"].lower() for k in all_kw}),
                "added_to_st": len(current_st) - len(w_st_deduped),
                "total_bytes": len(" ".join(current_st).encode("utf-8")),
            },
        }

    def _flatten(self, classified: dict) -> list[dict]:
        result = []
        for entries in classified.values():
            if isinstance(entries, list):
                for e in entries:
                    result.append(e if isinstance(e, dict) else {"keyword": e, "search_volume": 0})
        return result
```

### 3.3 Compliance Tool (`app/tools/compliance_tool.py`)

```python
import re, os, glob

class ComplianceTool:
    FORBIDDEN_WORDS = [
        "best", "cheapest", "#1", "guaranteed", "number one",
        "top rated", "best seller", "free", "bonus", "limited time",
    ]
    MAX_TITLE = 200
    MAX_BULLET = 500

    def load_rules(self, category: str | None = None) -> str:
        rules_dir = "compliance_rules"
        parts = []
        for md in sorted(glob.glob(os.path.join(rules_dir, "**/*.md"), recursive=True)):
            with open(md, "r") as f:
                parts.append(f.read())
        return "\n\n---\n\n".join(parts)

    def validate(self, listing: dict) -> list[str]:
        violations = []
        title = listing.get("title", "")
        bullets = listing.get("bullet_points", [])
        desc = listing.get("description", "")

        if len(title) > self.MAX_TITLE:
            violations.append(f"标题超长: {len(title)} > {self.MAX_TITLE}")
        for i, bp in enumerate(bullets):
            if len(bp) > self.MAX_BULLET:
                violations.append(f"Bullet #{i+1} 超长: {len(bp)} > {self.MAX_BULLET}")

        all_text = f"{title} {' '.join(bullets)} {desc}".lower()
        for word in self.FORBIDDEN_WORDS:
            if re.search(rf"\b{re.escape(word)}\b", all_text):
                violations.append(f"禁用词: \"{word}\"")

        return violations
```

### 3.4 File Store Tool (`app/tools/file_store.py`)

```python
import json, os

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
        with open(jp, "w") as f:
            json.dump({"final_listing": listing, "final_st": st}, f, ensure_ascii=False, indent=2)

        mp = os.path.join(d, "final_listing.md")
        with open(mp, "w") as f:
            f.write(self._listing_to_md(listing, st))

        sp = os.path.join(d, "final_st.json")
        with open(sp, "w") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)

        return {"json": jp, "markdown": mp, "st": sp}

    def _listing_to_md(self, listing: dict, st: list[str]) -> str:
        lines = ["# Amazon Listing\n", "## Title\n", listing.get("title", ""), "\n## Bullet Points\n"]
        for i, bp in enumerate(listing.get("bullet_points", []), 1):
            lines.append(f"{i}. {bp}")
        lines += ["\n## Description\n", listing.get("description", ""), "\n## Search Terms\n", " ".join(st)]
        return "\n".join(lines)
```

---

## 4. Prompt Registry (`app/agents/prompts.py`)

```python
import json, os, re

class PromptRegistry:
    def __init__(self, prompts_dir: str = "prompts"):
        self._dir = prompts_dir

    def render(self, agent_name: str, template_name: str, variables: dict) -> str:
        meta_path = os.path.join(self._dir, agent_name, "meta.json")
        with open(meta_path) as f:
            meta = json.load(f)

        version = meta.get("templates", {}).get(template_name, {}).get("active", "v1")
        tpl_path = os.path.join(self._dir, agent_name, f"{template_name}_{version}.md")
        with open(tpl_path) as f:
            template = f.read()

        def replacer(m):
            key = m.group(1).strip()
            val = variables.get(key, "")
            return val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
        return re.sub(r"\{\{(.+?)\}\}", replacer, template)

    def get_model(self, agent_name: str, template_name: str) -> str:
        meta_path = os.path.join(self._dir, agent_name, "meta.json")
        with open(meta_path) as f:
            meta = json.load(f)
        return meta.get("templates", {}).get(template_name, {}).get("model", "gemini-pro")
```

**Prompt 目录结构**：

```
prompts/
  research/
    meta.json
    rufus_extract_v1.md
  product_analyst/
    meta.json
    info_fusion_v1.md
    self_eval_v1.md
  keyword_strategist/
    meta.json
    classify_v1.md
  copywriter/
    meta.json
    round_1_draft_v1.md
    round_2_rufus_v1.md
    round_3_compliance_v1.md
```

**meta.json 示例** (`prompts/copywriter/meta.json`)：

```json
{
  "templates": {
    "round_1_draft":     { "active": "v1", "model": "gemini-pro" },
    "round_2_rufus":     { "active": "v1", "model": "claude-sonnet" },
    "round_3_compliance":{ "active": "v1", "model": "claude-sonnet" }
  }
}
```

---

## 5. Agent 实现 (`app/agents/`)

### 5.1 工具容器 (`app/agents/base.py`)

```python
from dataclasses import dataclass

@dataclass
class ToolBox:
    llm: LLMTool
    keyword: KeywordTool
    compliance: ComplianceTool
    file_store: FileStoreTool
    prompts: PromptRegistry
```

### 5.2 Research Agent (`app/agents/research.py`)

> MVP 版本：Research Agent 不做自动采集，仅校验用户上传的数据并写入 State。
> 如果用户上传了 Rufus 截图，使用 LLM 多模态提取问题列表。

```python
import time, os

async def research_node(state: ListingState, toolbox: ToolBox) -> dict:
    """LangGraph 节点：校验用户上传的竞品数据，写入 State。
    
    此节点在 interrupt 后执行——用户通过 upload API 将数据注入 State，
    然后 resume graph 时运行本节点做校验和 Rufus 解析。
    """
    logs = []
    t0 = time.time()

    listings = state.get("competitor_listings", [])
    if not listings:
        return {
            "status": "waiting_human",
            "pending_action": {
                "type": "upload_competitor_data",
                "message": "请上传竞品 Listing JSON（含 title, bullet_points 字段）",
            },
            "agent_log": [MemoryHelper.log_action("research", "waiting_upload")],
        }

    # 校验完整性
    for i, item in enumerate(listings):
        if not item.get("title") or not item.get("bullet_points"):
            return {
                "status": "waiting_human",
                "pending_action": {
                    "type": "upload_competitor_data",
                    "message": f"第 {i+1} 条 listing 缺少 title 或 bullet_points，请补充",
                },
                "agent_log": [MemoryHelper.log_action("research", "validation_failed", index=i)],
            }

    logs.append(MemoryHelper.log_action("research", "validate_listings",
                count=len(listings), duration_ms=int((time.time()-t0)*1000)))

    # Rufus 截图 → LLM 多模态提取
    rufus_qs = state.get("rufus_questions", [])
    screenshots = state.get("rufus_screenshots", [])
    for img_path in screenshots:
        if os.path.exists(img_path):
            t1 = time.time()
            prompt = toolbox.prompts.render("research", "rufus_extract",
                {"screenshot_count": str(len(screenshots))})
            result = await toolbox.llm.call("gemini-pro", prompt, attachments=[img_path])
            rufus_qs.extend(result.get("questions", []))
            logs.append(MemoryHelper.log_action("research", "extract_rufus",
                        duration_ms=int((time.time()-t1)*1000)))

    return {
        "competitor_listings": listings,
        "rufus_questions": rufus_qs,
        "status": "running",
        "agent_log": logs,
    }
```

### 5.3 Product Analyst Agent (`app/agents/product_analyst.py`)

```python
async def product_analyst_node(state: ListingState, toolbox: ToolBox) -> dict:
    """LangGraph 节点：融合分析生成属性表。"""
    t0 = time.time()
    attachments = [p for p in state.get("rufus_screenshots", []) if os.path.exists(p)]

    prompt = toolbox.prompts.render("product_analyst", "info_fusion", {
        "competitor_listings": json.dumps(state["competitor_listings"], ensure_ascii=False),
        "review_summary": json.dumps(state.get("review_summary", {}), ensure_ascii=False),
        "rufus_questions": json.dumps(state.get("rufus_questions", []), ensure_ascii=False),
    })

    draft = await toolbox.llm.call("gemini-pro", prompt, attachments=attachments)

    # 自我评估
    eval_prompt = toolbox.prompts.render("product_analyst", "self_eval", {
        "draft": json.dumps(draft, ensure_ascii=False),
    })
    evaluation = await toolbox.llm.call("claude-sonnet", eval_prompt)
    confidence = evaluation.get("confidence", 0.5)
    notes = evaluation.get("notes", "")

    # 如果 confidence 太低，用评估反馈再生成一次
    if confidence < 0.7:
        prompt_v2 = prompt + f"\n\n## 上一轮评估反馈\n{notes}\n请据此改进。"
        draft = await toolbox.llm.call("gemini-pro", prompt_v2, attachments=attachments)
        eval2 = await toolbox.llm.call("claude-sonnet", eval_prompt.replace(
            json.dumps(draft, ensure_ascii=False), json.dumps(draft, ensure_ascii=False)))
        confidence = eval2.get("confidence", confidence)
        notes = eval2.get("notes", notes)

    duration = int((time.time() - t0) * 1000)

    return {
        "product_attributes_draft": draft,
        "product_attributes_confidence": confidence,
        "product_attributes_notes": notes,
        "status": "waiting_human",
        "pending_action": {
            "type": "review_product_attributes",
            "data": draft,
            "confidence": confidence,
            "agent_notes": notes,
        },
        "agent_log": [MemoryHelper.log_action("product_analyst", "generate_attributes",
                      confidence=confidence, duration_ms=duration)],
    }
```

### 5.4 Keyword Strategist Agent (`app/agents/keyword_strategist.py`)

```python
async def keyword_classify_node(state: ListingState, toolbox: ToolBox) -> dict:
    """LangGraph 节点：关键词分类。"""
    t0 = time.time()
    prompt = toolbox.prompts.render("keyword_strategist", "classify", {
        "product_attributes": json.dumps(state["approved_product_attributes"], ensure_ascii=False),
        "keywords": json.dumps(state["keyword_library"], ensure_ascii=False),
    })

    classified = await toolbox.llm.call("claude-sonnet", prompt)

    # 自我评估：每个分类至少 3 个词
    for category, words in classified.items():
        if isinstance(words, list) and len(words) < 3:
            prompt_retry = prompt + f"\n\n注意：「{category}」分类下词太少（{len(words)}个），请补充。"
            classified = await toolbox.llm.call("claude-sonnet", prompt_retry)
            break

    return {
        "classified_keywords": classified,
        "agent_log": [MemoryHelper.log_action("keyword_strategist", "classify",
                      duration_ms=int((time.time()-t0)*1000))],
    }


async def st_optimize_node(state: ListingState, toolbox: ToolBox) -> dict:
    """LangGraph 节点：ST 词频优化（确定性算法）。"""
    t0 = time.time()
    result = toolbox.keyword.optimize_st(
        listing=state["final_listing"],
        st_v3=state.get("st_v3", []),
        classified_keywords=state.get("classified_keywords", {}),
    )

    # 持久化
    toolbox.file_store.write_json(state["run_id"], "final_st.json", result)

    return {
        "final_st": result["final_st"],
        "word_frequency_report": result["word_frequency_report"],
        "agent_log": [MemoryHelper.log_action("keyword_strategist", "optimize_st",
                      duration_ms=int((time.time()-t0)*1000))],
    }
```

### 5.5 Copywriter Agent (`app/agents/copywriter.py`)

```python
async def copywriter_node(state: ListingState, toolbox: ToolBox) -> dict:
    """LangGraph 节点：三轮迭代生成 Listing。"""
    logs = []

    # Round 1: 初稿
    t0 = time.time()
    p1 = toolbox.prompts.render("copywriter", "round_1_draft", {
        "approved_product_attributes": json.dumps(state["approved_product_attributes"], ensure_ascii=False),
        "classified_keywords": json.dumps(state["classified_keywords"], ensure_ascii=False),
    })
    v1 = await toolbox.llm.call("gemini-pro", p1)
    logs.append(MemoryHelper.log_action("copywriter", "round_1_draft",
                model="gemini-pro", duration_ms=int((time.time()-t0)*1000)))

    # Round 2: Rufus 优化
    t0 = time.time()
    p2 = toolbox.prompts.render("copywriter", "round_2_rufus", {
        "draft_v1": json.dumps(v1, ensure_ascii=False),
        "product_attributes": json.dumps(state["approved_product_attributes"], ensure_ascii=False),
        "rufus_questions": json.dumps(state.get("rufus_questions", []), ensure_ascii=False),
    })
    attachments = [p for p in state.get("rufus_screenshots", []) if os.path.exists(p)]
    v2 = await toolbox.llm.call("claude-sonnet", p2, attachments=attachments)
    logs.append(MemoryHelper.log_action("copywriter", "round_2_rufus",
                model="claude-sonnet", duration_ms=int((time.time()-t0)*1000)))

    # Round 3: 合规校正（含重试循环）
    rules_text = toolbox.compliance.load_rules()
    violations_ctx = ""
    final = None
    MAX_RETRIES = 2

    for attempt in range(MAX_RETRIES + 1):
        t0 = time.time()
        p3 = toolbox.prompts.render("copywriter", "round_3_compliance", {
            "draft_v2": json.dumps(v2, ensure_ascii=False),
            "product_attributes": json.dumps(state["approved_product_attributes"], ensure_ascii=False),
            "compliance_rules": rules_text,
            "previous_violations": violations_ctx,
        })
        v3 = await toolbox.llm.call("claude-sonnet", p3)

        listing_for_check = {
            "title": v3.get("title", ""),
            "bullet_points": v3.get("bullet_points", []),
            "description": v3.get("description", ""),
        }
        violations = toolbox.compliance.validate(listing_for_check)

        logs.append(MemoryHelper.log_action("copywriter", "round_3_compliance",
                    attempt=attempt, violations=len(violations),
                    duration_ms=int((time.time()-t0)*1000)))

        if not violations:
            final = v3
            break

        violations_ctx = "上一次违规：\n" + "\n".join(f"- {v}" for v in violations)

    if final is None:
        final = v3  # 超过重试次数仍用最后一版

    listing = {
        "title": final["title"],
        "bullet_points": final["bullet_points"],
        "description": final["description"],
    }

    # 自我评估：关键词覆盖率
    kw_all = set()
    for words in state.get("classified_keywords", {}).values():
        if isinstance(words, list):
            for w in words:
                kw_all.add(w.lower() if isinstance(w, str) else w.get("keyword", "").lower())
    listing_text = f"{listing['title']} {' '.join(listing['bullet_points'])} {listing['description']}".lower()
    covered = sum(1 for kw in kw_all if kw in listing_text)
    coverage = covered / len(kw_all) if kw_all else 0
    logs.append(MemoryHelper.log_action("copywriter", "self_eval",
                keyword_coverage=f"{coverage:.0%}"))

    return {
        "draft_listing_v1": v1,
        "st_v1": v1.get("search_terms", []),
        "draft_listing_v2": v2,
        "st_v2": v2.get("search_terms", []),
        "final_listing": listing,
        "st_v3": final.get("search_terms", []),
        "agent_log": logs,
    }


```

---

## 6. Orchestrator — LangGraph 图定义 (`app/agents/orchestrator.py`)

```python
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver

def build_graph(toolbox: ToolBox) -> StateGraph:
    graph = StateGraph(ListingState)

    # --- 注册节点 ---
    graph.add_node("research",          lambda s: research_node(s, toolbox))
    graph.add_node("product_analyst",   lambda s: product_analyst_node(s, toolbox))
    graph.add_node("human_review",      _human_review_passthrough)
    graph.add_node("keyword_upload",    _keyword_upload_passthrough)
    graph.add_node("keyword_classify",  lambda s: keyword_classify_node(s, toolbox))
    graph.add_node("copywriter",        lambda s: copywriter_node(s, toolbox))
    graph.add_node("st_optimize",       lambda s: st_optimize_node(s, toolbox))
    graph.add_node("export",            lambda s: _export_node(s, toolbox))

    # --- 入口 ---
    graph.set_entry_point("research")

    # --- 边（转移条件） ---
    graph.add_edge("research", "product_analyst")

    graph.add_conditional_edges("product_analyst", _after_analyst, {
        "human_review": "human_review",
        "keyword_classify": "keyword_classify",
    })

    # human_review 是人工卡点，LangGraph 用 interrupt 暂停
    graph.add_conditional_edges("human_review", _after_human_review, {
        "wait_keyword": "keyword_upload",
        "keyword_classify": "keyword_classify",
    })

    graph.add_edge("keyword_upload", "keyword_classify")
    graph.add_edge("keyword_classify", "copywriter")
    graph.add_edge("copywriter", "st_optimize")
    graph.add_edge("st_optimize", "export")
    graph.add_edge("export", END)

    return graph


# --- 条件路由函数 ---

def _after_analyst(state: ListingState) -> str:
    """属性表生成后，始终进入人工审核。"""
    return "human_review"

def _after_human_review(state: ListingState) -> str:
    """人工审核通过后，检查是否已有关键词库。"""
    if MemoryHelper.has(state, "keyword_library"):
        return "keyword_classify"
    return "wait_keyword"

def _human_review_passthrough(state: ListingState) -> dict:
    """占位节点，LangGraph 在此处 interrupt，等待人工提交。"""
    return {}

def _keyword_upload_passthrough(state: ListingState) -> dict:
    """占位节点，等待用户上传关键词。"""
    return {"status": "waiting_human", "pending_action": {"type": "upload_keywords"}}

def _export_node(state: ListingState, toolbox: ToolBox) -> dict:
    paths = toolbox.file_store.export_final(
        state["run_id"], state["final_listing"], state["final_st"],
    )
    return {
        "status": "completed",
        "agent_log": [MemoryHelper.log_action("orchestrator", "export", files=paths)],
    }


# --- 构建可运行实例 ---

def create_app_graph(toolbox: ToolBox):
    graph = build_graph(toolbox)
    checkpointer = SqliteSaver.from_conn_string(settings.checkpoint_db)

    compiled = graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_review", "keyword_upload"],  # 人工卡点
    )
    return compiled
```

---

## 7. API 路由 (`app/api/routes.py`)

> MVP 不含 `list_runs` 和 `chat` 接口。所有状态通过 LangGraph checkpoint 管理，无需自建数据库。

```python
from fastapi import APIRouter, HTTPException, UploadFile, File
import asyncio, json, uuid, datetime

router = APIRouter(prefix="/api")

@router.post("/runs", status_code=201)
async def create_run(req: CreateRunRequest):
    if not req.competitor_asins or len(req.competitor_asins) > 10:
        raise HTTPException(400, "需要 1~10 个 ASIN")

    run_id = f"run_{datetime.date.today():%Y%m%d}_{uuid.uuid4().hex[:6]}"
    thread_id = run_id
    initial_state = {
        "run_id": run_id,
        "competitor_asins": req.competitor_asins,
        "status": "running",
    }

    asyncio.create_task(_run_graph(thread_id, initial_state))
    return {"run_id": run_id, "status": "running"}


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    config = {"configurable": {"thread_id": run_id}}
    state = app_graph.get_state(config)
    if not state or not state.values:
        raise HTTPException(404, "Run not found")

    snapshot = state.values
    return {
        "run_id": run_id,
        "status": snapshot.get("status", "unknown"),
        "memory_snapshot": {
            key: MemoryHelper.has(snapshot, key)
            for key in ["competitor_listings", "review_summary", "approved_product_attributes",
                        "classified_keywords", "final_listing", "final_st"]
        },
        "pending_action": snapshot.get("pending_action"),
        "agent_log": snapshot.get("agent_log", [])[-20:],
    }


@router.put("/runs/{run_id}/review")
async def submit_review(run_id: str, req: SubmitReviewRequest):
    config = {"configurable": {"thread_id": run_id}}
    update = {"approved_product_attributes": req.approved_data, "status": "running", "pending_action": {}}
    await app_graph.aupdate_state(config, update)
    asyncio.create_task(_resume_graph(run_id))
    return {"status": "accepted"}


@router.put("/runs/{run_id}/upload")
async def upload_data(run_id: str, file: UploadFile = File(...), data_type: str = "auto"):
    config = {"configurable": {"thread_id": run_id}}
    content = await file.read()

    if file.filename.endswith(".json"):
        data = json.loads(content)
        if data_type == "keywords" or (data_type == "auto" and "keyword" in str(data)[:200]):
            cleaned = toolbox.keyword.clean(data)
            update = {"keyword_library": cleaned, "status": "running", "pending_action": {}}
        else:
            update = {"competitor_listings": data, "status": "running", "pending_action": {}}
        await app_graph.aupdate_state(config, update)
        asyncio.create_task(_resume_graph(run_id))
    elif file.filename.lower().endswith((".png", ".jpg", ".jpeg")):
        save_path = toolbox.file_store.run_dir(run_id) + f"/{file.filename}"
        with open(save_path, "wb") as f:
            f.write(content)
        state = app_graph.get_state(config)
        existing = state.values.get("rufus_screenshots", []) if state else []
        existing.append(save_path)
        await app_graph.aupdate_state(config, {"rufus_screenshots": existing})
        return {"status": "accepted", "saved": save_path}
    else:
        raise HTTPException(400, "支持 .json / .png / .jpg 文件")

    return {"status": "accepted"}


@router.get("/runs/{run_id}/final")
async def get_final(run_id: str):
    config = {"configurable": {"thread_id": run_id}}
    state = app_graph.get_state(config)
    if not state or not state.values:
        raise HTTPException(404)
    s = state.values
    if s.get("status") != "completed":
        raise HTTPException(400, f"Run 未完成: {s.get('status')}")
    return {
        "final_listing": s["final_listing"],
        "final_st": s["final_st"],
        "word_frequency_report": s.get("word_frequency_report", {}),
        "download": {
            "json": f"/artifacts/{run_id}/final/final_listing.json",
            "markdown": f"/artifacts/{run_id}/final/final_listing.md",
        },
    }


# --- 辅助 ---

async def _run_graph(thread_id: str, initial_state: dict):
    await app_graph.ainvoke(initial_state, {"configurable": {"thread_id": thread_id}})

async def _resume_graph(thread_id: str):
    await app_graph.ainvoke(None, {"configurable": {"thread_id": thread_id}})
```

---

## 8. FastAPI 入口 (`app/main.py`)

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    toolbox = ToolBox(
        llm=LLMTool(),
        keyword=KeywordTool(),
        compliance=ComplianceTool(),
        file_store=FileStoreTool(settings.artifacts_dir),
        prompts=PromptRegistry(),
    )

    app.state.toolbox = toolbox
    app.state.graph = create_app_graph(toolbox)

    yield

app = FastAPI(title="Eco Listing Agent", version="0.2.0-mvp", lifespan=lifespan)
app.include_router(router)
app.mount("/artifacts", StaticFiles(directory=settings.artifacts_dir), name="artifacts")
```

---

## 9. CLI 入口 (`run.py`)

```python
import argparse, asyncio, json, uuid, datetime

def _init_toolbox() -> ToolBox:
    return ToolBox(
        llm=LLMTool(),
        keyword=KeywordTool(),
        compliance=ComplianceTool(),
        file_store=FileStoreTool(settings.artifacts_dir),
        prompts=PromptRegistry(),
    )

async def main():
    parser = argparse.ArgumentParser(description="Eco Listing Agent CLI")
    sub = parser.add_subparsers(dest="cmd")

    rp = sub.add_parser("run"); rp.add_argument("--asins", required=True, help="逗号分隔的竞品 ASIN")
    sp = sub.add_parser("status"); sp.add_argument("--run-id", required=True)
    rv = sub.add_parser("review"); rv.add_argument("--run-id", required=True); rv.add_argument("--file", required=True)
    up = sub.add_parser("upload"); up.add_argument("--run-id", required=True); up.add_argument("--file", required=True)
    up.add_argument("--type", choices=["listings", "keywords", "screenshot"], default="listings")

    args = parser.parse_args()
    toolbox = _init_toolbox()
    graph = create_app_graph(toolbox)

    if args.cmd == "run":
        asins = [a.strip() for a in args.asins.split(",")]
        run_id = f"run_{datetime.date.today():%Y%m%d}_{uuid.uuid4().hex[:6]}"
        state = {"run_id": run_id, "competitor_asins": asins, "status": "running"}
        print(f"Starting run: {run_id}")
        result = await graph.ainvoke(state, {"configurable": {"thread_id": run_id}})
        print(f"Status: {result.get('status')}")
        if result.get("pending_action"):
            print(f"Pending: {json.dumps(result['pending_action'], ensure_ascii=False, indent=2)}")

    elif args.cmd == "status":
        s = graph.get_state({"configurable": {"thread_id": args.run_id}})
        print(json.dumps({
            "status": s.values.get("status"),
            "pending_action": s.values.get("pending_action"),
            "progress": {k: MemoryHelper.has(s.values, k) for k in
                ["competitor_listings", "approved_product_attributes",
                 "classified_keywords", "final_listing", "final_st"]},
        }, ensure_ascii=False, indent=2))

    elif args.cmd == "review":
        with open(args.file) as f:
            data = json.load(f)
        await graph.aupdate_state({"configurable": {"thread_id": args.run_id}},
            {"approved_product_attributes": data, "status": "running", "pending_action": {}})
        result = await graph.ainvoke(None, {"configurable": {"thread_id": args.run_id}})
        print(f"Status: {result.get('status')}")

    elif args.cmd == "upload":
        config = {"configurable": {"thread_id": args.run_id}}
        with open(args.file, "rb") as f:
            content = f.read()
        if args.type == "keywords":
            data = json.loads(content)
            cleaned = toolbox.keyword.clean(data)
            await graph.aupdate_state(config, {"keyword_library": cleaned, "status": "running", "pending_action": {}})
        elif args.type == "screenshot":
            save_path = f"{toolbox.file_store.run_dir(args.run_id)}/{args.file.split('/')[-1]}"
            with open(save_path, "wb") as out:
                out.write(content)
            s = graph.get_state(config)
            existing = s.values.get("rufus_screenshots", []) if s else []
            existing.append(save_path)
            await graph.aupdate_state(config, {"rufus_screenshots": existing})
        else:
            data = json.loads(content)
            await graph.aupdate_state(config, {"competitor_listings": data, "status": "running", "pending_action": {}})
        result = await graph.ainvoke(None, config)
        print(f"Status: {result.get('status')}")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 10. 错误处理

### 10.1 异常层级

```python
class EcoListingError(Exception): pass
class AgentError(EcoListingError):
    def __init__(self, agent: str, action: str, message: str):
        self.agent = agent
        self.action = action
        super().__init__(f"[{agent}.{action}] {message}")
class LLMError(EcoListingError): pass
class ComplianceError(EcoListingError): pass
```

### 10.2 Agent 内部错误策略

| Agent | 场景 | 策略 |
|-------|------|------|
| Research | 上传数据缺少必要字段 | 返回 `waiting_human`，提示补充 |
| Research | Rufus 截图 LLM 解析失败 | 跳过（非致命，后续 Round 2 无 Rufus 输入） |
| Product Analyst | LLM 返回非 JSON | 重试 1 次 |
| Product Analyst | confidence < 0.7 | 用评估反馈重新生成 1 次 |
| Keyword Strategist | 分类结果某类 < 3 词 | 补充 prompt 重试 1 次 |
| Copywriter | 合规后置校验失败 | 附带违规信息重试，最多 2 次 |
| Copywriter | LLM 超时 | 指数退避 3 次（LLM Tool 层处理） |

### 10.3 FastAPI 全局异常

```python
@app.exception_handler(EcoListingError)
async def handle_error(req, exc):
    return JSONResponse(500, {"error": type(exc).__name__, "message": str(exc)})
```

---

## 11. 测试方案

### 11.1 测试结构

```
tests/
  conftest.py                     ← Mock ToolBox, temp dirs
  test_graph/
    test_full_flow.py             ← 端到端：上传数据 → final_listing
    test_human_interrupt.py       ← 人工卡点暂停/恢复
    test_upload_flow.py           ← 上传竞品 + 关键词 → 恢复
  test_agents/
    test_research.py              ← 数据校验 + Rufus 解析
    test_product_analyst.py       ← 融合分析 + 自我评估
    test_keyword_strategist.py    ← 分类 + ST 优化
    test_copywriter.py            ← 三轮迭代 + 合规重试
  test_tools/
    test_llm_tool.py              ← 重试/降级/schema
    test_keyword_tool.py          ← 清洗 + ST 算法
    test_compliance_tool.py       ← 禁用词/长度
  test_api/
    test_routes.py                ← API 端到端
```

### 11.2 核心测试用例

| 测试 | 验证 |
|------|------|
| `test_full_happy_path` | 上传数据 → analyst → review → classify → copywriter → st → export |
| `test_interrupt_at_review` | graph 在 human_review 节点暂停，state 持久化到 checkpoint |
| `test_resume_after_review` | update_state 后 resume，graph 继续到 keyword_classify |
| `test_research_validation` | 上传缺少 title 的 listing → 返回 waiting_human |
| `test_copywriter_compliance_retry` | 第一次有违规 → 第二次通过 |
| `test_st_byte_limit` | final_st 总字节 ≤ 249 |
| `test_upload_keywords_resume` | 上传关键词 JSON → graph 自动 resume 进入分类 |

### 11.3 Mock 策略

```python
@pytest.fixture
def mock_toolbox(tmp_path):
    llm = LLMTool()
    llm._invoke = AsyncMock(return_value={
        "title": "Test Title", "bullet_points": ["P1","P2","P3","P4","P5"],
        "description": "Desc", "search_terms": ["kw1","kw2"],
        "target_users": ["user1"], "use_cases": ["case1"],
        "pain_points": ["pain1"], "core_features": ["feat1"],
        "selling_points": ["sell1"], "language_patterns": ["lang1"],
        "confidence": 0.85, "notes": "Good",
    })

    return ToolBox(
        llm=llm,
        keyword=KeywordTool(), compliance=ComplianceTool(),
        file_store=FileStoreTool(str(tmp_path)),
        prompts=PromptRegistry("tests/fixtures/prompts"),
    )
```

---

## 12. 依赖清单 (`requirements.txt`)

```
fastapi>=0.110
uvicorn>=0.27
pydantic>=2.6
pydantic-settings>=2.1
langgraph>=0.2
langchain-core>=0.3
litellm>=1.30
python-dotenv>=1.0
tenacity>=8.2
python-multipart>=0.0.9
pytest>=8.0
pytest-asyncio>=0.23
httpx>=0.27
```

---

## 13. 启动与部署

```bash
pip install -r requirements.txt
cp .env.example .env   # 填入 GEMINI_API_KEY, CLAUDE_API_KEY

# Web 服务
uvicorn app.main:app --reload --port 8000

# CLI 示例
python run.py run --asins B0XXXXXX,B0YYYYYY
python run.py upload --run-id run_20260325_xxx --file competitor_data.json --type listings
python run.py upload --run-id run_20260325_xxx --file keywords.json --type keywords
python run.py status --run-id run_20260325_xxx
python run.py review --run-id run_20260325_xxx --file reviewed_attrs.json
```
