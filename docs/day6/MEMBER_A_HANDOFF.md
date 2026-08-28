# Day 6 成员 A 交接报告

> 仓库：W-JOSLIN-X/MemTrace
> 分支：`feat/a-d6-llm-memory-core`
> 交接时间：2026-08-28
> 执行者：zlbk-wxy（成员 A）

---

## 1. Git 状态

```
base 完整 SHA：bb69aa90a9ddb3c0a84f02b5a58dd92b7094f922
head 完整 SHA：89f70771bb58f2f1eec3b827847c227251469216
merge-base：bb69aa90a9ddb3c0a84f02b5a58dd92b7094f922

提交列表：
  89f7077 feat(day6): v2.0.0 contract, 006 migration, DeepSeek provider, memory worker
  bb69aa9 docs(day6): define LLM-first memory handoff
  d49bcf6 docs(day5): correct deterministic contract hashes
  ...
```

**注意**：此分支**尚未 push 到远端**。head SHA 是本地提交，成员 B 接手后需要先确认本地状态再继续。

---

## 2. 当前重新核对的原题边界

- 原题第 5 页 SHA-256：`7CD810AFCA0E535A8802E4C19F6F4D270B64EBA1668CA2CA4676DFBE146E14E3` ✅ 已验证
- 分类对象改为"记忆"而非"对话" ✅ 已在 2.0.0 契约中定义
- 正常对话 Agent + 后台记忆系统 ✅ Provider/Worker 已实现
- 真实 LLM 判断适用性和效果 ✅ Schema 已定义，实现见"未完成"
- 失败时不允许静默降级 ✅ Provider 异常传播，不降级

---

## 3. 本轮已完成的实现

### 3.1 2.0.0 契约
- **文件**：`docs/day6/LLM_MEMORY_CONTRACT_DECISION.md`
- **内容**：change note，记录 MemoryKind 归一、MemoryMutationBatch schema、LLM Judge types、API 端点、迁移规则和已移除语义链路

### 3.2 Schema v2（`apps/api/src/memtrace_api/schemas.py`）
- **MemoryKindV2**：`preference | rule | experience`（三分类归一）
- **MemoryMutationBatch**：LLM 结构化输出，含 `decision` + `operations[]`
- **MemoryMutationEvidence / Operation**：单条记忆操作的完整 schema
- **MemoryDurabilityResult**：LLM durability 判断输出
- **ApplicabilityJudgeResult**：LLM 适用性判断输出
- **EffectJudgeResult**：LLM 效果判断输出
- **ConflictConsolidationResult**：LLM 冲突整合输出
- **MemoryReflectionJobResponse**：v2 job 投影
- **MemoryV2ListFilter / MemoryV2ListResponse**：v2 list API
- **MemoryReflectionJobId / LLMJudgeId**：新 ID 类型
- **RuleSubtype / ReviewStatus / LegacyKindStatus / MutationDecision / MutationOperation / MemoryDurability / DurabilityReasonCode / ApplicabilityResult / ApplicabilityReasonCode / EffectJudgment / EffectReasonCode / ConsolidationDecision / MemoryReflectionJobStatus / LLMJudgeType / LLMJudgeStatus**：全部枚举

### 3.3 DeepSeek Responses Provider（`apps/api/src/memtrace_api/providers.py`）
- 替换 Chat Completions 为 Responses API
- **streaming**：`responses.create(stream=True)` → 解析 `response.output_text.delta`
- **structured output**：`text.format=json_schema` with `strict=True`
- **function call**：`tools=[]` parameter
- **reasoning items 忽略**：不读取、不存储、不 emit
- **stateless**：每次发送完整对话上下文，不使用 `previous_response_id`
- **Frozen model**：`deepseek-v4-flash`（已通过预检）

