# 数据集契约

本文定义已准备数据的稳定身份、内容和完整性规则。[English version](data-contract.en.md)

## 身份

一个已准备的数据集由以下三元组标识：

```text
(report_code, report_revision, schema_version)
```

Fight Bundle 还包含一个数字 `fight_id`。不同 Report Revision 的文件绝不能混用。`latest.json` 只是指针；需要可复现结果的消费者应使用每个 manifest 中记录的 revision。

## Report Index

`report.json` 包含：

- 报告元数据和归档可访问状态
- 报告中的 actor 和 ability
- 每场 WCL 战斗，并分类为 `boss` 或 `trash`
- 团队参与者的 actor ID、名称、服务器、职业、专精和物品等级
- `packable` 和 `unpackable_reason`

包含团本 Boss Attempt 的 WCL Report 可以同时包含 Mythic+ fight。此时 Mythic+ fight 保留在 Report Index 中并标记为 `unpackable_reason: "mythic_plus"`，但不进入 `inspect` 的 `fight_choices`，也不能创建 Fight Bundle。纯 Mythic+ 报告仍被拒绝。

某次输入特有的战斗选择和 source hint 由 `inspect` 返回，不写入不可变的 Report Index。source hint 绝不能过滤 actor 或事件。

`inspect` 还按 WCL `zone.encounters` 的原始数组顺序返回一基的 `encounter_choices`。该列表用于解释 Encounter Designator，是当前查询的选择元数据，不写入已有 Report Index。数组项不得排序或按报告中出现过的首领过滤。

战斗的 `difficulty` 是 WCL 返回的原始数字 ID。消费者必须使用同一报告中的 `report.zone.difficulties` 解析它，不能使用静态全局映射。`inspect` 返回的精简 `selected_fight` 和 `fight_choices` 包含解析后的 `difficulty_name`；无法匹配时返回 `null`，不能猜测难度名称。

## Fight Bundle

`manifest.json` 最后写入。它存在且 `complete: true` 表示：

manifest 必须包含 `product: "wcl-raid-coach"`；其他产品生成的 Bundle 不属于本产品的输入。

1. 所有 WCL 事件页最终到达 `nextPageTimestamp: null`。
2. 分页游标没有重复。
3. 事件时间戳保持有序。
4. 采集结束后 Report Revision 没有变化。
5. `events.jsonl.gz` 已关闭并计算哈希。

所有分页都使用相同且包含边界的战斗开始与结束时间。旧采集协议生成的 Bundle 会被拒绝，必须重新准备。

manifest 记录按类型统计的事件数量、Raw Page 哈希、压缩事件文件哈希、解压后的 Canonical Event JSONL 内容哈希、采集选项和未知字段计数。哈希用于本地内容身份和损坏检测，不认证 Artifact 来源。

## Canonical Event

gzip JSONL 中的每一行使用以下结构：

```json
{
  "sequence": 42,
  "report_time_ms": 123456,
  "fight_time_ms": 3456,
  "type": "damage",
  "source": {"actor_id": 100, "instance_id": 1},
  "target": {"actor_id": 17, "instance_id": null},
  "ability_id": 456789,
  "fields": {"amount": 1000, "absorbed": 200},
  "raw_ref": {"page": 1, "index": 42}
}
```

actor 和 ability 名称保存在 `report.json`；ID 才是事件身份。已本地化的名称仅用于展示，不能用作键。

数据目录中的 `ability-names.zhCN.json` 是独立于 Report Index 的当前客户端展示 enrichment。`inspect`、`prepare` 或 `query` 首次需要它但文件不存在时，CLI 从 Wago Tools 下载完整 zhCN `SpellName` 表；metadata 记录客户端 build、来源和哈希。只有 Canonical Event 的 `ability_id` 同时匹配 Report Index `abilities[].gameID` 时才可应用；命中时仍须保留 WCL 名称、ability ID 和 mapping build 来源，未命中时使用 WCL 名称。mapping 更新不得改变 Report Revision 事实或 Complete Bundle 身份。

`content-names.zhCN.json` 是单独的当前内容展示 enrichment，只覆盖当前团本的 Normal、Heroic、Mythic 和配置的 8 个 Mythic+ 地图。Map 和 Encounter 以 Wago ID 记录；NPC 记录包含 `JournalEncounterCreature` ID、所属 Encounter 及中英文名。由于 Wago 数据没有提供到 WCL NPC `gameID` 的可靠直连，英文名索引仅可在 Encounter 上下文中用于展示，不得代替 actor ID。metadata 必须记录所有 Wago 表的相同客户端 build、来源和 mapping 哈希；更新 mapping 不得改写 Report Index 或 Complete Bundle。

