# wcl-raid-coach

<p align="center">
  <img src="assets/timewarp-inn-dog.svg" width="220" alt="大黄狗守护时空旅馆的原创奇幻图标">
</p>

`wcl-raid-coach` 是一个平台中立、自包含的 Agent Skill 和 Python 3.11+ 软件包，用于准备正式服 Warcraft Logs 团队副本证据、实时复核首领机制、复盘个人表现，以及基于当前 Boss 高分日志生成攻略。

它只使用 WCL 官方 OAuth 和 GraphQL API，不抓取报告网页。个人复盘和攻略以 Report Revision 隔离的 Complete Bundle 为事实基础；Mechanic Review 使用同样隔离、但不落盘的 Mechanic Evidence Set。

[English documentation](README.en.md)

## 适用范围

- 支持 Retail 团队副本；不支持怀旧服和 Mythic+。
- 支持公开和未列出报告；私有报告需要用户 OAuth，当前不支持。
- 支持 `warcraftlogs.com`、`www.warcraftlogs.com` 和 `cn.warcraftlogs.com` 报告链接。
- CN 链接会规范化为全球站链接，API 请求仍使用 WCL 官方全球端点。
- 运行时只依赖 Python 标准库，不需要第三方 Python 包。
- Mechanic Review 当前只覆盖 The Venomous Abyss 的官方 8 个团本首领及 Normal、Heroic、Mythic；不包含世界首领 Nymrissa Wavecaller。

## 快速开始

环境要求：Python 3.11+、可访问 `warcraftlogs.com`，以及 Warcraft Logs API v2 client ID 和 client secret。

从仓库根目录运行 CLI。Agent 使用已安装的 Skill 时，应先定位 `SKILL.md` 所在的 Skill 根目录，再以该目录为工作目录运行 bundled CLI；无需全局安装 Python 包：

```bash
python -m wcl_raid_coach doctor
```

确认输出中的 `wcl_api` 为 `reachable` 后，建立报告索引：

```bash
python -m wcl_raid_coach inspect "https://www.warcraftlogs.com/reports/<code>"
```

解析“邪 DK 打当前团本 H7/H8”的通用攻略请求：

```bash
python -m wcl_raid_coach coach resolve --spec "邪 DK" --encounter H7 --encounter H8
```

该命令只解析当前团本上下文并返回待确认任务。完整工作流见 [Skill 使用说明](SKILL.md)。

实时复核一个明确的 Boss Attempt：

```bash
python -m wcl_raid_coach coach mechanics \
  "https://www.warcraftlogs.com/reports/<code>#fight=12"
```

裸报告 URL 不会自动选择 Boss Attempt。可用 Encounter Designator 筛选候选，再把用户选定的数字 fight 写入 URL：

```bash
python -m wcl_raid_coach coach mechanics \
  "https://www.warcraftlogs.com/reports/<code>" --encounter H2
```

Mechanic Review 接受击杀和灭团，但只接受已完成的 Boss Attempt；`fight=last` 会被拒绝。

准备 URL 中选中的战斗：

```bash
python -m wcl_raid_coach prepare "https://www.warcraftlogs.com/reports/<code>#fight=12"
```

也可以从裸报告 URL 准备指定战斗，或准备某个首领的全部已完成尝试：

```bash
python -m wcl_raid_coach prepare "https://www.warcraftlogs.com/reports/<code>" --fight 12 --fight 15
python -m wcl_raid_coach prepare "https://www.warcraftlogs.com/reports/<code>" --encounter 3129
```

通过返回的 manifest 查询事件，避免把整个事件流放入模型上下文：

```bash
python -m wcl_raid_coach query \
  "<DATA_ROOT>/reports/<code>/revisions/<revision>/fights/12/manifest.json" \
  --type damage --target-id 17 --limit 200
```

CLI 始终向标准输出写入 JSON，领域错误也会返回结构化 JSON。完整参数参见 `python -m wcl_raid_coach --help`，完整工作流参见 [Skill 使用说明](SKILL.md)。

## Encounter Designator 与名称映射

Skill 能理解 `PT6`、`H6`、`M6` 形式的 Encounter Designator。前缀分别表示 Normal、Heroic、Mythic，数字表示 WCL `zone.encounters` 原始列表中的一基位置。Designator 只确定难度和 encounter；同一报告有多次匹配 Boss Attempt 时，Skill 必须列出明确的 fight ID 等待选择，不能自动选择击杀、最后一次或全部尝试。

