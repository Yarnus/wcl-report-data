# 个人复盘

[English](workflow-personal.en.md)。保留 [Skill 入口](../SKILL.md) 的选择、凭据和证据门槛。需要构造 Profile/Advice 时读取[数据契约](data-contract.md)的教练 Artifact、Report Document 与 Personal Review 计时规则；不在消息中重抄 artifact 字段。

## 选择后立即计时

裸报告 inspect 后让用户选择 attempt/player；URL 中的数字 fight/source 必须是用户预期对象。一经明确，早于 doctor、目标 Bundle、候选和 Profile retrieval/synthesis 初始化：

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach personal-workflow-init "https://www.warcraftlogs.com/reports/<REPORT_CODE>#fight=<FIGHT_ID>&source=<ACTOR_ID>"
```

保存 workflow_path。初始 blocked/retrieval in_progress/agent_synthesis unavailable/personal_analysis null 是预期状态。之后直接 prepare 目标并计算事实：

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach review "<MANIFEST_PATH>" --index "<REPORT_INDEX_PATH>" --source-id <ACTOR_ID> --partition-id <PARTITION_ID> --output "<WORK_DIR>/analysis.json"
```

## 本地复用优先

刷新排名前搜索兼容的本地 Encounter Benchmarks，连同其绑定的原 Ranking Cohort、两个 Profiles、Reference Analysis 与 Complete Bundles 一起检查。game version、encounter、difficulty、class、spec、partition、Profile ID/source 必须一致且当前有效；相同 encounter/spec 不足以复用。使用现有 personal-workflow 深度验证，精确重建 Benchmark；不能凭路径、mtime、size 或以前成功而信任。

已有合格3–10个立即使用，不为凑10等待。3–9低置信度，10正常。无有效复用时以3个合格 Reference Samples 为目标，候选不是样本。需要新候选/Profiles 时读[攻略采集](workflow-guide.md)，个人候选目标3，底层 candidates默认上限10。资料必须真实读到正文并核验当前版本；抓取失败记录缺口，不把搜索摘要或职业概述当专精攻略。

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach personal-workflow "<PERSONAL_ANALYSIS_PATH>" --cohort "<ORIGINAL_COHORT_PATH>" --encounter-profile "<ENCOUNTER_PROFILE>" --specialization-profile "<SPECIALIZATION_PROFILE>" --reference-analysis "<REFERENCE_ANALYSIS>" --benchmark "<EXISTING_BENCHMARK>" --previous-workflow "<INITIAL_OR_LATEST_WORKFLOW>" --progress "<CHECKPOINT_PATH>"
```

省略不存在的 optional benchmark/reference/progress 参数。每次传入初始化或最新 canonical workflow；其 registry、路径和 hash 必须有效。失败以稳定身份如 `--rejection ABC123:7:42=player_death` 记录。保留完整已查询去重排名页，按稳定候选身份恢复，不按样本/拒绝数推算 cursor。

`acquiring` 只处理返回的 next_ranking_candidate；每项可选工作前由 workflow 检查20秒预留。`comparison_ready` 运行 compare和完整报告；`partial_ready` 不创建 Benchmark/Comparison。仅分页 metadata 证明终页才是 ranking_page_exhausted，否则 ranking_cohort_refresh_required。API failure停止可选工作并保存 blocker/progress；在途请求可越界。progress只是 hash绑定的checkpoint引用，不是Complete Bundle。玩家证据不可用时blocked，不交付报告。

所有调用继承最初monotonic/wall起点，调用间隔包含网络、Profile与Agent合成；不接受手填 timing。时钟倒退或baseline超tolerance时保留进度并标记 timing_continuity_unavailable、停止可选工作；session marker仅诊断。最终Agent synthesis不可单独观测，标unavailable，target_met始终null，wcl_network_measurement为not_measured；180/30秒不是保证。

## 确定性交付

workflow建立/验证Benchmark后，`coach compare`保存精确Comparison。完整路径：

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach compare "<PERSONAL_ANALYSIS_PATH>" "<ENCOUNTER_BENCHMARK_PATH>" --output "<COMPARISON_PATH>"
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach personal-report "<PERSONAL_ANALYSIS_PATH>" "<ENCOUNTER_BENCHMARK_PATH>" "<COMPARISON_PATH>" --workflow "<COMPARISON_READY_WORKFLOW>" --advice "<WORK_DIR>/advice-draft.json" --encounter-profile "<ENCOUNTER_PROFILE>" --specialization-profile "<SPECIALIZATION_PROFILE>" --locale zh-CN
```

