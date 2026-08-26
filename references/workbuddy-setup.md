# WorkBuddy 凭据与存储配置

WorkBuddy 可能运行在带有持久化 `/workspace` 的云端沙盒中，也可能直接运行在本地 macOS、Linux 或 Windows。不得假定 `/workspace` 一定存在。

## 凭据

先运行：

```bash
python -m wcl_report_data doctor
```

如果结果包含 `"wcl_api": "reachable"`，现有凭据已经可用，直接继续即可。`credential_source` 会安全地标明来源，例如 `environment:WCL_ID`，但不会输出 client secret 或 access token。

凭据按以下顺序读取：

1. 进程环境变量中的 `WCL_CLIENT_ID` + `WCL_CLIENT_SECRET`，或 `WCL_ID` + `WCL_SECRET`
2. `/workspace/.env`
3. 启动 CLI 时所在目录的 `.env`

每组变量必须成对配置，不混用两组名称。进程环境变量已经可用时，无需另外创建 `.env`。

### WorkBuddy 云端

只有环境中确实存在 `/workspace` 时，才通过 WorkBuddy 文件编辑器创建 `/workspace/.env`：

```dotenv
WCL_CLIENT_ID=your-client-id
WCL_CLIENT_SECRET=your-client-secret
```

### 本地运行

macOS、Linux 或 Windows 本地没有 `/workspace` 时，在运行命令前的当前工作目录创建 `.env`。Skill 只检查该目录，不会自动扫描其他项目目录或安装目录。

```dotenv
WCL_CLIENT_ID=your-client-id
WCL_CLIENT_SECRET=your-client-secret
```

不要把 `.env` 提交到 Git。通过文件编辑器或平台密钥设置填写凭据，不要在对话中粘贴 secret。

## 存储

当 `/workspace` 存在时：

```text
/workspace/wcl-report-data/          prepared datasets
/workspace/.cache/wcl-report-data/   raw pages and resumable checkpoints
```

本地 Unix/macOS 默认使用：

```text
~/.local/share/wcl-report-data/      prepared datasets
~/.cache/wcl-report-data/            raw pages and resumable checkpoints
```

Windows 默认使用 `%LOCALAPPDATA%`。所有环境都可通过 `WCL_REPORT_DATA_HOME` 和 `WCL_REPORT_DATA_CACHE` 覆盖默认路径。

清理缓存会保留规范 Fight Bundle，但会删除被省略的未知字段值和下载检查点。
