# MemTrace Day 4 G3 契约冻结决策

状态：`frozen-for-member-a-implementation`

冻结日期：2026-08-24（Asia/Shanghai）

事实核验起点：`origin/main = 4a383660b65b9b9f7cd76c3acba293193b0a9c3f`

适用范围：Day 4 成员 A 的真实后端实现，以及成员 B 第二阶段的独立审查、前端实现和最终门禁。本文是共享契约 change note；实现若要改变本文字段、算法、事务或错误语义，必须先停下并由成员 B 更新本文和全部契约投影，不能在代码中静默漂移。

## 1. 事实优先级与已验证现状

本决策按以下优先级形成：当前用户要求、根目录 `AGENTS.md`、`docs/OWNER_LED_COLLABORATION_WORKFLOW.md`、当前可执行代码/契约/迁移/本轮测试、Day 4 continuation、总计划和旧报告。

本轮从当前 `origin/main` 独立确认：

- Day 3 锚点 `34681a4082f52da3a67e784f348111f9d0e38044` 是当前 main 的祖先；当前分支最初干净且与 `origin/main` 完全一致。
- 当前契约为 `1.2.0`，TaskFingerprint 为 `1.1`；G3 采用兼容的协调升级 `1.3.0`，不改变服务端 `auto_rule_v1` 分类来源，也不允许客户端提交 `scenario`。
- Alembic 当前唯一 head 是 `003_g2_job_retryable`。G3 必须新增唯一线性 head `004_g3_retrieval_usage`，不得产生并行 head。
- 当前只有瞬时占位事件 `memory.retrieval.started`，固定报告 `memory_count=0`；orchestrator、ProviderRequest 和 provider messages 均未接入真实长期记忆。
- 当前没有 retrieval trace、retrieval decision、usage receipt、verification job 或 memory counters 表；`memory_jobs` 仅支持 `extract_feedback` 且 `feedback_id` 非空，因此 G3 verifier 使用独立表，不破坏 G2 job 语义。
- 当前 active card 有不可变 version，但 `created_by_action` 仅允许 `accept|edit_accept`；active edit 需要新增 `edit` 动作并迁移约束。
- 当前后端只有候选 resolve、memory list/detail；没有 active edit、pause/resume、versions/usages/trace/user-effect 路由。前端也只有 G2 候选流和 Day 3 “尚未接入长期记忆检索”占位。
- 当前 Python 依赖没有 NumPy、scikit-learn 或 sentence-transformers；默认检索器必须用标准库实现确定性 char n-gram TF-IDF，不新增重型依赖、不联网下载模型。
- `fixtures/day4/retrieval_events.json` 是 30 条 `0.1-draft`，`review_status=member_b_draft_requires_joint_review` 且 `executable_in_day3=false`，不是 gold。

本轮基线：后端 `353 passed`；前端 typecheck、lint、`42 passed` 和 production build 通过；Ruff check/format、`pip check` 通过。Docker 与双浏览器是第二阶段门禁，不是本文的 Stage 1 通过证据。

## 2. G3 产品边界

Day 4 只交付：

1. owner-scoped、只读 active version 的确定性检索；
2. 服务端 scope/exception/status/time/conflict 硬过滤和冻结评分；
3. Top-K、阈值和 prompt 硬预算；
4. 低权限 prompt 注入；
5. 可恢复的 RetrievalTrace、RetrievalDecision、UsageReceipt 和验证任务；
6. active edit、pause/resume、versions/usages/trace 只读与 usage user-effect 最小 API；
7. task stream 上可恢复的 G3 persistent events；
8. Mock 可执行证据和真实 provider adapter 的严格 verifier 协议，但真实 Provider smoke 不是 Day 4 硬门禁。

Day 4 明确不做：BGE 下载或默认启用、向量数据库、reranker、Day 5 冲突裁决/merge/Pack、归档/永久删除全流程、Day 6 自动阈值调参、Day 7 发布分析。UI 不得把 retrieved/selected/injected 写成 active/applied/learned。

## 3. ID、枚举与严格投影

