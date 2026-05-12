【AMAZONCOMPLIANCERULES&FORBIDDENTERMS】
Version:2.0（优化版）
Purpose: 对Title、Bullets、Description、Images及BackendKeywords执行硬性拦截规则。
适用范围: 全类目通用规则（类目专项规则以各类目StyleGuide为准）
═══════════════════════════════════════
第1章 HARDBANS（全字段通用禁止项）
═══════════════════════════════════════
1.1 联系方式与流量导流
───────────────────────────────────────
[RULE]
严格禁止在任何前端字段（标题/五点/描述/图片文字）及后台搜索词中包含：
- 电话号码
- 电子邮件地址
- 外部URL（含缩短链接）
- 二维码
- 社交媒体账号或平台名称（用于引流目的）
[REGEX_TRIGGERS]
URL检测:
(http|https)://www\.\.com\b|\.net\b|\.io\b|\.cn\b\.co\b|\.org\b|\.shop\b
Email检测:
[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}
社交平台关键词:
whatsapp|wechat|line|telegram|instagram|tiktok|facebook|twitter|youtube|pinterest
|snapchat|dmme|followus|scanthecode
[说明]
包装插卡中的二维码不属于 Listing 字段，但若插卡内容违反评论操纵规则，参见
Supplementary_Rules.doc 第1章。
───────────────────────────────────────
1.2 价格与库存状态声明
───────────────────────────────────────
[RULE]
禁止在文字或图片中硬编码价格信息或库存状态描述。
[FORBIDDEN_WORDS]
价格类:
price | cheapest | discount | sale | deal | coupon | clearance | lowest price | best price |
pricedrop|save$X

---

促销类:
freeshipping|fastdelivery|shipstoday|arrivesinXdays|samedaydelivery
库存类:
in stock |availablenow |limited time |lastXunits |selling fast|hurry |todayonly |while
supplieslast
[说明]
"FreeReturns"属于平台政策展示，非Listing文字，不受此规则限制。
───────────────────────────────────────
1.3 竞品诋毁性比较
───────────────────────────────────────
[RULE]
仅描述本品事实性功能和参数，禁止以任何形式进行诋毁性竞品比较。
[FORBIDDEN_PATTERNS]
better than [Brand] | compare to [Brand] | beats [Brand] | cheaper than [Brand] | unlike
[Brand]which...|[Brand]can'tdoX,butwecan
[允许的中性比较格式]
"Compatiblewith[Brand][Model]"（参见IP_Infringement_Library.doc 第2章）
═══════════════════════════════════════
第2章 TITLERULES（标题专项规则）
═══════════════════════════════════════
2.1 字符长度限制
───────────────────────────────────────
[RULE]
标题字符上限因类目而异，不得假设统一适用单一上限。
[字符上限参考]
大多数类目: ≤200字符（含空格）
服装/鞋类: ≤80字符
电子产品: ≤200字符
书籍: 无硬性上限，但建议≤200字符
重要说明：
每次优化前必须以该ASIN所属类目的实际StyleGuide为准，不得以180字符或200字符作
为通用定值。如类目不明确，默认使用≤200字符, 并在输出中标注"请卖家确认类目上限"。
───────────────────────────────────────

---

2.2 禁止字符
───────────────────────────────────────
[HARD_BAN-SPECIALCHARACTERS]
!$?_{}^¬¦~<>*
[允许的标点符号]
逗号 ,| 连字符 -| 斜杠 /| 括号 ()|&（代替"and"）
───────────────────────────────────────
2.3 重复词限制
───────────────────────────────────────
[RULE]
同一词汇（含同义变体）不得在标题中重复出现超过2次。
[示例]
❌"BlueSiliconeBlueCaseBlueCover"
✅"BlueSiliconeCaseandCover"
───────────────────────────────────────
2.4 主观词与促销词禁止
───────────────────────────────────────
[FORBIDDEN_WORDS]
best | #1 | top rated | hot | amazing | perfect | ultimate | premium quality | must-have |
incredible|unbeatable
═══════════════════════════════════════
第3章 BULLETPOINTSRULES（五点描述专项）
═══════════════════════════════════════
3.1 格式规范
───────────────────────────────────────
[RULE]
- 每条Bullet建议≤255字符（含Header）
-Header必须全大写，后接冒号和空格, 格式：HEADER:[内容]
- 不得使用HTML标签（Description可用HTML，Bullets不可）
- 不得使用Emoji或特殊符号作为装饰
3.2 内容禁止项
───────────────────────────────────────
[FORBIDDEN]
- 重复标题中已出现的主关键词超过2次
- 价格、促销信息（参见第1.2章）
- 联系方式（参见第1.1章）
- 虚假安全声明（参见Evidence_Claims_Matrix.doc 第4章）

---

═══════════════════════════════════════
第4章 DESCRIPTIONRULES（产品描述专项）
═══════════════════════════════════════
4.1HTML标签使用
───────────────────────────────────────
[ALLOWEDHTMLTAGS]
<b></b> 加粗
<br> 换行
<p></p> 段落
[HARD_BANHTMLTAGS]
<h1>~<h6> 标题标签（不被渲染）
<ul><li> 列表（Bullets已有专属字段）
<img> 图片标签
<ahref> 超链接
<script> 脚本（合规硬违规）
<style> 样式表
4.2 内容规范
───────────────────────────────────────
[RULE]
- 内容不得与Bullets完全重复（需有增量信息）
- 禁止任何形式的价格、促销、联系方式
- 字符上限因类目而异，通常≤2000字符
═══════════════════════════════════════
第5章 BACKENDSEARCHTERMS（后台搜索词）
═══════════════════════════════════════
5.1 硬性禁止项
───────────────────────────────────────
[HARD_BAN]
竞品品牌名（如Nike、Lego、Apple）
ASIN或ProductID
临时性词汇:new|onsale|availablenow
主观性词汇:best|amazing|cheapest
重复词汇（与标题/Bullets中已有的完全相同的词无需重复填写）
5.2 格式规范
───────────────────────────────────────
[RULE]
- 字节上限：249bytes（注意：非字符数，中文字符占2bytes）

---

- 词与词之间用空格分隔
- 不使用逗号、引号等标点
- 不使用大写（全小写即可，亚马逊索引不区分大小写）
5.3 可填写内容
───────────────────────────────────────
[RECOMMENDED]
- 同义词、缩写、常见拼写变体
- 前端字段未覆盖的长尾关键词
- 用途/使用场景描述词
- 安全兼容性说明词（兼容性品牌词的使用边界参见IP_Infringement_Library.doc 第2章）
═══════════════════════════════════════
第6章 PROMOTIONAL&SUBJECTIVEBANS（全字段主观/促销词黑名单）
═══════════════════════════════════════
[BLOCKLIST- 完整版]
促销行动词:
buynow|ordernow|addtocart|clickhere|shopnow|getyours
紧迫性词汇:
hurry|limitedtime|todayonly|actnow|don'tmiss|sellingfast|lastchance|flashsale
排名主张词:
#1 |number one | bestseller | top rated | mostpopular | trending | viral |market leader |
awardwinning（无具体奖项来源时）
保证类词汇:
guaranteed | 100% guaranteed | money back（在标题/Bullets 中） | risk-free | lifetime
warranty（注：若有实际保修政策，可在Description中以事实陈述方式呈现，如"Backedby
2-yearmanufacturerwarranty"）
