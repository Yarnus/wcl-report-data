---
name: wcl-report-data
description: 从正式服 Warcraft Logs 团队副本报告中准备结构化的全团数据。当用户提供 WCL 报告链接、需要下载报告或战斗数据、希望为后续复盘整理事件，或需要团队死亡与承伤分析的机器可读数据基础时使用。
slug: wcl-report-data
displayName: WCL 团队报告数据
version: 1.0.7
summary: 为 WorkBuddy 准备按报告修订版本保存的正式服 WCL 全团数据集。
license: MIT
homepage: https://github.com/Yarnus/wcl-report-data
compatibility: 需要 WorkBuddy 或 Python 3.11+、互联网连接，以及用户自己的 Warcraft Logs API 客户端凭据。
metadata:
  tags: [warcraft-logs, world-of-warcraft, raid, structured-data]
---

# WCL 团队报告数据

把 Warcraft Logs 官方数据准备为可复现的全团事实。使用中文返回结构化结果和文件路径。战斗指导、可规避伤害分类和责任判断属于后续独立工作，不在本 Skill 中完成。

在本 Skill 目录中使用 `python -m wcl_report_data` 运行命令。CLI 始终向标准输出写入 JSON。

## 工作流程

### 1. 检查运行环境

首次请求 WCL 前运行：

```bash
python -m wcl_report_data doctor
```

`doctor` 已返回 `wcl_api: reachable` 时直接继续，不要求用户创建 `.env`。凭据不可用时，引导用户阅读 [WorkBuddy 配置](references/workbuddy-setup.md)。可以主动帮助创建 `.env`：先让用户只提供或确认真实 workspace 目录路径，不得询问凭据值；检查 `<WORKSPACE>/.env` 是否存在，已有文件绝不能覆盖；不存在时创建只含空白 `WCL_CLIENT_ID=` 和 `WCL_CLIENT_SECRET=` 的模板，再让用户通过文件编辑器私下填写。`/workspace` 确实存在时可直接使用 `/workspace/.env`；其他路径在所有后续 WCL 命令中使用全局参数 `--env-file "<WORKSPACE>/.env"`。绝不能在对话中粘贴、检查或输出 client secret。

完成标准：Python 不低于 3.11，数据和缓存目录均可写，WCL 认证成功。

### 2. 建立报告索引

对每个报告 URL 运行：

```bash
python -m wcl_report_data inspect "<WCL_URL>"
```

可直接使用 `warcraftlogs.com`、`www.warcraftlogs.com` 或 `cn.warcraftlogs.com` 的正式服报告链接。CN 报告链接会规范化为全球站链接，报告数据仍通过 WCL 官方 OAuth 和 GraphQL 端点读取。

索引始终覆盖报告中的整个团队。URL 的 `source` 参数只作为输入提示记录，绝不能用于过滤参与者或事件。

- 没有 `fight`：返回 `fight_choices`，等待用户选择单场战斗、一个首领的全部尝试或全部已完成首领战。
- 数字 `fight`：使用该战斗继续第 3 步。
- `fight=last`：使用报告顺序中的实际最后一场。如果它是小怪战或仍在进行，返回 `unpackable_reason` 并等待用户重新选择。

战斗选项应保持紧凑，只包含 fight ID、首领、击杀或灭团、`difficulty_name`、时长、进度、参与人数和是否可打包。难度名称必须使用同一报告 `zone.difficulties` 解析出的 `difficulty_name`；不得用静态数字表猜测 `difficulty` 是 Normal、Heroic 还是 Mythic。不得静默选择其他战斗。

完成标准：`index_path` 指向的 `report.json` 已存在；报告属于正式服、公开或未列出；每场可选战斗都有明确数字 ID。

### 3. 准备指定战斗

准备 URL 中已选择的一场战斗：

```bash
python -m wcl_report_data prepare "<WCL_URL_WITH_NUMERIC_FIGHT>"
```

从裸报告 URL 准备明确指定的多场战斗：

```bash
python -m wcl_report_data prepare "<WCL_URL>" --fight 12 --fight 15
```

准备某个首领的全部已完成尝试：

```bash
python -m wcl_report_data prepare "<WCL_URL>" --encounter 3129
```

只有用户明确要求全部已完成首领战时，才能使用 `--all-boss-fights`。开始大批量任务前，先报告索引中的战斗数量和当前限流状态。

采集器会在临时错误后从原始页检查点继续。遇到 `wcl_rate_limit` 时应保留已完成数据，稍后继续。只有 `manifest.json` 中 `complete: true` 的 Fight Bundle 才可使用。

完成标准：每场指定战斗都返回 `manifest_path`；小怪战、进行中战斗、未完成分页或混合报告修订版本的数据绝不能标记为完整。

### 4. 查询事件，避免挤占上下文

使用 `prepare` 返回的 manifest 路径：

```bash
python -m wcl_report_data query "<MANIFEST_PATH>" --type damage --target-id 17
```

可用过滤条件包括 `--type`、`--source-id`、`--target-id`、`--ability-id`、`--from-ms`、`--to-ms` 和 `--cursor`。默认最多返回 200 条。`truncated` 为 true 时，使用 `next_cursor` 继续或进一步缩小过滤范围。

查询结果是证据，不是结论。没有独立的首领机制知识来源时，不得把伤害标记为可规避、推断责任，或声称某次死亡可以避免。

完成标准：每个返回事件都能通过 `raw_ref` 回指原始页，查询结果不超过指定上限。

## 数据管理

查看已准备的数据集和原始缓存：

```bash
python -m wcl_report_data dataset list
python -m wcl_report_data cache status
```

删除操作必须显式确认：

```bash
python -m wcl_report_data dataset remove <REPORT_CODE> --confirm
python -m wcl_report_data cache clear --confirm
```

直接消费文件或构建后续分析时阅读 [数据契约](references/data-contract.md)。WCL 响应变化、分页失败或归档报告无法访问时阅读 [WCL API 说明](references/wcl-api.md)。

## 使用边界

- 仅支持正式服团队副本；不支持怀旧服和 Mythic+。
- 仅支持公开和未列出报告；私有报告需要用户 OAuth，当前不支持。
- 只使用 WCL 官方 OAuth 和 GraphQL 端点；不抓取网页，不做浏览器自动化。
- 只打包已完成的首领战；索引可列出小怪战和进行中战斗，但不能打包。
- 规范事件保留已知字段。未知字段的名称和次数会明确记录，未知值只保留在原始页缓存中。
- 角色名和服务器保留在本地数据集中。除官方 WCL API 请求外，不向其他位置发送数据。
- 本 Skill 只准备数据，不分类机制、不评价玩家，也不生成复盘结论。