所有响应继续 `extra=forbid`；所有新增 TS runtime parser 同样拒绝额外字段。

### 3.1 ID

- `RetrievalTraceId`：`trace_` + 26 字符 Crockford ULID。
- `UsageId`：`usage_` + 26 字符 Crockford ULID。
- `VerificationJobId`：`vjob_` + 26 字符 Crockford ULID。
- 三类记录都必须有 `owner_id` 数据库列；`owner_id` 只来自已验证 session，永不接受客户端字段，也不出现在公开响应。
- 每个 run 最多一个 trace：`UNIQUE(owner_id, run_id)`。
- 每个 run/memory/version 最多一个 usage：`UNIQUE(owner_id, run_id, memory_id, memory_version_id)`。

### 3.2 RetrievalMode 与算法版本

- `retrieval_mode`: `tfidf | tfidf_degraded`。
- Day 4 默认且正常的模式只能是 `tfidf`，`algorithm_version=char_tfidf_v1`。
- 本轮没有 BGE 的本机、第二设备和容器 smoke 证据，因此不实现或声明 BGE。
- `tfidf_degraded` 仅预留给未来“明确选择 BGE 后运行时回退 TF-IDF”的情形；Day 4 正常 TF-IDF 绝不能显示 degraded。

### 3.3 RetrievalDecision

每个同 owner 的被评估 card 产生一条持久 decision；跨 owner card 必须在 SQL owner 条件处消失，不能生成 decision/reason/event。

字段冻结为：

- `memory_id`
- `memory_version_id: string | null`
- `memory_status`
- `retrieved: boolean`：通过所有硬过滤并进入向量评分。
- `selected: boolean`：分数达到阈值且进入 Top-K。
- `injected: boolean`：最终通过 prompt budget 并进入 provider request。
- `rank: integer | null`：只对 selected 设置，从 1 开始；budget 排除不改变 rank。
- `scope_match: number | null`
- `semantic_similarity: number | null`
- `provenance_confidence: number | null`
- `verified_effect: number | null`
- `recency: number | null`
- `final_score: number | null`
- `reason_codes: non-empty unique list[RetrievalReasonCode]`

硬过滤发生前无法计算的分项必须为 `null`，不能伪造 0。分数公开序列化为 6 位小数，但排序使用未 round 的原始值。

`RetrievalReasonCode` 冻结为：

- `selected_above_threshold`
- `memory_mode_off`
- `status_not_active`
- `not_yet_valid`
- `expired`
- `scope_domain_mismatch`
- `scope_task_type_mismatch`
- `scope_artifact_mismatch`
- `scope_audience_mismatch`
- `scope_project_mismatch`
- `scope_language_mismatch`
- `scope_framework_mismatch`
- `current_constraint_override`
- `active_conflict`
- `invalid_active_card`
- `empty_vector`
- `below_threshold`
- `top_k_exceeded`
- `prompt_budget_exceeded`

selected decision 至少含 `selected_above_threshold`；selected 但未 injected 时再含 `prompt_budget_exceeded`。不得用自由文本 reason 替代受控码。

### 3.4 RetrievalTrace

字段冻结为：

- `request_id`
- `retrieval_trace_id`
- `task_id`
- `run_id`
- `retrieval_mode`
- `algorithm_version`
- `threshold`（Day 4 固定 `0.68`）
- `top_k`（Day 4 固定 `3`）
- `candidate_count`
- `retrieved_count`
- `selected_count`
- `injected_count`
- `decisions`
- `retrieval_ms`，非负整数，仅测 owner 查询、过滤、评分、编译和持久化前准备，不含 provider 生成。
- `memory_chars`：最终完整 `<MEMORY_CONTEXT>` UTF-8 文本的 Unicode scalar 数；无注入为 0。
- `memory_tokens_estimated`：第 7 节冻结 estimator 的结果；无注入为 0。
- `provider_prompt_tokens_actual: integer | null`：仅 real provider 明确返回 actual usage 时更新；Mock 永远为 `null`。
- `prompt_section_hash: lowercase sha256 hex | null`：对最终精确 UTF-8 memory section 求 SHA-256；无注入为 `null`。
- `reason_codes: unique list[RetrievalReasonCode]`：正常为空；memory off 时只能为 `[memory_mode_off]`。
- `created_at`、`updated_at`