首次运行 `inspect`、`prepare`、`query` 或生成 Guide 时，CLI 会从 Wago Tools 下载当前 Retail zhCN `SpellName` CSV，并在数据目录生成完整的 `ability-names.zhCN.json` 及 metadata；已有有效 JSON 时不会再次联网。只有 ID 同时存在于 Report Index 的 `abilities[].gameID` 时才可使用 mapping。Guide 和 Skill 面向用户的正文必须使用 mapping 中的中文 SpellName，不得自行直译；机制 Spell ID 缺少中文 mapping 时停止生成最终攻略。中文名是当前客户端展示 enrichment，不改写 Report Index。Mechanic Review 不初始化该本地 mapping；它使用版本化 Mechanic Ruleset 随附的中英文机制名称。

CLI 另行维护 `content-names.zhCN.json`，从同一 Wago 客户端 build 的 `Map`、`DungeonEncounter`、`JournalEncounter` 和 `JournalEncounterCreature` 中生成 Encounter/NPC 中英文映射。它只包含当前团队副本的 Normal、Heroic、Mythic 三个难度，以及当前配置的 8 个 Mythic+ 地图。WCL 原始英文名和 ID 继续作为审计数据；Wago 未提供 WCL NPC `gameID` 的可靠直连，因此 NPC 中文名只作为所属 Encounter 内的展示 enrichment，不能作为事件身份。

## 凭据配置

普通用户只需通过 Agent 宿主的私密环境配置提供以下规范变量：

```dotenv
WCL_CLIENT_ID=
WCL_CLIENT_SECRET=
```

CLI 也暂时兼容成对出现的 `WCL_ID` 和 `WCL_SECRET`。CLI 不自动读取当前目录或 `/workspace` 中的 `.env`；需要使用凭据文件时，把全局参数放在子命令之前并显式传入：

```bash
python -m wcl_raid_coach --env-file "<WORKSPACE>/.env" doctor
python -m wcl_raid_coach --env-file "<WORKSPACE>/.env" inspect "<WCL_URL>"
```

AI 不应要求用户在对话中提供或粘贴 secret，不应覆盖已有凭据文件，也不应输出 client secret 或 access token。详细规则参见[凭据与存储配置](references/setup.md)和 [English setup guide](references/setup.en.md)。

## 数据布局

普通用户无需配置存储路径。全局参数 `--data-root` 和 `--cache-root` 优先，其次是可选的 `WCL_RAID_COACH_HOME` 和 `WCL_RAID_COACH_CACHE`。未覆盖时，存在的持久 `/workspace` 作为云端 Agent 沙盒兼容 fallback；否则本地 Unix/macOS 使用 `~/.local/share/wcl-raid-coach/` 和 `~/.cache/wcl-raid-coach/`，Windows 使用 `%LOCALAPPDATA%/wcl-raid-coach/` 及其 `Cache/` 子目录。

Skill 安装目录只保存程序与文档。Report Index、Complete Bundle、Profiles、任务和 Guide Snapshot 写入数据目录；Raw Page 和可续传检查点写入缓存目录。运行 `doctor` 可从 JSON 中查看实际的 `data_root` 和 `cache_root`。

```text
reports/<report-code>/
├── latest.json
└── revisions/<revision>/
    ├── report.json
    └── fights/<fight-id>/
        ├── manifest.json
        └── events.jsonl.gz
ability-names.zhCN.json
ability-names.zhCN.meta.json
content-names.zhCN.json
content-names.zhCN.meta.json
```

同一 Report Revision 内的 Fight Bundle 不可变。重新导出报告会创建新的 revision 目录；`latest.json` 只是指针，可复现的消费者应使用 manifest 中记录的 revision。原始页单独压缩保存，以便中断下载继续并审计字段规范化过程。

## 数据与安全边界

