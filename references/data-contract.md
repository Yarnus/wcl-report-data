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
- WCL zone ranking partition 的正整数 `id`、非空 `name`、可空 `compactName` 和布尔 `default`
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

`coach mechanics <URL_WITH_NUMERIC_FIGHT> --report [--locale zh-CN|en]` 是 Mechanic Review 的第一方持久化与渲染路径。它必须在完成采集和 revision 复查的同一进程中，从实际结果派生 schema `1` 的净化 `mechanic_review` 来源。来源只允许保存 WCL Report、Report Revision、Boss Attempt 与 Mechanic Ruleset 身份及元数据、事件页/事件计数、受支持结论或异常、阶段、参与者，以及下文允许的扁平最小证据摘录；不得保存完整过滤事件范围、Raw Page、Fight Bundle 或 Complete Bundle 替代物、`raw_event`、`raw_events`、光环应用对象、任意 WCL payload、责任或灭团因果。

校验后的来源按格式化 JSON 文件字节的 SHA-256 写入 `outputs/mechanic-reviews/<sha256>.json`，通过 artifact lock 和原子写入协调；已有同身份内容必须复用，身份不匹配时拒绝覆盖。分页未到达显式 null、Report Revision 变化或采集失败时不会调用持久化。净化、来源校验或首次 HTML 渲染失败时删除本次新建的来源，因此不会留下误导性的部分来源。

## Report Document

Report Document 是展示层输入，不是证据层数据。schema `1` 接受 `document_type: "mechanic_review"`、`"personal_review"` 或 `"raid_guide"`。三者共享 locale、标题、副标题、来源 artifact 和审计边界说明，其余字段按类型严格区分。

完整输入形状如下；`phases`、每条机制的 `events` 和 `actions` 可以是空数组：

```json
{
  "schema_version": 1,
  "document_type": "mechanic_review",
  "locale": "zh-CN",
  "title": "首领机制复盘",
  "subtitle": "Heroic Boss Attempt 17",
  "source_artifacts": [
    {"kind": "mechanic_review", "path": "/work/mechanic-review.json", "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
  ],
  "identity": {
    "report_code": "AbC123",
    "report_revision": 7,
    "fight_id": 17,
    "encounter_name": "Encounter Name",
    "difficulty_name": "Heroic",
    "duration_ms": 342318,
    "outcome": "wipe",
    "boss_percentage": 32.7
  },
  "ruleset": {
    "version": "2026.09.1",
    "selection_policy": "latest",
    "sources": ["https://example.com/mechanic-source"]
  },
  "evidence": {"event_count": 184, "storage": "minimal_excerpts"},
  "phases": [{"name": "阶段一", "start_ms": 0, "end_ms": 342318}],
  "mechanics": [
    {
      "name": "机制名称",
      "status": "anomaly",
      "trigger_count": 18,
      "success_count": 14,
      "failure_count": 2,
      "description": "可复核结论及其限制。",
      "events": [
        {
          "fight_time_ms": 138440,
          "tone": "danger",
          "title": "事件标题",
          "description": "支持结论的最小事件说明。",
          "participants": ["Player 03"],
          "evidence_excerpt": {"event_type": "damage", "ability_id": 1284941}
        }
      ]
    }
  ],
  "actions": [{"title": "下一把验证", "description": "只改变一个可验证条件。"}],
  "scope_note": "异常不表示玩家责任、表现评价或灭团因果。"
}
```

`personal_review` 的完整顶层字段是 `schema_version`、`document_type`、`locale`、`title`、`subtitle`、`source_artifacts`、`identity`、`player`、`comparison`、`metrics`、`abilities` 和 `scope_note`。`identity` 与 Mechanic Review 使用相同 Boss Attempt 形状；来源必须同时包含 schema `3` 的 `personal_analysis`、schema `2` 的 `encounter_benchmark` 和 schema `2` 的 `comparison`。Comparison 必须与前两个来源重新计算的结果完全相同，不能由 renderer 静默重建后替代 provenance。

