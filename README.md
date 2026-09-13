# wcl-raid-coach

<p align="center">
  <img src="assets/timewarp-inn-dog.svg" width="220" alt="大黄狗守护时空旅馆的原创奇幻图标">
</p>

`wcl-raid-coach` 是一个平台中立、自包含的 Agent Skill 和 Python 3.11+ 软件包，用于准备正式服 Warcraft Logs 团队副本证据、实时复核首领机制、复盘个人表现，以及基于当前 Boss 高分日志生成攻略。

它只使用 WCL 官方 OAuth 和 GraphQL API，不抓取报告网页。个人复盘和攻略以 Report Revision 隔离的 Complete Bundle 为事实基础；Mechanic Review 使用同样隔离、但不落盘的 Mechanic Evidence Set。

[English documentation](README.en.md)

## 适用范围

- 支持 Retail 团队副本；不支持怀旧服和 Mythic+。同一 WCL Report 同时包含团本与 Mythic+ 时，只列出和准备其中的团本 Boss Attempt。
- 支持公开和未列出报告；私有报告需要用户 OAuth，当前不支持。
- 支持 `warcraftlogs.com`、`www.warcraftlogs.com` 和 `cn.warcraftlogs.com` 报告链接。
- CN 链接会规范化为全球站链接，API 请求仍使用 WCL 官方全球端点。
- 运行时只依赖 Python 标准库，不需要第三方 Python 包。
- Mechanic Review 当前只覆盖 The Venomous Abyss 的官方 8 个团本首领及 Normal、Heroic、Mythic；不包含世界首领 Nymrissa Wavecaller。

## 快速开始

环境要求：Python 3.11+、可访问 `warcraftlogs.com`，以及 Warcraft Logs API v2 client ID 和 client secret。

安装为 Agent Skill 后，可以先问“如何使用 wcl-report-data？”查看能力菜单，也可以直接使用自然语言发起任务：

- “帮我看看这份 WCL 报告里有哪些 Boss Attempt 和参与者：`<WCL_URL>`”
- “复核这场 Boss Attempt 的机制处理：`<WCL_URL_WITH_NUMERIC_FIGHT>`”
- “复盘我在这场 Boss Attempt 的表现，角色是 `<角色名>`：`<WCL_URL_WITH_NUMERIC_FIGHT>`”
- “给我一份邪恶死亡骑士打当前团本 H7 和 H8 的攻略。”

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

对当前对话中的快速机制检查，可使用紧凑输出。它保留机制计数和玩家异常，去除原始 WCL payload，汇总宠物/NPC 噪声，并限制每条机制展开的玩家异常数量：

```bash
python -m wcl_raid_coach coach mechanics \
  "https://www.warcraftlogs.com/reports/<code>#fight=12" --compact
```

若需要检查某次异常附近一名或多名参与者的死亡链，可按 fight-relative 毫秒采集前后事件窗口，无需先准备全场 Complete Bundle：

```bash
python -m wcl_raid_coach coach evidence \
  "https://www.warcraftlogs.com/reports/<code>#fight=12" \
  --at-ms 210472 --window-ms 10000 --player-id 17 \
  --expected-identity JKy1tpWXjw2rBYZm:17:22
```

`--expected-identity` 必须原样取自紧凑机制结果的 `evidence_identity`，同时防止两阶段跨 WCL Report、Report Revision 或 Boss Attempt。Focused Evidence Window 最多接受 3 名共享同一异常时间的参与者；不同时间必须分别调用。它对每人完整分页，并返回引用到的 actor/ability 名称；stdout 最多包含 200 条事件，死亡和战复优先，其余按靠近锚点排序，截断和完整匹配计数在 `evidence` 中说明。它只驻留进程内，不创建 Report Index、Raw Page、Fight Bundle、Complete Bundle、Canonical Event、manifest 或检查点，也不构成责任或灭团因果判断。

正式交付 Mechanic Review 时，在同一条命令中加入 `--report`；可用 `--locale zh-CN`（默认）或 `--locale en`：