0–2合格样本结束时：

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach personal-report "<PERSONAL_ANALYSIS_PATH>" --workflow "<PARTIAL_READY_WORKFLOW>" --encounter-profile "<ENCOUNTER_PROFILE>" --specialization-profile "<SPECIALIZATION_PROFILE>" --advice "<WORK_DIR>/advice-draft.json" --locale zh-CN
```

partial仍深验玩家、Cohort、资格、Reference Bundles和Profiles，由证据推导样本数，comparison unavailable；不接受调用方整数或Benchmark/Comparison。玩家不完整不能partial。无建议省略advice；英文用locale en。交付摘要、report.html_path及审计所需advice/document/hash/index身份。

assembly、renderer、delivery独立重验所有来源并重建精确Benchmark/Comparison；HTML/index存在且finalization成功才交付。只复用完全相同规范字节与hash，不覆盖损坏内容。Advice/workflow/delivery失败留下的不可变孤儿按明确人工或专用引用回收策略处理，不自动删除。Report Document仅schema2；旧schema1静态HTML可看但不可重渲染。

## 建议与指标

Advice草稿完整示例（示例ID、数值和source index必须替换为当前已校验证据；此示例为有条件的经验建议，伤害总量引用不证明能力动作应增加）：

```json
{
  "schema_version": 2,
  "locale": "zh-CN",
  "items": [{
    "dimension": "output",
    "evidence_class": "experience_based",
    "action": {"kind": "use_ability", "ability_id": 2},
    "conditions": ["effective_window", "mechanic_safe"],
    "verification_goal": "check_ability_usage",
    "ability_ids": [2],
    "fact_references": [{"source": "personal_analysis", "path": "/metrics/damage_total", "value": 150}],
    "guidance_references": [{"profile_kind": "specialization", "source_index": 0}]
  }]
}
```

合法枚举：action.kind为`use_ability`、`review_fact`、`observe_pattern`、`adjust_timing`；conditions项为`effective_window`、`mechanic_safe`、`target_available`、`next_attempt`；verification_goal为`compare_next_attempt`、`check_event_fact`、`check_ability_usage`。具体事实引用和证据门槛继续遵循数据契约及下文要求。

Agent从已校验artifact和当前Profile合成Advice schema2，不新增模型服务。使用上述有限action/condition/verification枚举、四维度output/survival/mechanics/team_contribution和event_supported/experience_based；事实逐值引用，指导按profile kind/零基source index引用。完整路径Profile路径/hash/ID/sources必须与Benchmark一致；partial经验仅Profile、事件仅Personal Analysis。引用验证不证明自然语言正确。

能力动作及ability_ids均绑定同ID的player_cast声明，事件支持只用同ID direct-player/key_action字段；owned damage/healing、automatic/internal/pet/synthetic Melee1仅审计。生存引用死亡，团队贡献引用打断/总治疗/资源；当前个人来源无Mechanic Review，mechanics仅可作有当前来源的有条件经验建议。关键动作仅key_action_*，全样本零次仍保留，不回退casts_median。中文建议必须命中zhCN，普通事实可回退WCL名。

保留精确revision/fight/actor、比较硬条件、Benchmark身份/置信度/样本数、总量、双方时长、每分钟量和有效分母；无分母用null。归一化不校正存活、停手、阶段、天赋、装备、分工；中位数不是建议次数。非空目标列表必须npc_game_id，旧report-local ID须迁移后重建下游。已有全部artifact/mapping时离线重建，缺失则获取。四维度无建议明确未评估，不声称责任、因果或保证提升。
