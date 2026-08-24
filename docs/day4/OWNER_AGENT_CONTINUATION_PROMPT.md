# 给 MemTrace Day 4 新对话 Owner Agent 的完整接续 Prompt

你现在是 MemTrace Day 4 的 Owner Agent，服务对象是仓库所有者 `W-JOSLIN-X`（成员 B）。你不是成员 A 的替代者，也不能恢复旧的强制 PR/同伴审批流程。你的任务分成两个严格阶段：

1. 先独立理解当前项目，写出并显示一份可以直接交给成员 A `zlbk-wxy` 的 Day 4 协作者 Agent Prompt；
2. 等用户明确告诉你成员 A 已完成并 push 功能分支、同时提供或允许你核对 handoff 后，再下载该分支，独立测试、修复、完成成员 B 的 Day 4 任务、合并测试，并由仓库所有者普通非强制直接 push 到 `main`。

在阶段 1 结束前，不要抢先实现成员 A 的 Day 4 后端任务；在没有收到远端功能分支的情况下，也不要虚构接管、测试或完成状态。

## 一、必须服从的工作方式

### 1. 文档和事实优先级

遇到任何冲突，按以下顺序执行：

1. 用户在新对话中的最新明确要求；
2. 根目录 `AGENTS.md`；
3. `docs/OWNER_LED_COLLABORATION_WORKFLOW.md`；
4. 当前可执行契约、实际代码、迁移和你本轮亲自运行的测试；
5. `docs/MEMTRACE_D2_D7_TWO_PERSON_EXECUTION_PLAN.md` 与 `Universal_Feedback_Memory_Agent_Project_Plan.md`；
6. Day 2/Day 3 的 HANDOFF、旧 Prompt、PR 描述和核验报告。

旧报告可以帮助定位文件和历史缺陷，但不能证明当前 head 已通过。若本 Prompt 中记载的 SHA、测试数量或 GitHub 状态与执行时远端不一致，必须先审查增量，以执行时实际状态为准。

### 2. 新协作规则不可回退

- 成员 A：`zlbk-wxy`，只在自己的 `feat/a-d4-*` 分支开发、commit、push；绝不更新 `main`。
- 成员 B：`W-JOSLIN-X`，仓库所有者、唯一日常集成与发布责任人。
- 成员 B 从最新 main 建 `codex/day4-owner-integration`，普通 merge 成员 A 分支，保留其 commit 历史。
- 成员 B 独立复现/修复并完成自己的范围，完整 G1+G2+G3 通过后普通直推 main。
- 日常不要求 PR，不要求 `zlbk-wxy` 审批，不再通过 `integration/day2` 二次晋级。
- 不 rebase/squash/amend 已交接的成员 A 历史；不 force push；不临时取消所有保护来绕过错误。

### 3. 严谨和登录规则

- 有问题直接指出，不恭维，不复述旧“全通过”结论冒充核验。
- 开始调用账号工具前先告诉用户需要哪些登录。Day 4 预计只需要 GitHub CLI 登录 `W-JOSLIN-X`；默认 `MOCK_MODE=true`，不需要模型平台或 `LLM_API_KEY`。
- Docker 本地 build/smoke 和 Chrome/Edge 本地验收不需要 Provider 登录，但要检查 Docker Engine 和浏览器是否可用。
- 若真实 GitHub 登录失效或执行中发现新的登录要求，立即暂停并告诉用户需要登录什么，不寻找绕过身份的替代方法。
- 沙箱/代理错误可能伪装成登录失败；可以使用获准的同一官方命令做最小复核。确认真实未登录后必须停止外部操作。
- 不读取、打印或提交 token、`.env`、SQLite、用户正文、编辑稿、evidence quote、浏览器 profile 或持久卷内容。

## 二、开始后必须完整阅读的材料

不要只搜索关键词或读摘要。以下高层文档必须从头到尾分块读完，避免工具截断：

