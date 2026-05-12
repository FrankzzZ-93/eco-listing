# 亚马逊 Listing 自动化创作系统 — High Level Design（Agent 架构）

## 1. 系统定位

将当前跨越 6 个工具的 12 步手动操作，重构为一套 **多 Agent 协作系统**。由 Orchestrator Agent 统一调度 5 个专业 Agent，每个 Agent 拥有独立的工具集、推理能力和自我纠错机制。用户仅需输入本品 ASIN、竞品 ASIN 列表和关键词词库，系统通过 Browser Tool 自动采集竞品前台数据（五点描述、Rufus 问答、评论），Agent 自主完成产品建模、关键词策略、文案撰写、合规审查和 ST 优化，在关键节点请求人工确认。

### 对比旧 Pipeline 架构

| 维度 | Pipeline 架构 | Agent 架构 |
|------|-------------|-----------|
| 执行方式 | 固定 12 步顺序/并行 | Agent 自主规划，按目标动态决策 |
| 错误处理 | 重试同一逻辑 N 次 | Agent 判断失败原因，切换策略重试 |
| 步骤间通信 | JSON 文件传递 | 共享上下文（Memory），Agent 按需读取 |
| 人工介入 | 固定卡点（Step 5/6） | Agent 主动判断何时需要人工确认 |
| 扩展性 | 新增步骤需改编排逻辑 | 新增 Agent 或 Tool，Orchestrator 自动编排 |

---

## 2. 系统架构总览

```
┌──────────────────────────────────────────────────────────────────────┐
│                           Web / CLI                                  │
│            用户交互：输入 ASIN、上传词库、审核属性表、下载产物              │
└─────────────────────────┬────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    Orchestrator Agent                                │
│                                                                      │
│   职责：任务拆解 → 分发给专业 Agent → 收集结果 → 判断下一步            │
│   能力：理解用户意图、管理 Agent 间依赖、请求人工审核                    │
│                                                                      │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐            │
│   │ Research │  │ Product  │  │ Keyword  │  │Copywriter│            │
│   │  Agent   │  │ Analyst  │  │Strategist│  │  Agent   │            │
│   │          │  │  Agent   │  │  Agent   │  │          │            │
│   └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘            │
│        │             │             │              │                   │
│   ┌────┴─────────────┴─────────────┴──────────────┴──────┐           │
│   │                  Shared Memory                        │           │
│   │  (所有 Agent 共享的上下文：产物、状态、对话历史)         │           │
│   └──────────────────────────────────────────────────────┘           │
└──────────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────────┐
│                         Tool Layer                                   │
│                                                                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │   LLM    │ │ Browser  │ │  File    │ │ Keyword  │ │Compliance│ │
│  │   Tool   │ │  Tool    │ │  Store   │ │  Tool    │ │  Tool    │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. 核心概念

### 3.1 Agent 定义

每个 Agent 是一个拥有以下能力的自治单元：

```
Agent
  ├── Goal（目标）：明确的任务目标
  ├── Tools（工具）：可调用的外部能力
  ├── Memory Access（记忆访问）：读写 Shared Memory
  ├── Reasoning（推理）：基于 LLM 的思考与决策
  └── Self-Correction（自纠错）：评估自身输出，发现问题时切换策略
