# Day 5 G4 Fixture Owner Decision

日期：2026-08-26  
所有者核验：W-JOSLIN-X（成员 B）

`fixtures/day5/conflict_events.json` 保持 `0.1-draft`，不改写成联合批准或 gold。成员 A 的审阅意见保留为历史输入，但其中“需要任意结构化 exception schema”和“时间窗口自动检测”没有进入冻结 G4 契约，不能据此扩展产品边界。

| draft | owner decision | executable case | 理由 |
|---|---|---|---|
| d5-c01 | revise | d5-g4-conflict-01 | 同 scope 的显式冲突由用户 `prefer`；另一卡暂停。 |
| d5-c02 | insufficient | d5-g4-conflict-06 | compatible 文本不是冲突；本轮改为验证跨 owner 冲突不可见。 |
| d5-c03 | revise | d5-g4-conflict-02 | 用冻结的 `separate_scopes` 创建双方新版本。 |
| d5-c04 | revise | d5-g4-conflict-07 | scope 裁决必须校验双方 current version，stale 返回 409。 |
| d5-c05 | revise | d5-g4-conflict-05 | 区分 evidence reinforcement 与用户填写正文的 manual merge。 |
| d5-c06 | revise | d5-g4-conflict-04 | G4 不自动推断时间偏好；显式冲突可选择 `pause_both`。 |
| d5-c07 | keep | d5-g4-conflict-03 | 用户填写合并卡，来源卡转为 merged。 |
| d5-c08 | revise | d5-g4-conflict-08 | 只使用冻结的受控 exception；本 case 聚焦幂等 replay 不重复事件。 |

可执行集是 `g4_conflict_cases.json` 的 8 条、`g4_pack_security_cases.json` 的 12 条。`g4_eval_manifest.json` 冻结 24/60/12/8 数量、每个源文件 SHA-256 和 `g4_split_v1`；这只表示成员 B 本轮核验，不声称成员 A 联合批准。