1. `AGENTS.md`
2. `docs/OWNER_LED_COLLABORATION_WORKFLOW.md`
3. `Universal_Feedback_Memory_Agent_Project_Plan.md`
4. `docs/MEMTRACE_D2_D7_TWO_PERSON_EXECUTION_PLAN.md`
5. `docs/day2/AUTO_CLASSIFICATION_DECISION.md`
6. `docs/day3/G2_CONTRACT_DECISION.md`
7. `docs/day3/OWNER_INTEGRATION_REPORT.md`
8. `contracts/README.md`
9. `contracts/day1-g0.json`
10. `contracts/day2-g1.json`
11. `contracts/day3-g2.json`
12. `contracts/schemas/g0-api.schema.json`
13. `contracts/schemas/events.schema.json`
14. `contracts/openapi.json`
15. `fixtures/day4/retrieval_events.json`

随后结合实际任务有针对性地完整阅读相关实现，而不是只相信文件名：

- 后端：`apps/api/src/memtrace_api/` 下的 `schemas.py`、`db_models.py`、`database.py`、`repositories.py`、`main.py`、`orchestrator.py`、`events.py`、`providers.py`、`worker.py`、`readiness.py`、`config.py`；
- 迁移：`apps/api/alembic/versions/` 的全部现有 revision；
- 后端测试：全部 Day 1–Day 3 测试，重点是 contract、OpenAPI、migration、worker runtime、owner G2、SSE cursor、idempotency/rollback；
- 前端：`apps/web/src/g0/` 的 types/api/reducer/runtime/event stream/hook，以及 `ChatPage.tsx`、`MemoriesPage.tsx`、现有 G1/G2 测试；
- 依赖与构建：`apps/api/pyproject.toml`、`requirements.in`、`requirements.lock`、`apps/web/package.json`、Dockerfile/Compose/entrypoint；
- Eval：`scripts/day1/validate_fixtures.py`、`scripts/day3/eval_runner.py` 和现有 future fixture 测试。

如果 fetch 后仓库又出现更深层 `AGENTS.md`，在编辑其作用域文件前也必须完整阅读。

## 三、已知历史锚点，但必须在线复核

以下只是帮助你定位，不是允许跳过检查：

- Day 3 G2 进入 main 的历史 merge commit 是 `34681a4082f52da3a67e784f348111f9d0e38044`。
- 本文件和新协作规则会在它之后形成新的治理文档 commit，因此执行时的 `origin/main` 应等于或后继于该 commit，不能机械要求 main 仍等于 `34681a4`。
- PR #1–#6 已完成历史使命；Day 4 不继续创建替代 PR，也不等待另一人审批。
- Day 3 contract 历史版本为 `1.2.0`，唯一 Alembic head 当时为 `003_g2_job_retryable`。
- Day 3 历史核验曾记录 353 项后端测试、42 项前端测试、G2 Docker/Chrome/Edge 通过；这些数字只能作为漂移对照，必须报告 Day 4 本轮实际数量。
- 现有 Day 4 `fixtures/day4/retrieval_events.json` 是 30 条 `0.1-draft`，历史状态是 `member_b_draft_requires_joint_review`，不能直接宣称 gold 或已批准。
- 现有代码已经有 run `retrieving` 阶段、MemoryCard/Version/Evidence 和 G2 worker，但这不证明真正的检索、注入、UsageReceipt、编辑/pause API 或 UI 已实现。
- 当前 Python 依赖中历史上有 RapidFuzz，但未必已有 NumPy/scikit-learn。不要仅为了计划中的名词盲目加重依赖；先审查 lock、容器体积和确定性需求。

开始时至少核对：

```text
git status --short --branch
git remote -v
git fetch --prune origin
git rev-parse origin/main
git merge-base --is-ancestor 34681a4082f52da3a67e784f348111f9d0e38044 origin/main
gh auth status
gh repo view / gh api 读取当前 main 规则和 ruleset
```

如果工作区已有用户改动，先保护并绕开，不能 reset 或覆盖。若远端 main 不包含 Day 3 merge anchor，立即停止并报告历史异常。

## 四、阶段 1：只读核验后生成成员 A 的 Day 4 Prompt

### 1. 阶段 1 的目标

你要根据实际 main，而不是照抄本文，写出 `docs/day4/TEAMMATE_AGENT_PROMPT.md`，同时在回复中给用户一份完整可复制文本。成员 A 看完后应无需再索取其他私有文件：所有引用文档和代码都应已在 GitHub main 上。

在写 Prompt 前完成以下只读核验：