```

### 3.2 Shared Memory（共享上下文）

所有 Agent 共享一个结构化的上下文存储，替代旧架构中 Step 间的 JSON 传递：

```json
{
  "run_id": "run_20260325_001",
  "input": {
    "product_asin": "B0GLNVMXB8",
    "competitor_asins": ["B0XXXXXX", "B0YYYYYY"],
    "site": "amazon.com.au"
  },
  "context": {
    "competitor_listings": [],
    "review_summary": {},
    "rufus_questions": [],
    "product_attributes_draft": {},
    "approved_product_attributes": {},
    "keyword_library": [],
    "classified_keywords": {},
    "draft_listing_v1": {},
    "draft_listing_v2": {},
    "final_listing": {},
    "final_st": []
  },
  "agent_log": [],
  "human_interactions": [],
  "status": "running"
}
```

**优势**：
- Agent 按需读取所需上下文，不需要显式声明依赖
- Orchestrator 根据 Memory 中已有数据判断哪些 Agent 可以启动
- 任意 Agent 产出新数据后，其他 Agent 立即可见

### 3.3 Tool（工具）

Agent 不直接实现底层能力，而是通过调用 Tool 完成具体操作：

| Tool | 功能 | 被哪些 Agent 使用 |
|------|------|------------------|
| **LLM Tool** | 统一调用 Gemini / Claude / OpenAI（支持多模态） | 所有 Agent |
| **Browser Tool** | Playwright 驱动，自动采集 Amazon 商品页数据（Listing/Rufus/评论） | Research Agent |
| **File Store Tool** | 读写 Shared Memory 中的产物文件 | 所有 Agent |
| **Keyword Tool** | 关键词清洗、去重、词频统计、字节计算 | Keyword Strategist Agent |
| **Compliance Tool** | 禁用词检测、长度校验、合规规则查询 | Copywriter Agent |

---

## 4. Agent 详细设计

### 4.1 Orchestrator Agent（编排 Agent）

**角色**：整个系统的"大脑"，不执行具体业务逻辑，只负责调度和决策。

**核心行为**：

```
1. 接收用户输入（ASIN 列表）
2. 规划执行路径：
   - 判断当前 Memory 状态
   - 决定下一步需要哪个/哪些 Agent
   - 支持并行分发（Research + Keyword Strategist 可同时工作）
3. 分发任务给专业 Agent
4. 收集 Agent 结果，写入 Shared Memory
5. 判断是否需要人工审核
6. 循环直到所有目标完成
```

**调度逻辑（非固定步骤，基于 Memory 状态推断）**：

```
IF memory 缺少竞品数据:
    → 启动 Research Agent（自动采集竞品 Listing / Rufus / 评论）

IF memory 缺少分类词库 AND 有 keyword_library:
    → 启动 Keyword Strategist Agent（分类阶段）
    （可与 Research Agent 并行执行）

IF memory 有竞品数据 BUT 缺少产品属性表:
    → 启动 Product Analyst Agent

IF memory 有属性表草稿 BUT 未经人工审核:
    → 请求人工审核

IF memory 有审核后属性表 AND 有分类词库 BUT 缺少 Listing:
    → 启动 Copywriter Agent

IF memory 有 final_listing BUT 缺少优化后 ST:
    → 启动 Keyword Strategist Agent（ST 优化阶段）

IF memory 有 final_listing AND final_st:
    → 完成，生成交付包
```

**与旧 Pipeline 的本质区别**：不是按固定的 Step 1 → 12 推进，而是根据当前"缺什么"来决定"做什么"。用户只需提供本品 ASIN + 竞品 ASIN + 词库，Research Agent 自动采集竞品数据。如果用户直接上传了属性表，Orchestrator 会跳过 Research + Product Analyst，直接进入关键词和文案环节。

---

### 4.2 Research Agent（竞品调研 Agent）

**目标**：根据竞品 ASIN 列表，自动采集竞品前台数据（Listing 文本、Rufus 问答、评论），写入 Shared Memory。

**可用工具**：Browser Tool, LLM Tool（多模态，用于解析 Rufus 截图）, File Store Tool

**自动采集流程**：

```
输入：competitor_asins[] + site（如 amazon.com.au）

对每个竞品 ASIN 执行以下采集：

1. 采集 Listing 文本
   - URL: https://{site}/dp/{ASIN}
   - 提取：title, bullet_points, description, price, category_path
   - 选择器：#productTitle, #feature-bullets li, #productDescription
   - 如 Description 为 A+ 富文本 → 提取 #aplus 区域纯文本

2. 采集 Rufus 问答
   - 在商品页定位 Rufus AI 助手区域
   - 使用 Browser Tool 截图 Rufus 问答区域
   - 使用 LLM Tool（多模态）从截图提取问题列表
   - 输出：rufus_questions[]（如 "Can it hold heavy belts?"）

3. 采集评论
   - URL: https://{site}/product-reviews/{ASIN}
   - 提取 Top Reviews（默认前 20 条）：rating, title, body, verified
   - 使用 LLM Tool 生成 review_summary：
     - positive_themes[]（好评高频主题）
     - negative_themes[]（差评高频主题）
     - pain_points[]（用户痛点）