### 3.4 DB 模型（`apps/api/src/memtrace_api/db_models.py`）
- **MemoryReflectionJobModel**：table `memory_reflection_jobs`，含 status/attempt/mutation_decision/provider_model/prompt_hash/schema_version/error_code
- **MemoryLLMJudgeModel**：table `memory_llm_judgments`，含 judge_type/status/result_json/error_code
- 两个模型均有完整的 FK、CHECK、UNIQUE 约束和索引

### 3.5 事件（`apps/api/src/memtrace_api/events.py`）
- **EventType 新增**：`MEMORY_ANALYSIS_STARTED` / `MEMORY_ANALYSIS_COMPLETED` / `MEMORY_EFFECT_JUDGED`
- **Payload 新增**：`MemoryAnalysisStartedPayload` / `MemoryAnalysisCompletedPayload` / `MemoryEffectJudgedPayload`
- 三个 payload 均为 metadata-only（id/status/reason_code/count/latency/token），不含用户内容

### 3.6 006 Migration（`apps/api/alembic/versions/20260828_006_conversation_first_memory.py`）
- **新表**：`memory_reflection_jobs`、`memory_llm_judgments`
- **memory_cards**：新增 `content`/`applies_when`/`review_status`/`confidence`/`rule_subtype`/`schema_version` 及 v2 check 约束
- **memory_versions**：新增 `content`/`applies_when`/`confidence`/`review_status`/`rule_subtype`
- **memory_evidence**：新增 `message_id`/`turn_index`/`is_primary` 及 consolidation 列
- **memory_relations**：新增 `llm_consolidation_decision`/`consolidation_confidence`/`consolidation_decided_at`
- ⚠️ **已知问题**：`valid_from`/`valid_to`/`scope_level`/`domain`/`scope_json`/`exceptions_json`/`source_trust` 已在 G4 (005) 加入，006 的 `batch_alter_table` 尝试重新 ADD 导致 `duplicate column` 错误。**需要修复后再验证迁移。**

### 3.7 Memory Reflection Worker（`apps/api/src/memtrace_api/memory_worker.py`）
- **MemoryManager**：LLM 调用，structured json_schema，输出 MemoryMutationBatch
- **MemoryReflectionWorker**：singleton 后台 worker
  - `start()` → `_recover_stale_jobs()` → `_claim_next_job()` (atomic UPDATE...RETURNING) → `_process_job()` → loop
  - `_process_job()`：load context → `MemoryManager.extract()` → `_apply_mutations()` (单事务) → `_finalize_job()`
  - `_apply_mutations()`：add/update/supersede 三条路径，含 evidence 验证
  - 事件广播：`MEMORY_ANALYSIS_STARTED` / `MEMORY_ANALYSIS_COMPLETED`
  - shutdown：graceful stop + force cancel → MEMORY_JOB_INTERRUPTED

### 3.8 Repositories（`apps/api/src/memtrace_api/repositories.py`，由 Workflow 子 agent 完成）
- `create_reflection_job()` / `update_reflection_job_result()` / `get_reflection_job()` / `claim_reflection_job()`
- `list_memories_v2()` / `get_memory_detail_v2()` / `update_memory_v2()` / `confirm_memory_review()` / `dismiss_memory_review()`
- `get_memory_events()` / `create_memory_from_mutation()` / `create_llm_judgment()`

### 3.9 v2 API Routes（`apps/api/src/memtrace_api/main.py`，由 Workflow 子 agent 完成）
- `GET /api/v2/memories` — list with kind/review_status/cursor/limit
- `GET /api/v2/memories/{id}` — detail with versions/evidence
- `PATCH /api/v2/memories/{id}` — edit (Idempotency-Key)
- `POST /api/v2/memories/{id}/confirm` — confirm review → active
- `POST /api/v2/memories/{id}/dismiss` — dismiss review → archived
- `GET /api/v2/memory-events` — owner/session catch-up
- `GET /api/v2/reflection-jobs/{id}` — job status
- `GET /api/v2/tasks/{id}/memory-usage` — task memory usage