```bash
python -m wcl_raid_coach coach mechanics \
  "https://www.warcraftlogs.com/reports/<code>#fight=12" --report --locale zh-CN
```

该路径只在内存 Mechanic Review 完整分页且前后 Report Revision 一致后，写入 `outputs/mechanic-reviews/<sha256>.json` 的严格净化来源，再从该来源组装并校验 Report Document，渲染到 `outputs/reports/`。JSON stdout 返回 `source.path`、`source.sha256`、`document` 及 `report` 的内容身份和路径，不需要抓取混合输出。来源只保留 WCL Report、Report Revision、Boss Attempt 和 Mechanic Ruleset 身份及元数据、计数、受支持结论、阶段、参与者和扁平最小证据摘录；不保存完整过滤事件范围、Raw Page、Fight Bundle、`raw_event`、`raw_events`、光环应用对象、任意 WCL payload、责任或灭团因果。分页、revision、采集、净化、校验或首次渲染失败时不留下新的来源 artifact；相同内容复用现有不可变 artifact。

其他类型的已构造 Report Document 仍可按[数据集契约](references/data-contract.md)单独渲染。该命令不访问 WCL，也不需要凭据：

```bash
python -m wcl_raid_coach coach render "<WORK_DIR>/report.document.json"
```

Raid Guide 不需要调用方重写 Report Document。把 `coach guide` 返回的一个 Guide Snapshot JSON 路径直接交给第一方 assembler；它会校验 Snapshot 和 Markdown 身份、从每个 Boss 章节派生完整文档并立即渲染：

```bash
python -m wcl_raid_coach coach guide-report "<DATA_ROOT>/guides/<SNAPSHOT_ID>.json"
```

Personal Review 同样不需要重抄指标或身份。正式交付必须把 `coach review`、`coach benchmark` 和 `coach compare` 生成的三个 JSON artifact 与 canonical comparison-ready `--workflow` 一起交给第一方 assembler；CLI 会在 HTML/index 后完成 delivery finalization，不提供绕过 workflow 的正式 Personal Review：

```bash
python -m wcl_raid_coach coach personal-report \
  "<WORK_DIR>/personal-analysis.json" \
  "<WORK_DIR>/encounter-benchmark.json" \
  "<WORK_DIR>/comparison.json" \
  --workflow "<DATA_ROOT>/outputs/personal-workflows/<WORKFLOW_ID>.json" \
  --advice "<WORK_DIR>/advice-draft.json" \
  --encounter-profile "<WORK_DIR>/encounter-profile.json" \
  --specialization-profile "<WORK_DIR>/specialization-profile.json" \
  --locale zh-CN
```

计时必须在 Boss Attempt 和玩家选定后立即开始，并早于目标 Complete Bundle retrieval、Ranking Candidate discovery 和 Profile retrieval/synthesis：运行 `coach personal-workflow-init "<WCL_URL>#fight=<FIGHT_ID>&source=<ACTOR_ID>"` 创建 canonical blocked workflow。该命令只需要所选 WCL Report、Boss Attempt 和玩家身份，不需要 Analysis、Complete Bundle、Ranking Cohort 或 Profile。后续 `coach personal-workflow` 每次都必须传入初始化或最新 workflow 的 `--previous-workflow`，并提供 Analysis、Cohort 和两个 Profiles；CLI 会将它们绑定到初始化身份。monotonic 起点与跨调用墙钟间隔保守覆盖候选发现、Profile 和 Agent synthesis、retrieval、validation、rendering 和 delivery；标准候选采集最多提供 10 个合格 Reference Samples，已有的 3 到 10 个全部保留。