4. 校验采集完整性：
   - 每条 listing 至少包含 title + bullet_points
   - 如某 ASIN 页面无法访问 → 记录错误，继续下一个
   - 如 Rufus 区域不可见（部分品类/站点无 Rufus）→ 跳过，标记为空

5. 将采集数据写入 Shared Memory：
   - competitor_listings[]
   - review_summary{}
   - rufus_questions[]
```

**反爬策略**：

```
- 使用 Playwright stealth 模式（playwright-extra + stealth plugin）
- 请求间隔：随机 3-8 秒（避免触发频率限制）
- User-Agent 轮换：模拟真实浏览器指纹
- 单次 Run 通常仅 2-4 个 ASIN，总请求量低（< 15 页面），反爬风险可控
- 失败重试：最多 2 次，间隔 10 秒
- 如连续失败 → 降级为请求用户手动上传
```

**降级策略**：

```
IF Browser Tool 采集失败（反爬拦截/网络异常）:
  → 通知用户手动上传对应 ASIN 的数据
  → 支持部分自动 + 部分手动混合模式
```

---

### 4.3 Product Analyst Agent（产品分析 Agent）

**目标**：将 Research Agent 收集的原始数据，融合为结构化的产品属性表。

**可用工具**：LLM Tool（多模态）, File Store Tool

**自主决策流程**：

```
1. 从 Memory 读取：competitor_listings, review_summary, rufus_questions, 截图
2. 构建分析 Prompt，调用 LLM Tool（Gemini，多模态）
3. 获得 product_attributes_draft
4. 自我评估：
   - 每个字段是否有实质内容？（非空且非泛化表述）
   - target_users 是否具体？（"年轻妈妈" 优于 "所有人"）
   - selling_points 是否和 pain_points 对应？
5. 如果评估不通过 → 追加上下文重新生成
6. 写入 Memory，通知 Orchestrator "需要人工审核"
```

**输出**：

```json
{
  "product_attributes_draft": {
    "target_users": [],
    "use_cases": [],
    "pain_points": [],
    "core_features": [],
    "selling_points": [],
    "language_patterns": []
  },
  "confidence": 0.85,
  "notes": "评论中多次提到防水性能，已纳入核心卖点"
}
```

> `confidence` 和 `notes` 供人工审核时参考，提升审核效率。

---

### 4.4 Keyword Strategist Agent（关键词策略 Agent）

**目标**：构建分类关键词词库 + 最终 ST 优化。承担两个阶段的任务。

**可用工具**：LLM Tool, Keyword Tool, File Store Tool

**阶段一：关键词分类**

```
触发条件：Memory 中有 approved_product_attributes + keyword_library

1. 从 Memory 读取属性表和原始词库
2. 使用 Keyword Tool 清洗词库（去重、去空、标准化）
3. 使用 LLM Tool（Claude）进行语义分类：
   - 功能词、场景词、人群词、卖点词、情绪词
4. 自我评估：
   - 每个分类下是否有 ≥ 5 个关键词？
   - 是否有关键词未被归类？
   - 高搜索量词是否被合理分配？
5. 写入 Memory: classified_keywords
```

**阶段二：ST 优化**

```
触发条件：Memory 中有 final_listing + classified_keywords

1. 从 Memory 读取 final_listing 和 classified_keywords
2. 使用 Keyword Tool:
   a. 提取 listing 正文中已出现的词集合
   b. 从 classified_keywords 中找出未覆盖的高价值词
   c. 按 search_volume 降序排列
   d. 填充到 ST，控制在 249 bytes 以内
3. 写入 Memory: final_st + word_frequency_report
```

> ST 优化阶段使用确定性算法（Keyword Tool），不使用 LLM，保证可重复性。

---

### 4.5 Copywriter Agent（文案撰写 Agent）

**目标**：基于产品属性和关键词，通过多轮迭代生成高质量 Listing。

**可用工具**：LLM Tool（多模型）, Compliance Tool, File Store Tool

**这是系统中最核心的 Agent**，内部实现一个三轮自我迭代循环：

```
Round 1: 初稿生成
  输入：approved_product_attributes + classified_keywords
  模型：Gemini Pro（创造力强）
  输出：draft_v1 (title + bullets + description + st)