- `player`：`name`、`class_name`、`spec_name`、可空 `item_level`、布尔 `anonymous`。
- `comparison`：完整比较硬条件 `game_version`、`partition_id`、`encounter_id`、`difficulty_id`、`class_name`、`spec_name`，至少 3 的 `sample_count`，以及 `low` 或 `normal` 的 `confidence`。ID 均为正数，class/spec 必须与 `player` 一致。
- `metrics`：非负整数 `damage_total`、`healing_total`、`interrupts`、`deaths`、`resource_events`，以及可空有限数 `damage_total_delta`。
- `abilities`：至多 100 项，每项包含 `name`、非负整数 `player_casts`，以及可空非负有限数 `median_casts`、`player_first_cast_ms`、`median_first_cast_ms`。

`raid_guide` 的完整顶层字段是共享字段加 `identity`、`specialization`、`snapshot_id`、`ability_names_build` 和 `chapters`；唯一来源类型是 `guide_snapshot`。`identity` 包含 `game_version`、正数 `partition_id`、`difficulty_name`、`class_name` 和 `spec_name`。`snapshot_id` 以及章节的两个 Profile ID 必须是 SHA-256。

- `chapters`：1 至 20 个 encounter ID 不重复的章节；每章包含 `encounter_id`、`encounter_name`、精确 `benchmark_id`、至少 3 的 `sample_count`、`confidence`、可空 `damage_total_median`、`abilities`、`target_damage`、`mechanic_anchors`、两个 Profile ID 和 `sources`。
- 章节 `abilities` 只保存技能名、施放中位数和首次施放中位时间；`target_damage` 只保存数字 target ID 与中位伤害；`mechanic_anchors` 只保存名称与可空观察时间。
- 章节 `sources` 只接受 `encounter` 或 `specialization` 类型、标题、公开 HTTP(S) URL 和引用摘要。规则集和章节来源 URL 的 authority 不得包含用户信息；query string 和 fragment 的参数名在忽略大小写、常见分隔符及百分号编码后，不得是凭据、密钥、令牌、认证或签名参数。

Personal Review 没有机制归因或建议字段。Raid Guide 没有 rotation、天赋、装备、阶段策略或具体建议字段。调用方不得利用标题、摘要或 `scope_note` 把伤害差值声明为可实现提升，也不得把样本中位数写成推荐次数。

`locale` 只接受 `zh-CN` 或 `en`；`status` 只接受 `anomaly`、`review`、`ok` 或 `unverified`；`tone` 只接受 `danger`、`warn`、`ok` 或 `info`。`boss_percentage` 可以为 `null`。

调用方不得提交 HTML、CSS 或 JavaScript，未知字段一律拒绝。Mechanic Review 每条机制最多保存 20 个展示事件。事件 `evidence_excerpt` 只接受 `event_type`、`ability_id`、`source_id`、`target_id`、`amount`、`duration_ms`、`delta_ms`、`episode`、`outcome` 和 `note` 这些扁平标量字段，文本值最多 300 字符；不得嵌入原始事件对象或完整 Mechanic Evidence Set。`anomaly` 状态必须有正数失败计数和展示事件；`ok` 必须有零失败计数；`unverified` 不能声明成功或失败计数。Report Document 不提供 `judgment` 或 `causal_attribution` 字段。

renderer 的信任边界不止是路径和文件 SHA-256。每个来源必须是有效 UTF-8 JSON，并符合其声明的 artifact 类型和当前 schema；Encounter Benchmark 和 Guide Snapshot 必须通过规范 JSON 内容 ID 校验，Guide Snapshot 的 Markdown 也必须通过哈希校验，Personal Analysis 必须从其 Complete Bundle 和 Report Index 重新计算。renderer 随后逐项核对文档声明的 Report Revision、Boss Attempt、actor/player、比较硬条件、Benchmark 样本数与置信度、Snapshot ID、Profile ID 及章节隔离。Mechanic Review 来源必须通过上述严格 schema，并记录分页终止及采集前后 Report Revision 已确认；renderer 会逐项核对来源中的身份、规则集、计数、结论、阶段和最小摘录。持久化 Report Document 仍不得保存完整 Mechanic Evidence Set。只有上述校验实际建立后，HTML 才会显示 Complete Bundle 或硬条件已校验。普通 SHA-256 仍只提供本地内容身份和损坏检测，不认证 artifact 的生成者。

