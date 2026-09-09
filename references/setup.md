# 凭据与存储配置

本文说明平台中立的凭据查找顺序和默认存储位置。[English version](setup.en.md)

普通用户只需通过 Agent 宿主的私密环境配置提供：

```dotenv
WCL_CLIENT_ID=
WCL_CLIENT_SECRET=
```

不要在对话中粘贴凭据，也不要把凭据写入 Skill 安装目录。

## 凭据

先从 Skill 根目录运行：

```bash
python -m wcl_raid_coach doctor
```

如果结果包含 `"wcl_api": "reachable"`，凭据已经可用。`credential_source` 会安全地标明来源，例如 `environment:WCL_CLIENT_ID`，但不会输出 client secret 或 access token。

CLI 先读取进程环境中的完整凭据对。需要使用凭据文件时，必须显式传入文件路径：

```bash
python -m wcl_raid_coach --env-file "<PRIVATE_PATH>/wcl.env" doctor
python -m wcl_raid_coach --env-file "<PRIVATE_PATH>/wcl.env" inspect "<WCL_URL>"
```

`--env-file` 必须放在子命令之前。CLI 不会自动读取当前目录或 `/workspace` 中的 `.env`。

每组变量必须成对配置，不混用两组名称。规范名称是 `WCL_CLIENT_ID` 和 `WCL_CLIENT_SECRET`；CLI 暂时兼容成对出现的 `WCL_ID` 和 `WCL_SECRET`。

Agent 不得询问、输出、记录或持久化 client secret/access token，不得覆盖已有凭据文件。凭据文件不得提交到 Git 或放入 Skill 发布包。

## 持久数据与缓存

普通用户无需配置存储路径。CLI 按以下优先级选择持久数据目录：

1. 全局参数 `--data-root`；
2. `WCL_RAID_COACH_HOME`；
3. 存在的持久 `/workspace`；
4. 操作系统用户数据目录。

缓存目录按以下优先级选择：

1. 全局参数 `--cache-root`；
2. `WCL_RAID_COACH_CACHE`；
3. 存在的持久 `/workspace`；
4. 操作系统用户缓存目录。

`/workspace` 是云端 Agent 沙盒的兼容 fallback，不用于判断具体宿主。默认位置为：

```text
持久 /workspace：
  /workspace/wcl-raid-coach/          Report Index、Complete Bundle、Profiles、任务、Guide Snapshot 与渲染报告
  /workspace/.cache/wcl-raid-coach/   Raw Page 与可续传检查点

本地 Unix/macOS：
  ~/.local/share/wcl-raid-coach/
  ~/.cache/wcl-raid-coach/

Windows：
  %LOCALAPPDATA%/wcl-raid-coach/
  %LOCALAPPDATA%/wcl-raid-coach/Cache/
```

`doctor` 的 JSON 输出会报告本次运行实际使用的 `data_root` 和 `cache_root`。高级用户或宿主可以设置 `WCL_RAID_COACH_HOME` 和 `WCL_RAID_COACH_CACHE`，但普通用户只需配置 WCL 凭据。

Skill 安装目录只保存程序和文档。Skill 更新不得影响上述持久数据或缓存。渲染后的 Report Document 位于数据目录的 `outputs/reports/`，Personal Review 的结构化 Advice 位于 `outputs/advice/`。Personal Review acquisition workflow 及其 artifact index 位于 `outputs/personal-workflows/`；最终交付记录和 finalization 记录位于 `outputs/personal-deliveries/`。这些目录中的 `index.json` 只登记对应的本地内容寻址 artifact，不是可替代来源数据的指针。canonical path、index 和 SHA-256 防止误用任意路径并检测损坏，但不认证生成者，也不能抵抗可同时修改 artifact 与 index 的本地进程。

组装、渲染或 finalization 失败时，已经写入但未被最终 Report Document 引用的不可变 Advice、delivery 或 workflow artifact 会作为 orphan 保留；它们不得被覆盖或自动删除，因为并发报告可能已经引用。回收必须由明确的人工或未来专用清理命令按引用关系和保留策略执行，不能通过清理缓存删除。清理缓存仍会保留 Complete Bundle、Report Index 和渲染报告，但会删除未知字段值的本地副本与下载检查点。公开 CLI 没有原始 timing 参数；Personal Review 的 timing 使用本机 monotonic/wall clock，180/30 秒测量仅在协作式本地 workspace 内可信。测试中的 deterministic injected clock 只用于验证状态，不代表真实本机耗时；`wcl_network_measurement` 为 `not_measured`。Mechanic Evidence Set 只存在于当前进程内，不写入以上目录；渲染报告只保存其最小证据摘录。
## 可选诊断

Skill入口按需读取[机制](workflow-mechanics.md)、[个人复盘](workflow-personal.md)、[攻略](workflow-guide.md)；这些文档随包发布，数据位置和凭据配置相同。优先复核使用单进程triage，个人复盘仍须先初始化workflow再查本地复用。

纯 `inspect`、`prepare`、`query` 不下载名称映射，stdout 不再包含 `ability_names`。inspect 仅使用已有且通过内容、build 与 hash 校验的 content mapping，否则展示 WCL 原名并返回 `content_names: null`。中文建议和正式输出仍要求各自的有效映射；需要这些输出时才初始化名称数据。

在子命令前加 `--diagnostics` 可向 stderr 输出数值性能诊断，不创建持久诊断文件，不包含凭据或事件内容。首次名称映射和 Complete Bundle 缓存命中的测量应分开记录；详见[性能诊断](performance.md)。stdout 仍是原有 JSON。
## 同一 OS 用户的 WCL 协调状态

固定目录 `~/.wcl-report-data/api/` 保存 `schedule.lock` 和原子写入的 `state.json`，独立于 workspace、data/cache root 与凭据。所有本工具的凭据共用一把锁；不假定 WCL 按 client ID 隔离额度。状态仅含额度观测、观测/重置相关时间、保守扣除、冷却与请求中断标志，不保存 token、secret 或请求/事件正文。`cache clear` 不删除此目录。

锁顺序为已有 dataset/cache 或 artifact lock，再到进程内 token lock，最后到共享 HTTP 文件锁；共享入口内不会再次认证或递归请求。POSIX 和 Windows 沿用现有 OS 文件锁，进程退出自动释放，等待最多 10 秒。冷却不通过换 data root 或重启 CLI 解除；到期后由协调 probe 恢复。状态损坏或时钟异常时返回 `wcl_rate_limit`，保留现有数据进度。详见[API 说明](wcl-api.md)。
这里的 `~` 指 OS 注册的用户目录：POSIX 使用 UID 的 passwd 记录，Windows 使用系统 Profile folder API；不会因 `HOME` 或 `USERPROFILE` 环境变量变化而改变共享位置。
