# Step 5：ST 词频分析与最终优化（Stage 3.4）

> 依据 `listing.md` 第 🔹 Step 3.4 节「ST 词频分析」的流程：
> 1. 去重（与 Title / 五点 / Description 已有词对比）
> 2. 统计词频
> 3. 删除冗余词
> 4. 控制字节长度 < 249 bytes
>
> 输入：
> - V3 Title + 五点 + Description（来自 R3 审核通过版本）
> - V2 ST 初稿："storage racks hangers holders bra neck necktie drawer slim compact tidy durable vertical rental apartment dorm organiser organizers multiple mens womens gifts dad husband clothes sturdy"
> - 词库 A/B/C/D 分类（`分类关键词词库.md`）

---

## 5.1 前台字段去重对照表（Title + 五点为核心核查范围）

以下是 V3 Title + 五点中已出现的关键词全集（小写归一化）：

`4 pack belt hanger for closet rust-resistant organizer tie rack with s-shaped hooks multi-use scarf hats bags holds 15 lbs lavender sachets black effortless setup hook this onto any rod or wall mount in seconds no drilling screws tools required true instant-use heavy-duty capacity built from coated metal up to 6.8 kg leather belts each includes fresh wardrobe ready out of box hangers set needs slides standard rods resists moisture note may slide extremely thin standard-width many items works as hat purse holder round loop lets easily ideal bedroom entryway office walk-in closets complete bonus 17 x 12 3 cm smart men women`

Description 额外覆盖：`tired tangled falling scarves cluttered drawers keeps every accessory neatly organized within reach needed key features instantly design structure makes sliding off quick handbags vertical layout frees drawer shelf space fresher-smelling specifications material color size weight package faq q can it hold heavy yes assembly installation hangs is made sturdy save maximizes reduces clutter other accessories will fit fits but`

---

## 5.2 V2 ST 逐词审计

| 序号 | V2 ST 词 | 是否在 Title+五点 | 是否在 Description | 决策 | 理由 |
|---|---|---|---|---|---|
| 1 | storage | ❌ | ❌ | ✅ 保留 | A 类 belt storage 首次覆盖 |
| 2 | racks | ❌ | ❌ | ✅ 保留 | "rack" 单数在前台，复数未覆盖 |
| 3 | hangers | ✅ (Bullet 3 + 5) | ✅ | ❌ 删除 | Title+五点已出现，A9 重复不增权重 |
| 4 | holders | ❌ | ❌ | ✅ 保留 | "holder" 单数在 Bullet 4，复数未覆盖 |
| 5 | bra | ❌ | ❌ | ✅ 保留 | C 类 bra hanger / bra hangers 首次覆盖 |
| 6 | neck | ❌ | ❌ | ✅ 保留 | B 类 neck tie organizer 首次覆盖 |
| 7 | necktie | ❌ | ❌ | ✅ 保留 | 合写变体，长尾流量补充 |
| 8 | drawer | ❌ | ✅ (KEY FEATURES) | ❌ 删除 | Description 已覆盖，保留浪费字节 |
| 9 | slim | ❌ | ❌ | ✅ 保留 | 场景描述词 |
| 10 | compact | ❌ | ❌ | ✅ 保留 | 场景描述词 |
| 11 | tidy | ❌ | ❌ | ✅ 保留 | 场景描述词 |
| 12 | durable | ❌ | ❌ | ✅ 保留 | 耐用性词，高频搜索修饰 |
| 13 | vertical | ❌ | ✅ | ❌ 删除 | Description 已覆盖 |
| 14 | rental | ❌ | ❌ | ✅ 保留 | 人群场景词（租房党） |
| 15 | apartment | ❌ | ❌ | ✅ 保留 | 场景词 |
| 16 | dorm | ❌ | ❌ | ✅ 保留 | 人群场景词（学生） |
| 17 | organiser | ❌ | ❌ | ✅ 保留 | UK 拼写变体（AU 站点必要） |
| 18 | organizers | ❌ | ❌ | ✅ 保留 | 复数变体 |
| 19 | multiple | ❌ | ❌ | ✅ 保留 | B 类 scarf hanger for multiple scarves 首次覆盖 |
| 20 | mens | ❌ | ❌ | ✅ 保留 | "men" 在 Bullet 5，"mens" 为所有格/变体，不同 token |
| 21 | womens | ❌ | ❌ | ✅ 保留 | 同上 |
| 22 | gifts | ❌ | ❌ | ✅ 保留 | 购买场景词 |
| 23 | dad | ❌ | ❌ | ✅ 保留 | 购买人群词 |
| 24 | husband | ❌ | ❌ | ✅ 保留 | 购买人群词 |
| 25 | clothes | ❌ | ❌ | ✅ 保留 | 相关品类词 |
| 26 | sturdy | ❌ | ✅ (FAQ) | ❌ 删除 | Description 已覆盖 |