Personal Review 只复用绑定当前 Ranking Cohort 且能从每个 Reference Sample 的 Complete Bundle evidence 完整重建的 Encounter Benchmark；已有的 3 到 10 个合格样本全部保留并立即可交付，不为达到 10 而等待或继续采集。3 到 9 个样本为低置信度，10 个为正常置信度。workflow 的 `retrieval` 在候选、Profile 或玩家 evidence 尚未齐备时为 `in_progress`；无法观测 Agent synthesis 时为 `unavailable`，玩家和 Profiles 齐备后为 `in_progress`。delivery/finalization 将无法单独计时的 Agent synthesis 标为 `unavailable`，所以最终 `target_met` 为 `null`；monotonic clock 倒退或 wall-minus-monotonic baseline 超出 tolerance 时同样停止目标判定。持久化的 session marker 只用于本地诊断，不参与严格相等比较。

workflow 保存精确的 Cohort、Profile、Benchmark、全部 Reference Samples 及其 Complete Bundle provenance。assembly、render 和 delivery 都重新读取并深度校验这些快照。delivery artifact 的计时边界只到 HTML/index 校验；随后写入的 finalization 才声明 delivery artifact 已持久化。CLI 从实际 artifact 状态推导 `stage_progress`，不接受调用方 timing。CLI 无法直接观测 Agent synthesis 持续时间，因此该阶段标为 `unavailable`，最终 `target_met` 为 `null`，不会仅凭总 elapsed 宣称 180/30 秒目标已证明。`wcl_network_measurement` 仍为 `not_measured`。content-addressed Artifact 只有规范文件字节和 SHA-256 完全一致时才复用；失败后已写入的不可变 artifact 可作为 orphan 保留。

每个 rejection 必须使用 Ranking Cohort 中的稳定候选身份，不能以样本数推算进度。`coach candidates` 达到目标时保留最后一次已查询的完整去重页，因此同页剩余候选可在后续 workflow 调用中继续使用；pagination 记录真实已查询页范围、远端 `hasMorePages`、`target_reached` 和 `exhausted`。只有 metadata 明确证明终页时才声明 page exhaustion；否则候选用尽要求刷新 Cohort。预算、已证明的 page exhaustion 或 API failure 后仍不足 3 个合格样本时，可运行 `coach personal-report <ANALYSIS> --workflow <PARTIAL_READY_WORKFLOW> --encounter-profile <PROFILE> --specialization-profile <PROFILE> [--advice <DRAFT>]`。报告从 workflow、Cohort 和 Reference Sample evidence 推导样本数，不接受手填整数。玩家 Complete Bundle 不完整时 workflow 只返回 `blocked`，并可用 `--progress <CHECKPOINT>` 按路径/hash 保留进度，不生成报告或声称 Complete Bundle。

该命令重新校验 Personal Analysis schema `4`、Encounter Benchmark schema `3` 和 Comparison schema `3`。`--advice` 可省略；提供时必须同时传入两个 Profile 路径。Coaching Advice schema `2` 不接受自由文本动作、条件或验证目标，只接受有限结构化枚举，由 CLI 按 `zh-CN`/`en` 生成文案，因此不能承载责任、因果、保证提升或中位数处方；这不是自然语言语义审查，超出枚举的表达必须人工复核。任何带 ability ID 的动作都要求 Specialization Profile 将该技能声明为 `action_type: "player_cast"`。事件支持的能力动作还必须引用同一 ability ID 的 direct-player `player_cast`/`key_action` 指标；owned aggregate damage/healing 只保留审计用途，不能支持建议。当前 Personal Review 没有 Mechanic Review 来源，所以机制 Advice 只能使用有当前 Profile 指导的条件性经验类别。CLI 同时验证事实值及本地 Profile 路径、文件哈希、Profile ID 和 sources。Advice 一经写入即保持不可变；后续组装或渲染失败时可能留下可安全复用的 content-addressed 孤儿 artifact。

建议中的 Spell 必须使用 ability ID；中文输出要求命中已校验的 zhCN SpellName mapping，缺失时返回结构化错误，不自行翻译。Specialization Profile 只有把技能显式声明为 `action_type: "player_cast"`，才会生成 `key_action_*`；即使所有 Reference Sample 都是零次也保留零中位数。未声明技能以及 `automatic`、`internal`、`owned_actor` 不进入关键动作，WCL synthetic Melee ID `1` 不能声明为玩家动作。关键动作展示不回退使用含宠物和内部事件的原始 `casts_median`。