1. 当前 main/head、Day 3 anchor、工作区和远端分支状态；
2. 当前 G2 路由、schema、数据库表、事件、snapshot、worker 生命周期和前端 parser；
3. Day 4 能复用什么，哪些只是状态枚举/占位；
4. 30 条 retrieval fixture 是否覆盖当前计划，标签是否有明显矛盾；
5. 当前依赖能否实现默认 char n-gram TF-IDF；
6. 现有 Provider/Orchestrator 如何在生成前接入 memory section，又如何在生成后异步 verify；
7. Day 4 最小公开 API/Event/Schema 和迁移边界；
8. 当前 main 分支技术保护是否确实为“只有 `W-JOSLIN-X` 可更新，协作者不可更新”。

允许在阶段 1 运行安全的基线测试来判断真实状态；如果没跑完整门禁，就必须在 Prompt 和回复中说清楚“未运行”，不能沿用旧数字。

### 2. 阶段 1 应形成的文档

建议先写两份文档 commit：

1. `docs/day4/G3_CONTRACT_DECISION.md`：冻结经实际代码核对后的 G3 最小契约；
2. `docs/day4/TEAMMATE_AGENT_PROMPT.md`：成员 A 可直接执行的完整任务 Prompt。

推荐提交信息：

```text
docs(day4): freeze G3 contract and assign member A
```

这些文档要让成员 A 从包含该 commit 的最新 main 开分支。按新流程，成员 B 在文档检查、`git diff --check`、秘密检查和远端竞态检查通过后可以普通直推 main，不开 PR、不等审批。推送后核对远端 SHA，再把完整协作者 Prompt 显示给用户，然后暂停等待用户去协调成员 A。

### 3. G3 契约必须明确的决策项

不能只写“实现 RetrievalTrace”。至少冻结并让 Pydantic、JSON Schema、实际 OpenAPI、TypeScript 类型/parser、events 和 fixtures 使用同一语义：

- contract 版本：预期从 G2 `1.2.0` 做向后兼容 minor bump；实际版本由你核对后在 decision 中明确；
- RetrievalTrace 的 ID/归属、task/run 关系、`retrieval_mode`、candidate/selected/excluded、各分项分数、最终分数、受控 reason code、耗时和 token 字段；
- UsageReceipt/MemoryUsage 的 ID、memory/version/run/task 关系，以及 retrieved、injected、verification、verifier、evidence excerpt、user effect、时间字段；
- 自动 verification 的受控值：`applied`、`violated`、`not_observable`、`unknown`，以及失败时为什么只能是 unknown/not_observable；
- user effect 的受控值和写接口，至少覆盖“有帮助 / 不该用 / 已过时”，写操作必须使用 `Idempotency-Key`；
- 获取 trace/receipt 的真实恢复路径：snapshot 投影、GET 路由、持久事件 catch-up 三者如何配合，不能只有 SSE 瞬时状态；
- Day 4 需要的 active memory 编辑、pause/resume、versions/usages 最小 API；跨用户/不存在统一按冻结契约返回 404；
- active 编辑必须创建不可变下一版本并原子更新 current version，不能原地改历史 v1；
- pause/resume 合法状态转换、重复操作语义、幂等和并发冲突；
- 新 persistent event 名称、stream 必须仍是 task stream、metadata-only payload 和连续 seq；
- nullable 字段是否始终显式 `null`，分页 cursor 和稳定排序沿用 G2 的已冻结规则；
- 错误码、HTTP status、幂等重放/冲突和事务回滚语义；
- estimated memory tokens 与 provider actual prompt tokens 必须是两个不同字段；Mock 无 actual usage 时必须为 `null`，不能伪造数字；
- 默认 TF-IDF 是正常模式，不显示 degraded；只有本来选定 BGE 后运行时回退才是 degraded。

不要为了“看起来完整”提前加入 Day 5 的 merge/conflict resolve/Pack/永久删除完整流程或 Day 6 动态 eval API。

## 五、你写给成员 A 的 Prompt 必须包含的 Day 4 范围

成员 A 的建议分支为：

```text
feat/a-d4-memory-retrieval
```

它必须从你刚推送 G3 决策/Prompt 后的精确 `origin/main` 创建。你要在成员 A Prompt 中写出完整 base SHA；若协作者执行时 main 已变化，他必须停下核对增量，不能盲从旧 SHA。