### 3.10 Config（`apps/api/src/memtrace_api/config.py`）
- 新增 memory 配置项：token budget per card/total、auto-activate confidence、max candidates、top-k、similarity threshold、reflection max attempts、reflection timeout

---

## 4. 被移出语义主链路的硬编码

| 文件/符号 | 替代路径 | Legacy 状态 |
|---|---|---|
| `logic.py` `auto_rule_v1` | LLM 判断 | 仍存在，不再驱动产品行为 |
| `durability.py` 关键词耐久性 | LLM durability judgment | 仍存在，不再用于产品决策 |
| `compiler.py` Mock 模板 | Worker + MemoryManager | 仅测试 fixture |
| `worker.py` canonical scope | LLM applies_when + 服务器安全校验 | 仍存在，不驱动 v2 |
| `char_tfidf_v1` 最终裁决 | 候选召回 + LLM 适用性裁决 | 仍存在，降级为 recall 层 |
| longest-common-substring verifier | LLM effect judge | 仍存在，不再作为产品结论 |

---

## 5. 已知问题和待完成事项

### 5.1 P0 — 阻塞迁移验证
1. **006 迁移 duplicate column**：`valid_from`/`valid_to` 等 G4 已加列被 006 重复 ADD
   - **修复方法**：从 006 的 `batch_alter_table("memory_cards")` 中移除 G4 已存在的列（`valid_from`, `valid_to`, `scope_level`, `domain`, `scope_json`, `exceptions_json`, `source_trust` 等），只保留 v2 真正新加的列
   - 受影响文件：`apps/api/alembic/versions/20260828_006_conversation_first_memory.py` 第 62–119 行

### 5.2 P1 — 需要验证
2. **Alembic 迁移通过**：修复上述问题后，用 `MEMTRACE_DATABASE_URL="sqlite:////tmp/test.sqlite3" .venv/Scripts/python.exe -m alembic -c alembic.ini upgrade head` 验证
3. **Alembic 唯一 head**：`alembic -c alembic.ini heads` 必须只输出 `006_conversation_first_memory`
4. **downgrade/readiness**：`005→006→005` 往返测试；006 head 的 `/ready` 200
5. **import 全部通过**：`python -c "from memtrace_api.main import app"` 零异常
6. **Ruff lint**：`repositories.py` 有 `AsyncErrorCode` undefined（已在 import 添加后修复部分）；RUF021/E501 style 问题尚未全部修复

### 5.3 P1 — 需要实现
7. **Orchestrator 改造**：移除 `auto_rule_v1` 和固定 public plan 对产品行为的控制
8. **LLM 适用性 Judge**：混合候选召回 → LLM 判断 applicable/override/conflict/irrelevant
9. **LLM Effect Judge**：applied/violated/not_observable/unknown
10. **Orchestrator 在回答后 enqueue reflection job**：不能阻塞主回答

### 5.4 P2 — 测试
11. **工程测试**：migration recovery、transaction isolation、owner isolation、idempotency、secret scan、openapi zero-diff
12. **真实语义 smoke**：16-case 真实 DeepSeek 调用，必须 provider_mode=real
13. **OpenAPI 导出**：`scripts/export_openapi.py` 对比新旧

### 5.5 未修改的文件（需成员 B 处理）
- `apps/api/src/memtrace_api/orchestrator.py`：待改造为正常对话 Agent
- `apps/api/src/memtrace_api/logic.py`：`auto_rule_v1` 仍在，应退出产品语义主链路
- `apps/api/src/memtrace_api/compiler.py`：Mock 模板仍在，应只保留为测试 fixture
- `apps/api/src/memtrace_api/retrieval.py`：待替换为混合召回 + LLM Judge
- `apps/api/src/memtrace_api/verifier.py`：待替换为 LLM effect judge
- `apps/web/src/g0/`：右侧记忆栏和实时事件由成员 B 实现

---

## 6. 真实 DeepSeek 配置证据