Encounter Profile 的非空 `priority_target_ids` 和 `excluded_target_ids` 必须声明 `target_id_type: "npc_game_id"`；旧的 report-local actor ID 不能跨 WCL Report 比较，必须按各 Report Index 的 NPC `gameID` 重建 Profile、Benchmark 和 Comparison。已有本地 Complete Bundle、Report Index、Profile 和 ability-name mapping 足够时，这个重建流程可以离线运行；缺少 Reference Sample 数据或中文 mapping 时仍需先联网准备。Personal Review 同时展示总量、双方时长、每分钟伤害/治疗及有效 Reference Sample 分母；归一化不校正存活、停手、阶段、天赋、装备或任务分配差异，样本中位数也不是推荐动作。数字只能出现在结构化事实引用中。Advice/Report renderer 对来源 URL 使用相同的公开 HTTP(S)、无认证信息和无 credential query 检查。

CLI 返回派生的 `document` 和 `report` 路径/内容身份；带建议时还返回 `advice.path`、`advice.sha256` 和 `advice.advice_id`。HTML 无外部资源。Personal Review 固定展开输出、生存、机制和团队贡献四个维度，每个维度把可用事实/比较、改进建议、适用条件、下一次 Boss Attempt 验证目标及证据/限制放在一起；完整比较明细随后保留。没有建议、未评估、中文 SpellName 缺失或 Reference Samples 不足时不会补写结论，对应位置明确显示“未评估”或拒绝生成带未验证中文名的 Advice。renderer 会重新解析并核对所有来源；Personal Review 建议不得声明未验证原因、责任、保证提升或把样本中位数当作推荐次数。当前只接受 Report Document schema `2`；旧 schema `1` 的静态 HTML 仍可直接查看，但不能重新渲染。需要先基于当前 Analysis、Benchmark、Comparison source artifacts 重新运行 `personal-report`。

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

`coach review`、`coach benchmark`、`coach guide`、`coach compare` 和 `coach personal-report` 只消费本地 Artifact。当前链路使用 Personal Analysis `4`、Encounter Benchmark `3` 和 Comparison `3`；旧 schema 必须重新生成。访问 WCL API 的命令仍需要 OAuth client credentials。

## Encounter Designator 与名称映射

Agent 入口按需加载[机制/triage](references/workflow-mechanics.md)、[个人复盘](references/workflow-personal.md)和[攻略](references/workflow-guide.md)。个人复盘先初始化计时，再搜索绑定原 Cohort/Profiles 的本地兼容 Benchmark；深度验证后复用已有3–10样本。多 Boss 攻略复用当前有效公共 Specialization Profile与合格已完成章节，只获取缺失部分。详细字段与来源规则在数据契约中按需读取。

外部攻略按[有界抓取流程](references/guide-retrieval.md)读取：WebFetch一次失败后尝试本地curl，再尝试可用浏览器和版本相关的替代来源。HTTP 200仍须核验实际正文；验证页、脚本外壳、搜索摘要或Blizzard通用职业概述不能替代专精指南。工具不可用或正文/patch无法确认时披露证据缺口。

优先复核候选使用 `python -m wcl_raid_coach coach triage "<WCL_URL_WITH_NUMERIC_FIGHT>"`。CLI 在同一进程复用客户端和报告元数据，输出紧凑 `mechanics`、有序 `candidates`、`windows` 与 `coverage`；只考虑 verified/enabled/target 玩家异常，最多 3 人、每人 3 个不同异常时间。同一异常中的并列玩家才能共享窗口。缺少死亡前 10 秒覆盖时补一次死亡窗口。无受支持候选时返回 `no_supported_candidate`，不请求 focused events。团队事实保持并列；judgment/causal_attribution 为 null。全过程保持临时内存证据和阶段前后的 Report Revision 校验，失败不返回成功的合并结果。coverage 明确记录紧凑异常展示抑制和窗口截断；不代表完整个人复盘。