### 1. 默认 TF-IDF 检索器

- 实现确定性的字符 n-gram TF-IDF，默认不依赖模型、不联网、不持久化词表。
- 在 G3 contract decision 中冻结 Unicode 规范化、casefold、空白处理、n-gram 范围、TF/IDF 公式、零向量、余弦、rounding、最小语料和稳定 tie-break；测试必须能锁住这些细节。
- 是否使用 NumPy由实际依赖、lock 和容器证据决定；不能把“计划写了 NumPy”当作必须新增重量依赖的理由。
- BGE 只有在仓库已经存在独立的本机、第二设备和容器 smoke 通过证据时才可作为可选模式；没有证据就只实现 TF-IDF，不下载模型、不要求登录，不把它标为缺陷。

### 2. 先硬过滤，再评分

查询必须先绑定验证 session 的 owner，并在相似度计算前排除：

- 非 `active`；
- candidate/rejected/paused/archived/superseded/merged/deleted；
- 未到 `valid_from` 或已超过 `valid_to`；
- domain/project/task_type/artifact/audience 等明确 scope 冲突；
- 命中 exceptions；
- unresolved active conflict（只按 Day 4 能表达的已有关系处理，不提前造 Day 5 裁决器）；
- `memory_mode=off` 或 current constraint 明确关闭；
- 其他 owner。

不得先全库 Top-K 再过滤 owner；不得把 null 当 `ANY`；`ANY` 只能是显式通配。

### 3. 分项评分和稳定 Top-3

按总计划冻结的开发公式实现并记录每一项：

```text
final_score =
0.35 * scope_match
+ 0.30 * semantic_similarity
+ 0.15 * provenance_confidence
+ 0.10 * verified_effect
+ 0.10 * recency
```

- 开发起始阈值 `0.68`，Top-K=`3`；Day 6 只能在 validation 上调参，Day 4 不看 test 偷调。
- scope 细项权重、ANY 半分、父类映射和冲突零分遵循总计划，并在单测中固定。
- 排序 tie-break 必须稳定且有契约/测试，不能依赖 SQLite 未指定顺序或 Python set。
- selected、excluded 都保留受控 reason code；UI 需要的是可解释依据，不是模型思维链。
- 当前任务明确要求和 `current_constraints` 高于长期记忆；冲突时排除并记录 `CURRENT_TASK_OVERRIDE`，不能让记忆覆盖本次指令。

### 4. Prompt Compiler 与 300 token 硬预算

- 只把被选中的卡压缩为低权限 `<user_memory policy="untrusted-personalization-data">` section。
- 总预算最多 300 estimated tokens，单卡最多 100；冻结 estimator 和截断顺序，截断必须在生成前发生且可测试。
- 不把 evidence 全文、反馈正文、历史任务、confidence 解释或隐藏推理注入 Prompt。
- 记录编译 section 的 SHA-256、字符数和 estimated tokens；事件/日志不记录 section 正文。
- Provider 获得的是 system/safety > current task > current constraints > memory 的正确优先级。
- Mock provider 也要以确定性方式证明 memory section 确实接入生成链路，不能只生成 trace 而从未把内容交给 Provider。

### 5. RetrievalTrace、持久事件和恢复

- 每次 run 在 `retrieving` 阶段执行一次检索，trace 绑定真实 owner/task/run。
- 记录 candidate count、selected/excluded、分项分数、决策/reason、mode、latency、chars、estimated token 和 compile hash。
- trace、usage、run 状态和相关 persistent event 事务边界必须明确；DB 提交后才做最佳努力的内存 SSE 广播。
- persistent event 使用 task_id stream，沿用 SQLite 单语句事件 seq 分配器；重连可从 event log catch-up。
- 事件、服务日志和 Eval 输出只含 ID、状态、受控代码、分数、计数、hash、token/latency，不含任务、memory rule 或输出正文。

### 6. UsageReceipt 与后台 verifier

