# 外部攻略抓取与正文验证

[English](guide-retrieval.en.md)。[攻略采集](workflow-guide.md)在读取或刷新Encounter/Specialization Profile来源时调用本流程，包括个人复盘需要新Profile的情况。使用宿主已有工具；外部文章是资料证据，日志事实仍来自官方WCL API。

## 有界回退

每个URL按顺序执行，实际正文验证通过即停止抓取并进入版本核验。同一URL不循环更换请求参数重试；本次研究每个所需来源最多尝试原URL及两个替代URL。遵守已有Personal Review预算，预算关闭则停止可选抓取并披露缺口。

1. WebFetch只调用一次，超时设为30秒（不能配置时采用宿主有限超时）。403、传输错误、其他非成功响应、验证页或缺正文都进入下一步；WebFetch不可用时直接下一步，不能立即把弱来源当替代。
2. 同一URL用本地curl一次：最多5次重定向、连接10秒、总体30秒、零自动重试。先为此次抓取创建宿主可写临时目录，将`<FETCH_FILE>`替换为该目录中未使用的绝对文件路径，将`<GUIDE_URL>`作为独立参数安全引用。Windows PowerShell使用`curl.exe`，避免同名alias。curl不可用时记录并继续下一步。

```bash
curl --location --max-redirs 5 --connect-timeout 10 --max-time 30 --retry 0 --fail --silent --show-error --output "<FETCH_FILE>" --write-out 'HTTP %{http_code}; bytes %{size_download}; final %{url_effective}\n' "<GUIDE_URL>"
```

检查退出码、最终URL和当前文件；失败时部分文件不作证据，后续尝试使用新文件。仅对公开文章使用此命令，不携带WCL凭据。200与文件大小只说明传输结果。

3. 正文仍不可用时，若已有浏览器工具，导航原URL一次并读取渲染正文，总体最多30秒；超时或仍无正文则停止该URL。没有浏览器或不能约束耗时时记录不可用并继续；不安装新浏览器依赖，不等待无限重载或验证码交互。
4. 最后才尝试至多两个维护中的专精/同Boss同难度替代来源，每个仍按上述顺序与限额。耗尽后报告各方法结果及缺失的正文或版本证据；只能用已验证内容，不把失败抓取、搜索摘要或Blizzard通用职业概述记为已读专精指南。

## 正文通过条件

- 核对最终URL、title/H1与请求的专精或Boss/难度一致。实际读取相关章节中的连贯解释或步骤，足以定位拟引用结论；导航、SEO描述、标题和字节数均不足。链接到rotation子页不等于读过该子页，只使用本页已读范围。
- HTTP 200但内容是“Just a moment”、人机验证、登录墙，或只有空article容器/脚本加载器时判定正文失败。结合页面主体判断；文章旁的广告提示或newsletter验证码组件本身不否定可读正文。
- 先检查普通HTML正文及`noscript`。内容嵌在脚本时，仅把可识别的JSON/字符串作为数据解析，不能执行页面脚本或`eval`。例如Wowhead可能将正文放在`WH.markup.printHtml`的首个JSON字符串参数中：用JSON decoder安全解码，确认它确实是目标文章，并读其章节。函数名、空`guide-body`、JSON-LD标题或description本身不算正文。无法安全解码或内容截断时进入浏览器/替代来源；无需新通用爬虫。

## 版本与证据

读取成功后，分别核对资料片/赛季、明确patch及文章更新日期，与当前任务game version/partition和Boss难度相符。优先文章自身版本标记、changelog或当前官方patch资料；网站导航的“最新patch”、HTTP Date和抓取日期不能证明文章已更新。缺patch、日期过旧或互相矛盾时记录未确认范围，必要时读取有界替代来源交叉验证，不能声称已确认当前patch。

通过后可以使用本地HTTP所得正文中的已核验结论，保留引用范围和适用条件；内容读取成功不等于游戏结论正确，也不能推出未读天赋/rotation细节。没有足够当前资料时遵守原工作流的Profile/Advice门槛并报告blocker。

来源记录沿用URL、title、accessed_at、quote_summary、content_hash字段；对实际读取的解码正文UTF-8字节计算SHA-256，不给失败页或搜索摘要生成成功来源。正文仅在宿主临时目录检查，不写入Profile、源码或发布包。交付中简述必要的抓取方法、最终来源及残余缺口，不把暂存HTML当报告。