Skill 能理解 `PT6`、`H6`、`M6` 形式的 Encounter Designator。前缀分别表示 Normal、Heroic、Mythic，数字表示 WCL `zone.encounters` 原始列表中的一基位置。Designator 只确定难度和 encounter；同一报告有多次匹配 Boss Attempt 时，Skill 必须列出明确的 fight ID 等待选择，不能自动选择击杀、最后一次或全部尝试。

`inspect`、`prepare`、`query` 不下载展示名称映射，也不返回 `ability_names`。`inspect` 使用有效的已有 content mapping；缺失或损坏时展示 WCL 原名，返回 `content_names: null`。已明确数字 fight 时直接 prepare；同一 WCL Report 的多个明确选择可使用 `prepare "<WCL_URL>" --fight 1 --fight 3`，共享一次报告元数据查询。

生成 Guide 等需要名称的输出时，CLI 从 Wago Tools 下载当前 Retail zhCN `SpellName` CSV，在数据目录生成完整的 `ability-names.zhCN.json` 及 metadata；已有有效 JSON 时不会再次联网。只有 ID 同时存在于 Report Index 的 `abilities[].gameID` 时才可使用 mapping。Guide 和 Skill 面向用户的中文正文必须使用 mapping 中的中文 SpellName，不得自行直译；机制 Spell ID 缺少中文 mapping 时停止生成最终攻略。中文名是当前客户端展示 enrichment，不改写 Report Index。Mechanic Review 不初始化该本地 mapping；它使用版本化 Mechanic Ruleset 随附的中英文机制名称。

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

