# 发给 zlbk-wxy 的 MemTrace Day 4 成员 A Agent Prompt

> 使用说明：本文随 G3 决策进入 main 后，成员 B 会在同一条交接消息中给出 `DAY4_BASE_SHA` 的 40 位完整值。Git commit 不能在其自身受哈希保护的文件内容中自嵌该 commit SHA，因此这里不伪造自引用 SHA；如果交接消息没有完整 SHA，必须停下索取，不能自行猜测。

你现在是 MemTrace Day 4 的成员 A（GitHub：`zlbk-wxy`）。你只负责 Day 4 后端检索/注入/trace/usage/verifier/最小生命周期 API 和相称测试；不要实现成员 B 的前端、Docker、双浏览器、最终整合或发布任务。

## 零、先取得最新 main 的完整本地工作区

开始阅读或修改任何文件前，必须先把 GitHub 当前 `origin/main` 的全部内容取到本地工作区。不得在旧 main、旧工作区、手工复制的文件或 GitHub ZIP 上继续开发。

如果本地还没有 MemTrace 仓库，先执行：

```powershell
git clone https://github.com/W-JOSLIN-X/MemTrace.git MemTrace
Set-Location MemTrace
```

如果已经有本地仓库，先进入该仓库根目录。随后两种情况都执行：

```powershell
git remote get-url origin
git status --short --branch
```

`origin` 必须是 `W-JOSLIN-X/MemTrace`。如果 `git status --short` 显示任何已有 tracked/untracked 改动，立即停止并报告，不能覆盖、删除、stash 或归入本次提交。

确认工作区干净后，下载远端最新 main 并把工作区完整检出到该快照：

```powershell
git fetch --prune origin
git switch --detach origin/main

$remoteMain = git rev-parse origin/main
$workspaceHead = git rev-parse HEAD
"origin/main=$remoteMain"
"workspace HEAD=$workspaceHead"

if ($workspaceHead -ne $remoteMain) {
    throw '本地工作区没有完整检出最新 origin/main，停止执行。'
}

git status --short
git diff --exit-code HEAD --
Test-Path 'AGENTS.md'
Test-Path 'docs/day4/G3_CONTRACT_DECISION.md'
Test-Path 'docs/day4/TEAMMATE_AGENT_PROMPT.md'
```

要求：

- `workspace HEAD` 必须与本次 fetch 后的 `origin/main` 完整 SHA 一致。
- `git status --short` 必须没有输出，`git diff --exit-code HEAD --` 必须退出码 0。
- 三个 `Test-Path` 必须全部为 `True`。任何一项不成立都立即停止并报告。
- 不执行会产生隐式 merge 的普通 `git pull`；后续严格从成员 B 给出的 `DAY4_BASE_SHA` 创建功能分支。

## 一、开始前必须读完

按顺序完整阅读：

1. 根目录 `AGENTS.md`
2. `docs/OWNER_LED_COLLABORATION_WORKFLOW.md`
3. `docs/day4/G3_CONTRACT_DECISION.md`
4. `docs/day4/OWNER_AGENT_CONTINUATION_PROMPT.md` 中“成员 A 阶段”的边界
5. `Universal_Feedback_Memory_Agent_Project_Plan.md` 的 Day 4/G3 部分
6. `docs/MEMTRACE_D2_D7_TWO_PERSON_EXECUTION_PLAN.md`
7. `docs/day2/AUTO_CLASSIFICATION_DECISION.md`
8. `docs/day3/G2_CONTRACT_DECISION.md`
9. 当前 `contracts/`、`apps/api`、Alembic、测试和 `fixtures/day4/retrieval_events.json`

事实优先级是：当前用户要求 > `AGENTS.md` > owner-led workflow > 当前可执行代码/契约/迁移/本轮测试 > Day 4 continuation/G3 决策 > 总计划 > 旧 PR、旧 Prompt、旧报告。发现矛盾直接指出，不要照抄旧流程。

## 二、登录与安全边界

- 你需要已经登录 GitHub，且 push 身份必须是 `zlbk-wxy`。开始前执行 `gh auth status` 和 `gh api user --jq .login`；如果未登录、身份不是 `zlbk-wxy`、或执行中首次发现登录失效，立即暂停告诉用户，不要改找免登录替代路径。
- 默认 `MOCK_MODE=true`。不要读取、索取或输出真实 Provider Key；真实 Provider smoke 不是 Day 4 成员 A 完成门禁。
- `.env`、token、SQLite、用户正文、evidence/output 正文、浏览器资料、模型缓存、临时结果不得提交、放进 URL、日志、截图或 handoff。

## 三、精确 base 与分支

成员 B 交接消息会写：

```text
DAY4_BASE_SHA=<两份 Day 4 文档进入 origin/main 后的 40 位完整 SHA>
```

执行：

```powershell
$env:DAY4_BASE_SHA = '<把成员 B 交接消息中的 40 位 SHA 粘贴到这里>'
git status --short --branch
git fetch --prune origin
git rev-parse origin/main
git cat-file -t $env:DAY4_BASE_SHA
git merge-base --is-ancestor $env:DAY4_BASE_SHA origin/main
git show --no-patch --format=fuller $env:DAY4_BASE_SHA
git switch -c feat/a-d4-memory-retrieval $env:DAY4_BASE_SHA
```

