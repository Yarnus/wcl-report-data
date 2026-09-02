---
name: wcl-raid-coach
description: 分析正式服 Warcraft Logs 团队副本。用户提供 WCL 报告链接、要求个人复盘、需要团队事件数据，或询问当前团本指定 Boss 和专精的高分日志攻略时使用。
slug: wcl-raid-coach
displayName: WCL 团队副本教练
version: 2.0.0
summary: 准备可复现的全团证据，复盘个人表现，并从当前高分日志生成 Boss 攻略。
license: MIT
homepage: https://github.com/Yarnus/wcl-raid-coach
compatibility: 需要 WorkBuddy 或 Python 3.11+、互联网连接，以及用户自己的 Warcraft Logs API 客户端凭据。
metadata:
  tags: [warcraft-logs, world-of-warcraft, raid, coaching]
---

# WCL 团队副本教练

只使用 Warcraft Logs 官方 GraphQL API 建立日志事实。使用当前、有来源的资料解释事实。始终使用中文回答。

在 Skill 目录中运行 `python -m wcl_raid_coach`。CLI 始终向标准输出写入 JSON。

## 1. 路由请求

将用户请求归入一个主要工作流：

- **报告数据**：用户要求下载、准备或查询一份 WCL Report 的团队事实。
- **个人复盘**：用户提供 WCL URL，并要求评价一个玩家在一个 Boss Attempt 中的表现。
- **通用攻略**：用户没有提供个人日志，要求当前 Retail 团本中某专精打一个或多个 Boss 的攻略。
- **混合请求**：先完成个人复盘；用户明确要求通用打法时，再附同一 Boss 的通用原则。个人结论和群体结论必须分开。

不支持 Mythic+、Classic、私有报告和历史团本通用攻略。不得把不支持的请求静默改成其他工作流。

## 2. 检查环境

首次访问 WCL 前运行：

```bash
python -m wcl_raid_coach doctor
```

不得询问、输出、记录或持久化 client secret/access token。凭据不可用时阅读 [WorkBuddy 配置](references/workbuddy-setup.md)。

## 3. 报告数据

建立整个团队的 Report Index：

```bash
python -m wcl_raid_coach inspect "<WCL_URL>"
```

没有数字 fight 时，展示 Boss Attempt 与参与者选择并等待用户确认。不得自动选择最后一场、击杀场或 URL source hint。Encounter Designator 只用于解释用户选择，不能代替数字 fight ID。

准备用户明确选择的 Boss Attempt：

```bash
python -m wcl_raid_coach prepare "<WCL_URL_WITH_NUMERIC_FIGHT>"
```

只有 `complete: true`、到达显式 `nextPageTimestamp: null`、通过哈希检查且没有跨 Report Revision 的 Complete Bundle 才能进入分析。

按需查询 Canonical Event：

```bash
python -m wcl_raid_coach query "<MANIFEST_PATH>" --type damage --source-id 10
```

## 4. 个人复盘

裸报告 URL 先执行 `inspect`，让用户明确选择一个 Boss Attempt 和一个参与者。完整 URL 仍须确认 URL 中的 fight/source 指向预期对象。

准备 Complete Bundle 后计算个人日志事实：

```bash
python -m wcl_raid_coach coach review \
  "<MANIFEST_PATH>" \
  --index "<REPORT_INDEX_PATH>" \
  --source-id <ACTOR_ID> \
  --partition-id <PARTITION_ID>
```

`coach review` 只产生结构化日志事实。要评价表现，必须再建立同 encounter、difficulty、class、spec 和 partition 的 Encounter Benchmark。不得把总排名差距写成可实现提升。

## 5. 通用攻略

例如用户说“给我一个邪 DK 打 H7 H8 的攻略”，先解析请求：

```bash
python -m wcl_raid_coach coach resolve \
  --spec "邪 DK" \
  --encounter H7 \
  --encounter H8
```

该命令使用 WCL 官方元数据解析唯一当前 Retail 团本、Heroic 难度、原始 encounter 顺序和默认 ranking partition。向用户展示 Boss 名称、encounter ID、难度、partition 和规范专精；用户确认前不得发现排名或下载候选事件。

确认任务：

```bash
python -m wcl_raid_coach coach confirm "<TASK_ID>"
```

H7 与 H8 是两个 Encounter Benchmark。不得混合它们的 cohort、分析或样本数量。

### 准备 Profiles

每个攻略需要：

- 一个匹配 game version/partition/class/spec 的 Specialization Profile。
- 每个 Boss 一个匹配 game version/partition/encounter/difficulty 的 Encounter Profile。

资料优先级：Blizzard/WCL 官方资料；维护中的职业社区、专精指南和模拟文档；Wowhead/Icy Veins 交叉验证。Profile 保存 URL、标题、访问时间、引用摘要和内容哈希，不保存整篇第三方文章。

```bash
python -m wcl_raid_coach coach profile "/tmp/profile.json"
```

Encounter Profile 必须声明优先目标与排除目标。Profile 缺失或校验失败时，可以展示排名候选，但禁止生成稳定高分打法 benchmark。

### 发现近期高分候选

每个 Boss 分别运行：

```bash
python -m wcl_raid_coach coach candidates \
  --game-version <GAME_VERSION> \
  --encounter-id <ENCOUNTER_ID> \
  --difficulty-id <DIFFICULTY_ID> \
  --partition-id <PARTITION_ID> \
  --class-name DeathKnight \
  --spec-name Unholy
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

```bash
python -m wcl_raid_coach coach benchmark \
  /tmp/analysis-1.json /tmp/analysis-2.json /tmp/analysis-3.json \
  --cohort /tmp/cohort.json \
  --encounter-profile /tmp/encounter-profile.json \
  --specialization-profile /tmp/specialization-profile.json \
  --output /tmp/benchmark.json
```

最后将多个独立 benchmark 合并成不可变 Guide Snapshot：

```bash
python -m wcl_raid_coach coach guide \
  /tmp/h7-benchmark.json /tmp/h8-benchmark.json \
  --spec-display-name "邪恶死亡骑士"
```

输出包括中文 Markdown 和 JSON 索引。报告必须区分：

- **日志事实**：Complete Bundle 直接计算的事实。
- **资料结论**：当前 Profile 来源支持的规则或机制。
- **推断**：事实与资料结合后的建议，必须说明置信度。

## 6. 限流与恢复

API 点数低于 15% 或 50 点的较高者时停止。遇到 `wcl_rate_limit`，保留 Complete Bundle 检查点和已完成 Boss 章节，不降低证据要求。使用以下命令查看任务：

```bash
python -m wcl_raid_coach coach status
```

多 Boss 请求允许 `partial`：已完成章节可以交付，未完成章节必须显示阻塞原因，不能用低证据内容填充。

## 7. 使用边界

- 仅支持 Retail 团队副本；Mythic+ 留待后续版本。
- 仅支持公开和未列出 WCL Report。
- 官方 WCL API only；不抓取 WCL 网页或私有端点。
- 统一使用 Complete Bundle，不维护另一套按玩家下载的事件缓存。
- 没有独立 Encounter Profile 时，不判断 padding、机制责任或可规避伤害。
- 坦克和治疗建议必须先满足相应的生存/治疗 guardrail；证据不足时停止建议。
- 不建立持久玩家历史；只分析当前请求明确提供的报告。
