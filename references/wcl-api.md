# Warcraft Logs API 说明

本文记录影响采集与恢复行为的 API 约束。[English version](wcl-api.en.md)

## 认证

- Token 端点：`https://www.warcraftlogs.com/oauth/token`
- GraphQL 端点：`https://www.warcraftlogs.com/api/v2/client`
- 接受的报告域名：`warcraftlogs.com`、`www.warcraftlogs.com` 和 `cn.warcraftlogs.com`
- 授权方式：OAuth2 client credentials
- 规范变量名：`WCL_CLIENT_ID`、`WCL_CLIENT_SECRET`
- 兼容变量名：`WCL_ID`、`WCL_SECRET`

CN 报告链接可直接作为输入，并会规范化为全球站报告链接。认证和 GraphQL 请求仍使用 WCL 官方全球端点。

已知报告代码时，client credentials 可以读取公开和未列出报告。它不能读取需要用户 OAuth 的私有报告。access token 只保存在进程内存中。

## 查询

建立 Report Index 时会获取 Report Revision、归档状态、Retail 游戏版本、主 actor 与 ability、战斗参与元数据、报告难度元数据、ranking partition 的 `id`、`name`、`compactName`、`default`，以及 WCL zone encounter 顺序。严格校验并规范化后的 `zone.partitions` 写入不可变 Report Index，供 Personal Analysis 解析比较身份；`zone.encounters` 只作为当前 `inspect` 的选择元数据返回，不写入已有不可变 Report Index。

通用攻略解析通过 `worldData.zones` 获取当前未冻结的 Retail raid zone、原始 encounter 顺序、difficulty 和默认 partition。必须恰好得到一个当前 zone、一个 Heroic difficulty 和一个默认 partition；否则停止，不能猜测。

排名候选通过官方 `Encounter.characterRankings` 查询，并传入精确 encounter、difficulty、partition、class 和 spec，使用 `externalBuffs: Exclude` 排除 major external buffs。返回的排名 JSON 仍是不可信输入。WCL 排名通常不返回 source ID；CLI 必须通过候选报告的 actor/fight metadata 唯一补全后，候选才能进入内容寻址的近期 Ranking Cohort。

战斗难度 ID 只能通过该报告返回的 `zone.difficulties { id name }` 解释。不同 WCL 上下文中的 ID 可能不同，因此不能使用硬编码的全局枚举。

WCL 的 `translate: true` 会把 Report master ability 名称统一为英文，不能指定目标 locale。当前 zhCN 显示名来自首次使用时由 Wago Tools 下载、带客户端 build 来源的完整本地 mapping；WCL GraphQL `gameData.ability` 没有 locale 参数，只返回英文名。

采集战斗时，`Report.events` 使用：

- 一个 `fightID`
- 每一页都传入该战斗固定的 `startTime` 和 `endTime`
- `dataType: All`
- `includeResources: true`
- actor 和 ability ID
- 每页上限 10,000

当多个事件位于同一分页边界时，WCL 返回的事件可能超过请求上限。每次分页请求都必须重复传入战斗 `endTime`；省略它可能导致后续页返回空数据。采集器跟随 `nextPageTimestamp`，保留事件顺序，允许时间戳重复，并拒绝重复游标。

Mechanic Review 使用独立的 `Report.events` 查询：单一数字 `fightID`、首页面以 Boss Attempt 起点作为 `startTime`、后续页以当前游标作为 `startTime`、固定 Boss Attempt `endTime`、`dataType: All`、actor/ability ID、每页上限 10,000，以及由当前规则集 ability ID 加 `death`、`interrupt`、`dispel` 组成的服务端 `filterExpression`。它不请求 `includeResources`。返回事件必须处于当前页游标和固定结束时间之间，并最终到达 `nextPageTimestamp: null`。

Focused Evidence Window 使用独立的 `Report.events` 查询，范围是显式 fight-relative 锚点前后的短窗口。它为每个 Boss Attempt 参与者分别传入 WCL `targetID`，再在本地按返回事件的报告 actor ID 与伤害、治疗、吸收、光环、死亡、战复类型白名单过滤。它不请求 `includeResources`，每个参与者都必须到达 `nextPageTimestamp: null`，全部完成后复查一次 Report Revision。

## 限流

客户端会使用指数退避重试临时连接失败，以及 HTTP 500、502、503 和 504 响应。HTTP 429 会立即打开进程内断路器。

执行 WCL 数据查询前，客户端至少保留 15% 或 50 个 API 点数，取两者中较大值。Report Index 查询的成本会随报告元数据增长，因此预留 500 点。事件和 revision 请求为完整重试预算预留点数，并在同一 GraphQL 响应中刷新限流快照。持久化采集因安全预留而停止后会保留 Raw Page 和检查点；Mechanic Review 不落盘，必须从头重试。

WCL client secret 只用于 OAuth，不参与本地 Artifact 身份。Ranking Cohort 和 Encounter Benchmark 使用规范 JSON 的 SHA-256 内容 ID；Complete Bundle 使用 Report Index、Raw Page、压缩事件文件和 Canonical Event 内容 hash。它们只支持本地生成和消费，hash 不认证来源。

## Revision 与归档

最后一个事件页完成后会再次检查 Report Revision。revision 已变化时不能发布 Fight Bundle，也不能返回 Mechanic Review 结果。持久化采集的下一次调用会创建或使用新的 revision 目录；Mechanic Review 重新采集临时证据。

归档报告的元数据可能仍然可见，但事件不可访问。只有 WCL 明确表示当前 API 客户端可以访问归档事件时，才能创建 Fight Bundle 或执行 Mechanic Review。