**删除小计**：hangers / drawer / vertical / sturdy = 4 词（共 27 bytes 含空格）

---

## 5.3 补充候选词（填充释出的字节空间）

> 原则：每新增词必须在 A/B/C 类中找到明确支撑，或属于通用购买/场景/人群词；严禁与 D 类产生词义重叠。

| 候选词 | 类别 | 支撑依据 |
|---|---|---|
| stylish | 通用修饰 | 衣柜类目高频搜索组合词（stylish closet organizer） |
| modern | 通用修饰 | 同上（modern belt rack） |
| holiday | 购买场景 | 节日礼品（holiday gift for men） |
| birthday | 购买场景 | 生日礼品（birthday gift for dad / husband） |
| wedding | 购买场景 | 新婚购新家收纳场景 |
| brother | 购买人群 | 礼品对象（gift for brother） |
| boyfriend | 购买人群 | 礼品对象（gift for boyfriend） |
| mudroom | 场景词 | 玄关/储物间（与属性表"Entryways"场景同源） |
| hanging | 功能变体 | "hanger"/"hang"在前台，"hanging"为 -ing 形式新 token |

---

## 5.4 ST V3 最终输出

```
storage racks holders bra neck necktie slim compact tidy durable rental apartment dorm organiser organizers multiple mens womens gifts dad husband clothes stylish modern holiday birthday wedding brother boyfriend mudroom hanging
```

**字节数：228 / 249 bytes ✓**

### 字节核算明细
| 词 | chars |
|---|---|
| storage | 7 |
| racks | 5 |
| holders | 7 |
| bra | 3 |
| neck | 4 |
| necktie | 7 |
| slim | 4 |
| compact | 7 |
| tidy | 4 |
| durable | 7 |
| rental | 6 |
| apartment | 9 |
| dorm | 4 |
| organiser | 9 |
| organizers | 10 |
| multiple | 8 |
| mens | 4 |
| womens | 6 |
| gifts | 5 |
| dad | 3 |
| husband | 7 |
| clothes | 7 |
| stylish | 7 |
| modern | 6 |
| holiday | 7 |
| birthday | 8 |
| wedding | 7 |
| brother | 7 |
| boyfriend | 9 |
| mudroom | 7 |
| hanging | 7 |
| **合计词字符** | **198** |
| 空格数（30） | 30 |
| **总字节** | **228** |

### D 类终检（26 组词均未出现）
✅ cedar / acrylic / duty / organizador / tie+belt / bag+organizer / accessory+organizer / rack+organizer / clip / bag+ties / bag+accessories / hair+tie / legging / tank+top / closet+organization / hanger（单数）等 D 类词均无任何出现。

### 词频去重再确认
- 无任何一个 ST 词出现在 Title + 五点中 ✓
- drawer / vertical / sturdy / hangers 均已从 ST 中移除，消除与 Description 的冗余 ✓
- 未出现标点、引号、连字符、逗号、分号（Amazon ST 规范 §4.3）✓

---

## 5.5 ST 层关键词覆盖矩阵（最终）

| 词库等级 | Title/五点/Description 已覆盖 | ST 补充覆盖 | 总覆盖率 |
|---|---|---|---|
| A 类（18 组） | 17 组（belt storage 未在前台但 "storage" 进 ST） | 1 组（storage） | **18 / 18 = 100%** |
| B 类（26 组） | 22 组核心词 | 4 组变体（neck, multiple, holders, organizers 复数/变体）| **26 / 26 = 100%** |
| C 类（13 组） | 7 组（walk-in / office / bedroom / entryway / purse / hat / closet accessories） | 6 组变体（bra / racks / organiser / mens / womens + drawer已由描述覆盖） | **13 / 13 = 100%** |
| D 类（26 组） | **0 组（严禁出现）** | **0 组** | **100% 排除** |

---

**✅ Step 5 ST 词频分析完毕。Final ST = 228 / 249 bytes，A/B/C 三类 100% 覆盖，D 类 100% 排除。**