- 对 retrieved/selected/injected 建立持久 usage/receipt，绑定实际 memory version 和 run。
- 回答完成后异步 verify，不阻塞首字或正文完成。
- `evidence_excerpt` 最长 120 字且必须是最终 answer 的精确子串；找不到就不能写 `applied` 的伪证据。
- verifier 失败或无法观察必须持久化为受控 `unknown`/`not_observable`，最多一次修复/重试，不吞异常。
- 自动 verifier 只更新 verified-applied 计数，不替用户增加 helpful；helpful/harmful/stale 只由用户写操作更新。
- 用户效果写入、计数和 idempotency response 必须同事务；同 key 同 body 重放，不同 body 冲突；跨 owner 404。
- 重启后未完成的 verifier job 应有明确恢复/failed 语义，不能永远 running。

### 7. Day 4 最小 Memory API 后端支持

成员 B 当天要做 active 卡编辑、pause/resume、版本只读列表和 usages/receipt UI，因此成员 A 的后端范围必须包括 G3 决策冻结的最小真实路由和 response model：

- active 卡受控编辑，创建不可变下一版本；
- pause/resume；
- versions 只读；
- usages/trace/receipt 只读；
- usage user-effect 写入；
- 所有写操作的 `Idempotency-Key`、owner 404、严格 body、response model、OpenAPI 和事务测试。

不要扩展为 Day 5 的完整搜索筛选、归档/永久删除、冲突合并或 Pack。

### 8. 成员 A 必须完成的测试

Prompt 至少要求实际覆盖：

- TF-IDF 中英文、规范化、空/零向量、确定性、稳定 tie-break；
- owner/status/validity/domain/project/task type/artifact/audience/exception/memory-off 硬过滤；
- 正例、近似负例、完全负例、paused、expired、cross-user；
- Top-3、阈值、分项分数、current override、冲突排除；
- 300 总预算、100 单卡、稳定截断、hash 不含正文日志；
- Orchestrator 真实链路在生成前检索并注入，而非只测纯函数；
- 0 卡、1卡、3 卡、超预算；
- trace/usage/事件同事务、连续 task seq、SSE catch-up；
- exact-substring verifier 的 applied/violated/not_observable/unknown；
- provider/verifier 失败、进程重启、幂等重放/冲突和回滚；
- active 编辑不可变版本、pause 后立即不召回、resume 后可召回；
- 跨用户 task/memory/trace/usage/API/SSE 统一不可见；
- 空库升级、从 D3 revision 升级、唯一 Alembic head 和 readiness；
- Pydantic、JSON Schema、实际 FastAPI OpenAPI 与 TypeScript contract fixture 一致；
- 当前 30 条 draft retrieval fixture 经逐条复核，不直接改 review status 冒充双方批准。

成员 A 交接前至少运行 Ruff、format check、完整 pytest、pip check、fixture/contract validator、migration tests。报告实际数量，不复制 353。

### 9. 成员 A 的提交和 handoff

建议提交顺序应便于 B 定位回归，例如：

```text
chore(contract): define G3 retrieval and usage projections
feat(memory): add deterministic scoped retrieval and prompt budget
feat(memory): persist retrieval traces and usage receipts
feat(api): add Day 4 memory lifecycle and usage endpoints
test(day4): cover G3 retrieval injection and recovery
docs(day4): record member A verification evidence
```

成员 A 完成后只 push `feat/a-d4-memory-retrieval`，不开 PR、不推 main，然后按 `docs/OWNER_LED_COLLABORATION_WORKFLOW.md` 的模板提供完整 base/head、提交、测试和限制。交接后不得静默追加 commit。

## 六、阶段 1 的停止条件

当以下事项完成后，你必须在当前回复中给用户：

1. 一份可直接复制给成员 A Agent的完整 Prompt；
2. 已保存的 `docs/day4/TEAMMATE_AGENT_PROMPT.md` 路径；
3. 该文档是否已经由成员 B 按新流程推到 main，以及远端完整 SHA；
4. 本轮只读核验发现的真实基线和未验证项；
5. 明确下一步是等待用户回复“成员 A 已 push”，并附 branch/head/handoff。

然后停止。不要在等待期间自行写成员 A 的检索后端，不要创建 PR，也不要声称 Day 4 开始合并测试。

## 七、阶段 2 触发条件：用户带回成员 A 分支

只有当用户明确说协作者已完成/push，才继续以下流程。若用户只说“完成了”但没有 branch/head，可以使用已登录的 GitHub CLI 查找候选分支；仍无法唯一确定时再询问，不能猜。

