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

同一 WCL Report 的明确选择应使用一次批量 `prepare`，共享一次 Report Index 查询；每个 Boss Attempt 仍独立检查采集结束时的 Report Revision。一次候选发现中的 WclClient 按 `(report_code, fight_id)` 在内存复用 actor/fight metadata，每个候选仍独立匹配角色、服务器、职业和专精，歧义身份拒绝。缓存不持久化，也不作为 Complete Bundle 资格或 Report Revision 的证明。

建立 Report Index 时会获取 Report Revision、归档状态、Retail 游戏版本、主 actor 与 ability、战斗参与元数据、报告难度元数据、ranking partition 的 `id`、`name`、`compactName`、`default`，以及 WCL zone encounter 顺序。严格校验并规范化后的 `zone.partitions` 写入不可变 Report Index，供 Personal Analysis 解析比较身份；`zone.encounters` 只作为当前 `inspect` 的选择元数据返回，不写入已有不可变 Report Index。

通用攻略解析通过 `worldData.zones` 获取当前未冻结的 Retail raid zone、原始 encounter 顺序、difficulty 和默认 partition。必须恰好得到一个当前 zone、一个 Heroic difficulty 和一个默认 partition；否则停止，不能猜测。

排名候选通过官方 `Encounter.characterRankings` 查询，并传入精确 encounter、difficulty、partition、class 和 spec，使用 `externalBuffs: Exclude` 排除 major external buffs。返回的排名 JSON 仍是不可信输入。WCL 排名通常不返回 source ID；CLI 必须通过候选报告的 actor/fight metadata 唯一补全后，候选才能进入内容寻址的近期 Ranking Cohort。

Personal Review 的排名发现与样本资格是两个阶段：Ranking Candidate 只有在 Complete Bundle、硬条件和 Encounter Profile eligibility 均通过后才成为 Reference Sample。新建 Personal Review 以 3 个 Reference Samples 为交付目标，拒绝候选后按 Cohort 中的稳定 `report_code:fight_id:source_id` 身份补位；Raid Guide 和底层 `coach candidates` 的默认目标仍为 10。Ranking Cohort 保留最后一次已查询的完整去重页，并记录真实已查询页范围、WCL `hasMorePages`、`target_reached`、本地 `truncated` 和派生的 `exhausted`；因此达到目标后的同页候选无需重新请求即可补位。只有 `hasMorePages` 非 true 且结果未截断时才能证明 page exhaustion。预算关闭、已证明的 page exhaustion、API failure 或 WCL 429 断路器会在下一项可选工作前停止调度，但不会取消已在途请求或破坏 Raw Page/checkpoint。
交付的 finalization artifact 记录从 workflow 选择开始、经过验证/锁/持久化直到 HTML 和 index 哈希确认后的 elapsed、`target_met` 与 `completion_status`。计时连续性要求 monotonic clock 不倒退，且当前 wall-minus-monotonic baseline 与持久化 baseline 的差值不超过记录的 tolerance；否则保留进度但停止可选采集和连续计时。session marker 只是持久化 metadata 和本地诊断信息，不参与严格相等比较。

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

Focused Evidence Window 使用独立的 `Report.events` 查询，范围是显式 fight-relative 锚点前后的短窗口。它为每个 Boss Attempt 参与者分别传入 WCL `targetID`，再在本地按返回事件的报告 actor ID 与伤害、治疗、吸收、光环、死亡、战复类型白名单过滤。调用方必须传入前一阶段绑定 WCL Report、Report Revision 和 Boss Attempt 的预期身份；采集开始前必须匹配，每个参与者都必须到达 `nextPageTimestamp: null`，全部完成后再次匹配 Report Revision。它不请求 `includeResources`。

## 限流

`coach triage` 使用一个 WclClient、一次完整报告元数据查询，并复用内存 token。Mechanic Review 完成后检查 Report Revision；每个 Focused Evidence Window 开始前再查 revision，分页完成后再次检查。窗口沿用 targetID、固定范围、显式 null 分页终止和本地参与者过滤。任何阶段 API 错误、共享冷却或 revision 改变都会拒绝合并结果，不持久化事件证据。