estimated memory tokens 与 provider actual prompt tokens 是不同字段、不同来源，UI 必须分别标注。

### 3.5 UsageReceipt

每个 selected decision 创建一条 receipt；未通过预算时 `injected=false`，不创建 verifier job。字段冻结为：

- `usage_id`
- `retrieval_trace_id`
- `task_id`
- `run_id`
- `memory_id`
- `memory_version_id`（必须绑定检索时的不可变版本）
- `rank`
- `retrieved=true`
- `selected=true`
- `injected`
- `estimated_tokens`
- `verification_status: pending | applied | violated | not_observable | unknown`
- `verification_method: exact_substring | structured_provider | null`
- `evidence_excerpt: string | null`，最多 120 Unicode scalar，必须是实际 assistant output 的原文连续子串。
- `user_effect: helpful | harmful | stale | null`
- `created_at`、`updated_at`

`applied` 只能由实际输出证据产生；selected/injected 不能推导为 applied。验证失败或中断最终只能是 `unknown`，不能假装成功。

## 4. MemoryCard、scope 与生命周期增量

### 4.1 MemoryCard 投影增量

G3 在 Pydantic、JSON Schema、OpenAPI、TS、runtime parser 和 examples 中同步新增：

- `valid_from: datetime | null`
- `valid_to: datetime | null`
- `retrieved_count: integer >= 0`
- `injected_count: integer >= 0`
- `verified_applied_count: integer >= 0`
- `helpful_count: integer >= 0`
- `harmful_count: integer >= 0`
- `stale_count: integer >= 0`
- `last_used_at: datetime | null`

paused card 必须继续满足 active version 的结构不变量：有 current version、`version>=1`、confirmed rule/scope confidence、无 rejection reason。pause 不创建新 version；resume 也不创建新 version。

### 4.2 MemoryScope 增量

当前 `null` 表示 unknown/未确认，绝不是 wildcard。G3 扩展 scope：

- `task_type`、`artifact_type`、`audience` 允许各自现有枚举、显式 `any` 或 `null`。
- `project_key` 允许规范化字符串、显式 `any` 或 `null`。
- `language` 允许 ProgrammingLanguage、显式 `any` 或 `null`。
- `framework` 允许规范化小写 tag、显式 `any` 或 `null`。
- `concepts` 为唯一、排序后的规范化 Concept 列表，最多 12 个；空列表表示 unknown，不是 any。

现有 scope JSON 缺少新增字段时迁移/读取按 `null/null/[]` 补齐，不能按 any 补齐。

### 4.3 active edit、pause、resume

- active edit 仅允许当前 `active` card；请求必须带 `expected_current_version_id` 和非空 `MemoryCardPatch`。
- edit 在一个事务中创建 `version+1` 的不可变 row（`created_by_action=edit`），原子切换 card current version 与镜像字段。旧版本不更新、不删除。
- pause：仅 `active -> paused`，保留 current version。
- resume：仅 `paused -> active`，恢复前重跑 active admission invariants；不绕过 evidence/confidence/current-version 门禁。
- 同一个 Idempotency-Key + 同一请求返回原响应；同 key 不同请求为 `409 IDEMPOTENCY_CONFLICT`。
- 新 key 对已经完成的同向重复操作为 `409 MEMORY_STATE_CONFLICT`；stale `expected_current_version_id` 为 `409 MEMORY_VERSION_CONFLICT`。
- SQLite 写路径使用现有 owner-scoped transaction 约定并在竞争写前取得写锁；禁止先读后在另一个事务盲写。
- missing 与 cross-owner memory 统一 `404 MEMORY_NOT_FOUND`。

## 5. 硬过滤

检索必须先在 SQL 中按 `owner_id` 约束，再按以下顺序评估；任一命中即 `retrieved=false`，相应分数为 null：