- 只有 `manifest.json` 中 `complete: true` 的 Fight Bundle 才能用于个人复盘、Benchmark 或 Guide；Mechanic Review 使用下述临时证据例外。
- Complete Bundle 必须到达显式的 `nextPageTimestamp: null`，事件时间戳有序，未跨 Report Revision，并通过文件哈希校验。
- 所有分页请求都重复传入该战斗的固定 `startTime` 和 `endTime`；旧采集协议生成的 Bundle 会被拒绝并要求重新准备。
- Canonical Event 只保留已知字段；未知字段名和次数写入 manifest，未知值留在 Raw Page 缓存中。
- 角色名和服务器会保留在本地数据集，以便识别团队成员；对话中展示的数据可能由当前配置的模型服务商处理。
- 查询结果是证据，不是结论。没有独立的首领机制知识来源时，不得把伤害标记为可规避或推断责任。
- Mechanic Evidence Set 只在当前进程中存在，不创建 Report Index、Raw Page、Fight Bundle、manifest 或检查点。它必须完整跟随过滤事件分页到 `nextPageTimestamp: null`，保持固定 Boss Attempt 时间范围，并在前后校验同一 Report Revision。
- Mechanic Review 使用安装包内最新版本的规则，不按报告日期回放历史热修规则。更新规则需要更新软件包；输出记录规则版本、来源和 `selection_policy: latest`。
- 每条机制的触发、成功和失败计数都是规则定义的事件信号统计；不可由日志判定时为 `null`。异常仅表示已验证事件模式命中，不表示玩家责任、表现评价或灭团因果。

## 数据管理

```bash
python -m wcl_raid_coach dataset list
python -m wcl_raid_coach cache status
python -m wcl_raid_coach dataset remove <REPORT_CODE> --confirm
python -m wcl_raid_coach cache clear --confirm
```

删除操作必须显式传入 `--confirm`。清理缓存会保留规范 Fight Bundle，但会删除未知字段值的本地副本和下载检查点。

## 开发与文档

技能名称首次使用时固定从 `https://wago.tools/db2/SpellName/csv?locale=zhCN` 下载。CLI 依据响应文件名（例如 `SpellName.12.1.0.69587.csv`）保存客户端 build、来源文件和 SHA-256。删除数据目录中的 `ability-names.zhCN.json` 和 `ability-names.zhCN.meta.json` 后，下次相关命令会重新下载；无法下载时返回结构化 `dataset_error`。

Encounter/NPC mapping 使用代码中声明的当前地图范围，并要求所有 Wago 来源表具有同一客户端 build。删除 `content-names.zhCN.json` 和 `content-names.zhCN.meta.json` 后，下次 `inspect`、`coach resolve` 或 `coach guide` 会重新生成；下载不完整、build 不一致或当前地图缺失时返回结构化 `dataset_error`。

```bash
make check
```

手动执行等价检查：

```bash
python -m unittest -v
python -m compileall -q wcl_raid_coach tests tools
git diff --check
```

## 发布

`main` 使用 Conventional Commits 自动发布：`fix` 触发 patch、`feat` 触发 minor，`!` 或 `BREAKING CHANGE` 触发 major；其他提交类型不单独发布。workflow 自动同步 `SKILL.md`、`pyproject.toml` 和 `wcl_raid_coach/__init__.py`，创建 release commit 与 `vX.Y.Z` tag，从该不可变 tag 构建唯一 Agent Skill zip，创建 GitHub Release，再把同一个 zip 发布到原有 `wcl-raid-coach` SkillHub 条目。

仓库维护者需将 SkillHub personal API token 配置为 GitHub Actions secret `SKILLHUB_TOKEN`。普通 Skill 用户不需要该 token，仍只需配置 `WCL_CLIENT_ID` 和 `WCL_CLIENT_SECRET`。发布 workflow 固定并校验 SkillHub CLI artifact；发布前先执行本地 dry-run。

文档入口：

- [English README](README.en.md)
- [领域术语](CONTEXT.md)
- [数据契约](references/data-contract.md)
- [English data contract](references/data-contract.en.md)
- [WCL API 说明](references/wcl-api.md)
- [English API notes](references/wcl-api.en.md)
- [凭据与存储配置](references/setup.md)
- [English setup guide](references/setup.en.md)
- [Skill 使用说明](SKILL.md)
- [原创图标](assets/timewarp-inn-dog.svg)

图标使用原创的大黄狗、旅馆和时空传送门造型，不包含 Warcraft Logs、Blizzard 或游戏内 Logo 与角色素材。本项目与 Warcraft Logs 或 Blizzard Entertainment 没有关联。使用时请遵守 Warcraft Logs API 访问规则和限流要求。