要求：

- 工作区若有用户改动，先停下报告，不能覆盖或归为你的提交。
- `origin/main` 必须仍包含 `DAY4_BASE_SHA`；如果 main 已移动，先审查 `DAY4_BASE_SHA..origin/main` 并回报成员 B，不能盲从旧 SHA。
- 只使用 `feat/a-d4-memory-retrieval`；不直接 push/force-push/merge/rebase/squash/amend main，也不使用 `integration/day2`，不开日常 PR。

## 四、当前已核验事实（不能当作待实现功能）

成员 B 在 Stage 1 基线 `4a383660b65b9b9f7cd76c3acba293193b0a9c3f` 独立确认：

- 当前 contract `1.2.0`、fingerprint `1.1`、唯一 migration head `003_g2_job_retryable`。
- 后端基线 `353 passed`，Ruff/pip/迁移头通过；前端基线 42 tests/typecheck/lint/build 通过。
- 目前仅有 Day 2 占位 `memory.retrieval.started`，没有真实 retrieval/injection/trace/usage/verifier/lifecycle routes。
- `memory_jobs` 只支持 `extract_feedback`；active version 的 `created_by_action` 只支持 `accept|edit_accept`。
- 当前依赖不含 NumPy、scikit-learn 或 sentence-transformers。
- Day 4 的 30 条 fixture 是不可执行 draft，不是 gold。

你必须从实际 `DAY4_BASE_SHA` 重新核对这些事实并记录差异；旧数字不算你的测试证据。

## 五、你的严格范围

以 `docs/day4/G3_CONTRACT_DECISION.md` 为唯一 G3 冻结 change note，完成以下后端范围。

### A. 契约投影

- 新增 `contracts/day4-g3.json`、`contracts/examples/day4-g3.json`。
- 同步 `contracts/README.md`、两个 JSON Schema、实际 OpenAPI、Pydantic、ErrorCode、EventType、payload mapping 和 contract tests。
- contract version 为 `1.3.0`；不改变服务端 `auto_rule_v1`，客户端仍不得提交 `scenario`。
- 严格拒绝 extra field；estimated memory tokens 和 provider actual prompt tokens 绝不能混成一个字段。

### B. 迁移与持久化

- 新增唯一线性 head `004_g3_retrieval_usage`。
- 新增 `retrieval_traces`、`retrieval_decisions`、`memory_usages`、`memory_verification_jobs`，以及冻结的 card counters/last_used_at、scope/value check、version action `edit`。
- owner、FK、CHECK、UNIQUE、索引、事务、upgrade/downgrade/readiness 必须真实可执行。
- 不新增 embedding 表，不把 verifier 硬塞进当前非空 feedback 的 `memory_jobs`。

### C. 确定性检索

- 用标准库实现 `char_tfidf_v1`：NFKC、casefold、空白折叠、2/3/4-char grams、冻结 TF/IDF、L2/cosine、零向量、6 位公开 rounding 和稳定 tie-break。
- 严格实现 owner/status/time/scope/current constraint/active conflict 硬过滤；`null`/`unknown` 不是 any。
- 按冻结公式计算 scope/semantic/provenance/verified effect/recency/final score。
- 阈值固定 `0.68`，Top-K 固定 `3`；不看 test fixture 偷调。
- Day 4 只有正常 `tfidf`；不下载/接入 BGE，不显示 degraded。

### D. Prompt Compiler

- 只注入 selected 且通过预算的 immutable current version。
- 使用冻结 `<MEMORY_CONTEXT>` 低权限格式、XML escape、100 单卡/300 总 estimated tokens、固定截断顺序和 SHA-256 hash。
- 在 provider 生成前完成截断；ProviderRequest 的 memory_context 与 usage_ids 是独立字段。
- MockProvider 和 real adapter 必须走同一 memory-aware request path；默认日志只能有 ID、count、latency、token、hash，不能有正文。

### E. Trace、receipt、事件和恢复

- 持久化完整 RetrievalTrace/Decision，以及每个 selected memory 的 UsageReceipt。
- 实现 task snapshot 和冻结 GET/write routes；所有 write 有 Idempotency-Key，跨 owner 统一不可见。
- 新事件全部是 task stream persistent event，seq 连续；只有 started 仍是 transient。DB commit 后才 best-effort broadcast。
- 进程刷新/重启后通过 snapshot、GET 和 `after_event_seq` 恢复，不依赖内存 SSE/React 状态。

### F. Verifier

- 独立 verification job 表/worker；Mock 使用冻结的真实 output exact-substring 算法，避免词先于 rule。
- real provider 复用严格 StructuredProvider JSON 协议，非法字段/enum/excerpt/repair 按冻结语义失败为 unknown。
- pending/stale running/attempt/竞争 claim/restart/重复 event 和 counters 都要测试。
- 没有 output 证据不能写 applied；selected/injected 也不能推导 applied。

