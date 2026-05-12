# 亚马逊 Listing 自动化创作系统 — 需求详情文档

## 一、项目概述

本项目旨在将亚马逊 Listing 创作流程从手工多工具操作，系统化为一个可执行的自动化/半自动化工作流。整个流程分为 **三大阶段**（认知层 → 语义层 → 表达层），共 **12 个操作步骤**，最终产出高质量的亚马逊商品 Listing（标题、五点描述、产品描述、Search Terms）。

---

## 二、整体流程总览

```
阶段一（认知层）：构建产品认知模型
  竞品ASIN → Listing抓取 → 评论分析 → Rufus问题获取 → AI融合分析 → 本品属性表 → 人工审核 ✅

阶段二（语义层）：构建关键词语义库
  鸥鹭反查关键词 → 人工清洗 → AI分类建模 → 分类关键词词库 ✅

阶段三（表达层）：多模型迭代生成 Listing
  属性表 + 分类关键词 → 初稿（模型A） → 二稿（模型B + Rufus） → 三稿（合规校正） → ST词频优化 → 最终输出 ✅
```

---

## 三、阶段一：生成本品属性表（认知层）

> **目标**：通过分析竞品信息，构建一个"可驱动生成的产品认知模型"  
> **阶段输入**：竞品 Amazon 链接（ASIN）  
> **阶段输出**：经人工审核的本品属性表（Markdown 格式）

---

### Step 1（对应 listing.md Step 1.1）— 竞品 Listing 抓取


| 项目        | 说明                                                              |
| --------- | --------------------------------------------------------------- |
| **操作描述**  | 2~4 个竞品 ASIN，从亚马逊前台复制其价格、标题、五点描述、类目信息，整理为结构化 JSON，形成竞品 Listing 文本 |
| **当前工具**  | 手动在亚马逊前台操作 + JSON 模板                                             |
| **自动化方向** | 爬虫/API 自动抓取，输入 ASIN 即可批量获取                                      |


**输入：**

```json
{
  "competitor_asins": ["ASIN_1", "ASIN_2", "ASIN_3"]
}
```

> URL 拼接规则：`https://www.amazon.com.au/dp/{ASIN}`

**输出：**

```json
{
  "competitor_listings": [
    {
      "asin": "ASIN_1",
      "title": "商品标题",
      "bullet_points": ["五点1", "五点2", "五点3", "五点4", "五点5"],
      "description": "产品描述",
      "price": "$29.99",
      "category": "Home & Kitchen > ..."
    }
  ]
}
```

---

### Step 2（对应 listing.md Step 1.3）— Rufus 截图获取


| 项目        | 说明                                                        |
| --------- | --------------------------------------------------------- |
| **操作描述**  | 从亚马逊前台获取每个竞品的 Rufus（AI 问答）截图，保存到本地，命名为 `{ASIN}_rufus.png` |
| **当前工具**  | 手动截图保存                                                    |
| **自动化方向** | 浏览器自动化（Playwright/Selenium）自动截取 Rufus 区域                  |


**输入：**

```json
{
  "competitor_urls": [
    "https://www.amazon.com.au/dp/ASIN_1",
    "https://www.amazon.com.au/dp/ASIN_2"
  ]
}
```

**输出：**

```json
{
  "rufus_screenshots": ["ASIN_1_rufus.png", "ASIN_2_rufus.png"],
  "rufus_questions": [
    "Is this product suitable for ...?",
    "How does this compare to ...?"
  ]
}
```

---

### Step 3（对应 listing.md Step 1.2）— 竞品评论抓取 + AI 评论总结


| 项目        | 说明                                                                |
| --------- | ----------------------------------------------------------------- |
| **操作描述**  | 使用腾讯 IMA 浏览器打开竞品亚马逊链接，让 AI 分析竞品评论，截图保存到本地，命名为 `{ASIN}_review.png` |
| **当前工具**  | 腾讯 IMA 浏览器（内置 AI 分析）                                              |
| **自动化方向** | 评论爬取 + LLM 自动总结                                                   |