`coach guide-report` 是 Raid Guide 的第一方组装路径。它只接受一个已校验 Guide Snapshot JSON artifact，不接受调用方重写章节；派生文档保留精确 Snapshot ID 与 artifact 文件 SHA-256，并按原章节复制 encounter identity、`benchmark_id`、Profile ID、样本数/置信度、指标、本地化技能、机制锚点和来源。每章必须逐项回查同一 Snapshot 章节，禁止跨 Boss 交换同值指标、技能或来源。

校验后的规范 JSON 以排序、紧凑 UTF-8 JSON 的 SHA-256 作为 `document_id`。renderer schema `1` 生成无外部资源的自包含 HTML；HTML 文件名是最终 UTF-8 HTML 字节的 SHA-256。HTML 与 JSON 索引写入 `outputs/reports/<html-sha256>.html` 和同名 `.json`，已有内容必须复用，身份或哈希不匹配时拒绝覆盖。JSON 索引保存规范 Report Document、来源 artifact、renderer schema 和 HTML 哈希。

Report Document 的持久化不改变 Mechanic Evidence Set 的临时性：只允许保存 Agent 选择的结论、计数和最小证据摘录，不得保存完整过滤事件范围。

## 教练 Artifact

个人复盘、Benchmark 和 Guide 只消费通过上述完整性检查的 Complete Bundle，不能重写 Report Index、Fight Bundle 或 Canonical Event。Mechanic Review 是非持久化例外，只消费当前进程中的 Mechanic Evidence Set。

- `profiles/` 保存声明式 Specialization Profile 和 Encounter Profile。Profile 身份包括 game version 与 ranking partition；Encounter Profile 还包括 encounter 和 difficulty。Profile ID 是校验后规范 JSON 的 SHA-256。
- `cohorts/` 保存单一 encounter、difficulty、class、spec 与 partition 的 Ranking Cohort。`cohort_id` 是排除自身 ID 后规范 JSON 的 SHA-256。Ranking Candidate 只有在 Complete Bundle、硬条件和 Encounter Profile eligibility 全部通过后才成为 Reference Sample。
- Encounter Benchmark 只能聚合同一 Ranking Cohort 中至少三个不重复的 Reference Sample，且必须记录准确的 `cohort_id`。`benchmark_id` 是排除自身 ID 后规范 JSON 的 SHA-256。不同 Encounter Designator 必须使用不同 benchmark。
- `tasks/` 保存 Coach Request Manifest。部分完成状态必须保留每个 encounter 的 blocker 与 artifact 引用。
- `guides/` 保存不可变 Guide Snapshot。每个章节记录准确的 `benchmark_id` 和按 ability ID 本地化的章节技能指标；一个 snapshot 可以引用多个 Encounter Benchmark，但不能覆盖旧 snapshot。

个人复盘分析 schema `3` 必须记录 Report Revision、fight ID、actor ID 和比较硬条件。比较身份中的 `game_version` 使用同一 Report Index 中指定 ranking partition 的非空 `compactName`，缺失或为空白时回退该 partition 的非空 `name`；不得使用 WCL `masterData.gameVersion` 数字产品 ID。partition 列表缺失、不是数组、为空、包含非对象、ID 不是正整数（包括布尔值）、ID 重复、名称无效、`compactName` 类型无效或 `default` 不是布尔值时，分析必须失败。指定 ID 不存在时也必须失败，不能猜测默认 partition。分析与 benchmark 的 game version、encounter、difficulty、class、spec 和 partition 不完全相同时，比较必须失败。

Personal Analysis schema `2` 使用旧的 `game_version` 语义，`coach benchmark` 和 `coach compare` 会明确拒绝它；必须重新运行 `coach review` 生成 schema `3`。缺少 ranking partition 字段的旧不可变 Report Index 和引用它的 Complete Bundle 仍可用于不需要 partition 比较身份的操作，但不能用于带 `--partition-id` 的个人复盘；必须先删除对应本地 Report Revision 数据，再重新 `prepare`，不能在原地改写 Report Index 或 manifest hash。

教练 Artifact 只支持本 CLI 在用户本地数据目录或工作目录中生成和消费。普通 SHA-256 不认证生成者；不得把外部提供的 Artifact 当作可信输入。旧 HMAC schema 的 Complete Bundle、Ranking Cohort、Personal Review、Encounter Benchmark 和 Guide Snapshot 不兼容，必须重新生成。