### G. active edit / pause / resume / usages

- 实现 active edit 的 immutable next version + atomic current switch。
- pause 后新任务立即不召回；resume 通过 admission invariants 后重新参与。
- 实现 versions/usages/trace receipt 只读与 usage helpful/harmful/stale 写入。
- 写入幂等、stale version、重复状态和并发竞争按冻结 404/409 语义。
- 不实现 Day 5 搜索中心、冲突裁决、merge/Pack、archive/delete 全流程。

### H. Day 4 draft fixture

- 不直接改成 approved/gold。
- 新建 `docs/day4/RETRIEVAL_FIXTURE_REVIEW.md`，逐条写 `keep|revise|insufficient` 和理由。
- 特别核对 d4-r06 的 other/session 假设、d4-r16/r17 缺失结构化 constraints/exceptions、d4-r18..29 缺失完整 scope，以及 corpus/threshold 不确定性。
- 算法 gate 使用你新增的完整、确定性 fixture；原 30 条只保留 review 草案身份，等成员 B 第二阶段共同决定。

## 六、必须覆盖的测试

至少包括：

1. 中英文、NFKC、casefold、空白、2/3/4-gram、空/零向量、最小 corpus、IDF、cosine、rounding、100 次确定性、稳定 tie-break；
2. 正例、近似负例、完全负例与全部 hard filters；
3. candidate/rejected/conflicted/paused/superseded/merged/archived/deleted、expired/not-yet-valid、memory off、cross-user；
4. scope exact/any/null，null 不扩大；current direct-fix/urgent override；active conflict 只阻断；
5. threshold/Top-3 和完整 score projection；
6. 100/300 token、稳定截断、XML escape、hash、正文不进日志；
7. memory_context 确实进入 Mock 和 real adapter request；Mock actual provider tokens 仍为 null；
8. trace/decisions/receipts/events/counters/idempotency 同事务，连续 task seq、SSE catch-up、snapshot/GET/restart 恢复；
9. exact verifier applied/violated/not_observable，失败 unknown，job recovery/claim；
10. active edit 不可变版本、stale version、pause/resume、并发竞争；
11. task/memory/trace/usage/API/SSE 跨用户不可见；
12. fresh upgrade、`003 -> 004` 数据保留、downgrade、约束、唯一 head 和 readiness；
13. OpenAPI/JSON Schema/Pydantic/examples 精确同步；
14. G1+G2 不回退。

测试不能只 assert 文件或路由存在，必须从公开 API/数据库事务/事件流证明行为。

## 七、实际执行与提交

先记录失败基线，再小步实现。建议单目标提交：

```text
chore(contract): define G3 retrieval and usage projections
feat(memory): add deterministic scoped retrieval and prompt budget
feat(memory): persist retrieval traces and usage receipts
feat(api): add Day 4 memory lifecycle and usage endpoints
test(day4): cover G3 retrieval injection and recovery
docs(day4): record member A verification evidence
```

提交前至少执行并记录每条命令的退出码和真实数量（按实际环境使用仓库 `apps/api/.venv`，不要假设全局 Python）：

```powershell
& 'apps/api/.venv/Scripts/python.exe' -m pip check
& 'apps/api/.venv/Scripts/python.exe' -m ruff check apps/api
& 'apps/api/.venv/Scripts/python.exe' -m ruff format --check apps/api
& 'apps/api/.venv/Scripts/python.exe' -m alembic -c apps/api/alembic.ini heads
& 'apps/api/.venv/Scripts/python.exe' -m pytest apps/api/tests -q
git diff --check
git status --short
```

如果你碰了共享 TS 或 web 契约投影，还要在 `apps/web` 跑 typecheck、lint、test、build；否则明确写“未改前端，前端由成员 B 第二阶段完成”，但不能留下与后端 OpenAPI 不可消费的未冻结字段。

完成后只做普通提交并：

```powershell
git push -u origin feat/a-d4-memory-retrieval
```

不开 PR，不推 main。push 后不要静默追加 commit。

## 八、handoff 必须一次给全

按 owner workflow 模板报告：

- 分支名；
- 40 位完整 base SHA 与 head SHA；
- `git log --oneline BASE..HEAD` 全部提交；
- `git merge-base --is-ancestor BASE HEAD` 结果；
- 实际修改文件、契约/迁移/API/event/算法/事务变化；
- 每条测试命令、退出码、测试数量和运行环境；
- fixture review 结论；
- 秘密/正文日志/SQLite/临时产物检查；
- 已知失败、真实 Provider 未验证项、降级和明确未实现项；
- 所需登录（如果没有也写“无新增登录”）。

任何 gate 未通过只能报告具体阻塞，不能写 Day 4 完成。成员 B 会从最新 origin/main 建 `codex/day4-owner-integration`，普通 `--no-ff` merge 你的精确 head，独立复测/修复并完成前端、Docker、Chrome、Edge，最后由 W-JOSLIN-X 普通非强制直推 main；不需要你审批，也不使用 `integration/day2` 晋级。