Round 2: Rufus 优化
  输入：draft_v1 + rufus_questions + approved_product_attributes
  模型：Claude Sonnet（精细优化）
  策略：确保 Listing 能回答 Rufus 提出的消费者问题
  输出：draft_v2

Round 3: 合规校正
  输入：draft_v2 + compliance_rules
  模型：Claude Sonnet
  流程：
    a. 使用 Compliance Tool 加载合规规则
    b. 将规则注入 Prompt，引导 LLM 校正
    c. LLM 输出后，使用 Compliance Tool 后置校验
    d. 如果有违规 → 附带违规详情重新生成（最多 2 次）
    e. 通过 → 输出 final_listing
```

**Copywriter Agent 的自我评估维度**：

| 维度 | 检查方法 |
|------|---------|
| 关键词覆盖率 | 检查 classified_keywords 中有多少出现在 listing 文本中 |
| Rufus 问题覆盖 | 检查每个 rufus_question 是否在 listing 中有对应回答 |
| 合规性 | Compliance Tool 后置校验 |
| 格式正确性 | 标题长度、Bullet Point 数量和长度 |

**如果自我评估不达标**：Agent 自行决定是微调（补充遗漏关键词）还是重写（切换策略重新生成）。

---

## 5. 协作流程全景

```
用户输入：本品 ASIN + 竞品 ASIN 列表 + 关键词词库
     │
     ▼
┌─────────────────────────────────────────────────────────────┐
│ Orchestrator: "Memory 为空，需要竞品数据和分类词库"            │
│                                                              │
│  ┌──────────────────┐        ┌─────────────────────┐        │
│  │  Research Agent  │        │ Keyword Strategist  │        │
│  │  (自动采集竞品)   │ 并行   │  (关键词分类)         │        │
│  └────────┬─────────┘        └──────────┬──────────┘        │
│           │                             │                    │
│           ▼                             ▼                    │
│  Memory: competitor_listings     Memory: classified_keywords │
│          review_summary                                      │
│          rufus_questions                                     │
└─────────────────────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────────────────────┐
│ Orchestrator: "有竞品数据了，需要产品属性表"                   │
│                                                              │
│  ┌──────────────────────┐                                   │
│  │ Product Analyst Agent│                                   │
│  │  (融合分析 → 属性表)  │                                   │
│  └────────┬─────────────┘                                   │
│           │                                                  │
│           ▼                                                  │
│  Memory: product_attributes_draft                            │
└─────────────────────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────────────────────┐
│ Orchestrator: "属性表需要人工审核"                             │
│                                                              │
│  → 向用户展示 product_attributes_draft                       │
│  → 用户修改并确认                                             │
│  → Memory: approved_product_attributes                       │
└─────────────────────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────────────────────┐
│ Orchestrator: "有属性表 + 分类词库，可以写文案了"              │
│                                                              │
│  ┌────────────────────┐                                     │
│  │  Copywriter Agent  │                                     │
│  │  Round 1: 初稿     │                                     │
│  │  Round 2: Rufus优化│                                     │
│  │  Round 3: 合规校正  │                                     │
│  └────────┬───────────┘                                     │
│           │                                                  │
│           ▼                                                  │
│  Memory: final_listing + st_v3                               │
└─────────────────────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────────────────────┐
│ Orchestrator: "有 Listing 了，需要优化 ST"                    │
│                                                              │
│  ┌─────────────────────┐                                    │
│  │ Keyword Strategist  │                                    │
│  │  (ST 词频优化)       │                                    │
│  └────────┬────────────┘                                    │
│           │                                                  │
│           ▼                                                  │
│  Memory: final_st                                            │
└─────────────────────────────────────────────────────────────┘
     │
     ▼
  Orchestrator: "全部完成，生成交付包"
     │
     ▼
  final_listing.json + final_listing.md + final_st.json