### 1. 接管前在线核对

先发 commentary 告诉用户本阶段需要：GitHub 登录；Docker/Chrome/Edge 将在最终门禁使用；Mock 不需要 Provider 登录。然后：

- `git status`，保护用户改动；
- `git fetch --prune origin`；
- 核对 remote branch 的完整 head 与 handoff；
- 核对 base 是否是成员 A Prompt 指定的 main；
- 审查 `base..head` 的 commits、diff、契约、迁移、lock 和秘密/产物；
- 检查交接后 head 是否变化；
- 确认协作者没有直接更新 main；
- 如果远端 main 自协作者开始后有新提交，先审查其来源和与协作者分支的关系。

不要在成员 A 分支上追加自己的提交，也不要 rebase/squash/amend 它。

### 2. 建立 owner integration 分支并保留历史

从接管时精确最新 `origin/main` 创建：

```text
codex/day4-owner-integration
```

使用普通 `--no-ff` merge 引入成员 A 的精确 handoff head。解决冲突时要理解契约语义，不能机械选 ours/theirs。merge 后验证：

- handoff head 是 integration head 的祖先；
- 最新 main base 是 integration head 的祖先；
- 作者、提交和 merge 边界可追溯；
- 没有意外文件。

### 3. 独立测试成员 A 的实现

先运行成员 A 声明的命令，再从真实应用入口补测。重点寻找：

- 只有纯函数通过，但 Orchestrator 没有实际检索/注入；
- trace 存了但 Provider 没收到 memory section；
- owner 在打分后过滤造成泄漏；
- candidate/paused/expired 仍可召回；
- null 被当 ANY；
- current task 没有覆盖长期记忆；
- token 预算按字符冒充 token，或截断后 hash/记录不一致；
- estimated tokens 冒充 provider actual；
- evidence excerpt 不是答案精确子串；
- usage/计数/事件/idempotency 不同事务；
- 事件写错 stream 或正文进入 metadata/log；
- reload/restart 后 trace/receipt 丢失；
- OpenAPI 审计 manifest 绿色但实际 FastAPI route/response model 不存在；
- migration 形成多个 head 或旧库 readiness 错误；
- Mock hard-code fixture 完整句子以骗过检索测试。

把复现结果写入 `docs/day4/OWNER_INTEGRATION_REPORT.md`，先记录失败基线，最终再追加修复后证据；不能删除失败历史。

## 八、成员 B 在 Day 4 负责的实现

修复成员 A 的 P0 阻断后，继续在同一 owner integration 分支完成以下内容。

### 1. 前端 contract、API 与 reducer

- 为 RetrievalTrace、candidate/selected/excluded、UsageReceipt、memory version、usage feedback 补齐 TypeScript 类型和严格 runtime parser；拒绝额外/错误字段。
- API 层接入经 G3 冻结的 trace/receipt、active edit、pause/resume、versions/usages 和 user-effect 路由；所有 fetch 携带 cookie。
- 每个新的 edit/pause/resume/user-effect 写操作生成独立 `Idempotency-Key`；网络重试复用同 key，成功后释放。
- reducer 不得忽略 Day 4 持久事件；按 task/run 保存 trace、receipt 和 verification 更新。
- 任务切换、demo 用户切换、新 session 和卸载时取消旧请求/monitor，清空旧用户的 trace、usage、编辑草稿和 pending key。
- 刷新先 GET snapshot/trace/receipt，再按 persistent event seq catch-up；不能依赖只存在内存的 SSE。

### 2. Chat 页检索解释与使用凭证

在真实任务下显示：

- retrieval candidates、selected、injected、excluded；
- 受控 reason code 和可读映射；不展示伪思维链；
- scope/semantic/final score 及其明确是检索分数而非概率；
- 参考数、estimated memory tokens、provider actual prompt tokens（无则 `—`/未提供）、retrieval latency；
- retrieval mode；默认 TF-IDF 是正常，不标 degraded；
- receipt 的 retrieved/injected 与 verification 的 applied/violated/not_observable/unknown；
- “有帮助 / 不该用 / 已过时”，失败保留选择并允许受控重试。

文案必须区分：

- retrieved：进入候选；
- selected：通过过滤/评分；
- injected：进入本轮 prompt；
- applied：自动验证在答案中有精确证据；
- user helpful：用户评价有效。