**输入：**

```json
{
  "competitor_urls": [
    "https://www.amazon.com.au/dp/ASIN_1",
    "https://www.amazon.com.au/dp/ASIN_2"
  ]
}
```

**输出：**

```json
{
  "review_screenshots": ["ASIN_1_review.png", "ASIN_2_review.png"],
  "review_summary": {
    "pros": ["优点1", "优点2"],
    "cons": ["缺点1", "缺点2"],
    "high_freq_issues": ["高频问题1", "高频问题2"],
    "usage_scenarios": ["使用场景1", "使用场景2"],
    "user_language": ["用户高频表达1", "用户高频表达2"]
  }
}
```

> **关键说明**：`user_language` 是后续关键词和文案的核心语料来源，直接影响 Listing 的买家视角表达。

---

### Step 4（对应 listing.md Step 1.4）— 第一次 AI 融合分析（Info Fusion）


| 项目        | 说明                                                                                              |
| --------- | ----------------------------------------------------------------------------------------------- |
| **操作描述**  | 将竞品 Listing 文本、Rufus 截图、Review 截图统一输入 AI（Cherry Studio 调用 Gemini，已预设 Prompt），提炼产品属性信息，形成本品属性表初稿 |
| **当前工具**  | Cherry Studio + Gemini（预设提示词）                                                                   |
| **自动化方向** | 多模态 LLM Agent（支持文本+图片输入）                                                                        |


**输入：**

```json
{
  "competitor_listings": [],
  "review_summary": {},
  "review_screenshots": [],
  "rufus_questions": [],
  "rufus_screenshots": []
}
```

**输出：**

```json
{
  "product_attributes_draft": {
    "target_users": ["目标人群1", "目标人群2"],
    "use_cases": ["使用场景1", "使用场景2"],
    "pain_points": ["痛点1", "痛点2"],
    "core_features": ["核心功能1", "核心功能2"],
    "selling_points": ["卖点1", "卖点2"],
    "language_patterns": ["高频表达模式1", "高频表达模式2"]
  }
}
```

---

### Step 5（对应 listing.md Step 1.5 + 1.6）— 属性表结构化 + 人工审核


| 项目        | 说明                                 |
| --------- | ---------------------------------- |
| **操作描述**  | 人工复核本品属性表信息，进行修正和结构化标准化，另存为 Markdown 格式 |
| **当前工具**  | 人工操作                               |
| **自动化方向** | 提供可编辑的审核界面，支持修改后一键导出 Markdown      |


**输入：**

```json
{
  "product_attributes_draft": {}
}
```

**输出：**

```json
{
  "approved_product_attributes": {
    "target_users": [],
    "use_cases": [],
    "pain_points": [],
    "core_features": [],
    "selling_points": [],
    "language_patterns": []
  }
}
```

> 输出格式：JSON 结构 + 同步导出 Markdown 文件供存档

---

## 四、阶段二：生成分类关键词词库（语义层）

> **目标**：基于产品属性认知和市场关键词数据，建立结构化的关键词语义库  
> **阶段输入**：本品属性表（阶段一） + 鸥鹭原始关键词数据  
> **阶段输出**：分类关键词词库（JSON 格式）

---

### Step 6（对应 listing.md Step 2.1）— 鸥鹭关键词反查 + 人工清洗


| 项目        | 说明                                              |
| --------- | ----------------------------------------------- |
| **操作描述**  | 通过欧鹭选品软件，用 ASIN 反查关键词，导出到本地。人工删除多余字段信息后保存为 JSON，形成词库表 |
| **当前工具**  | 欧鹭软件（网页端操作） + 人工清洗                              |
| **自动化方向** | API 对接欧鹭或替代数据源；自动字段过滤                           |


**输入：**

```json
{
  "competitor_asins": ["ASIN_1", "ASIN_2"]
}
```

**输出：**