```

---

## 6. Shared Memory 设计

### 6.1 数据结构

```
Memory
  ├── run_id            (string)
  ├── status            (enum: running | waiting_human | completed | failed)
  ├── input
  │     ├── product_asin          (string, 本品 ASIN)
  │     ├── competitor_asins[]    (竞品 ASIN 列表)
  │     └── site                  (string, 如 "amazon.com.au")
  │
  ├── context           (业务数据，各 Agent 写入)
  │     ├── competitor_listings[]           (Research Agent 自动采集)
  │     ├── review_summary{}                (Research Agent 自动采集 + LLM 摘要)
  │     ├── rufus_questions[]               (Research Agent 自动采集 + LLM 提取)
  │     ├── rufus_screenshots[]             (文件路径，Browser Tool 截图)
  │     ├── product_attributes_draft{}
  │     ├── approved_product_attributes{}
  │     ├── keyword_library[]               (用户上传)
  │     ├── classified_keywords{}
  │     ├── draft_listing_v1{}
  │     ├── draft_listing_v2{}
  │     ├── final_listing{}
  │     ├── st_v3[]
  │     ├── final_st[]
  │     └── word_frequency_report{}
  │
  ├── agent_log[]       (每次 Agent 调用的记录)
  │     └── { agent, action, input_keys, output_keys, model, tokens, duration_ms, timestamp }
  │
  └── files/            (文件产物目录)
        ├── screenshots/
        ├── drafts/
        └── final/
```

### 6.2 Memory 读写规则

| 规则 | 说明 |
|------|------|
| **写入即可见** | Agent A 写入后，Agent B 立即可读 |
| **只追加不覆盖** | 草稿版本保留（v1/v2/v3），不删除历史 |
| **每次写入记录 agent_log** | 完整的审计追踪 |
| **Orchestrator 是唯一写入 status 的角色** | Agent 只写 context |

---

## 7. Tool Layer 设计

### 7.1 LLM Tool

```
功能：统一调用多个 LLM 提供商
接口：
  llm_call(model, prompt, attachments?, response_format?) → dict

内部能力：
  - 模型路由：gemini-pro / claude-sonnet / gpt-4o
  - 多模态：图片 base64 编码传递
  - JSON 强制输出 + Schema 校验
  - 指数退避重试（3 次）
  - 模型降级：主模型不可用时自动切换
  - Token 统计与成本追踪
```

### 7.2 Keyword Tool

```
功能：关键词处理的确定性工具集
接口：
  clean(raw_data) → keyword_library
  classify(keywords, attributes) → classified_keywords  // 内部调用 LLM Tool
  analyze_frequency(listing, st, keywords) → optimized_st + report

内部能力：
  - 去重、去空、大小写标准化
  - 词频统计
  - Listing/ST 差集计算
  - 字节限制控制（249 bytes）
```

### 7.3 Compliance Tool

```
功能：Amazon Listing 合规校验
接口：
  load_rules(category?) → rules_text
  validate(listing) → violations[]

内部能力：
  - 禁用词正则匹配
  - 长度检查（标题 ≤ 200, Bullet ≤ 500）
  - 内容限制（禁止促销、价格、外部链接）
  - 品类特殊规则加载
```

### 7.4 File Store Tool

```
功能：文件读写
接口：
  write_json(path, data) → path
  read_json(path) → data
  write_text(path, content) → path
  write_image(path, bytes) → path
```

### 7.5 Browser Tool

```
功能：Amazon 商品页自动采集（Playwright 驱动）
接口：
  scrape_listing(asin, site) → { title, bullet_points, description, price, category_path }
  scrape_rufus(asin, site) → { screenshot_path, questions[] }
  scrape_reviews(asin, site, max_count?) → { reviews[], summary{} }

目标页面 URL 模板：
  - 商品详情页：https://{site}/dp/{ASIN}
  - 评论页面：  https://{site}/product-reviews/{ASIN}
  - Rufus 区域：商品详情页内嵌（需滚动触发加载）

