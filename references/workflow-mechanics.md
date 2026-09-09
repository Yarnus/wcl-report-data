# 机制复盘与优先复核

[English](workflow-mechanics.en.md)。从 [Skill 入口](../SKILL.md) 的对应分支进入；执行前保留入口全部门槛。

当前规则仅覆盖 The Venomous Abyss（zone 53）官方八个团本首领：Nek'zali、Entombed Sentinels、Vashnik、The Lost Explorers、Sszorak、The Twin Fangs、The Coiled Altar、Ula'tek，Normal/Heroic/Mythic；排除世界首领 Nymrissa Wavecaller（3379）。使用包内最新规则，不按报告日期替换历史规则；未验证难度只报告观察。

## 选择与执行

裸报告或 Encounter Designator 先列出候选，等待数字 fight：

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach mechanics "<WCL_REPORT_URL>" --encounter H2
```

用户只要机制事实时执行 compact；要求优先复核时直接 triage：

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach mechanics "<WCL_URL_WITH_NUMERIC_FIGHT>" --compact
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach triage "<WCL_URL_WITH_NUMERIC_FIGHT>"
```

triage 在同一进程复用一个客户端/报告 metadata，执行完整机制分页、revision 复查、候选选择和必要窗口；每个窗口前后检查 revision。失败拒绝合并结果；不生成 Report Index、Raw Page、Fight Bundle、manifest、checkpoint、持久事件缓存或 HTML。

候选仅来自 `verified`、`enabled`、`target` 的完整 `player_anomaly_summary`，跨机制累计 record_count/event_count 降序、actor_id 升序，最多三人。时间来自 compact 展示的 anomaly，逐时间升序、每人最多三个不同时间；仅同一 anomaly 中共享时间的玩家可合并。team scope 保持并列且不参与排序。compact 每条机制至多展示20个玩家异常，但候选统计包含全部；披露 `coverage` 中抑制记录与窗口截断。

异常 outcome=death 使用该时间；其他异常先取窗口，若观察到死亡且其前10秒未被当前窗口覆盖，补一次该玩家的死亡窗口。默认窗口前后10秒，范围截断于 Boss Attempt。结果 `status: no_supported_candidate` 表示没有规则支持的候选，不等于处理正确；此时不请求 focused events、不任意补玩家。

## 额外局部追问

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach evidence "<WCL_URL_WITH_NUMERIC_FIGHT>" --at-ms <TIME_MS> --player-id <ACTOR_ID> --expected-identity <EVIDENCE_IDENTITY>
```

token 原样取自 compact 的 `evidence_identity`，绑定报告/revision/fight；不匹配重跑机制阶段。可用 `--window-ms`（最多30000）和重复 player-id（最多三名明确参与者），仅共享锚点的玩家可一起请求。每人独立完整分页、targetID 请求和本地再次过滤；结果只支持目标收到的允许事件。最多200条，死亡/战复优先、其余距锚点由近到远；按时间显示，使用返回的 actors/abilities 解释 ID。`truncated` 必须披露。不会请求资源或持久化。

回答依次给出身份与击杀/灭团、已验证机制命中时间、窗口内时序事实、已观察团队同时事件、未建立因果。使用“优先复核候选”“并列”“无受支持候选”；团队影响仅复述机制已观察事实，否则“未建立”。需要完整个人表现/Benchmark/全场 Canonical Events 时才 prepare。

## 正式报告

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach mechanics "<WCL_URL_WITH_NUMERIC_FIGHT>" --report --locale zh-CN
```

同一采集进程完整分页及 revision 一致后净化来源、持久化、组装与渲染。只保存身份、规则、计数、支持结论和扁平最小摘录；不保存完整过滤事件或任意 payload。首次失败删除本次新来源，相同内容复用不可变来源。不要从 stdout 重抄完整结果或通用 renderer 绕过采集门槛。返回 source/document/report 身份与路径；交付摘要和 `report.html_path`。英文用 `--locale en`。