1. `effective_memory_mode=off` 或 `current_constraints.memory_disabled=true`：整个 run 不查询 card，trace 计数全为 0，并记录 run 级 `memory_mode_off`；不得生成泄露 card 数量的 decision。
2. status 不是 `active`：`status_not_active`。
3. active card 缺 current version、confirmed confidence 或其他结构不变量：`invalid_active_card`；不能用默认值掩盖脏数据。
4. `valid_from > now`：`not_yet_valid`；`valid_to <= now`：`expired`。比较统一使用 UTC aware datetime。
5. scope 中显式非-any 的 domain/task_type/artifact/audience/project/language/framework 与 TaskFingerprint 显式值冲突：对应 mismatch。`null`/`unknown` 只是不贡献匹配分，不能视为 any，也不能单独扩大适用范围。
6. memory exception 与当前约束命中：`response_policy:direct_fix` 对 `DIRECT_FIX`，`urgency:urgent` 对 `URGENT`，结果为 `current_constraint_override`。
7. 与另一条 active card 存在未解除的 `conflicts_with` 关系：`active_conflict`。Day 4 只阻断，不裁决、不 merge。

只读取 current version；candidate/rejected/conflicted/paused/superseded/merged/archived/deleted 均不可召回。

## 6. 确定性 char n-gram TF-IDF 与评分

### 6.1 检索文本

- query 使用当前 TaskFingerprint 的 `semantic_query`。
- memory document 按固定顺序连接：`title + "\n" + rule + "\n" + trigger_text + "\n" + concepts.join(" ")`。
- 不把 evidence、feedback 正文或其他用户历史正文放入检索文档。

### 6.2 `char_tfidf_v1`

完全使用 Python 标准库：

1. Unicode `NFKC`。
2. `str.casefold()`。
3. 所有连续 Unicode whitespace 折叠为一个 ASCII space，随后 strip。
4. 对规范化字符串生成包含 space 的连续字符 2、3、4-gram；长度不足 2 或空串得到零向量。
5. corpus 是一个 query document 加本次通过硬过滤的所有 memory documents；有候选时 `N >= 2`。不持久化词表。
6. `tf(term, doc) = raw_count / total_ngrams_in_doc`；零 gram 文档所有 tf 为 0。
7. `idf(term) = ln((1 + N) / (1 + df(term))) + 1`。
8. 权重为 `tf * idf`，随后 L2 normalize；任一零向量的 cosine 定义为 0。
9. cosine 是两个 L2 向量点积，限制到 `[0,1]` 以消除浮点尾差。
10. 排序和阈值用未 round 值；公开值 round 到 6 位。

### 6.3 scope_match

scope 权重固定：domain `.25`、task_type `.25`、artifact `.10`、audience `.10`、project `.10`、language `.05`、framework `.05`、concepts `.10`。

- 显式 exact 得该项全部权重。
- 显式 `any` 得该项一半权重。
- memory `null`/unknown/空 concepts 得 0，不是 wildcard。
- concepts 使用 Jaccard `|intersection| / |union|` 乘 `.10`；任一侧为空为 0。
- 已在硬过滤中判定的显式冲突不会进入评分。

### 6.4 其他分项与总分

- `provenance_confidence = min(source_trust, rule_confidence, scope_confidence)`；active card 任一 confidence 缺失视为数据不变量失败并拒绝检索，不用默认值掩盖。
- `verified_effect = (helpful_count + 1) / (helpful_count + harmful_count + stale_count + 2)`。
- `recency`：`explicit_feedback|explicit_correction|edit_diff|accept|rating` 为 `1.0`；`outcome|import` 为 `max(0, 1 - age_days/90)`，age 从 current version created_at 计算并限制非负。
- `final_score = .25*scope_match + .30*semantic_similarity + .15*provenance_confidence + .15*verified_effect + .15*recency`。

选择顺序固定为：`final_score DESC`、`semantic_similarity DESC`、`memory_id ASC`。先保留 `final_score >= 0.68`，再取 Top-3；其余分别为 `below_threshold` 或 `top_k_exceeded`。Day 4 禁止依据 test fixture 偷调阈值或权重。