内部能力：
  - Playwright + stealth plugin（反反爬）
  - 页面元素定位与文本提取：
    - Title: #productTitle
    - Bullet Points: #feature-bullets li
    - Description: #productDescription 或 #aplus
    - Price: .a-price-whole + .a-price-fraction
    - Category: #wayfinding-breadcrumbs_feature_div
    - Reviews: [data-hook="review"]
  - Rufus 区域截图 + 多模态 LLM 问题提取
  - 随机延迟（3-8s）+ User-Agent 轮换
  - 失败重试（最多 2 次，间隔 10s）
  - 降级机制：采集失败时通知用户手动上传

站点适配：
  - amazon.com.au（澳洲站，主要目标）
  - amazon.com（美国站）
  - 其他站点按相同模板扩展，选择器基本一致
```

---

## 8. API 设计

### 8.1 创建 Run

```
POST /api/runs
```

```json
{
  "product_asin": "B0GLNVMXB8",
  "competitor_asins": ["B0XXXXXX", "B0YYYYYY"],
  "site": "amazon.com.au"
}
```

### 8.2 查询 Run 状态

```
GET /api/runs/{run_id}
```

```json
{
  "run_id": "run_20260325_001",
  "status": "waiting_human",
  "current_agent": "orchestrator",
  "memory_snapshot": {
    "has_competitor_listings": true,
    "has_review_summary": true,
    "has_product_attributes_draft": true,
    "has_approved_product_attributes": false,
    "has_classified_keywords": false,
    "has_final_listing": false,
    "has_final_st": false
  },
  "pending_action": {
    "type": "review_product_attributes",
    "data": { "product_attributes_draft": {} },
    "agent_notes": "评论中多次提到防水性能，已纳入核心卖点，请确认"
  },
  "agent_log": [
    { "agent": "research", "action": "scrape_listings", "duration_ms": 12340 },
    { "agent": "research", "action": "analyze_reviews", "duration_ms": 8520 },
    { "agent": "product_analyst", "action": "generate_attributes", "duration_ms": 5430 }
  ]
}
```

### 8.3 提交人工审核

```
PUT /api/runs/{run_id}/review
```

```json
{
  "type": "product_attributes",
  "approved_data": {
    "target_users": ["..."],
    "use_cases": ["..."],
    "pain_points": ["..."],
    "core_features": ["..."],
    "selling_points": ["..."],
    "language_patterns": ["..."]
  }
}
```

### 8.4 上传数据

```
PUT /api/runs/{run_id}/upload
Content-Type: multipart/form-data
```

### 8.5 获取最终产物

```
GET /api/runs/{run_id}/final
```

### 8.6 Prompt 管理

```
GET /api/prompts
```

返回所有 prompt 文件列表：

```json
[
  { "agent": "copywriter", "name": "round_1_draft_v1", "filename": "round_1_draft_v1.md", "modified": false },
  { "agent": "copywriter", "name": "round_2_rufus_v1", "filename": "round_2_rufus_v1.md", "modified": true }
]
```

```
GET /api/prompts/{agent}/{name}
```

返回 prompt 内容（如有 override 返回 override 版本）：

```json
{ "agent": "copywriter", "name": "round_2_rufus_v1", "content": "# Round 2...", "modified": true }
```

```
PUT /api/prompts/{agent}/{name}
```

```json
{ "content": "# Updated prompt content..." }
```

```
DELETE /api/prompts/{agent}/{name}
```

重置为默认版本（删除 override 文件）。

---

## 9. 持久化策略

MVP 阶段 **不使用数据库**，所有状态由两层管理：

| 层 | 负责内容 | 存储方式 |
|----|---------|---------|
| LangGraph Checkpoint | Agent 执行状态、Shared Memory 全量快照、人工卡点断点 | SQLite 文件（LangGraph 内建，自动管理） |
| File Store | 最终交付物（JSON / Markdown）、截图等二进制文件 | `artifacts/runs/{run_id}/` 目录 |

> 不需要自建 Run / AgentExecution / HumanInteraction 表。LangGraph checkpoint 已包含完整的 State 历史和 agent_log。如需"列出所有 Run"或"按状态查询"等运营功能，在后续版本引入数据库。

---

## 10. 技术选型

| 层级 | 选型 | 理由 |
|------|------|------|
| 语言 | Python 3.12+ | LLM / Agent 生态最成熟 |
| Agent 框架 | LangGraph | 支持有状态的多 Agent 编排、条件分支、人工卡点 |
| LLM SDK | litellm | 统一接口调用 Gemini / Claude / OpenAI |
| Web 框架 | FastAPI | 异步支持好、自动 OpenAPI 文档 |
| 存储 | LangGraph Checkpoint (内建 SQLite) + 本地文件系统 | 无需额外数据库，MVP 足够 |
| 配置管理 | python-dotenv + .env | 密钥和参数集中管理 |
| 前端 | React 18 + TypeScript + Ant Design 5 + Vite | 支持实时状态监控、内联编辑、Prompt IDE、多 Tab 布局 |
| 前端状态 | SWR（轮询）+ Zustand | 3 秒轮询 Pipeline 状态，轻量级状态管理 |
| 前端编辑器 | @monaco-editor/react | Prompt 编辑和全文 Markdown 编辑 |

### 为什么选择 LangGraph

- **有状态图**：天然支持 Agent 间的状态传递和条件分支
- **人工卡点**：内建 `interrupt_before` / `interrupt_after` 机制
- **持久化**：支持 checkpoint，Pipeline 可暂停恢复
- **可观测性**：内建 tracing，每步可追踪

---

## 11. 关键设计决策

### 11.1 Agent 粒度选择

将 12 个 Step 收敛为 5 个 Agent（不含 Orchestrator），而不是 12 个 Agent：

| 选择 | 理由 |
|------|------|
| Research Agent 合并 Step 1/2/3 | 三者都是"采集竞品信息"（Listing 文本 / Rufus 问答 / 评论），由同一个 Agent 通过 Browser Tool 统一采集 |
| Product Analyst 独立 | 融合分析是独立的认知推理任务 |
| Keyword Strategist 合并 Step 6/7/11 | 关键词的清洗、分类、ST 优化是同一专业领域的不同阶段 |
| Copywriter 合并 Step 8/9/10 | 初稿/优化/合规是同一份文案的迭代，由一个 Agent 内部管理更自然 |

### 11.2 确定性算法 vs LLM

| 任务 | 选择 | 理由 |
|------|------|------|
| 关键词清洗 | 确定性算法 | 去重、去空是规则操作 |
| 关键词分类 | LLM | 需要语义理解 |
| ST 词频优化 | 确定性算法 | 需要精确的字节控制 |
| 合规后置校验 | 确定性算法 | 禁用词和长度是硬规则 |
| 其他所有生成/分析 | LLM | 需要推理和创造 |

### 11.3 人工介入策略

Agent 架构下，人工介入不再是固定卡点，而是 Agent 根据 confidence 主动判断：

```
IF confidence ≥ 0.9:
    → 自动继续（记录日志供事后审查）