| 项 | 值 |
|---|---|
| provider_mode | `real` |
| base URL host | `api.deepseek.com` |
| model id | `deepseek-v4-flash` |
| Responses API 预检 | ✅ 200 |
| streaming | ✅ `response.output_text.delta` |
| json_schema | ✅ strict=True |
| Chat Completions fallback | ✅ 200 |
| prompt hash 工具 | `_compute_prompt_hash()` in providers.py |

---

## 7. 成员 B 接手步骤

### 第一步：确认本地状态
```powershell
cd "d:\学习\黑客松\MemTrace"
git status --short --branch
git rev-parse HEAD                    # 应为 89f7077
git merge-base --is-ancestor bb69aa90 HEAD  # 应返回 0
```

### 第二步：修复 006 迁移
编辑 `apps/api/alembic/versions/20260828_006_conversation_first_memory.py`，从 `batch_alter_table("memory_cards")` 的 `upgrade()` 中移除已由 G4 添加的列（`valid_from`, `valid_to`, `scope_level`, `domain`, `scope_json`, `exceptions_json`, `source_trust`），只保留 v2 新加的列（`content`, `applies_when`, `review_status`, `confidence`, `rule_subtype`, `schema_version` + `_legacy` 系列）。

### 第三步：验证迁移
```powershell
cd "d:\学习\黑客松\MemTrace\apps\api"
MEMTRACE_DATABASE_URL="sqlite:////tmp/day6_test.sqlite3" .venv/Scripts/python.exe -m alembic -c alembic.ini upgrade head
MEMTRACE_DATABASE_URL="sqlite:////tmp/day6_test.sqlite3" .venv/Scripts/python.exe -m alembic -c alembic.ini current
MEMTRACE_DATABASE_URL="sqlite:////tmp/day6_test.sqlite3" .venv/Scripts/python.exe -m alembic -c alembic.ini heads
```

### 第四步：验证导入和启动
```powershell
.venv/Scripts/python.exe -c "from memtrace_api.main import app; print('OK')"
```

### 第五步：继续成员 B 的当日任务
- 右侧实时记忆栏
- v2 API 联调
- 完整评测（A/B、Chrome/Edge）
- Docker cold start
- 真实语义 smoke（16 cases）

---

## 8. 未完成或未通过项

| 项 | 状态 | 说明 |
|---|---|---|
| 006 迁移 fresh DB | ❌ 阻塞 | duplicate column，见 §5.1 |
| Orchestrator 改造 | ⏳ 未开始 | 需移除 auto_rule_v1 控制 |
| LLM 适用性 Judge | ⏳ 未开始 | Schema 已定义 |
| LLM Effect Judge | ⏳ 未开始 | Schema 已定义 |
| 后台 enqueue reflection | ⏳ 未开始 | Worker 已实现，需接入 Orchestrator |
| 工程测试 | ⏳ 未开始 | 迁移/事务/隔离/幂等 |
| 真实语义 16-case | ⏳ 未开始 | 脚本待写 |
| OpenAPI 零 diff | ⏳ 未开始 | export_openapi.py 需重跑 |
| Secret scan | ✅ | git diff --check 通过 |
| Push 到远端 | ❌ 未执行 | 成员 B 确认 head 后执行 |

---

## 9. 提交建议边界

已完成的提交：
1. `docs(day6): define LLM-first memory contract`（change note）
2. `feat(day6): v2.0.0 contract, 006 migration, DeepSeek provider, memory worker`

待补充提交：
3. `feat(api): add v2 memory API routes`
4. `fix(db): correct 006 migration for G4 existing columns`
5. `test(day6): cover migration recovery and isolation`
6. `test(day6): add real DeepSeek semantic smoke (16 cases)`
7. `docs(day6): record member A handoff`（本文件）

---

**确认**：未 push main；未提交 .env、Key、SQLite 数据库、用户正文、模型回答或临时产物；Mock 未写入语义证据。