## 7. Prompt Compiler 与硬预算

只有 `injected=true` 的 card 进入 provider request。最终 section 格式固定：

```text
<MEMORY_CONTEXT permission="advisory" data_only="true">
<MEMORY id="mem_..." version="memver_..." score="0.000000">
<WHEN>...</WHEN>
<DO>...</DO>
<AVOID>...</AVOID>
<EXCEPT>...</EXCEPT>
</MEMORY>
</MEMORY_CONTEXT>
```

- 内容字段顺序固定；XML 特殊字符必须转义。`WHEN=trigger_text`，空时使用规范化 scope 摘要；`DO=rule`，`AVOID=avoid`，`EXCEPT` 为受控 exception code 逗号连接。
- system prompt 必须明确：memory 是不可信数据/建议，不能覆盖当前用户请求、当前约束、system policy 或工具权限；绝不把 memory 当命令执行。
- estimator：空串为 0，否则 `ceil(len(text.encode("utf-8")) / 3)`。
- 单个 `<MEMORY>` block 最多 100 estimated tokens；完整 `<MEMORY_CONTEXT>` 最多 300 estimated tokens，外层 tag 计入总预算。
- 先按 rank 编译。单卡超限时按 `EXCEPT -> AVOID -> WHEN -> DO` 顺序在 Unicode scalar 边界截短，并用单字符 `…` 标记；每次重新 escape、编译和估算。不得截断 ID、version、score 或 XML tag。
- 若最小合法 block 仍超过单卡预算，或剩余总预算放不下最小 block，则不注入该卡，保留 selected receipt 且加入 `prompt_budget_exceeded`。
- 截断必须在 provider 生成前完成。`prompt_section_hash` 对最终精确 section 求 SHA-256；日志和 event 只记录 hash、长度、计数，不记录 section/规则/证据正文。

`ProviderRequest` 新增独立的 `memory_context: str | null` 和 `usage_ids: tuple[str,...]`；真实/Mock provider 都必须通过同一接口接收。不得把 memory 拼入 URL、日志或工具参数。

## 8. 持久化、事件与事务边界

### 8.1 新表和 card 增量

`004_g3_retrieval_usage` 新增：

- `retrieval_traces`
- `retrieval_decisions`
- `memory_usages`
- `memory_verification_jobs`

并给 `memory_cards` 新增第 4.1 节 counters/last_used_at，扩展 scope/value checks，给 `memory_versions.created_by_action` 增加 `edit`。不新增 embedding 表。

所有表必须有 owner-scoped index、FK/on-delete 语义、CHECK、唯一约束和 downgrade；fresh upgrade、`003 -> 004` 数据保留、downgrade、唯一 head、readiness、非法状态/跨 owner 引用都要测试。

### 8.2 persistent task-stream events

新增以下 persistent event，`event_seq` 必须非空且沿现有 task stream 连续递增：

- `memory.retrieval.completed`：trace_id、mode、algorithm_version、四个 count、threshold、top_k、retrieval_ms、memory_chars、estimated tokens、prompt hash；不含 decisions 正文。
- `memory.injected`：usage_id、trace_id、memory_id、memory_version_id、rank、estimated_tokens、prompt hash；每个 injected receipt 一条。
- `memory.usage.verified`：usage_id、memory_id、memory_version_id、verification_status、verification_method、`evidence_present`；不含 excerpt。
- `memory.usage.feedback.recorded`：usage_id、memory_id、user_effect；不含自由文本。

瞬时 `memory.retrieval.started` 保持 `event_seq=null`，payload 改为只含 `retrieval_mode`；它不是恢复依据。`agent.plan.published.memory_summary_code` 改为受控 `no_memory_selected|memory_selected`，不能继续谎报 Day 2 占位。

### 8.3 原子性

