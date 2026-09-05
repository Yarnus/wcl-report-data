---
name: wcl-report-data
description: 分析正式服 Warcraft Logs 团队副本。用户提供 WCL 报告链接、要求机制或个人复盘、需要团队事件数据、询问当前团本指定 Boss 和专精的高分日志攻略，或询问“如何使用”“能做什么”、how to use、what can this skill do 时使用。
slug: wcl-report-data
displayName: WCL 团队副本教练
version: 3.0.1
summary: 准备可复现的全团证据，复核首领机制与个人表现，并从当前高分日志生成 Boss 攻略。
license: MIT
homepage: https://github.com/Yarnus/wcl-report-data
compatibility: 需要 Python 3.11+、互联网连接，以及用户自己的 Warcraft Logs API 客户端凭据。
metadata:
  tags: [warcraft-logs, world-of-warcraft, raid, coaching]
---

# WCL 团队副本教练

只使用 Warcraft Logs 官方 GraphQL API 建立日志事实。使用当前、有来源的资料解释事实。使用用户当前使用的语言回答。

先定位本文件所在的目录并记为 `<SKILL_ROOT>`；该目录必须同时包含 `SKILL.md` 和 `wcl_raid_coach/`。每次都在同一条 shell 命令中先进入该目录，再运行 bundled CLI；不得先从当前工作目录尝试，也不得假设 Skill 已全局安装。CLI 始终向标准输出写入 JSON，持久数据和缓存不得写入 Skill 根目录。需要暂存 Profile 或聚合输入时，由宿主选择 Skill 根目录之外可写的 `<WORK_DIR>`；命令中的尖括号表示应替换的路径或参数，不是字面值。

## 1. 路由请求

将用户请求归入一个主要工作流：

- **报告数据**：用户要求下载、准备或查询一份 WCL Report 的团队事实。
- **机制复盘**：用户要求检查一份 WCL Report 中单个 Boss Attempt 的首领机制处理结果，但不要求个人表现评价。
- **个人复盘**：用户提供 WCL URL，并要求评价一个玩家在一个 Boss Attempt 中的表现。
- **通用攻略**：用户没有提供个人日志，要求当前 Retail 团本中某专精打一个或多个 Boss 的攻略。
- **混合请求**：先完成个人复盘；用户明确要求通用打法时，再附同一 Boss 的通用原则。个人结论和群体结论必须分开。
- **使用帮助**：用户询问如何使用、能做什么或索要使用示例。

不支持 Mythic+、Classic、私有报告和历史团本通用攻略。同一 WCL Report 同时包含团本与 Mythic+ 时，只列出和准备其中的团本 Boss Attempt；不得因存在 Mythic+ fight 而拒绝整份报告，也不得把 Mythic+ fight 静默当作团本。不得把不支持的请求静默改成其他工作流。

### 使用帮助

只根据随包文档回答，不访问 WCL 或运行 CLI。使用用户当前使用的语言，先用一句话说明需要用户自己的 WCL API 凭据、仅支持 Retail 团本的公开或未列出报告，并提醒用户不要在对话中粘贴 secret；再简短列出以下能力和自然语言示例，输出菜单即结束：

- **报告数据**：“帮我看看这份 WCL 报告里有哪些 Boss Attempt 和参与者：<WCL_URL>”
- **机制复盘**：“复核这场 Boss Attempt 的机制处理：<WCL_URL_WITH_NUMERIC_FIGHT>”
- **个人复盘**：“复盘我在这场 Boss Attempt 的表现，角色是 <角色名>：<WCL_URL_WITH_NUMERIC_FIGHT>”
- **通用攻略**：“给我一份邪恶死亡骑士打当前团本 H7 和 H8 的攻略。”

## 2. 检查环境

首次访问 WCL 前运行：

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach doctor
```

普通用户只需通过 Agent 宿主的私密环境配置提供 `WCL_CLIENT_ID` 和 `WCL_CLIENT_SECRET`。不得询问、输出、记录或持久化 client secret/access token。凭据不可用或需要确认存储位置时阅读[凭据与存储配置](references/setup.md)。

## 3. 报告数据

建立整个团队的 Report Index：

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach inspect "<WCL_URL>"
```

没有数字 fight 时，展示 Boss Attempt 与参与者选择并等待用户确认。不得自动选择最后一场、击杀场或 URL source hint。Encounter Designator 只用于解释用户选择，不能代替数字 fight ID。

准备用户明确选择的 Boss Attempt：

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach prepare "<WCL_URL_WITH_NUMERIC_FIGHT>"
```

只有 `complete: true`、到达显式 `nextPageTimestamp: null`、通过哈希检查且没有跨 Report Revision 的 Complete Bundle 才能进入持久化的个人复盘、Benchmark 或 Guide 分析。机制复盘使用第 4 节的临时证据路径。

按需查询 Canonical Event：

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach query "<MANIFEST_PATH>" --type damage --source-id 10
```