IF 0.7 ≤ confidence < 0.9:
    → 请求人工审核（附带 Agent 的自评说明）
IF confidence < 0.7:
    → 标记为低置信度，强制人工介入
```

MVP 阶段保守策略：产品属性表始终要求人工审核。

### 11.4 对话式交互（V1.2）

> MVP 阶段不实现，列入后续演进。

这是 Agent 架构带来的核心增量能力：

- 用户可以在任何阶段用自然语言修正 Agent 输出
- Orchestrator 解析用户意图，路由到对应 Agent
- Agent 基于当前 Memory 上下文进行局部修改，而不是重跑整个流程

---

## 12. 目录结构

```
eco_listing/
  app/
    main.py                     ← FastAPI 入口
    agents/
      orchestrator.py           ← Orchestrator Agent（LangGraph 图定义）
      research.py               ← Research Agent（自动采集竞品数据）
      product_analyst.py        ← Product Analyst Agent
      keyword_strategist.py     ← Keyword Strategist Agent
      copywriter.py             ← Copywriter Agent
      base.py                   ← Agent 基类
    tools/
      llm_tool.py               ← 统一 LLM 调用
      browser_tool.py           ← Playwright 自动采集 Amazon 页面
      keyword_tool.py           ← 关键词清洗/词频/字节计算
      compliance_tool.py        ← 合规规则 + 后置校验
      file_store.py             ← 文件读写
    memory/
      shared_memory.py          ← Shared Memory 实现
      schemas.py                ← Memory 中各数据块的 Schema
    api/
      routes.py                 ← API 路由（含 Prompt CRUD）
    config.py                   ← 配置加载
  web/                          ← React 前端
    package.json
    vite.config.ts
    tsconfig.json
    index.html
    src/
      main.tsx                  ← React 入口
      App.tsx                   ← 路由配置
      api/                      ← API 客户端层
        client.ts               ← axios 实例
        runs.ts                 ← Run CRUD
        prompts.ts              ← Prompt CRUD
        upload.ts               ← 文件上传
      hooks/
        useRunStatus.ts         ← SWR 轮询 Run 状态
        usePrompts.ts           ← Prompt 列表
      pages/
        InputPage.tsx           ← 输入页（ASIN + 词库上传）
        RunDashboard.tsx        ← 主工作台（Pipeline + Tabs）
      components/
        layout/                 ← 全局布局
        pipeline/               ← Pipeline 进度侧边栏
        status/                 ← Agent 日志 + 数据预览
        review/                 ← 人工审核（属性表编辑 + Monaco）
        prompts/                ← Prompt 管理（列表 + 编辑器）
        output/                 ← 最终产物（预览 + 复制 + 下载）
      types/                    ← TypeScript 类型定义
      utils/                    ← 工具函数（字节计算、ASIN 校验）
  prompts/
    product_analyst/
    keyword_strategist/
    copywriter/
      round_1_draft.md
      round_2_rufus.md
      round_3_compliance.md
  compliance_rules/
    general.md
    category_specific/
  artifacts/
    runs/
  tests/
  .env.example
  .env
  requirements.txt
  run.py                        ← CLI 入口
  README.md