```json
{
  "keyword_library": [
    {
      "keyword": "关键词1",
      "search_volume": 12000,
      "competition": "medium"
    },
    {
      "keyword": "关键词2",
      "search_volume": 8500,
      "competition": "low"
    }
  ]
}
```

> 输出格式：清洗后的关键词列表（JSON）

---

### Step 7（对应 listing.md Step 2.2）— AI 关键词分类


| 项目        | 说明                                                                                          |
| --------- | ------------------------------------------------------------------------------------------- |
| **操作描述**  | 通过 Cherry Studio（调用 Claude Sonnet，已预设提示词），上传本品属性表和词库表，让 AI 对关键词进行语义分类，将结果导出本地，形成分类关键词词库 JSON |
| **当前工具**  | Cherry Studio + Claude Sonnet（预设提示词）                                                        |
| **自动化方向** | Keyword Clustering Agent（LLM + 规则引擎）                                                        |


**输入：**

```json
{
  "approved_product_attributes": {},
  "keyword_library": []
}
```

**输出：**

```json
{
  "classified_keywords": {
    "功能词": ["keyword_a", "keyword_b"],
    "场景词": ["keyword_c", "keyword_d"],
    "人群词": ["keyword_e", "keyword_f"],
    "卖点词": ["keyword_g", "keyword_h"],
    "情绪词": ["keyword_i", "keyword_j"]
  }
}
```

> 输出格式：分类关键词词库.json

---

## 五、阶段三：生成 Listing（表达层）

> **目标**：通过多模型迭代，逐步生成、优化、合规校正最终 Listing 文案  
> **阶段输入**：本品属性表 + 分类关键词词库  
> **阶段输出**：最终 Listing（标题、五点、描述）+ 最终 Search Terms

---

### Step 8（对应 listing.md Step 3.1）— 初稿生成（模型 A）


| 项目        | 说明                                                               |
| --------- | ---------------------------------------------------------------- |
| **操作描述**  | 登录 Google AI Studio，用提前调试好的模型，上传本品属性表和分类关键词词库，生成标题、五点、产品描述、ST 初稿 |
| **当前工具**  | Google AI Studio（预调模型）                                           |
| **自动化方向** | Gemini API / 其他 LLM API 调用                                       |


**输入：**

```json
{
  "approved_product_attributes": {},
  "classified_keywords": {}
}
```

**输出：**

```json
{
  "draft_listing_v1": {
    "title": "初稿标题",
    "bullet_points": ["五点1", "五点2", "五点3", "五点4", "五点5"],
    "description": "初稿产品描述"
  },
  "st_v1": ["search term 1", "search term 2", "..."]
}
```

---

### Step 9（对应 listing.md Step 3.2）— 二稿优化（模型 B + Rufus）


| 项目        | 说明                                                             |
| --------- | -------------------------------------------------------------- |
| **操作描述**  | 用第 8 步初稿信息，连同本品属性表和 Rufus 截图，交给第二个模型做优化，生成新的优化后的标题、五点、产品描述和 ST |
| **当前工具**  | Google AI Studio / Cherry Studio（第二个模型）                        |
| **自动化方向** | 第二个 LLM Agent，侧重 Rufus 问题覆盖和文案优化                               |


**输入：**

```json
{
  "draft_listing_v1": {},
  "approved_product_attributes": {},
  "rufus_questions": [],
  "rufus_screenshots": []
}
```

> **关键点**：这是流程中的"质量跃迁点"。引入 Rufus 数据使 Listing 能回应亚马逊 AI 助手可能提出的消费者问题，提升 A9/COSMO 算法匹配度。

**输出：**

```json
{
  "draft_listing_v2": {
    "title": "优化后标题",
    "bullet_points": ["优化五点1", "优化五点2", "优化五点3", "优化五点4", "优化五点5"],
    "description": "优化后产品描述"
  },
  "st_v2": ["search term 1", "search term 2", "..."]
}
```

---

### Step 10（对应 listing.md Step 3.3）— 最终稿生成（合规校正）