## 4. 机制复盘

Mechanic Review 当前只覆盖 The Venomous Abyss（WCL zone `53`）的官方 8 个团本首领：Nek'zali、Entombed Sentinels、Vashnik、The Lost Explorers、Sszorak、The Twin Fangs、The Coiled Altar 和 Ula'tek，难度为 Normal、Heroic 或 Mythic。Nymrissa Wavecaller（encounter `3379`）是世界首领，必须排除。

裸报告 URL 或只给 Encounter Designator 时列出候选 Boss Attempt，等待用户选择数字 fight。不得自动选择击杀、最后一次或全部尝试：

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach mechanics "<WCL_REPORT_URL>" --encounter H2
```

用户确认数字 fight 后直接分析 URL 中明确的 Boss Attempt：

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach mechanics "<WCL_URL_WITH_NUMERIC_FIGHT>"
```

用户要求正式报告或 HTML 时，不要从 stdout 重抄字段，也不要先保存完整 Mechanic Review 结果；必须在同一采集进程直接运行：

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach mechanics "<WCL_URL_WITH_NUMERIC_FIGHT>" --report --locale zh-CN
```

英文交付使用 `--locale en`。向用户交付 JSON stdout 中的短摘要和 `report.html_path` 链接，并保留 `source.path`、`source.sha256`、`report.document_id`、`report.html_sha256` 与 `report.index_path` 供复核。

击杀和灭团均可分析，但 Boss Attempt 必须已完成；`fight=last` 不够明确，必须拒绝。`--encounter` 与 URL 数字 fight 同时存在时，两者必须匹配。

该命令用当前 Mechanic Ruleset 的 ability ID 和 `death`、`interrupt`、`dispel` 建立服务端过滤表达式，固定 Boss Attempt 起止时间，完整分页到 `nextPageTimestamp: null`，并在结束后再次校验 Report Revision。Mechanic Evidence Set 只驻留进程内，不得创建 Report Index、Raw Page、Fight Bundle、manifest 或检查点，也不得称为 Complete Bundle 或 Canonical Event 集。

输出必须保留规则集版本、来源和 `selection_policy: latest`。`latest` 指当前安装包随附规则，不按报告发生时间回放历史热修规则，也不会运行时在线更新。机制名称使用规则集内版本化的中英文名称，不触发本地 Wago mapping 初始化。

每条机制展示规则定义的触发、成功和失败事件计数；无法客观判断时值为 `null`。只有当前难度标记为 `verified` 的事件模式才能产生异常；`event_pattern_unverified` 和 observation 规则只列观察事实。没有匹配事件不等于机制处理正确。普通内存输出可以展开用于当前分析的原始 WCL 事件证据；`--report` 来源只能保留参与者和扁平最小证据摘录，必须删除完整事件范围、`raw_event`、`raw_events`、光环应用对象和任意 WCL payload。异常只表示事件模式命中，不表示玩家责任、表现评价或灭团因果；最终裁决交给人。

### 正式 HTML 交付

Mechanic Review 的正式交付必须使用上面的 `coach mechanics ... --report`，由同一进程完成采集、净化来源持久化、Report Document 组装、来源校验和 HTML 渲染。只有分页明确结束且 Report Revision 前后一致后才允许写入；净化、校验或首次渲染失败时不留下新来源，重复内容复用 content-addressed 不可变来源。不得用下面的通用 renderer 绕过该边界。

其他已构造的 Report Document 可调用：

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach render "<WORK_DIR>/report.document.json"
```

候选选择、澄清、进度、错误、数据查询和局部追问仍直接使用文本。用户说“直接回答”或“不要报告”时不生成 HTML；用户明确说“生成报告”或“导出 HTML”时必须生成。对话中交付短摘要和 `html_path` 的可点击链接。

Report Document 只能包含对应类型允许的结构化字段，不得包含调用方 HTML、CSS 或 JavaScript；`source_artifacts` 必须记录来源 artifact 路径和 SHA-256。Mechanic Review 只保留结论、计数和扁平最小证据摘录，不得复制完整 Mechanic Evidence Set；Personal Review 不得补写机制归因或建议；Raid Guide 不得补写 Snapshot 中不存在的 rotation、天赋、装备、阶段策略或具体建议。只有玩家、Boss Attempt、Benchmark 或正式结论范围变化时才生成新报告；不改变正式结论的局部追问直接文本回答。

## 5. 个人复盘

