# WorkBuddy 凭据与存储配置

本文说明凭据查找顺序和各平台的默认存储位置。[English version](workbuddy-setup.en.md)

WorkBuddy 可能运行在带有持久化 `/workspace` 的云端沙盒中，也可能直接运行在本地 macOS、Linux 或 Windows。不得假定 `/workspace` 一定存在。

## 凭据

先运行：

```bash
python -m wcl_raid_coach doctor
```

如果结果包含 `"wcl_api": "reachable"`，现有凭据已经可用，直接继续即可。`credential_source` 会安全地标明来源，例如 `environment:WCL_ID`，但不会输出 client secret 或 access token。

进程环境变量始终优先。没有进程凭据时：

- 使用 `--env-file` 时，只读取该参数明确指定的文件。
- 未使用 `--env-file` 时，依次读取 `/workspace/.env` 和启动 CLI 时所在目录的 `.env`。

每组变量必须成对配置，不混用两组名称。进程环境变量已经可用时，无需另外创建 `.env`。

### WorkBuddy 云端

只有环境中确实存在 `/workspace` 时，才使用 `/workspace/.env`。AI 可以先检查文件是否存在；不存在时创建以下空白模板，已有文件绝不能覆盖：

```dotenv
WCL_CLIENT_ID=
WCL_CLIENT_SECRET=
```

### 本地运行

macOS、Linux 或 Windows 本地没有 `/workspace` 时，AI 应让用户只提供或确认真实 workspace 目录路径。不得让用户在对话中提供 client ID 或 secret。AI 检查 `<WORKSPACE>/.env`；文件不存在时可以创建以下空白模板，存在时保留原内容：

```dotenv
WCL_CLIENT_ID=
WCL_CLIENT_SECRET=
```

用户通过文件编辑器或平台密钥设置私下填写后，AI 从 Skill 目录运行命令并显式传入文件：

```bash
python -m wcl_raid_coach --env-file "<WORKSPACE>/.env" doctor
python -m wcl_raid_coach --env-file "<WORKSPACE>/.env" inspect "<WCL_URL>"
```

`--env-file` 必须放在子命令之前，后续 `prepare` 也使用同一路径。不要把 `.env` 提交到 Git，不要在对话中粘贴 secret。

## 存储

当 `/workspace` 存在时：

```text
/workspace/wcl-raid-coach/          evidence, profiles, tasks, and guides
/workspace/.cache/wcl-raid-coach/   raw pages and resumable checkpoints
```

本地 Unix/macOS 默认使用：

```text
~/.local/share/wcl-raid-coach/      evidence, profiles, tasks, and guides
~/.cache/wcl-raid-coach/            raw pages and resumable checkpoints
```

Windows 数据目录默认使用 `%LOCALAPPDATA%/wcl-raid-coach/`，缓存目录使用其下的 `Cache/`。所有环境都可通过 `WCL_RAID_COACH_HOME` 和 `WCL_RAID_COACH_CACHE` 覆盖默认路径。2.0 使用全新目录，不读取旧 `wcl-report-data` 数据。

清理缓存会保留规范 Fight Bundle，但会删除被省略的未知字段值和下载检查点。