已知 `fields` 覆盖数值、减伤、治疗、资源、生命值、光环层数、施法、首领战元数据、战斗人员装备与天赋，以及观测到的战斗属性。WCL 事件 JSON 并非固定不变。新键会计入 `unknown_fields`，其值只保留在 Raw Page 缓存中，直到 schema 明确接纳这些字段。

Guide Snapshot 的 Markdown 展示必须使用已校验 Wago zhCN mapping 的中文 SpellName 和 Encounter 名称；JSON 索引可以同时保留 ID、WCL 原始名称和 mapping build 供审计。

## 查询契约

`query` 以流式方式读取 gzip 文件，最多返回 `limit` 行。`matched` 统计输入游标之后的所有匹配行。`truncated` 为 true 时，`next_cursor` 是最后一条已返回事件的 sequence，可用于下一次查询。

时间过滤使用 `fight_time_ms`，上下界均包含在结果中。

## Mechanic Evidence Set

Mechanic Evidence Set 是 Mechanic Review 对一个数字 fight ID 的临时输入，绑定一个 WCL Report、Report Revision、Boss Attempt 固定起止时间和 Mechanic Ruleset。它包含 WCL 按规则 ability ID 与 `death`、`interrupt`、`dispel` 服务端过滤后返回的原始事件对象，不是 Canonical Event 集。

采集必须保持事件时间有序、拒绝无效或重复分页游标、首页面从 Boss Attempt 起点开始、后续页面从当前游标开始、始终固定 Boss Attempt 结束时间、到达显式 `nextPageTimestamp: null`，并在最后再次确认 Report Revision 未变化。战斗难度 ID 仍须通过该报告的 `zone.difficulties` 解释，再匹配规则的 Normal、Heroic 或 Mythic 范围。

Mechanic Evidence Set 仅存在于当前进程内，不创建 Report Index、Raw Page、Fight Bundle、manifest、哈希或检查点；中断、限流或失败后必须重新采集。结果记录规则集版本、来源和 `selection_policy: latest`。`latest` 指安装包随附的最新规则，不按报告日期选择历史热修规则，也不表示运行时在线更新。

每条机制的计数只描述规则定义的事件信号；日志无法客观判定成功或失败时，相应值为 `null`。只有当前难度标记为 `verified` 的事件模式才可产生异常；`event_pattern_unverified` 和 observation 规则不得产生异常。异常不是责任、表现评价或灭团因果。

## 教练 Artifact

个人复盘、Benchmark 和 Guide 只消费通过上述完整性检查的 Complete Bundle，不能重写 Report Index、Fight Bundle 或 Canonical Event。Mechanic Review 是非持久化例外，只消费当前进程中的 Mechanic Evidence Set。

- `profiles/` 保存声明式 Specialization Profile 和 Encounter Profile。Profile 身份包括 game version 与 ranking partition；Encounter Profile 还包括 encounter 和 difficulty。Profile ID 是校验后规范 JSON 的 SHA-256。
- `cohorts/` 保存单一 encounter、difficulty、class、spec 与 partition 的 Ranking Cohort。`cohort_id` 是排除自身 ID 后规范 JSON 的 SHA-256。Ranking Candidate 只有在 Complete Bundle、硬条件和 Encounter Profile eligibility 全部通过后才成为 Reference Sample。
- Encounter Benchmark 只能聚合同一 Ranking Cohort 中至少三个不重复的 Reference Sample，且必须记录准确的 `cohort_id`。`benchmark_id` 是排除自身 ID 后规范 JSON 的 SHA-256。不同 Encounter Designator 必须使用不同 benchmark。
- `tasks/` 保存 Coach Request Manifest。部分完成状态必须保留每个 encounter 的 blocker 与 artifact 引用。
- `guides/` 保存不可变 Guide Snapshot。每个章节记录准确的 `benchmark_id`；一个 snapshot 可以引用多个 Encounter Benchmark，但不能覆盖旧 snapshot。

个人复盘分析必须记录 Report Revision、fight ID、actor ID 和比较硬条件。分析与 benchmark 的 encounter、difficulty、class、spec 和 partition 不完全相同时，比较必须失败。

教练 Artifact 只支持本 CLI 在用户本地数据目录或工作目录中生成和消费。普通 SHA-256 不认证生成者；不得把外部提供的 Artifact 当作可信输入。旧 HMAC schema 的 Complete Bundle、Ranking Cohort、Personal Review、Encounter Benchmark 和 Guide Snapshot 不兼容，必须重新生成。