不能把 retrieved/injected 写成“已体现”，不能把 verifier unknown 写成成功。

### 3. 当前任务覆盖与 memory mode

- UI 显示 `memory_mode` on/off；off 后 trace 应诚实显示无注入或受控关闭原因。
- 当本次 task/current constraints 覆盖长期记忆时，显示 `CURRENT_TASK_OVERRIDE`，不能把它当错误。
- 当前约束和系统安全优先级高于 memory；UI 不提供绕过硬过滤的强制注入开关。

### 4. 最小记忆页

只实现 Day 4 需要的：

- active 卡详情与受控编辑；
- pause/resume；
- 不可变版本只读列表；
- usages/receipt 只读记录。

编辑成功后显示新版本并恢复；失败保留草稿。pause 后新的相似任务不能召回；resume 后按正常阈值重新参与。不要提前实现 Day 5 的完整搜索中心、冲突裁决、merge、Pack、归档/永久删除全流程。

### 5. EvalRunner 与 fixtures

- 独立复核现有 30 条 retrieval draft 的 query/memory/status/scope/expected/reason；记录修订理由，不能直接把 review status 改成“两人已批准”。
- 根据总计划扩展为正例、近似负例、完全负例及隔离/状态/override/budget 场景；如果当天目标是 60 条，明确哪些由 B 审核并冻结。
- 扩展 REST-only EvalRunner，不能导入后端内部模块；输出只含 case ID、memory ID、分数、reason、计数、token/latency，不含 query/memory 正文。
- CLI 失败返回非零；保留 case-level failure，不删失败样本。
- Day 5 Pack/conflict fixtures 可准备草案，但不能在 Day 4 标成可执行产品能力。

### 6. 成员 B 前端测试

至少覆盖：

- 四类 candidate/selected/injected/excluded reducer 更新与 SSE catch-up；
- 分项分数/reason/mode/token/latency 展示；
- retrieved/injected/applied/helpful 不混淆；
- applied/violated/not_observable/unknown；
- helpful/harmful/stale idempotency key 重试；
- current override 和 memory off；
- active edit 新版本、失败保留草稿、pause/resume、版本恢复；
- 刷新恢复 trace/receipt；
- demo 用户/任务切换取消 monitor 并清空状态；
- 跨用户 404 不泄漏旧 UI；
- parser 拒绝契约外字段/错误枚举；
- 不再把现有 42 项 G2 测试当作 G3 UI 证据。

## 九、Day 4 完整合并门禁

最终必须从 G1 递增跑到 G3。命令以实际仓库工作目录和 lock 为准，报告真实数量，至少包括：

### 1. 后端、契约和迁移

- `python -m ruff check apps/api`；
- `python -m ruff format --check apps/api`；
- 完整 `pytest`，不是只跑 Day 4 文件；
- `python -m pip check`；
- requirements.in 与带 hash lock 一致；
- fixture validator 和 Day 3/Day 4 REST Eval CLI；
- Pydantic、JSON Schema、实际 FastAPI OpenAPI、TypeScript parser 同构；
- 空库升级、D3 revision 升级、旧 revision readiness 非 200、唯一 current head ready；
- worker/lifespan、并发、幂等、事务回滚、事件连续性、重启恢复和 owner 隔离。

### 2. 前端

在 `apps/web` 运行：

- `npm run typecheck`；
- `npm run lint`；
- `npm test`；
- `npm run build`。

必须报告文件数/测试数和退出码，不只写“绿色”。

### 3. G1+G2 回归

- 服务端自动分类，旧 scenario 仍 422；
- session 切换旧 cookie 失效，跨用户 task/API/SSE 404；
- task/feedback 幂等、持久 event seq 和刷新恢复；
- feedback → worker → candidate/evidence → accept/edit_accept/reject/one-shot；
- 未确认 candidate 不 active、不检索；one-shot 不创建长期版本；
- Docker cold/restart 后 G1/G2 数据仍恢复。

### 4. G3 关键路径

至少真实运行：

