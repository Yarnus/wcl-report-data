# 当前团本攻略与参考采集

[English](workflow-guide.en.md)。保留 [Skill 入口](../SKILL.md) 全部门槛。个人复盘仅在需要新候选/Profiles时读取此文，继续原workflow和3样本目标；通用攻略执行下列确认与每Boss目标10路径。

## 解析、确认和复用

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach resolve --spec "邪 DK" --encounter H7 --encounter H8
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach confirm "<TASK_ID>"
```

resolve通过官方元数据确定唯一当前Retail zone、Heroic难度、原始Encounter顺序、默认partition和规范专精；向用户展示名称与身份，明确确认后才发现排名/下载事件。Encounter Designator不是fight ID。H7/H8始终独立Cohort/Encounter Profile/Benchmark和样本数。

先查本地兼容、当前有效的Specialization Profile，可跨Boss共享相同game version/partition/class/spec及来源。每Boss独立Encounter Profile匹配game version/partition/encounter/difficulty。先验证已完成章节及其原Cohort/Profile/Complete Bundle证据；只获取缺失工作，已完成章节可交付，其他明确blocker。匹配名称或旧成功不足以复用；重新运行现有benchmark资格/内容检查及guide校验。样本3–9低置信度、10正常；少于3不能稳定聚合。

## Profiles与候选

资料优先Blizzard/WCL官方、维护中的职业社区/专精指南/模拟文档，Wowhead/Icy Veins交叉验证。需要读取或刷新外部Profile来源时，先读并执行[资料抓取与正文验证](guide-retrieval.md)：WebFetch失败后先尝试同URL的有界本地HTTP抓取，再考虑浏览器及替代来源。Profile只保存URL、标题、访问时间、引用摘要与内容hash；只有实际读到且版本相关的正文才能支持资料结论。

构造Profile时读[数据契约](data-contract.md)的教练Artifact与Advice规则。Encounter eligibility必须声明优先/排除目标，非空列表为跨报告NPC gameID。Profile缺失或失败可展示候选，不能生成稳定Benchmark。

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach profile "<WORK_DIR>/profile.json"
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach candidates --game-version <GAME_VERSION> --encounter-id <ENCOUNTER_ID> --difficulty-id <DIFFICULTY_ID> --partition-id <PARTITION_ID> --class-name DeathKnight --spec-name Unholy --output "<WORK_DIR>/cohort.json"
```

默认最近14天身份完整候选；每Boss目标10。排名未提供source ID时CLI按角色/服务器/职业/专精唯一补全，歧义拒绝。一个调用按report/fight复用metadata，每个候选单独验证。最后已查询页全部保留，继续按稳定身份消费。

候选已给数字fight时直接prepare；同报告多个明确候选可批量prepare，省略inspect。由返回Report Index和coach review验证encounter/difficulty/partition/class/spec，再按Encounter Profile检查死亡、优先/排除目标。只有完整证据和资格通过才是Reference Sample；匿名正文用“样本N（排名/分数）”，保留公开WCL链接。

## 聚合与报告

每个Boss独立聚合，共享合格Specialization Profile：

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach benchmark "<WORK_DIR>/analysis-1.json" "<WORK_DIR>/analysis-2.json" "<WORK_DIR>/analysis-3.json" --cohort "<WORK_DIR>/cohort.json" --encounter-profile "<WORK_DIR>/encounter-profile.json" --specialization-profile "<WORK_DIR>/specialization-profile.json" --output "<WORK_DIR>/benchmark.json"
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach guide "<WORK_DIR>/h7-benchmark.json" "<WORK_DIR>/h8-benchmark.json" --spec-display-name "邪恶死亡骑士"
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach guide-report "<GUIDE_SNAPSHOT_JSON_PATH>"
```

guide-report直接从唯一已校验Snapshot派生，保留每章独立Benchmark/Profile/样本/指标/技能/锚点/来源，校验内容ID和Markdown hash；不通过Agent消息复制字段，不跨Boss混合。交付摘要与report.html_path，保留审计身份。Snapshot只有中文Markdown，英文请求生成前告知限制，不能假装英文artifact。

区分日志事实、当前资料结论和有置信度的推断；不补写Snapshot不存在的rotation、天赋、装备、阶段策略、具体建议或可实现目标。需要已构造的其他Report Document时按数据契约运行coach render；不传HTML/CSS/JS，来源必须路径+SHA256。

中文Spell门槛：由具体ability_id关联、命中已校验Wago完整zhCN SpellName与metadata，不按英文名反查/翻译；机制Spell缺失停止最终攻略。检查锚点、统计、首次施法与建议中的Spell。无法确认Spell的术语标机制描述。JSON可保留ID/WCL原名/build供审计。Encounter/NPC使用独立content mapping，NPC仅所属Encounter内展示，不能据名字确定actor身份；未命中保留原名。规则自带名称的Mechanic Review不受此下载门槛影响。

限流/中断保存持久检查点与已完成章节，coach status/record维护任务进度；partial章节声明blocker，不降低证据要求填充。临时机制证据无检查点。
