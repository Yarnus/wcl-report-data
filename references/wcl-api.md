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

建立 Report Index 时会获取 Report Revision、归档状态、Retail 游戏版本、主 actor 与 ability、战斗参与元数据、报告难度元数据和 WCL zone encounter 顺序。`zone.encounters` 只作为当前 `inspect` 的选择元数据返回，不写入已有不可变 Report Index。

战斗难度 ID 只能通过该报告返回的 `zone.difficulties { id name }` 解释。不同 WCL 上下文中的 ID 可能不同，因此不能使用硬编码的全局枚举。

WCL 的 `translate: true` 会把 Report master ability 名称统一为英文，不能指定目标 locale。当前 zhCN 显示名来自仓库随附、带客户端 build 来源的轻量 mapping；WCL GraphQL `gameData.ability` 没有 locale 参数，只返回英文名。

采集战斗时，`Report.events` 使用：

- 一个 `fightID`
- 每一页都传入该战斗固定的 `startTime` 和 `endTime`
- `dataType: All`
- `includeResources: true`
- actor 和 ability ID
- 每页上限 10,000

当多个事件位于同一分页边界时，WCL 返回的事件可能超过请求上限。每次分页请求都必须重复传入战斗 `endTime`；省略它可能导致后续页返回空数据。采集器跟随 `nextPageTimestamp`，保留事件顺序，允许时间戳重复，并拒绝重复游标。

## 限流

客户端会使用指数退避重试临时连接失败，以及 HTTP 500、502、503 和 504 响应。HTTP 429 会立即打开进程内断路器。

执行 WCL 数据查询前，客户端至少保留 15% 或 50 个 API 点数，取两者中较大值。Report Index 查询的成本会随报告元数据增长，因此预留 500 点。事件和 revision 请求为完整重试预算预留点数，并在同一 GraphQL 响应中刷新限流快照。因安全预留而停止后，Raw Page 和检查点会保留，下一次调用可以继续。

## Revision 与归档

最后一个事件页完成后会再次检查 Report Revision。revision 已变化时不能发布 Fight Bundle。下一次调用会创建或使用新的 revision 目录。

归档报告的元数据可能仍然可见，但事件不可访问。只有 WCL 明确表示当前 API 客户端可以访问归档事件时，才能创建 Fight Bundle。