1. 检索阶段在一个事务中写 trace、全部 decisions、selected receipts、card retrieved/injected counters、`memory.retrieval.completed` 和逐条 `memory.injected`，同时分配连续 task seq；提交后才做 best-effort 内存 SSE broadcast。
2. provider 失败时，上述 trace/receipt 仍保留；在 run failure 事务把 injected receipt 的 pending verification 置为 `unknown`，不创建 applied。
3. provider 成功时，在现有最终 output/run/event 事务中补写 real actual prompt tokens（若 provider 真返回）、为 injected receipt 创建 verification jobs；提交后广播。
4. verifier 在一个事务中更新 job、receipt、card verified counter 和 `memory.usage.verified`，再广播。
5. user-effect 在一个事务中更新 receipt、恰好一次调整 card counters、存 idempotency response、写 event，再广播；同 key replay 不重复计数。

任务 snapshot、专用 GET 和 `after_event_seq` catch-up 必须能恢复 trace/usage/verification；刷新或进程重启后不能依赖 React/SSE 内存状态。

## 9. Verifier

### 9.1 Mock 的确定性 exact-substring verifier

对实际持久化 assistant output 和绑定的 immutable memory version 执行：

1. 若 `avoid` 非空，计算 output 与 avoid 的最长原文连续公共子串；长度达到 `max(4, min(12, ceil(len(avoid)/4)))` 时为 `violated`。
2. 否则计算 output 与 rule 的最长原文连续公共子串；长度达到 `max(4, min(12, ceil(len(rule)/4)))` 时为 `applied`。
3. 两者均无证据为 `not_observable`，不是 applied/violated。
4. excerpt 是命中位置在原始 output 中的连续原文，最多 120 Unicode scalar；禁止用 memory 文本或模型解释伪造 output 证据。

比较使用原始 Unicode scalar，不做模糊匹配；avoid 优先，避免同一输出同时标 applied 和 violated。Mock provider 必须确实把 memory_context 纳入生成路径；测试可用确定性输出证明 applied/violated/not_observable 三种结果。

### 9.2 real provider verifier

复用/扩展 `StructuredProvider`，输入只含最小必要 rule/avoid 与实际 output，要求严格 JSON：

```json
{"status":"applied|violated|not_observable","evidence_excerpt":"string|null"}
```

额外字段、非法 enum、非 output 原文子串或超过 120 字符都判 schema invalid；允许一次同接口 repair，仍失败则 job failed、receipt `unknown`。Provider 异常/body 不进入公开错误、日志或 event。真实 key/smoke 不是 Day 4 默认门禁。

### 9.3 job recovery

`memory_verification_jobs` 一 usage 一 job，状态 `pending|running|completed|failed`，attempt 从 0 开始，受控错误至少有 `MEMORY_VERIFIER_INTERRUPTED|MEMORY_VERIFIER_PROVIDER_ERROR|MEMORY_VERIFIER_SCHEMA_INVALID`。

- 启动时 pending 继续执行。
- stale running 若 `attempt < 2`，原子转回 pending 并递增 attempt；否则置 failed，并把 receipt 置 `unknown`。
- 未 injected receipt 不创建 job。
- worker shutdown、恢复和竞争 claim 必须测试；同一 usage 不能重复 event 或 counters。

## 10. API 冻结

所有 fetch 使用 session cookie；所有 write 使用 `Idempotency-Key`。新增/扩展：

- `GET /api/v1/tasks/{task_id}`：snapshot 新增 `retrieval_trace: RetrievalTrace|null`、`memory_usages: UsageReceipt[]`。
- `GET /api/v1/tasks/{task_id}/retrieval-trace`：当前 run 的完整 trace；无 trace 或 cross-owner task 为 `404 TASK_NOT_FOUND`，不能泄露其他 owner。
- `GET /api/v1/tasks/{task_id}/memory-usages`：当前 run receipts，稳定按 rank/memory_id。
- `PATCH /api/v1/memories/{memory_id}`：`{expected_current_version_id, patch}`，返回 `MemoryDetailResponse`。
- `POST /api/v1/memories/{memory_id}/pause`：`{expected_current_version_id}`，返回 `MemoryDetailResponse`。
- `POST /api/v1/memories/{memory_id}/resume`：同上。
- `GET /api/v1/memories/{memory_id}/versions?cursor=`：不可变版本倒序分页，返回 `MemoryVersionListResponse`。
- `GET /api/v1/memories/{memory_id}/usages?cursor=`：owner-scoped receipt 倒序分页，返回 `MemoryUsageListResponse`。
- `POST /api/v1/tasks/{task_id}/memory-usages/{memory_id}/feedback`：`{effect: helpful|harmful|stale}`，返回更新后的 `UsageReceipt`；以 task current run + memory 唯一定位 receipt。
- `GET /api/v1/memories` 的 status filter 至少扩展到 `candidate|active|rejected|paused`；Day 4 UI 不需要提前实现其他生命周期操作。