裸报告 URL 先执行 `inspect`，让用户明确选择一个 Boss Attempt 和一个参与者。完整 URL 仍须确认 URL 中的 fight/source 指向预期对象。

准备 Complete Bundle 后计算个人日志事实：

```text
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach review "<MANIFEST_PATH>" --index "<REPORT_INDEX_PATH>" --source-id <ACTOR_ID> --partition-id <PARTITION_ID>
```

`coach review` 只产生结构化日志事实。要评价表现，必须再建立同 encounter、difficulty、class、spec 和 partition 的 Encounter Benchmark。不得把总排名差距写成可实现提升。

运行 `coach benchmark` 建立 Encounter Benchmark，再运行 `coach compare` 保存精确 Comparison 后，正式交付不得手工重写身份、指标或正文。直接把三个 artifact 组装为 Personal Review Report Document 并渲染自包含 HTML：

```text
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach personal-report "<PERSONAL_ANALYSIS_PATH>" "<ENCOUNTER_BENCHMARK_PATH>" "<COMPARISON_PATH>" --locale zh-CN
```

英文交付使用 `--locale en`。命令会重新校验 schema `3`/`2`/`2`，从 Complete Bundle 重算 Personal Analysis，从 Analysis 与 Benchmark 重算并精确核对 Comparison，再派生完整文档。向用户交付短摘要和 `report.html_path`，并保留 `report.document_id`、`report.html_sha256` 与 `report.index_path` 供复核。

Personal Review 必须保留精确 Report Revision、Boss Attempt、actor、匿名状态、职业/专精、可用装等、完整比较硬条件、Benchmark ID、样本数、置信度和指标。技能以数字 `ability_id` 作为审计身份；中文展示仅使用已校验 `ability-names.zhCN.json` 的 ID mapping，未命中时回退同一 Report Index 的 WCL 原名并把 mapping build 记录为 `null`。不得根据文本名称反查技能。assembler 不接受自定义标题、摘要、指标或建议参数，并使用固定中性文字；不得补写机制归因、死亡原因、责任、建议、推荐或可实现提升。

## 6. 通用攻略

例如用户说“给我一个邪 DK 打 H7 H8 的攻略”，先解析请求：

```text
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach resolve --spec "邪 DK" --encounter H7 --encounter H8
```

该命令使用 WCL 官方元数据解析唯一当前 Retail 团本、Heroic 难度、原始 encounter 顺序和默认 ranking partition。向用户展示 Boss 名称、encounter ID、难度、partition 和规范专精；用户确认前不得发现排名或下载候选事件。