全局 `--diagnostics` 可单独测量本次调用的 OAuth、quota probe、GraphQL 和重试的 HTTP 次数、接收正文字节与 monotonic 网络耗时；首末有效额度快照只是观测，不能排除其他客户端消费。它不修改 workflow 的 `wcl_network_measurement` 或 `target_met`；详见[诊断边界](performance.md)。

客户端会使用指数退避重试临时连接失败，以及 HTTP 500、502、503 和 504 响应。每次 OAuth、quota probe、GraphQL 和重试 HTTP attempt 都经过同一 OS 用户的文件锁；HTTP 429 会立即打开进程内断路器，并写入共享冷却状态，阻止其他 workspace 或 data root 的新请求。

执行 WCL 数据查询前，客户端至少保留 15% 或 50 个 API 点数，取两者中较大值。Report Index 查询的成本会随报告元数据增长，因此预留 500 点。事件和 revision 请求为完整重试预算预留点数，并在同一 GraphQL 响应中刷新限流快照。持久化采集因安全预留而停止后会保留 Raw Page 和检查点；Mechanic Review 不落盘，必须从头重试。

共享入口进一步在每次 HTTP attempt 前保守扣除 Report Index 的 500 点或其他 GraphQL 的 10 点；未得到新额度观测的失败保留扣除值。OAuth 不假定点数成本。有效共享快照可满足 quota 初始化，不发重复 probe；诊断中的额度观测只计实际 API 响应。其他客户端仍可消费额度，不能保证服务器永不返回 429。

冷却优先使用合法 `Retry-After` 秒数或 HTTP date，其次使用仍可靠的额度 reset 时间，否则采用 60 秒。冷却期间立即返回 `wcl_rate_limit`，不睡完整额度窗口；错误提供共享冷却或已知 reset 的 Unix 时间。过期后只在文件锁内 probe，成功后其他进程复用观测，再次 429 会重建冷却。失效快照或中断请求后的普通查询要求先运行 `doctor` 刷新。损坏状态和时钟连续性异常返回领域错误，不能自动恢复为满额度。

WCL client secret 只用于 OAuth，不参与本地 Artifact 身份。Ranking Cohort 和 Encounter Benchmark 使用规范 JSON 的 SHA-256 内容 ID；Complete Bundle 使用 Report Index、Raw Page、压缩事件文件和 Canonical Event 内容 hash。它们只支持本地生成和消费，hash 不认证来源，也不能抵抗可同时修改 artifact 与 index 的本地进程。Personal Review 的 180/30 秒是协作式本地 workspace 内的 monotonic/wall-clock 测量，`wcl_network_measurement` 为 `not_measured`，不是 WCL 网络 benchmark。

## Revision 与归档

最后一个事件页完成后会再次检查 Report Revision。revision 已变化时不能发布 Fight Bundle，也不能返回 Mechanic Review 结果。持久化采集的下一次调用会创建或使用新的 revision 目录；Mechanic Review 重新采集临时证据。

归档报告的元数据可能仍然可见，但事件不可访问。只有 WCL 明确表示当前 API 客户端可以访问归档事件时，才能创建 Fight Bundle 或执行 Mechanic Review。

Personal Review 在选定 Boss Attempt/玩家后立即运行 `coach personal-workflow-init`，早于目标 Complete Bundle retrieval、Ranking Candidate discovery 和 Profile retrieval/synthesis；初始化只持久化所选 report/fight/actor 身份及内部 clock origin。后续 `coach personal-workflow --previous-workflow` 将 Analysis、Ranking Cohort 和 Profiles 绑定到该身份，调用间隔计入 elapsed，所以总 elapsed 覆盖候选/Profile/Agent 工作。WCL 网络仍标为 `not_measured`；Agent synthesis 无法单独计时，finalization 将其标为 `unavailable`，最终 `target_met` 为 `null`。