task/trace/usage 缺失或 cross-owner 都必须使用不泄露存在性的 404；memory 路由统一 `MEMORY_NOT_FOUND`。新增 `MEMORY_STATE_CONFLICT`、`MEMORY_VERSION_CONFLICT` 两个 409 code。请求/响应/错误全部进入 OpenAPI、JSON Schema、Pydantic、TS 和 runtime parser。

user-effect 只允许作用于 `injected=true` 的 receipt；selected 但因预算未注入的 receipt 用新 key 写入时返回 `409 MEMORY_STATE_CONFLICT`，不能影响 helpful/harmful/stale counters。

## 11. Fixture 决策

现有 30 条 draft 不改 `review_status`，不直接成为 G3 阈值测试。已发现至少这些阻断：

- `d4-r06` 把“会议纪要”配为 `scope_domain=other` 并假设 session scope，但 fixture 没有 scope level/session 字段；当前服务端 classifier 很可能把文本任务判为 `general_text`，不能把 `other` 当 wildcard。
- `d4-r16`、`d4-r17` 的 override 只写在自然语言 query/reason 中，没有结构化 `current_constraints` 和 memory `exceptions`，不足以执行硬过滤。
- `d4-r18` 至 `d4-r29` 多数依赖 language/audience/project/artifact/concept，但 fixture 没有完整 TaskFingerprint/MemoryScope 字段。
- 全部条目缺少完整 MemoryCard/version/confidence/counters/corpus；TF-IDF 的 IDF 依赖同批 corpus，单条 query/memory 不能唯一锁定最终分数。
- 草案里的 `reason` 是人工标签，不等于本决策冻结的 reason code。

成员 A 只能逐条写 `docs/day4/RETRIEVAL_FIXTURE_REVIEW.md`，记录 `keep|revise|insufficient` 与理由，并用独立、完整、确定性的 G3 fixtures 锁算法。成员 B 第二阶段共同复核后才能决定是否升级 review status；不得冒充“两人已批准”。

## 12. 契约同步与成员 A 完成门槛

成员 A 必须同步：

- `contracts/day4-g3.json`
- `contracts/README.md`
- `contracts/schemas/g0-api.schema.json`
- `contracts/schemas/events.schema.json`
- `contracts/openapi.json`（必须与实际 app OpenAPI 精确一致）
- `contracts/examples/day4-g3.json`
- Pydantic/ErrorCode/EventType/PAYLOAD_TYPES
- TS types、严格 runtime parser 由成员 B 第二阶段完成，但成员 A 必须交付足够清晰的真实后端 schema/API 供其消费；若 A 修改现有共享 TS 投影，必须同步测试。

成员 A 后端测试至少锁定：中英文/NFKC/casefold/空白/零向量/IDF/round/tie-break；全部硬过滤；阈值/Top-3；300/100 token 和截断/hash；Prompt injection 实际进入 Mock/real adapter；trace/usage/event 同事务与 seq catch-up；verifier 三态与 restart；active edit/version/pause/resume；idempotency/concurrency；cross-owner task/memory/trace/usage/SSE；fresh/upgrade/downgrade/唯一 head/readiness；actual-token 与 estimate 分离；metadata-only logs。

任何与本文不一致或无法实现的点都必须在编码前回报成员 B；不能用降级、自由文本字段或跳过测试悄悄替代。
