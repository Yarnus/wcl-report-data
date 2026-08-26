# wcl-report-data

`wcl-report-data` 是一个面向 WorkBuddy 的 Agent Skill 和 Python 3.11 软件包，用于把正式服 Warcraft Logs 团队副本报告整理为按修订版本保存的全团数据集。它只使用 WCL 官方 OAuth 和 GraphQL API，不抓取报告网页。

首个版本只准备事实数据，不判断伤害是否可规避，不为死亡归责，不比较排名，也不生成复盘结论。

## 环境要求

- WorkBuddy 网页版或 Python 3.11+
- 能够访问 `warcraftlogs.com`
- Warcraft Logs API v2 client ID 和 client secret

运行时没有第三方 Python 依赖。

## WorkBuddy 配置

自行创建 `/workspace/.env`，不要在对话中粘贴文件内容：

```dotenv
WCL_CLIENT_ID=your-client-id
WCL_CLIENT_SECRET=your-client-secret
```

CLI 也兼容成对出现的 `WCL_ID` 和 `WCL_SECRET`。进程环境变量优先于 `.env`。凭据和 access token 不会写入数据集、缓存或命令输出。

运行环境检查：

```bash
python -m wcl_report_data doctor
```

WorkBuddy 默认把数据集保存到 `/workspace/wcl-report-data/`，把可续传原始页保存到 `/workspace/.cache/wcl-report-data/`。可通过 `WCL_REPORT_DATA_HOME` 或 `WCL_REPORT_DATA_CACHE` 覆盖路径。

## 基本流程

建立报告索引：

```bash
python -m wcl_report_data inspect "https://www.warcraftlogs.com/reports/<code>"
```

准备 URL 中已选择的战斗：

```bash
python -m wcl_report_data prepare "https://www.warcraftlogs.com/reports/<code>#fight=12"
```

准备指定战斗或某个首领的全部已完成尝试：

```bash
python -m wcl_report_data prepare "https://www.warcraftlogs.com/reports/<code>" --fight 12 --fight 15
python -m wcl_report_data prepare "https://www.warcraftlogs.com/reports/<code>" --encounter 3129
```

查询完整 Fight Bundle，避免把整个事件流放入模型上下文：

```bash
python -m wcl_report_data query "/workspace/wcl-report-data/reports/<code>/revisions/<revision>/fights/12/manifest.json" \
  --type damage --target-id 17 --limit 200
```

完整流程参见 `python -m wcl_report_data --help` 和 `SKILL.md`。

## 数据布局

```text
reports/<report-code>/
├── latest.json
└── revisions/<revision>/
    ├── report.json
    └── fights/<fight-id>/
        ├── manifest.json
        └── events.jsonl.gz
```

同一报告修订版本内的 Fight Bundle 不可变。报告重新导出后会创建新的 revision 目录。WCL 原始页单独压缩保存，使中断的下载可以继续，也便于审计已知字段规范化过程。

事件分页会在每一页固定传入该战斗的 `startTime` 和 `endTime`。省略 `endTime` 可能导致后续页错误返回空数据；旧采集协议生成的 Bundle 会被拒绝并要求重新准备。

规范事件流会有意省略未知字段值。`manifest.json` 会列出每个未知字段名和出现次数。清除原始缓存后，这些未知值的本地副本也会被删除。

## 隐私

报告索引保留角色名和服务器，以便后续团队复盘识别参与者。数据保留在 WorkBuddy 工作区中，但对话里展示的事件内容可能由当前配置的模型服务商处理。

## 开发

```bash
python -m unittest -v
python -m compileall -q wcl_report_data tests
```

使用同一环境中的凭据执行真实检查：

```bash
python -m wcl_report_data doctor
python -m wcl_report_data inspect "<PUBLIC_WCL_URL>"
```

本项目与 Warcraft Logs 或 Blizzard Entertainment 没有关联。使用时请遵守 Warcraft Logs API 访问规则和限流要求。
