# wcl-report-data

<p align="center">
  <img src="assets/timewarp-inn-dog.svg" width="220" alt="大黄狗守护时空旅馆的原创奇幻图标">
</p>

`wcl-report-data` 是一个面向 WorkBuddy 的 Agent Skill 和 Python 3.11+ 软件包，用于把正式服 Warcraft Logs 团队副本报告整理为按 Report Revision 保存的、可复现的全团事实数据集。

它只使用 WCL 官方 OAuth 和 GraphQL API，不抓取报告网页。首个版本只准备事实数据，不判断伤害是否可规避、不为死亡归责、不比较排名，也不生成复盘结论。

[English documentation](README.en.md)

## 适用范围

- 支持 Retail 团队副本；不支持怀旧服和 Mythic+。
- 支持公开和未列出报告；私有报告需要用户 OAuth，当前不支持。
- 支持 `warcraftlogs.com`、`www.warcraftlogs.com` 和 `cn.warcraftlogs.com` 报告链接。
- CN 链接会规范化为全球站链接，API 请求仍使用 WCL 官方全球端点。
- 运行时只依赖 Python 标准库，不需要第三方 Python 包。

## 快速开始

环境要求：Python 3.11+、可访问 `warcraftlogs.com`，以及 Warcraft Logs API v2 client ID 和 client secret。

从仓库根目录或已安装的 Skill 目录运行 CLI：

```bash
python -m wcl_report_data doctor
```

确认输出中的 `wcl_api` 为 `reachable` 后，建立报告索引：

```bash
python -m wcl_report_data inspect "https://www.warcraftlogs.com/reports/<code>"
```

准备 URL 中选中的战斗：

```bash
python -m wcl_report_data prepare "https://www.warcraftlogs.com/reports/<code>#fight=12"
```

也可以从裸报告 URL 准备指定战斗，或准备某个首领的全部已完成尝试：

```bash
python -m wcl_report_data prepare "https://www.warcraftlogs.com/reports/<code>" --fight 12 --fight 15
python -m wcl_report_data prepare "https://www.warcraftlogs.com/reports/<code>" --encounter 3129
```

通过返回的 manifest 查询事件，避免把整个事件流放入模型上下文：

```bash
python -m wcl_report_data query \
  "/workspace/wcl-report-data/reports/<code>/revisions/<revision>/fights/12/manifest.json" \
  --type damage --target-id 17 --limit 200
```

CLI 始终向标准输出写入 JSON，领域错误也会返回结构化 JSON。完整参数参见 `python -m wcl_report_data --help`，完整工作流参见 [Skill 使用说明](SKILL.md)。

## Encounter Designator 与技能名称

Skill 能理解 `PT6`、`H6`、`M6` 形式的 Encounter Designator。前缀分别表示 Normal、Heroic、Mythic，数字表示 WCL `zone.encounters` 原始列表中的一基位置。Designator 只确定难度和 encounter；同一报告有多次匹配 Boss Attempt 时，Skill 必须列出明确的 fight ID 等待选择，不能自动选择击杀、最后一次或全部尝试。

[zhCN ability mapping](references/ability-names.zhCN.json) 提供当前 Retail 客户端的官方中文显示名。只有 ID 同时存在于 Report Index 的 `abilities[].gameID` 时才可使用 mapping；缺失时保留 WCL 名称，不进行直译。中文名是当前客户端展示 enrichment，不改写 Report Index，使用时同时保留 ability ID、WCL 原名和 [mapping build metadata](references/ability-names.zhCN.meta.json)。

## 凭据配置

进程环境变量优先于 `.env` 文件。推荐使用规范名称：

```dotenv
WCL_CLIENT_ID=
WCL_CLIENT_SECRET=
```

CLI 也兼容成对出现的 `WCL_ID` 和 `WCL_SECRET`。需要使用明确路径时，把全局参数放在子命令之前：

```bash
python -m wcl_report_data --env-file "<WORKSPACE>/.env" doctor
python -m wcl_report_data --env-file "<WORKSPACE>/.env" inspect "<WCL_URL>"
```

