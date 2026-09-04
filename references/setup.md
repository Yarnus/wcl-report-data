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
  /workspace/wcl-raid-coach/          Report Index、Complete Bundle、Profiles、任务与 Guide Snapshot
  /workspace/.cache/wcl-raid-coach/   Raw Page 与可续传检查点

本地 Unix/macOS：
  ~/.local/share/wcl-raid-coach/
  ~/.cache/wcl-raid-coach/

Windows：
  %LOCALAPPDATA%/wcl-raid-coach/
  %LOCALAPPDATA%/wcl-raid-coach/Cache/
```

`doctor` 的 JSON 输出会报告本次运行实际使用的 `data_root` 和 `cache_root`。高级用户或宿主可以设置 `WCL_RAID_COACH_HOME` 和 `WCL_RAID_COACH_CACHE`，但普通用户只需配置 WCL 凭据。

Skill 安装目录只保存程序和文档。Skill 更新不得影响上述持久数据或缓存。清理缓存会保留规范 Fight Bundle，但会删除未知字段值的本地副本和下载检查点。Mechanic Evidence Set 只存在于当前进程内，不写入以上目录。
