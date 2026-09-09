# 性能诊断

[English version](performance.en.md)

全局 `--diagnostics` 选项仅为本次 CLI 调用启用进程内统计，并在 stderr 输出一行 `kind: "wcl_diagnostics"` JSON；成功与运行中的领域错误都会输出。参数解析失败时尚未开始测量。默认关闭，不创建诊断文件、后台进程或服务。stdout 仍是原有命令结果。

- `network` 按固定操作名聚合每次 HTTP attempt，包含 OAuth、quota probe、GraphQL 和 Wago；`retries` 是首次尝试之后实际发出的次数。`seconds` 使用 monotonic，从打开连接到读取/关闭响应，不包括退避等待与 JSON/gzip 解析。接收字节指 Python 实际读取的 response body，gzip 在解压前计数，包含 WCL HTTP 错误正文及 `IncompleteRead.partial`；不包括头部、TLS 或套接字中未交付给 Python 的字节。Wago 统计成功读取的 chunk，HTTP 错误正文未读取时不计入。
- `stages` 记录调用次数、包含子阶段的 `seconds` 与扣除已测量子阶段后的 `exclusive_seconds`。名称映射时间含其下载、解析及写入；玩家分析时间含 Complete Bundle 校验，报告生成时间含来源重验与文件写入。网络时间与阶段时间可能重叠，不能直接相加。锁等待从开始尝试到获取或超时，不包括持锁执行。
- `counters.canonical_event_passes` 是开始的 Canonical Event 解压/解析遍历次数；损坏导致中止的遍历也计入。它不是 Raw Page 解压次数或成功校验次数。
- `quota` 保存有效数值快照的观测次数及首末快照。观测到的 `pointsSpentThisHour` 变化可能包含其他工具、OS 用户或机器的消费，或额度窗口重置；`attributable_cost` 始终为 `null`，不得把差值标为本命令的确定费用。

诊断只记录固定标签和数值，不记录 URL、报告代码、玩家信息、查询变量、响应正文、错误文本、secret、token 或认证头。已有命令结果可能含其正常证据字段；stderr 诊断是独立输出。

诊断不向 Personal Review workflow/finalization 写入网络测量，也不修改 elapsed、stage progress 或最终 `target_met: null`。Agent synthesis 仍未单独测量，不建立端到端交付保证。

仓库 checkout 可运行 `python -m tools.benchmark --repetitions 3`。工具使用合成 HTTP 响应及真实本地校验/渲染；输入、缓存状态、环境、重复次数与基线结果见[仓库基线记录](https://github.com/Yarnus/wcl-report-data/blob/main/docs/performance-baseline.md)。`tools/`、`tests/`、`docs/` 不包含在 Skill archive 中。

可选真实 WCL 测量使用已有本地凭据，给实际命令加 `--diagnostics`，记录精确命令、输入身份、缓存状态和重复次数，并单独计算中位数。首次 inspect、cold prepare 必须使用独立的新 data/cache root；cached prepare 必须先在同一 root 准备完整数据。明确列出实际测量的场景和未测量项；不要把合成 HTTP 时间称为线上网络延迟。