AI 不应要求用户在对话中提供或粘贴 secret，不应覆盖已有 `.env`，也不应输出 client secret 或 access token。详细规则参见 [WorkBuddy 配置](references/workbuddy-setup.md) 和 [English setup guide](references/workbuddy-setup.en.md)。

## 数据布局

默认数据目录取决于运行环境：存在 `/workspace` 时使用 `/workspace/wcl-report-data/`；本地 Unix/macOS 使用 `~/.local/share/wcl-report-data/`；Windows 使用 `%LOCALAPPDATA%/wcl-report-data/`。可用 `WCL_REPORT_DATA_HOME` 覆盖。

原始页和可续传检查点默认放在 `/workspace/.cache/wcl-report-data/` 或 `~/.cache/wcl-report-data/`，Windows 使用 `%LOCALAPPDATA%` 下的 `wcl-report-data/Cache`。可用 `WCL_REPORT_DATA_CACHE` 覆盖。

```text
reports/<report-code>/
├── latest.json
└── revisions/<revision>/
    ├── report.json
    └── fights/<fight-id>/
        ├── manifest.json
        └── events.jsonl.gz
```

同一 Report Revision 内的 Fight Bundle 不可变。重新导出报告会创建新的 revision 目录；`latest.json` 只是指针，可复现的消费者应使用 manifest 中记录的 revision。原始页单独压缩保存，以便中断下载继续并审计字段规范化过程。

## 数据与安全边界

- 只有 `manifest.json` 中 `complete: true` 的 Fight Bundle 才能被后续分析使用。
- Complete Bundle 必须到达显式的 `nextPageTimestamp: null`，事件时间戳有序，未跨 Report Revision，并通过文件哈希校验。
- 所有分页请求都重复传入该战斗的固定 `startTime` 和 `endTime`；旧采集协议生成的 Bundle 会被拒绝并要求重新准备。
- Canonical Event 只保留已知字段；未知字段名和次数写入 manifest，未知值留在 Raw Page 缓存中。
- 角色名和服务器会保留在本地数据集，以便识别团队成员；对话中展示的数据可能由当前配置的模型服务商处理。
- 查询结果是证据，不是结论。没有独立的首领机制知识来源时，不得把伤害标记为可规避或推断责任。

## 数据管理

```bash
python -m wcl_report_data dataset list
python -m wcl_report_data cache status
python -m wcl_report_data dataset remove <REPORT_CODE> --confirm
python -m wcl_report_data cache clear --confirm
```

删除操作必须显式传入 `--confirm`。清理缓存会保留规范 Fight Bundle，但会删除未知字段值的本地副本和下载检查点。

## 开发与文档

维护者可直接从 Wago Tools 下载当前 zhCN `SpellName` CSV，并只导入现有 mapping 与指定 Report Index 所需的 ID：

```bash
python tools/import_ability_names.py \
  --report-index "/path/to/report.json"
```

脚本固定从 `https://wago.tools/db2/SpellName/csv?locale=zhCN` 下载，依据响应文件名（例如 `SpellName.12.1.0.69587.csv`）保存客户端 build。导入器保留已有 ID，更新合法改名，并在当前 CSV 缺少任何已有 ID 时拒绝写入。

```bash
make check
```

手动执行等价检查：

```bash
python -m unittest -v
python -m compileall -q wcl_report_data tests
git diff --check
```

文档入口：

- [English README](README.en.md)
- [领域术语](CONTEXT.md)
- [数据契约](references/data-contract.md)
- [English data contract](references/data-contract.en.md)
- [WCL API 说明](references/wcl-api.md)
- [English API notes](references/wcl-api.en.md)
- [WorkBuddy 凭据与存储配置](references/workbuddy-setup.md)
- [English setup guide](references/workbuddy-setup.en.md)
- [Skill 使用说明](SKILL.md)
- [原创图标](assets/timewarp-inn-dog.svg)

图标使用原创的大黄狗、旅馆和时空传送门造型，不包含 Warcraft Logs、Blizzard 或游戏内 Logo 与角色素材。本项目与 Warcraft Logs 或 Blizzard Entertainment 没有关联。使用时请遵守 Warcraft Logs API 访问规则和限流要求。
