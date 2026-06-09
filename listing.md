一、最终三阶段流程（完全对齐你定义）

---
🧩 阶段一：生成【本品属性表】（认知层）
输入：竞品 Amazon 链接（1个或多个）
输出：本品属性表（人工审核后）

---
🔹 Step 1.1 竞品 Listing 抓取
输入
{
  "competitor_asin": ""
}
https://www.amazon.com.au/dp 拼上 asin，即可打开商品链接
输出
{
  "competitor_listings": [
    {
      "title": "",
      "bullet_points": [],
      "description": "",
      "price": "",
      "category": ""
    }
  ]
}

---
🔹 Step 1.2 评论抓取 + 评论总结
输入
{
  "competitor_urls": []
}
输出
{
  "review_summary": {
    "pros": [],
    "cons": [],
    "high_freq_issues": [],
    "usage_scenarios": [],
    "user_language": []
  }
}
👉 ⚠️ 注意你这里已经隐含了一个关键能力：
user_language = 后面关键词和文案的核心来源

---
🔹 Step 1.3 Alex 问题获取 ⭐（你修正的点）
输入
{
  "competitor_urls": []
}
输出
{
  "alex_questions": []
}

---
🔹 Step 1.4 第一次AI分析（Info Fusion）
输入（聚合）
{
  "competitor_listings": [],
  "review_summary": {},
  "alex_questions": []
}

---
输出（本品属性表初稿）
{
  "product_attributes_draft": {
    "target_users": [],
    "use_cases": [],
    "pain_points": [],
    "core_features": [],
    "selling_points": [],
    "language_patterns": []
  }
}

---
🔹 Step 1.5 属性表结构化
👉（字段标准化，方便后续用）

---
🔹 Step 1.6 ⭐人工审核（必须）
输入
{
  "product_attributes_draft": {}
}
输出
{
  "approved_product_attributes": {}
}

---
🧠 阶段一总结（你这阶段的本质）
👉 你不是在“分析竞品”，而是在：
构建一个“可驱动生成的产品认知模型”

---
🧩 阶段二：生成【分类关键词词库】（语义层）
输入：
- 本品属性表（阶段一）
- 人工处理后的鸥鹭词库表
输出：分类关键词词库

---
🔹 Step 2.1 鸥鹭关键词 → 人工清洗 ⭐
网页直接操作，人工删除数据

---
🔹 Step 2.2 分类关键词生成（Cherry步骤系统化）
输入
{
  "approved_product_attributes": {},
  "keyword_library": []
}

---
输出（分类关键词词库）
{
  "classified_keywords": {
    "功能词": [],
    "场景词": [],
    "人群词": [],
    "卖点词": [],
    "情绪词": []
  }
}

---
👉 ⚠️ 关键点：
这一步 = 你原来：
Cherry Studio + Claude + Prompt
现在变成：
Keyword Clustering Agent

---
🧩 阶段三：生成 Listing（表达层）
输入：
- 本品属性表
- 分类关键词词库
输出：
- 最终 Listing
- 最终 ST

---
🔹 Step 3.1 初稿生成（多模型）
输入
{
  "approved_product_attributes": {},
  "classified_keywords": {}
}

---
输出
{
  "draft_listing_v1": {
    "title": "",
    "bullet_points": [],
    "description": ""
  },
  "st_v1": []
}

---
🔹 Step 3.2 二稿生成（换模型 + 加Alex）
👉 这是你流程里的“质量跃迁点”

---
输入
{
  "draft_listing_v1": {},
  "approved_product_attributes": {},
  "alex_questions": []
}

---
输出
{
  "draft_listing_v2": {},
  "st_v2": []
}

---
🔹 Step 3.3 最终 Listing（结构优化 + 校正）
输入prompt，和合规rule作为知识库
输入
{
  "draft_listing_v2": {},
  "approved_product_attributes": {}
}

---
输出
{
  "final_listing": {},
  "st_v3": []
}

---
🔹 Step 3.4 ST词频分析（你补的关键步骤）
👉 这是一个非常专业的动作（很多人没有）

---
输入
{
  "st_v3": [],
  "keyword_library": []
}

---
处理逻辑
- 去重
- 统计词频
- 删除冗余词
- 控制字符长度（Amazon限制）

---
输出
{
  "final_st": []
}

---
四、最终完整流程（可执行版）
阶段一（认知层）
竞品URL
 → Listing抓取
 → 评论分析
 → Alex问题
 → Info Fusion
 → 属性表
 → 人工审核 ✅

阶段二（语义层）
鸥鹭关键词
 → 分类建模（AI）

阶段三（表达层）
属性表 + 分类关键词
 → 初稿（模型A）
 → 二稿（模型B + Alex）
 → 三稿（结构优化）
 → ST词频优化
 → 最终输出 ✅