确认任务：

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach confirm "<TASK_ID>"
```

H7 与 H8 是两个 Encounter Benchmark。不得混合它们的 cohort、分析或样本数量。

### 准备 Profiles

每个攻略需要：

- 一个匹配 game version/partition/class/spec 的 Specialization Profile。
- 每个 Boss 一个匹配 game version/partition/encounter/difficulty 的 Encounter Profile。

资料优先级：Blizzard/WCL 官方资料；维护中的职业社区、专精指南和模拟文档；Wowhead/Icy Veins 交叉验证。Profile 保存 URL、标题、访问时间、引用摘要和内容哈希，不保存整篇第三方文章。

```text
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach profile "<WORK_DIR>/profile.json"
```

Encounter Profile 必须声明优先目标与排除目标。Profile 缺失或校验失败时，可以展示排名候选，但禁止生成稳定高分打法 benchmark。

### 发现近期高分候选

每个 Boss 分别运行：

```text
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach candidates --game-version <GAME_VERSION> --encounter-id <ENCOUNTER_ID> --difficulty-id <DIFFICULTY_ID> --partition-id <PARTITION_ID> --class-name DeathKnight --spec-name Unholy
```

默认只使用最近 14 天且身份完整的候选。Ranking Candidate 不是 Reference Sample。目标为每个 Boss 10 个有效样本；3 到 9 个只能给低置信度聚合；少于 3 个只能做个案观察，不能生成稳定打法。

排名结果不包含 source ID 时，CLI 通过候选报告的官方 actor/fight metadata 按角色名、服务器、职业和专精唯一补全；无法唯一补全的候选必须拒绝。

候选必须逐一：

1. `inspect` 并验证 encounter、difficulty、partition、class 和 spec。
2. `prepare` 为候选 Boss Attempt 建立 Complete Bundle。
3. `coach review` 生成分析。
4. 根据 Encounter Profile 检查死亡、优先目标伤害和排除目标伤害。

正文匿名使用“样本 N（排名/分数）”，但保留公开 WCL 链接供审计。

### 聚合和生成攻略

每个 Boss 分别聚合：

```text
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach benchmark "<WORK_DIR>/analysis-1.json" "<WORK_DIR>/analysis-2.json" "<WORK_DIR>/analysis-3.json" --cohort "<WORK_DIR>/cohort.json" --encounter-profile "<WORK_DIR>/encounter-profile.json" --specialization-profile "<WORK_DIR>/specialization-profile.json" --output "<WORK_DIR>/benchmark.json"
```

最后将多个独立 benchmark 合并成不可变 Guide Snapshot：

```text
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach guide "<WORK_DIR>/h7-benchmark.json" "<WORK_DIR>/h8-benchmark.json" --spec-display-name "邪恶死亡骑士"
```

正式交付时，不要手工重写 Boss 章节。把上一步返回的唯一 Guide Snapshot JSON 直接组装为 `raid_guide` Report Document 并渲染自包含 HTML：

```text
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach guide-report "<GUIDE_SNAPSHOT_JSON_PATH>"
```

该命令重新校验 Snapshot 内容 ID 和 Markdown hash，保留精确 Snapshot ID 与来源文件 SHA-256，并只从各自章节派生 encounter/Benchmark/Profile 身份、样本数、置信度、指标、本地化技能、机制锚点和来源。不得跨 Boss 移动或合并字段；不得补写 Snapshot 中没有的 rotation、天赋、装备、阶段策略、建议或可实现目标。向用户交付短摘要和返回的 `report.html_path` 链接。

输出包括与用户语言一致的 Markdown 和 JSON 索引。当前 bundled Guide Snapshot renderer 只生成中文 Markdown；英文请求生成最终 Guide Snapshot 前必须明确告知这一限制，不得把中文 artifact 伪装成英文结果。报告必须区分：

- **日志事实**：Complete Bundle 直接计算的事实。
- **资料结论**：当前 Profile 来源支持的规则或机制。
- **推断**：事实与资料结合后的建议，必须说明置信度。

### Spell 名称输出门禁

生成中文攻略前必须确保 `ability-names.zhCN.json` 已从 Wago Tools 初始化并通过 metadata 哈希检查。所有由 `ability_id` 确认的 Spell 在中文 Markdown 和中文对话正文中必须使用该 mapping 的中文名称；不得根据英文名自行翻译，也不得把裸数字 ID 或英文 SpellName 写入中文正文。该门禁不适用于只使用随包规则名称的 Mechanic Review。

机制名称必须通过 Encounter Profile 的具体 `ability_id` 关联，不得按英文名称反查。若机制 Spell ID 缺少 zhCN mapping，停止生成最终攻略并返回结构化错误；不得静默回退为英文。JSON 索引可以保留 `ability_id`、WCL 原始名称和 mapping build 作为审计信息。

输出前逐项检查机制锚点、技能统计、首次施放时间和实战建议中引用的 Spell，确保正文使用中文名称。无法确认是 Spell 的阶段描述或资料术语，必须标记为机制描述，不得伪装成 SpellName。

Encounter 和 NPC 名称使用独立的 `content-names.zhCN.json`。该 mapping 只覆盖当前团本 Normal、Heroic、Mythic 和配置的 8 个 Mythic+ 地图，并保留 Wago Encounter/NPC ID、英文原名及客户端 build。Encounter 命中 mapping 时正文使用中文名；NPC 中文名只能作为所属 Encounter 内的展示 enrichment，不得按名称推断 WCL actor 身份。未命中时保留 WCL 原名，不得自行翻译。

## 7. 限流与恢复

API 点数低于 15% 或 50 点的较高者时停止。持久化采集遇到 `wcl_rate_limit` 时保留 Complete Bundle 检查点和已完成 Boss 章节，不降低证据要求。Mechanic Review 没有检查点，限流或中断后必须重新运行。使用以下命令查看任务：

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach status
```

多 Boss 请求允许 `partial`：已完成章节可以交付，未完成章节必须显示阻塞原因，不能用低证据内容填充。

## 8. 使用边界

- 仅支持 Retail 团队副本；Mythic+ 留待后续版本。
- 仅支持公开和未列出 WCL Report。
- 官方 WCL API only；不抓取 WCL 网页或私有端点。
- 个人复盘、Benchmark 和 Guide 统一使用 Complete Bundle，不维护另一套按玩家下载的持久事件缓存；Mechanic Review 只使用临时 Mechanic Evidence Set。
- 没有独立 Encounter Profile 或版本化 Mechanic Ruleset 时，不判断 padding、机制责任或可规避伤害。
- Mechanic Review 的顶层 `judgment` 和 `causal_attribution` 必须始终为 `null`。
- 坦克和治疗建议必须先满足相应的生存/治疗 guardrail；证据不足时停止建议。
- 不建立持久玩家历史；只分析当前请求明确提供的报告。
