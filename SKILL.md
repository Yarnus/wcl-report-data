---
name: wcl-report-data
description: 分析正式服 Warcraft Logs 团队副本。用户提供 WCL 报告链接、要求机制或个人复盘、询问“谁是战犯”或优先复核谁、需要团队事件数据、询问当前团本指定 Boss 和专精的高分日志攻略，或询问“如何使用”“能做什么”、how to use、what can this skill do 时使用。
slug: wcl-report-data
displayName: WCL 团队副本教练
version: 3.4.1
summary: 准备可复现的全团证据，复核首领机制与个人表现，并从当前高分日志生成 Boss 攻略。
license: MIT
homepage: https://github.com/Yarnus/wcl-report-data
compatibility: 需要 Python 3.11+、互联网连接，以及用户自己的 Warcraft Logs API 客户端凭据。
metadata:
  tags: [warcraft-logs, world-of-warcraft, raid, coaching]
---

# WCL 团队副本教练

使用用户当前语言回答。先定位同时包含本文件和 `wcl_raid_coach/` 的 `<SKILL_ROOT>`；每条 bundled CLI 命令从该目录运行。数据、缓存与宿主选择的可写 `<WORK_DIR>` 位于 Skill 根目录之外。尖括号是待替换参数。CLI stdout 始终是 JSON。

## 路由与首次动作

只读取命中工作流的文档；不要预先加载所有 references。

| 请求 | 首次动作与必读文档 |
| --- | --- |
| 使用帮助：如何使用、能做什么、how to use | 直接输出下方菜单，不运行 CLI、不访问 WCL |
| 报告数据，缺少数字 fight | `inspect` 列出 Boss Attempt/参与者，等待明确选择 |
| 报告数据，已明确选择 | 直接 `prepare`；同一报告多个选择使用一次批量命令 |
| 机制复盘 | 先读[机制与优先复核](references/workflow-mechanics.md)，数字 fight 用 `coach mechanics`，裸报告列出选择 |
| 谁是战犯、谁失误最大、优先复核候选 | 先读[机制与优先复核](references/workflow-mechanics.md)，数字 fight 直接 `coach triage` |
| 个人复盘 | 先读[个人复盘](references/workflow-personal.md)；明确 attempt/player 后立即 `coach personal-workflow-init`，早于所有 retrieval/Profile synthesis |
| 当前团本多 Boss 专精攻略 | 先读[攻略](references/workflow-guide.md)，`coach resolve` 后展示解析身份并等待确认 |
| 混合请求 | 先个人复盘；仅在用户明确要求时追加同 Boss 通用攻略 |

## 使用帮助

说明需要用户自己的 WCL API 凭据，仅支持 Retail 团本公开或未列出报告；提醒不要在对话粘贴 secret。简短列出以下菜单后结束：

- 报告数据：“列出这份报告的 Boss Attempt 和参与者：<WCL_URL>”
- 机制复盘：“复核这场机制处理：<WCL_URL_WITH_NUMERIC_FIGHT>”
- 优先复核候选：“快速看看谁最值得复核：<WCL_URL_WITH_NUMERIC_FIGHT>”
- 个人复盘：“复盘我的表现，角色是 <角色名>：<WCL_URL>”
- 通用攻略：“给我邪恶死亡骑士打当前团本 H7、H8 的攻略。”

## 环境与数据

首次访问 WCL 前运行；凭据或存储不可用时读[配置](references/setup.md)。用户已选定个人复盘对象时，先初始化 workflow 再运行任何网络检查。

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach doctor
```

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach inspect "<WCL_URL>"
cd "<SKILL_ROOT>" && python -m wcl_raid_coach prepare "<WCL_URL_WITH_NUMERIC_FIGHT>"
cd "<SKILL_ROOT>" && python -m wcl_raid_coach prepare "<WCL_URL>" --fight <ID_1> --fight <ID_2>
cd "<SKILL_ROOT>" && python -m wcl_raid_coach query "<MANIFEST_PATH>" --type damage --source-id <ACTOR_ID>
```

已明确选择时省略独立 inspect；批量 prepare 共享一次报告元数据查询，仅包含用户明确选择。inspect/prepare/query 不初始化展示映射，不返回 `ability_names`；inspect 使用有效本地 content mapping，否则保留 WCL 原名并返回 `content_names: null`。

## 必须保留的边界

- 只用官方 OAuth/WCL v2 GraphQL 建立日志事实。凭据由宿主私密配置提供；不请求、打印、记录或持久化 secret/access token。
- 仅支持 Retail 团本、公开/未列出报告。混合 Mythic+ 报告仅选择团本 Boss Attempt；不支持 Classic、私有报告、历史团本通用攻略，不静默转换请求。
- 无数字 fight 时等待明确选择；不自动选最后一次、击杀场、全部尝试或 source hint。Encounter Designator 不是数字 fight ID。个人复盘还须明确参与者。
- Personal Review/Benchmark/Guide 只用 Complete Bundle：显式 `nextPageTimestamp: null`、Boss Attempt 范围、完整 hash 校验及单一 Report Revision。Mechanic Review/triage 仅用进程内证据；不建立持久玩家历史或额外玩家事件缓存。
- 个人复盘选定后立即初始化计时；复用 Benchmark 必须连同绑定的原 Ranking Cohort、Profiles 和 Complete Bundles 深度验证。先查本地兼容 artifact，再刷新排名。初始目标 3 个合格 Reference Samples，已有 3–10 个立即使用。
- 机制异常不证明责任或灭团因果。judgment/causal_attribution 为 null；团队事实保持并列。没有当前 Profile/规则证据不判断 padding、责任或可规避伤害；坦克/治疗建议遵守相应生存/治疗 guardrail。
- 中文建议和攻略 Spell 必须命中已校验的 zhCN mapping，不自行翻译。普通数据可保留 WCL 原名，机制名称使用随包规则。未知维度明确未评估。
- 限流遵循同一 OS 用户的共享调度，保留至少 15% 或 50 点的较高者。失败保留已有持久进度；临时机制证据无 checkpoint，需重跑。多 Boss 可交付已完成章节并披露 blocker。
- 正式交付使用 `personal-report`、`guide-report` 或 `mechanics --report` 的确定性来源校验和渲染；对话给短摘要与 HTML 链接。选择、进度、错误、查询和追问使用文本；用户明确不要报告时遵从。详细 schema 仅在构造 artifact 时读[数据契约](references/data-contract.md)，API/恢复问题读[API 说明](references/wcl-api.md)。
