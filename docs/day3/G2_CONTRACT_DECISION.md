# Day 3 G2 契约决策（共享契约 PR）

> 状态：草案，待成员 B 在最终 head 上复核。
> 版本：兼容性增量 `1.2.0`（minor）。这不是破坏性 major 升级：唯一破坏项是
> `MemoryJobResponse` 字段演进，而该字段在 D2 只是 pending 占位，尚无消费方。

## 1. 范围

G2 = `feedback/edit-diff → MemoryJob → 自动长期性与类别 → 0–3 张候选
MemoryCard → 真实 Evidence → resolve(accept/edit_accept/reject/one_shot)`。

本 PR 只冻结公开契约：Pydantic 请求/响应、四个新事件 payload、JSON Schema 增量、
`contracts/openapi.json` 确定性导出、Mock 示例和一致性测试。**不实现** worker、
migration、Diff、Compiler、resolve 业务逻辑——那些是后续实现 PR。

## 2. 决策

### 2.1 MemoryJob 状态机（§9.1）

- `status`：`pending → running → completed | failed`；`failed → pending` 只能显式 retry。
- `stage` 在既有 `queued` 上扩展为 `diffing / classifying_durability / extracting /
  validating / admitting / done / failed`。边界态 `queued/done/failed` 不计入“五阶段”。
- `GET /memory-jobs/{id}` 返回 `feedback_id`、`candidate_ids`（固定顺序、最多 3）、
  `disposition`、受控 `error_code` 与 `retryable`，**不回传 provider 原文异常**。
- 新增 `POST /memory-jobs/{id}/retry`，要求 `Idempotency-Key`，只有本人 `failed` 可重试。

### 2.2 自动类别与 MemoryCard kind（§9.2）

`preference / rule / experience / one-shot` 是**自动提取类别**，不是用户下拉框。
固定映射：`preference→preference`；`rule→constraint|procedure`（必须/禁止→constraint，
可复用步骤→procedure，服务端决定）；`experience→experience`；`one_shot/no_memory→不建卡`。

### 2.3 MemoryCard 最小公开字段（§9.3）

确认前不变式：`status=candidate`、`version=0`、`current_version_id=null`、
`rule_confidence=null`、`scope_confidence=null`；explicit durable 只令
`save_preselected=true`，**不得**令 status=active。确认后才建不可变 v1 并原子置 active。

### 2.4 resolve（§9.4）

- `accept/edit_accept/reject/one_shot`；`accept/reject/one_shot` 的 patch 必须空。
- `edit_accept` 至少改一个允许字段，**不得**改 kind/owner/source/trust/status。
- 只允许本人 candidate；跨 owner 与不存在统一 404；同 key 同 body 重放，同 key 不同 body 409。

### 2.5 读 API（§9.5）

`GET /memories?status=...&cursor=...` 与 `GET /memories/{memory_id}`，list/detail 都 owner
隔离；detail 为证据抽屉提供 evidence 投影与版本元数据；event_log 不含正文。

### 2.6 事件（§9.6）

新增持久事件：`memory.extraction.stage`、`memory.candidate.created`、
`memory.admission.resolved`、`memory.job.failed`。payload 只有 ID、受控枚举、序号、状态与
安全错误码。新增事件已同步：`EventType`、Pydantic payload、`PAYLOAD_TYPES`、
`PERSISTENT_EVENT_TYPES`、`contracts/schemas/events.schema.json`、OpenAPI、Mock 示例、契约测试。

### 2.7 错误码（新增）

HTTP：`MEMORY_NOT_FOUND`（统一 404）、`MEMORY_ALREADY_RESOLVED`（409）、
`MEMORY_JOB_NOT_RETRYABLE`（409）。Job 受控错误码见 manifest `new_job_error_codes`。

## 3. 文档描述 / 代码事实 / 本次决策 / 对应测试

| 文档描述 | 代码事实 | 本次决策 | 对应测试 |
|---|---|---|---|
| 总计划 §11.4 含 `trust_level`、多状态枚举 | D2 无 MemoryCard | G2 只暴露最小字段，`trust_level` 折叠为 `source_trust`，`conflicted/paused/...` 枚举一次容纳但 G2 不实现 | `test_memory_card_invariants` |
| 总计划 §12.4 resolve 含 `patch.scope` | 无实现 | 冻结 `MemoryCardPatch` 允许字段，patch 只对 `edit_accept` 合法 | `test_resolve_request_rules` |
| TEAMMATE_AGENT_PROMPT §9.1 `error_code` | D2 `last_error_code` 列存在 | job 响应字段名 `error_code`，值为受控枚举 | `test_memory_job_response_shape` |
| 总计划 §12.8 事件 `memory.candidate.created` 只带 `memory_id,evidence_id` | 无实现 | 增补 `ordinal`（0..2），服务端生成 | `test_new_event_payloads_validate` |

## 4. 未决（需成员 B 确认）

1. `MemoryCard.avoid`/`trigger_text` 是否允许空串（当前默认 `""`）。
2. `MemoryListResponse.next_cursor` 的光标编码格式（当前保留 `string|null`）。
3. `ResolveResponse.disposition` 对 `reject/one_shot` 的取值约定（建议沿用提取 disposition）。
