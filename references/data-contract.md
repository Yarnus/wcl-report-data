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

某次输入特有的战斗选择和 source hint 由 `inspect` 返回，不写入不可变的 Report Index。source hint 绝不能过滤 actor 或事件。

`inspect` 还按 WCL `zone.encounters` 的原始数组顺序返回一基的 `encounter_choices`。该列表用于解释 Encounter Designator，是当前查询的选择元数据，不写入已有 Report Index。数组项不得排序或按报告中出现过的首领过滤。

战斗的 `difficulty` 是 WCL 返回的原始数字 ID。消费者必须使用同一报告中的 `report.zone.difficulties` 解析它，不能使用静态全局映射。`inspect` 返回的精简 `selected_fight` 和 `fight_choices` 包含解析后的 `difficulty_name`；无法匹配时返回 `null`，不能猜测难度名称。

## Fight Bundle

`manifest.json` 最后写入。它存在且 `complete: true` 表示：

1. 所有 WCL 事件页最终到达 `nextPageTimestamp: null`。
2. 分页游标没有重复。
3. 事件时间戳保持有序。
4. 采集结束后 Report Revision 没有变化。
5. `events.jsonl.gz` 已关闭并计算哈希。

所有分页都使用相同且包含边界的战斗开始与结束时间。旧采集协议生成的 Bundle 会被拒绝，必须重新准备。

manifest 记录按类型统计的事件数量、Raw Page 哈希、规范事件流哈希、采集选项和未知字段计数。

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

已知 `fields` 覆盖数值、减伤、治疗、资源、生命值、光环层数、施法、首领战元数据、战斗人员装备与天赋，以及观测到的战斗属性。WCL 事件 JSON 并非固定不变。新键会计入 `unknown_fields`，其值只保留在 Raw Page 缓存中，直到 schema 明确接纳这些字段。

## 查询契约

`query` 以流式方式读取 gzip 文件，最多返回 `limit` 行。`matched` 统计输入游标之后的所有匹配行。`truncated` 为 true 时，`next_cursor` 是最后一条已返回事件的 sequence，可用于下一次查询。

时间过滤使用 `fight_time_ms`，上下界均包含在结果中。