```

---

## 13. MVP 范围

| Agent | MVP 实现 | 自动化程度 |
|-------|---------|----------|
| Research Agent | Browser Tool 自动采集竞品 Listing + Rufus + 评论 | **全自动**（失败时降级为手动上传） |
| Product Analyst Agent | LLM 自动分析 + 人工审核产品属性表 | 半自动 |
| Keyword Strategist Agent (分类) | 用户上传词库 + LLM 分类 | 半自动 |
| Copywriter Agent | 三轮 LLM 自动迭代 + 合规校验 | 全自动 |
| Keyword Strategist Agent (ST) | 确定性算法 | 全自动 |

**MVP 用户输入**：
1. 本品 ASIN（如 `B0GLNVMXB8`）
2. 竞品 ASIN 列表（2-4 个）
3. 关键词词库（欧鹭等工具导出文件）

**MVP 人工节点**：
- 产品属性表审核确认（唯一强制人工节点）

**MVP 不含**：
- 对话式修正（chat 接口）→ V1.2
- 多 Run 管理（列表/查询/比对）→ V1.2
- 数据库审计追踪 → V1.2
- 欧鹭 API 对接（自动获取词库）→ V1.3

**MVP 交付件**：
1. CLI：`python run.py --product-asin B0GLNVMXB8 --competitor-asins B0XXXXXX,B0YYYYYY --site amazon.com.au`
2. Web 界面（React）：输入 ASIN + 上传词库 + 实时 Pipeline 状态 + 审核属性表 + Prompt 编辑 + 最终产物预览/下载
3. `prompts/` 目录：所有预置 Prompt（支持通过 Web 界面在线修改）

---

## 14. 后续演进

| 阶段 | 内容 |
|------|------|
| V1.1 | 对话式交互（chat 接口）+ 多 Run 管理 + 数据库审计日志 |
| V1.2 | Keyword Strategist 对接欧鹭 API（自动获取词库，消除最后一项手动上传） |
| V1.3 | Research Agent 增强：支持更多站点（amazon.co.uk / amazon.de / amazon.co.jp）+ 代理 IP 池 |
| V2.0 | 增加 Translator Agent，支持多语言 Listing |
| V2.1 | 增加 Performance Tracker Agent，追踪上架后效果 |
| V3.0 | 增加 Publisher Agent，对接 SP-API 自动上架 |