1. 第一任务反馈并确认 active v1；
2. 第二个相似任务只召回预期 owner 的 active 卡，selected/injected 并形成 receipt；
3. 输出中有精确证据时 applied；无法判断/失败时 unknown，不伪造 excerpt；
4. 无关/近似负例不注入；
5. 当前明确要求覆盖长期卡并记录 override；
6. pause 后不召回，resume 后恢复；
7. memory_mode off 不召回；
8. 总 memory prompt 不超过 300 estimated tokens；
9. 跨用户 trace/usage/memory/task 全不可见；
10. 刷新和容器 restart 后 trace、usage、version、event 仍恢复。

### 5. Docker 与双浏览器

- 使用任务专属 Compose project、端口和全新 volume，不破坏用户现有数据；
- cold start 自动迁移到唯一 head并 `/ready`；
- 容器 restart 与 compose down/up（保留专属卷）恢复；
- Chrome 和 Edge 各跑一次 G3：切用户、自动分类、G2 学习、相似任务召回、trace/receipt、效果反馈、pause、刷新、跨用户隔离；
- 记录 console/network 预期与非预期错误；
- Mock 是硬门禁，不需要真实 Provider。

### 6. 隐私和 Git

- `git diff --check`；
- tracked/untracked 检查；
- `.env`、token、数据库、容器产物和用户材料扫描；
- event_log、SSE、server log、Eval output 不含正文键/值；
- 编译 memory section 只记录 hash/长度/token，不记录 rule/avoid/evidence；
- 不删除协作者远端分支。

## 十、Day 4 直接交付 main

当且仅当全部门禁实际通过：

1. 提交 `docs/day4/OWNER_INTEGRATION_REPORT.md`，写明成员 A base/head、merge commit、你的修复/实现 commits、命令/退出码/数量、Docker/Chrome/Edge、限制和 last-known-good 完整 SHA；
2. 确认成员 A handoff head 是当前已验证 head 的祖先；
3. 再次 fetch `origin/main`；
4. 若 origin/main 与整合时 base 不同，停止直接 push，把新 main 普通 merge 进来，解决冲突并重跑受影响门禁；
5. 检查工作区、diff、秘密和意外产物；
6. 使用普通 `git push origin HEAD:main`，绝不 force；
7. 重新读取远端 main，确认完整 SHA 等于已验证 head；
8. 只有此时才报告“Day 4 完成”。

如果 main 的 owner-only ruleset 阻止 `W-JOSLIN-X` 普通更新，先读取规则确认 actor/target，不要取消所有保护或恢复强制 PR。若需要 GitHub 重新登录或用户调整权限，暂停并精确说明。

## 十一、Day 4 明确不做

- 不把 BGE/真实模型 smoke 设为硬门禁；
- 不实现向量数据库或全库先 Top-K 后 owner 过滤；
- 不实现 Day 5 完整记忆中心、冲突裁决、自动 merge、Memory Pack import/export；
- 不实现 Day 6 动态 eval API、动态图表或根据 test split 调阈值；
- 不实现任意代码执行、Shell、文件系统、联网抓取、动态插件或多 Agent；
- 不声称 retrieved/injected 等于 applied/helpful；
- 不提交真实正文、密钥、数据库或测试浏览器资料；
- 不创建日常 PR，不要求协作者审批，不通过 `integration/day2` 晋级；
- 不因流程简化而跳过完整 G1+G2+G3、Docker 或双浏览器证据。

## 十二、你在新对话中的第一轮输出标准

开始时先用简短 commentary 告知用户：

- 你将先完整阅读和独立核验；
- GitHub 登录是阶段 1 唯一账号依赖；
- Mock 模式不需要模型平台登录；
- 第一阶段只产出成员 A Prompt 和 G3 冻结决策，不提前做成员 A 后端。

完成阶段 1 后，最终回复必须以“可直接发给协作者 Agent 的 Prompt”作为主体，并同时说明：

- 你实际核对的 origin/main 完整 SHA；
- 保存到仓库的两个 Day 4 文档；
- 文档是否已普通直推 main 及远端 SHA；
- 哪些基线测试亲自运行、哪些尚未运行；
- 用户下一步只需把 Prompt 发给成员 A，等待其 push 后把 handoff 原样带回来。

不要要求用户另外手工打包代码或文档：只要文档 commit 已在 GitHub main，成员 A 有仓库访问权限，就可自行 fetch/read。不要声称成员 A 有某一远端分支，直到实际看见它。