Skill 安装目录只保存程序与文档。Report Index、Complete Bundle、Profiles、任务、Guide Snapshot 和渲染后的 Report Document 写入数据目录；Raw Page 和可续传检查点写入缓存目录。运行 `doctor` 可从 JSON 中查看实际的 `data_root` 和 `cache_root`。

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
outputs/reports/
├── <html-sha256>.html
└── <html-sha256>.json
outputs/advice/
└── <advice-id>.json
outputs/personal-workflows/
├── <workflow-id>.json
└── index.json
outputs/personal-deliveries/
├── <delivery-id>.json
└── <finalization-id>.json
```

同一 Report Revision 内的 Fight Bundle 不可变。重新导出报告会创建新的 revision 目录；`latest.json` 只是指针，可复现的消费者应使用 manifest 中记录的 revision。原始页单独压缩保存，以便中断下载继续并审计字段规范化过程。

## 数据与安全边界

- 只有 `manifest.json` 中 `complete: true` 的 Fight Bundle 才能用于个人复盘、Benchmark 或 Guide；Mechanic Review 使用下述临时证据例外。
- Complete Bundle 必须到达显式的 `nextPageTimestamp: null`，事件时间戳有序，未跨 Report Revision，并通过文件哈希校验。
- Complete Bundle 同时校验压缩事件文件的 SHA-256 与解压后 Canonical Event JSONL 的内容 SHA-256。Ranking Cohort 和 Encounter Benchmark 使用规范 JSON 的内容 ID，不使用 WCL client secret 做 HMAC。
- 所有分页请求都重复传入该战斗的固定 `startTime` 和 `endTime`；旧采集协议生成的 Bundle 会被拒绝并要求重新准备。
- Canonical Event 只保留已知字段；未知字段名和次数写入 manifest，未知值留在 Raw Page 缓存中。
- 角色名和服务器会保留在本地数据集，以便识别团队成员；对话中展示的数据可能由当前配置的模型服务商处理。
- 查询结果是证据，不是结论。没有独立的首领机制知识来源时，不得把伤害标记为可规避或推断责任。
- Mechanic Evidence Set 只在当前进程中存在，不创建 Report Index、Raw Page、Fight Bundle、manifest 或检查点。它必须完整跟随过滤事件分页到 `nextPageTimestamp: null`，保持固定 Boss Attempt 时间范围，并在前后校验同一 Report Revision。
- Mechanic Review 使用安装包内最新版本的规则，不按报告日期回放历史热修规则。更新规则需要更新软件包；输出记录规则版本、来源和 `selection_policy: latest`。
- Personal Review 的 workflow、Advice、Report Index、delivery 和 finalization 都是本 CLI 写入的内容寻址 Artifact。组装、渲染或 finalization 失败后已经写入但没有被最终报告引用的 Artifact 会作为 orphan 保留；必须依据引用关系和保留策略由明确的人工或专用回收命令处理，不能自动删除或覆盖。
- Personal Review timing 使用本机 monotonic 与 wall clock；测试中的 deterministic injected clock 只验证状态和连续性，不代表实际本机墙钟耗时，也不包含 WCL 网络测量。CLI 的正式报告命令必须提供 `--workflow`。
- `coach mechanics --compact` 只裁剪当前 stdout，不改变 Mechanic Evidence Set；Focused Evidence Window 是显式参与者和短时间范围的临时跟进证据，不是 Complete Bundle 或 Canonical Event 集。
- 每条机制的触发、成功和失败计数都是规则定义的事件信号统计；不可由日志判定时为 `null`。异常仅表示已验证事件模式命中，不表示玩家责任、表现评价或灭团因果。
- 教练 Artifact 只支持本 CLI 在用户本地数据目录或工作目录中生成和消费。Hash 用于内容身份和损坏检测，不认证来源；外部提供的 Artifact 不属于受支持输入。使用旧 HMAC schema 的 Complete Bundle、Ranking Cohort、Personal Review、Encounter Benchmark 和 Guide Snapshot 必须重新生成。

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

Encounter/NPC mapping 使用代码中声明的当前地图范围，并要求所有 Wago 来源表具有同一客户端 build。删除 `content-names.zhCN.json` 和 `content-names.zhCN.meta.json` 后，下次需要名称的 `coach resolve` 或 `coach guide` 会重新生成；inspect 仍仅使用本地有效映射。下载不完整、build 不一致或当前地图缺失时返回结构化 `dataset_error`。

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

`main` 使用 Conventional Commits 自动发布：`fix` 触发 patch、`feat` 触发 minor，`!` 或 `BREAKING CHANGE` 触发 major；其他提交类型不单独发布。workflow 自动同步 `SKILL.md`、`pyproject.toml` 和 `wcl_raid_coach/__init__.py`，创建 release commit 与 `vX.Y.Z` tag，从该不可变 tag 构建唯一 Agent Skill zip，创建 GitHub Release，再把同一个 zip 发布到原有 `wcl-report-data` SkillHub 条目。SkillHub 发布身份固定为 `name/slug: wcl-report-data`；这与 bundled Python 模块名 `wcl_raid_coach` 相互独立。

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
## 可选性能诊断

在子命令前加 `--diagnostics`，将数值诊断 JSON 输出到 stderr；原有 stdout JSON 与领域错误契约保持不变。例如：

```bash
python -m wcl_raid_coach --diagnostics inspect 'https://www.warcraftlogs.com/reports/REPORT_CODE'
```

诊断按操作统计 WCL/Wago 请求次数、重试、收到的响应正文字节、网络耗时，以及名称映射、Complete Bundle 校验、玩家分析、报告组装/生成和锁等待。它不包含凭据或事件内容，不改变 Personal Review 的 elapsed/`target_met` 语义。测量边界见[性能诊断说明](references/performance.md)。
同一 OS 用户的 WCL 请求会跨进程协调额度与 HTTP 429 冷却；更换 workspace 或 data/cache root 不会绕过冷却。协调状态位于 `~/.wcl-report-data/api/`，不保存凭据；详见[配置说明](references/setup.md)。
## 混合报告识别

同一 WCL Report 混有 Mythic+ 和团本时，即使主要区域是大秘境，工具也会通过官方区域的 Encounter 成员关系解析唯一团本区域。只选择团本 Boss Attempt；无法唯一解析时返回错误。难度来自该团本的官方元数据，不使用固定数字映射。