| 项目        | 说明                                                                          |
| --------- | --------------------------------------------------------------------------- |
| **操作描述**  | 用第 9 步优化后的信息，连同本品属性表，交给第三个模型做合规审查，生成最终版的标题、五点、产品描述和 ST，复制到本地作为本品 Listing 文案 |
| **当前工具**  | Google AI Studio / Cherry Studio（第三个模型 + 合规规则知识库）                           |
| **自动化方向** | Compliance Agent（LLM + 合规规则库）                                               |


**输入：**

```json
{
  "draft_listing_v2": {},
  "approved_product_attributes": {},
  "compliance_rules": "合规规则知识库（Amazon Listing政策、禁用词等）"
}
```

**输出：**

```json
{
  "final_listing": {
    "title": "最终标题",
    "bullet_points": ["最终五点1", "最终五点2", "最终五点3", "最终五点4", "最终五点5"],
    "description": "最终产品描述"
  },
  "st_v3": ["search term 1", "search term 2", "..."]
}
```

---

### Step 11（对应 listing.md Step 3.4）— ST 词频分析优化


| 项目        | 说明                                                                                                                     |
| --------- | ---------------------------------------------------------------------------------------------------------------------- |
| **操作描述**  | 复制第 7 步分类关键词词库表以及第 10 步 ST，进入词频统计分析工具（amz123.com/tools-wordcounter），导出词频 JSON，将词频导入本地文件，提炼出尚未在标题、五点、产品描述中使用过的关键词，形成最终版 ST |
| **当前工具**  | amz123 词频分析工具（网页端） + 人工比对                                                                                              |
| **自动化方向** | 本地词频统计脚本 + 自动去重比对                                                                                                      |


**输入：**

```json
{
  "st_v3": [],
  "classified_keywords": {},
  "final_listing": {}
}
```

**处理逻辑：**

1. 统计 ST 中所有词的词频
2. 对比标题、五点、描述中已使用的关键词
3. 提炼出**尚未被使用**的高价值关键词
4. 去重、删除冗余词
5. 控制总字符长度（Amazon ST 限制：通常 249 bytes）

**输出：**

```json
{
  "final_st": ["optimized search term 1", "optimized search term 2", "..."],
  "word_frequency_report": {
    "total_keywords": 150,
    "used_in_listing": 95,
    "added_to_st": 55,
    "total_bytes": 248
  }
}
```

---

### Step 12 — 上传亚马逊后台


| 项目        | 说明                           |
| --------- | ---------------------------- |
| **操作描述**  | 将最终版标题、五点、产品描述、ST 上传到亚马逊卖家后台 |
| **当前工具**  | 手动在 Amazon Seller Central 操作 |
| **自动化方向** | Amazon SP-API 对接自动填写（远期）     |


**输入：**

```json
{
  "final_listing": {
    "title": "最终标题",
    "bullet_points": [],
    "description": "最终产品描述"
  },
  "final_st": []
}
```

**输出：**

> 商品 Listing 上线

---

## 六、数据流转全景图

```
┌─────────────────────────── 阶段一：认知层 ───────────────────────────┐
│                                                                      │
│  竞品ASIN ──→ [Step1] Listing抓取 ──→ competitor_listings            │
│           ──→ [Step2] Rufus截图    ──→ rufus_questions/screenshots   │
│           ──→ [Step3] 评论分析     ──→ review_summary/screenshots    │
│                         │                                            │
│                         ▼                                            │
│              [Step4] AI融合分析(Gemini)                               │
│                         │                                            │
│                         ▼                                            │
│              product_attributes_draft                                │
│                         │                                            │
│                         ▼                                            │
│              [Step5] 人工审核 ──→ approved_product_attributes (MD)    │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────── 阶段二：语义层 ───────────────────────────┐
│                                                                      │
│  鸥鹭ASIN反查 ──→ [Step6] 人工清洗 ──→ keyword_library              │
│                         │                                            │
│     approved_product_attributes + keyword_library                    │
│                         │                                            │
│                         ▼                                            │
│              [Step7] AI分类(Claude Sonnet)                            │
│                         │                                            │
│                         ▼                                            │
│              classified_keywords (JSON)                              │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────── 阶段三：表达层 ───────────────────────────┐
│                                                                      │
│  approved_product_attributes + classified_keywords                   │
│                         │                                            │
│                         ▼                                            │
│              [Step8]  初稿生成(Google AI Studio) ──→ v1              │
│                         │                                            │
│              v1 + attributes + rufus                                 │
│                         ▼                                            │
│              [Step9]  二稿优化(模型B)            ──→ v2              │
│                         │                                            │
│              v2 + attributes + 合规规则                               │
│                         ▼                                            │
│              [Step10] 合规校正(模型C)            ──→ v3(final)       │
│                         │                                            │
│              st_v3 + classified_keywords + final_listing             │
│                         ▼                                            │
│              [Step11] ST词频优化                  ──→ final_st       │
│                         │                                            │
│                         ▼                                            │
│              [Step12] 上传亚马逊后台 ✅                               │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 七、关键依赖与工具清单


| 步骤      | 当前工具/平台               | 涉及模型/能力       | 人工介入    |
| ------- | --------------------- | ------------- | ------- |
| Step 1  | Amazon 前台 + JSON 模板  | —             | ✅ 手动抓取  |
| Step 2  | Amazon 前台 + 截图        | —             | ✅ 手动截图  |
| Step 3  | 腾讯 IMA 浏览器            | IMA 内置 AI     | ✅ 触发+截图 |
| Step 4  | Cherry Studio         | Gemini（多模态）   | ❌ AI 自动 |
| Step 5  | 人工操作（Markdown）       | —             | ✅ 审核修正  |
| Step 6  | 欧鹭选品软件                | —             | ✅ 人工清洗  |
| Step 7  | Cherry Studio         | Claude Sonnet | ❌ AI 自动 |
| Step 8  | Google AI Studio      | 预调模型（Gemini）  | ❌ AI 自动 |
| Step 9  | Google AI Studio      | 第二个模型         | ❌ AI 自动 |
| Step 10 | Google AI Studio      | 第三个模型 + 合规库   | ❌ AI 自动 |
| Step 11 | amz123 词频工具           | —             | ✅ 人工比对  |
| Step 12 | Amazon Seller Central | —             | ✅ 手动上传  |


---

## 八、核心设计原则

1. **三层分离**：认知（属性表）→ 语义（关键词）→ 表达（Listing），各层输出独立可复用
2. **多模型协作**：初稿、优化、合规三轮迭代，利用不同模型的优势（Gemini 生成力、Claude 分析力、合规模型约束力）
3. **人机协同**：关键节点保留人工审核（Step 5 属性表审核、Step 6 关键词清洗），确保数据质量
4. **Rufus 覆盖**：将亚马逊 AI 助手（Rufus）的问题融入文案优化，提升 COSMO 算法匹配
5. **ST 差异化补充**：通过词频分析确保 Search Terms 与正文互补而非重复，最大化关键词覆盖率

---

## 九、自动化优先级建议


| 优先级   | 步骤                  | 理由                         |
| ----- | ------------------- | -------------------------- |
| 🔴 P0 | Step 4, 7, 8, 9, 10 | 核心 AI 生成环节，可通过 API 调用实现全自动 |
| 🟡 P1 | Step 1, 3           | 数据采集环节，可通过爬虫/浏览器自动化实现      |
| 🟡 P1 | Step 11             | 词频分析可本地化，无需依赖外部网站          |
| 🟢 P2 | Step 2              | Rufus 截图可通过浏览器自动化获取        |
| 🟢 P2 | Step 6              | 依赖欧鹭平台，需确认 API 可用性         |
| ⚪ P3  | Step 5, 12          | 人工审核和后台上传，短期内保留人工操作        |


