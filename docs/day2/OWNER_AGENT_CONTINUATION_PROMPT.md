# MemTrace Day 2 项目负责人新对话 Agent 完整交接 Prompt

> 使用方法：把本文件全文连同 `Universal_Feedback_Memory_Agent_Project_Plan.md` 提供给新对话 Agent。不要只截取其中的任务清单；当前状态、设计修正、验证门禁和 Git 边界同样属于执行要求。

---

## 给新对话 Agent 的 Prompt

```text
你现在接手 MemTrace 项目 Day 2 的项目负责人部分。你的任务不是只给建议，而是：先独立理解并审查当前仓库和队友 PR，再制定本次可执行计划，完成自动任务分类的跨层修正、Day 2 前端与后端联调、持久化容器交付、全链路验证、逐步 Git 提交和 PR 交接。

你必须以实际仓库、实际 diff、实际测试和实际日志为准。交接文档、聊天描述和测试数量只是线索，不是独立证据。不得宣称“百分百正确”；只能报告已验证事实、证据和仍未验证项。

### 0. 开始前必须说明的登录与安全要求

在调用任何会依赖账号状态的工具前，先向用户明确说明：

1. 本任务现在需要 GitHub CLI 已登录，用于读取、评论、创建和更新 PR。
2. 到 Docker 验收阶段，需要 Docker Desktop 已启动且账号状态可用；在到达该阶段前不要求用户一直等待。
3. 本任务只用 `MOCK_MODE=true` 完成 Day 2 验收，不需要调用真实 DeepSeek，不需要用户提供 API Key。

随后执行 `gh auth status`。如果 GitHub 未登录或登录失效，立即暂停并告诉用户需要登录 GitHub；不要因为公开仓库可匿名读取就改用匿名下载规避登录要求。到 Docker 阶段前再执行 `docker info`；如果不可用，暂停并告诉用户需要启动或登录 Docker Desktop。

安全要求：

- 不读取、输出、复制或提交本地 `.env` 中的 Secret。
- 不把 Cookie、Session Secret、API Key、任务正文、代码正文或用户反馈写入日志和验证报告。
- 测试和验收统一使用 Mock Provider。
- 提交前用仓库既有规则扫描 staged diff；发现已知 API Key/Authorization 前缀、真实
  Cookie、凭据值或异常高熵字符串时停止提交并清理。示例环境变量名不等于凭据值。

### 1. 项目位置与截至交接时的已知事实

工作目录：

`C:\Users\lenovo\Desktop\2026Hackathon`

GitHub 仓库：

`https://github.com/W-JOSLIN-X/MemTrace`

截至 2026-08-22 交接时：

- `main` 和 `integration/day2` 指向 Day 1 已验收基线 `0468904332ffa79512ac2319f9dfd81d1f67c4cd`。
- 第二成员 PR 是 `#2 feat: complete day2 backend feedback implementation`。
- PR #2 base=`integration/day2`，head=`feat/day2-backend-feedback`。
- 交接时远端 head 是 `d5afd441d11a84db85f7a434ea41a625703c097a`；这是时间点快照，开始工作时必须重新 fetch 和核对，不能假定未变化。
- PR #2 交接时为 OPEN、非 Draft、mergeable，但因需要另一成员 Review 而 BLOCKED。
- PR #2 当时没有 CI status、没有 Review、没有评论，PR body 为空。
- PR #2 有 7 个提交，约 37 个文件、5641 行新增、308 行删除。交接时顺序为：
  `dc2fe38` contract、`8db059c` dependencies/Alembic、`9222d45` SQLite schema/repository、
  `c0d4f0f` demo session/owner isolation、`5c66c52` G0 persistence、`79bf42a`
  OpenAPI re-export、`d5afd44` Day 2 tests。
- 队友 `docs/day2/HANDOFF.md` 声称后端 99 tests、前端 25 tests 通过，但报告中的 head 仍写成早期 `dc2fe38`，并称网络、push、PR 尚未验证；它与真实远端状态已经不一致。你必须独立复跑，不能把它作为验收证据。
- 当前另有文档 PR #1，head=`docs/day2-handoff`，包含 Day 2 交接文档。不要把文档 PR 当成代码集成分支。

第一步必须重新确认这些事实：

```powershell
git status --short --branch
git remote -v
gh auth status
git fetch origin --prune
gh pr view 2 --json number,title,state,isDraft,baseRefName,headRefName,headRefOid,mergeable,mergeStateStatus,commits,files,reviews,statusCheckRollup,url
gh pr diff 2 --name-only
```

如果工作区有用户的未提交修改，不得覆盖、stash、reset 或清除；先报告冲突范围并设法绕开。禁止 `git reset --hard`、force push、改写队友历史或直接 push 受保护分支。

### 2. 必读资料及优先级

开始修改前完整阅读：

1. 仓库中的 `AGENTS.md`，其指令优先于普通文档。
2. 本 Prompt。
3. PR #2 的实际提交、diff、代码、migration、测试和 OpenAPI。
4. `Universal_Feedback_Memory_Agent_Project_Plan.md` 中 Day 2、Task Fingerprint、API、反馈生命周期、测试和两人协作章节。
5. `docs/day2/HANDOFF.md`、`docs/day2/OWNER_INTEGRATION_PLAN.md`、`docs/day2/TEAMMATE_AGENT_PROMPT.md`。
6. `contracts/day2-g1.json`、`contracts/openapi.json`、`contracts/schemas/*.schema.json`。

`AGENTS.md` 的安全和协作要求始终必须遵守；本 Prompt中的产品设计修正优先于旧契约、
总计划旧描述和交接报告。如果 `AGENTS.md` 与本 Prompt出现真实冲突，先暂停并向用户说明，
不得自行降低安全要求。实际代码用于确认现状，不是凌驾于用户新决策之上的指令。

如果总计划或旧契约仍要求用户手动提交 `scenario`，本 Prompt中的“自动分类决策”取代该旧设计；你还必须同步修订总计划和契约，不能只在代码中偷偷改变。

### 3. 先建立真实代码地图

不要凭文件名猜实现。至少定位并读懂：

- `apps/api/src/memtrace_api/schemas.py`
- `apps/api/src/memtrace_api/logic.py`
- `apps/api/src/memtrace_api/main.py`
- `apps/api/src/memtrace_api/store.py`
- `apps/api/src/memtrace_api/orchestrator.py`
- `apps/api/src/memtrace_api/repositories.py`
- `apps/api/src/memtrace_api/database.py`
- `apps/api/src/memtrace_api/db_models.py`
- `apps/api/src/memtrace_api/session_auth.py`
- `apps/api/src/memtrace_api/idempotency.py`
- `apps/api/src/memtrace_api/readiness.py`
- `apps/api/src/memtrace_api/events.py`
- `apps/api/alembic.ini` 与 `apps/api/alembic/`
- `apps/api/tests/`
- `apps/web/src/pages/ChatPage.tsx`
- `apps/web/src/g0/useG0Agent.ts`
- `apps/web/src/g0/api.ts`
- `apps/web/src/g0/eventStream.ts`
- `apps/web/src/g0/types.ts`
- `apps/web/src/g0/runtime.ts`
- `apps/web/src/g0/reducer.ts`
- `apps/web/src/**/*.test.*`
- `fixtures/`
- `scripts/day1/smoke.ps1`、`scripts/day1/real_provider_smoke.py` 和新增 Day 2 smoke
  （如果存在）
- `Dockerfile`、`compose.yaml`、`.dockerignore`、`README.md`

你应当能够画出并用文字说明以下真实链路后再改代码：

`浏览器 -> session cookie -> POST task + Idempotency-Key -> SQLite task/run/event -> TaskStore/worker -> SSE -> task snapshot -> feedback transaction -> pending memory job -> post-run catch-up event`

### 4. 必须纠正的产品设计：用户不选择对话类别

当前实现的以下行为是错误设计：

- Chat 页显示“使用场景”下拉框。
- 前端 `TaskCreateRequest` 强制发送 `scenario`。
- 后端 `TaskCreateRequest` 强制接收 `scenario`。
- `analyze_task()` 虽然会自动识别 language、task_type、framework、concepts，却直接把 `request.scenario` 当作 domain。
- 数据库和快照因此保存的是用户自报类别，而不是 Agent 的任务理解。

这与产品目标冲突。用户只应描述任务和提供反馈；系统应自动识别当前任务属于什么类别，再结合任务轨迹和反馈归纳偏好、规则和经验。用户不应该先懂系统的分类体系，更不应该替 Agent 做分类工作。

本次必须完成跨层修正，不能只隐藏下拉框。

#### 4.1 Day 2 固定决策

1. 从任务创建请求中彻底移除 `scenario`，并保持请求模型 `extra=forbid`；旧客户端继续发送该字段时应明确返回契约错误，而不是悄悄信任它。
2. 前端删除场景下拉框，不再在任何提交路径、fixture 或 smoke 中发送 `scenario`。
3. 后端使用确定性、可测试的规则分类器自动得出 domain。
4. Day 2 继续保留 4 个受控 domain：
   - `programming_learning`
   - `software_development`
   - `general_text`
   - `other`
5. 数据库 `tasks.scenario` 字段在 Day 2 暂不改列名，以避免无价值 migration；但语义改为“服务端检测出的 domain”。任何写入都只能来自分类器。
6. API 快照暂时可以继续返回 `scenario` 以减少破坏面，但必须在 Schema、OpenAPI 和文档中标注为 server-derived；前端显示文案应为“系统识别场景”，不能叫“选择场景”。
7. `response_policy`、`memory_mode` 和用户当前约束仍可由用户控制，因为它们是执行要求，不是任务类别。
8. 用户以后可以通过“纠正识别”提供反馈，但 Day 2 不新增第二套手工分类输入；更不能让纠正值直接绕过记忆准入。

#### 4.2 自动分类的实现约束

为保证两名初学者能在 7 天计划内完成，Day 2 不在每次创建任务前新增一次 LLM 调用。先扩展现有规则式 Task Fingerprint：

- 代码块、语言特征、报错、调试、解释、学习、教程、初学者、为什么、提示而非答案等信号倾向 `programming_learning`。
- 修复、实现、重构、审查、部署、环境配置、依赖、生产项目等信号倾向 `software_development`。
- 改写、总结、翻译、语气、格式等非代码文本任务倾向 `general_text`。
- 证据不足或冲突时使用 `other`，而不是伪造高置信判断。

分类器必须是纯函数、确定性、无 I/O、无模型调用；中文和英文线索都要覆盖。不要把整段用户文本保存为分类理由。

在 `TaskFingerprint` 中新增并冻结：

- `classification_source`: 固定为 `auto_rule_v1`；
- `classification_confidence`: 0 到 1；
- `classification_reasons`: 受控理由代码列表，例如 `code_present`、`learning_cue`、`explanation_intent`、`development_action`、`deployment_cue`、`text_task`、`ambiguous`。

置信度是规则分数的结果，不得冒充统计学概率。必须在文档中写清评分方法和边界。事件日志只记录受控 reason code、domain 和 confidence，不记录用户全文。

#### 4.3 一个分类来源，禁止双重计算漂移

推荐固定实现：

1. 路由接收无 `scenario` 的 `TaskCreateRequest`，先按规范请求体计算 idempotency hash；
   已存在的同载荷请求直接重放，不能再生成一套 fingerprint ID。
2. 新请求获得可靠的 TaskStore 容量 reservation 后，调用一次纯函数
   `analyze_task(request)` 得到完整 `TaskAnalysis`；任何失败路径都释放 reservation。
3. `TaskRepository.create_task(...)` 接收
   `detected_domain=analysis.fingerprint.domain`，写入 `tasks.scenario`。
4. `TaskStore.create(...)` 接收同一个 `analysis`，快照和 worker record 都复用它；已经
   reservation 成功的注册不能再因容量竞争留下数据库幽灵任务。
5. Orchestrator 到 fingerprint 阶段只发布并持久化这个已经生成的 fingerprint，不得再次
   独立分类。

如果由于现有类型依赖必须采取等价结构，也必须证明一个 task 只产生一个分类结果；不得在 route、repository、store、orchestrator 各写一套规则。

#### 4.4 契约、测试与界面必须同步

至少更新：

- Pydantic request/response 模型；
- OpenAPI 导出；
- `contracts/schemas` 中相关 JSON Schema；
- `contracts/day2-g1.json` 决策和版本；
- TypeScript 类型与 runtime parser；
- Chat 表单和提交 hook；
- reducer / timeline 的 fingerprint 展示；
- 所有 fixtures、后端测试、前端测试和 smoke 请求；
- 总计划中 Task Fingerprint、Task API、隐私表、Day 2 前端任务、Day 3 Feedback Compiler 输入的旧描述。

推荐把 TaskFingerprint schema 版本提升为 `1.1`，Day 2 contract 版本提升为 `1.1.0`，并在 `docs/day2/AUTO_CLASSIFICATION_DECISION.md` 记录“为什么改、兼容策略、测试和 Day 3 连接点”。如果代码现状需要不同版本号，说明理由，但不得不更新版本。

必须新增的分类测试至少包括：

- 中文编程学习：要求解释原因、不要直接给答案 -> `programming_learning`；
- 英文编程学习；
- Python 报错调试教学；
- 项目代码重构/代码审查 -> `software_development`；
- 开发环境或部署配置 -> `software_development`；
- 非代码改写/总结 -> `general_text`；
- 模糊输入 -> `other` 或有明确记录的低置信结果；
- 同一输入重复分类完全一致；
- snapshot `scenario`、fingerprint `domain`、DB `tasks.scenario` 三者一致；
- 请求仍携带手工 `scenario` 时被严格拒绝；
- UI 中不存在“使用场景”选择控件，fingerprint 到达后显示只读分类、置信度和简短理由。

### 5. Day 2 与 Day 3 的边界：必须改方案，但不能抢做假功能

用户最终目标是自动总结“偏好、规则、经验”。这个目标不会在 Day 2 通过一个 category 下拉框实现，也不应把尚未设计完整的记忆提取塞进 Day 2。

正确分层：

- Day 2：自动生成 Task Fingerprint；保存原输出、用户直接修改、采纳/拒绝、评分和自然语言反馈；事务性创建 `memory_job=pending`；实时显示反馈事件。此时还没有生成长期记忆。
- Day 3：Feedback Compiler 读取自动 Task Fingerprint、原结果、修改后结果/diff、显式反馈、评分和任务轨迹，自动判断候选内容是 `preference`、`rule`、`experience` 还是一次性要求，再做记忆准入；用户只对系统生成的候选卡片确认、修改、拒绝或标记仅本次。

Day 3 计划输入必须改为：

`TaskFingerprint + original_output + edited_output/diff + explicit_feedback + rating/accepted + safe execution trace`

Day 3 分类含义：

- preference：用户偏好的风格、流程、技术选择；
- rule：明确的应当/禁止/先后顺序约束；
- experience：从任务结果和反馈中得到、在相似任务可能复用的方法或教训；
- one-shot：只适用于本次，不进入长期记忆。

候选记忆的 scope 应优先由自动 fingerprint 的 domain、task_type、language、framework、project 等推导，而不是用户事先选择。将这些写入总计划的 Day 3 章节，但本次不要生成假 MemoryCard、不要把 `pending` 伪装成“已经学会”。

### 6. 在做前端前，对 PR #2 做独立复核

先从远端 PR head 创建只读验证点。不要先合并 PR #2。

建议流程：

```powershell
git switch --detach origin/feat/day2-backend-feedback
apps/api/.venv/Scripts/python.exe -m pip install --require-hashes -r apps/api/requirements.lock
apps/api/.venv/Scripts/python.exe -m ruff check apps/api/src apps/api/tests apps/api/scripts
apps/api/.venv/Scripts/python.exe -m ruff format --check apps/api/src apps/api/tests apps/api/scripts
apps/api/.venv/Scripts/python.exe -m pytest -W error apps/api/tests -q
Set-Location apps/web
npm ci
npm run typecheck
npm run lint
npm run test
npm run build
Set-Location ../..
```

若 `.venv` 不存在，创建项目本地 venv；不要使用损坏的 Windows `py -3.11` 映射。依赖安装需要网络而网络不可用时，按权限流程请求网络访问，不要偷换未锁版本。

交接时源码审查已经发现以下高风险点，你必须逐一验证；若真实代码已变化，以实际结果为准：

1. `allocate_next_event_seq()` 采用 `SELECT ... WITH FOR UPDATE` 再 `UPDATE`。SQLite 不提供预期的行级 `FOR UPDATE` 语义，这不满足“单语句分配序号”的并发承诺。改为 SQLite 支持的原子 `UPDATE ... RETURNING` 或等价单语句，并加入真实并发测试。
2. `POST /tasks` 可能先提交 task/idempotency，再调用内存 `TaskStore.create()`；如果 store 容量满，数据库保留一个已返回/可重放却没有 worker 的任务。必须在 durable 202 前完成容量 admission，或实现同事务/补偿清理，并测试容量失败没有幽灵任务和脏幂等记录。
3. `POST /session/demo` 可能没有撤销当前 cookie 对应的旧 session；`GET /session` 可能按 owner 查“最新活跃 session”，而不是当前 token 的 expiry。修正切换语义，并测试切换后旧 cookie 变为 401、当前 cookie 返回自身信息。
4. `/ready` 可能只验证数据库连通而不验证 Alembic head；这不足以证明运行时 schema 可用。
5. Dockerfile/compose 交接时没有 Day 2 migration、持久化 SQLite、`SESSION_SECRET` 注入和 volume 改动；不能把 Day 1 容器通过当成 Day 2 容器通过。
6. 队友测试中需要确认是否真的包含“同 owner + 同 Idempotency-Key 并发请求”的测试，而不是仅顺序重放。
7. 所有 repository 查询和写入必须由可信 `UserContext.owner_id` 隔离；请求体不得提供 owner_id。

对每一项给出：代码位置、复现测试、修复提交和回归证据。不要只在最终报告里说“已检查”。

如果 PR #2 有 P0/P1 且队友在线，优先在 PR 留精确 review 并让队友追加 fix commit；如果用户明确要求你继续完成且不能等待，可以从经过记录的 PR head 创建自己的分支修复，但不得修改或 force-push 对方分支，最终报告要区分“队友代码”和“负责人修复”。

### 7. 创建负责人分支

在 PR #2 head 已核对并记录后创建：

```powershell
git switch -c feat/day2-frontend-integration origin/feat/day2-backend-feedback
```

如果该分支已经存在，不要覆盖；检查本地、远端和 worktree 后继续或创建清晰的新分支，并报告选择。

不要提前把 PR #2 merge 进 `integration/day2`，因为前端需要基于同一已验证 head 联调。不得直接 push `main` 或 `integration/day2`。

### 8. Day 2 负责人要完成的真实产品闭环

#### 8.1 会话切换与用户隔离

前端实现并严格按 OpenAPI 调用：

- 获取当前 demo session；
- 切换 `blank_demo` / `seeded_demo`；
- 可选注销/重建流程；
- 所有 fetch 使用 `credentials: 'same-origin'`；
- 切换后清空当前用户的本地任务状态、EventSource、feedback draft 和 sessionStorage 恢复指针；
- UI 不要把 `seeded_demo` 写成“已经有长期记忆”，Day 2 尚未实现长期记忆；可标为“演示用户 B（隔离测试）”。

验收：用户 A 的 task/feedback 不能被用户 B 的 API、URL 恢复或 SSE 读取；切回 A 后仍可读 A 数据。

#### 8.2 任务提交、幂等与自动分类展示

- 新任务请求不含 `scenario`。
- task create 和 feedback create 两个契约要求的写请求生成 `Idempotency-Key`；网络重试同一次操作必须复用原 key，用户主动新建才生成新 key。session bootstrap/logout 是已冻结的例外，不擅自加 header。
- POST 返回后 URL 至少包含 `task_id`，并把当前 task 指针放入 sessionStorage。
- 页面刷新先 GET snapshot，再用 `last_persistent_event_seq` 做 SSE catch-up。
- EventSource 断线恢复继续保留 Day 1 的 event ID/chunk offset 去重。
- `task.fingerprinted` 后显示“系统识别：domain / task_type / language / confidence”，可展开受控理由的人类可读映射。
- 低置信结果必须显示“识别不确定”，不能伪装确定。

#### 8.3 原输出、直接修改与显式反馈

完成以下 post-run UI：

- 原始结果只读保留；
- 用户可以复制到编辑区并直接修改；
- 采纳 / 拒绝；
- 1–5 评分（允许按契约为空则明确）；
- 自然语言反馈；
- 提交前显示本次会发送哪些字段；
- 重复点击、网络重试和刷新不会产生重复 feedback；
- 失败时保留用户未提交的 edited_output 和 feedback_text，不清空表单。

不得在浏览器或日志展示 feedback 原文以外的隐式诊断上传；不得把用户编辑覆盖原 message。

#### 8.4 Feedback 事务与后台任务状态

后端一次 feedback 事务必须原子写入：

- feedback；
- memory_job，状态为 `pending`；
- 一个 `feedback.recorded` persistent event，payload 同时携带 `feedback_id`、
  `memory_job_id` 和 `feedback_type`；
- idempotency record。

响应成功后前端不能只依赖已经结束的 EventSource。必须按冻结契约执行一次 post-run catch-up：

1. 记录提交前的 `last_persistent_event_seq`；
2. POST feedback；
3. GET `events?after_event_seq=<last_persistent_event_seq>`；
4. reducer 按 persistent seq 去重；
5. UI 显示 feedback 已保存、memory job pending。

文案只能是“反馈已保存，等待 Day 3 处理”，不能说“Agent 已学会”。

#### 8.5 页面刷新和进程重启恢复

验证：

- 任务运行中刷新；
- 任务完成后刷新；
- feedback 提交后刷新；
- API 进程重启；
- 浏览器重新打开同 task URL；
- session A/B 切换。

持久 snapshot 为权威，内存 TaskStore 只负责活动任务。重启前 ACTIVE run 应按设计变为 interrupted/failed 且可解释；已完成正文和反馈仍可恢复。

### 9. 前端代码组织约束

允许在 Day 2 将 `g0` 模块重命名为更中性的 `agent` 或 `tasks`，但不要为了命名做大规模无功能重构。如果保留 `g0` 目录，应在文档说明它已承载 G1 兼容层。

至少建立清晰边界：

- API client：session、task、feedback、events；
- runtime parser：所有外部 JSON 严格解析；
- reducer：ephemeral event ID、persistent seq、chunk offsets 三种去重；
- hooks/controller：任务生命周期、恢复、重连、post-run catch-up；
- components：SessionSwitcher、DetectedFingerprint、EditableResult、FeedbackPanel、FeedbackLifecycle；
- 页面只组合状态，不内嵌所有网络和去重逻辑。

禁止：

- 使用 `any` 绕过新增契约；
- 只改 TypeScript interface 不改 runtime parser；
- 在 UI 中写死假 job 状态；
- 把 reasoning_content、Cookie、内部异常栈展示给用户；
- 通过刷新清空问题来假装恢复成功。

### 10. Fixture、自动测试与手工验收

Day 2 最少保留并整理 24 条 fixture：

- 8 条 Day 1/G0 核心任务；
- 8 条 feedback/edit/accept/reject/rating 案例；
- 8 条 session、idempotency、restart、并发、自动分类和隔离案例。

这些 fixture 是测试数据，不是“真实模型实测”。必须标注 expected domain、task_type、是否可反馈、预期 persistent event sequence。

后端新增/复核：

- migration upgrade 全新库；
- 当前 schema 等于 Alembic head；
- session 旧 token 撤销；
- owner 隔离；
- task create/request 严格契约；
- 自动分类表驱动测试；
- DB/domain/fingerprint 一致性；
- 幂等顺序重放与真实并发；
- event seq 原子分配；
- store capacity 失败无幽灵任务；
- completed snapshot 恢复；
- restart interrupted run；
- feedback、memory job、`feedback.recorded` event 和 idempotency record 四对象同事务，
  任一失败全部回滚；
- feedback event catch-up；
- 日志脱敏。

前端新增/复核：

- 无场景下拉框；
- 无 `scenario` 请求字段；
- 自动分类只读展示与低置信状态；
- session 切换和状态清理；
- fetch credentials；
- Idempotency-Key 复用；
- 刷新 snapshot 恢复；
- EventSource reconnect；
- feedback 编辑/保留/校验；
- post-run persistent catch-up；
- 重复事件不重复渲染；
- 用户 A/B 隔离错误状态。

浏览器手工验收至少使用 Chrome 和 Edge。若需要使用已登录浏览器自动化，先说明需要哪一个浏览器会话；不要发现未登录后改用不需要登录的外部方案。

### 11. Docker 与持久化交付

Day 2 容器不是 Day 1 镜像复用即可。至少完成：

- 镜像包含 `alembic.ini`、migration 目录和运行依赖；
- 容器启动先执行 `alembic upgrade head`，成功后再启动单 worker Uvicorn；
- Compose 通过环境变量注入 `SESSION_SECRET`，示例值只用于本地 Mock，不提交真实 secret；
- SQLite 位于明确的数据目录并挂载 named volume；
- 容器内 `MOCK_MODE=true`；
- `/ready` 验证数据库可访问且 schema 位于 Alembic head；
- cold start、restart、down/up 后任务正文和反馈仍存在；
- healthcheck 不能在 migration 未完成时提前宣告 ready。

到本阶段前先告诉用户将使用 Docker Desktop，然后检查 `docker info`。实际执行 build、up、smoke、restart、down；未实际运行不得标记通过。

### 12. 文档和总计划必须怎样修改

不能只改代码。至少更新：

1. `Universal_Feedback_Memory_Agent_Project_Plan.md`
   - 删除 Task Fingerprint 中“UI scenario 优先”的描述；
   - Task 创建示例删除 `scenario`；
   - 隐私/Provider 表改为本地自动分类，只把必要 fingerprint 摘要用于执行；
   - Day 2 前端任务明确删除手工类别选择，显示系统检测结果；
   - Day 3 Feedback Compiler 明确自动判断 preference/rule/experience/one-shot；
   - scope 从自动 fingerprint 推导；
   - 不改第 8–10 天，不把 Day 3 代码提前宣称完成。
2. 新建 `docs/day2/AUTO_CLASSIFICATION_DECISION.md`，记录设计原因、分类规则、数据流、兼容策略、风险、测试和未来模型增强点。
3. 更新 `contracts/day2-g1.json` 和 Schema/OpenAPI hash。
4. 更新 README 的 Day 2 启动、migration、Mock、session、feedback、恢复和已知限制。
5. 更新 handoff/verification，使用实际最终 head，不复制队友旧 head。

### 13. 分步 Git 提交要求

每一步独立提交，禁止 amend 和 squash 队友提交。建议顺序：

1. `fix(contract): derive task classification server-side`
   - 自动分类决策、请求移除 scenario、Pydantic/TS/Schema/OpenAPI、fixtures 和最小测试一起完成，保证该提交本身可运行。
2. `fix(api): close G1 persistence and session gaps`
   - 原子 event seq、容量 admission、session token/current semantics、对应测试。
3. `feat(web): add demo session switching and isolation`
4. `feat(web): restore persisted tasks and idempotent writes`
5. `feat(web): add editable results and explicit feedback`
6. `feat(web): render post-run feedback lifecycle`
7. `test(day2): add automatic classification and G1 fixtures`
8. `build(day2): add migration-aware persistent container`
9. `docs(day2): align memory extraction plan with automatic classification`
10. `test(day2): record full G1 verification evidence`

如果实际依赖要求合并或拆分提交，可以调整，但每个提交必须只有一个可解释目的、能够回退，且不能留下编译失败或契约半更新状态。

每次提交前：

```powershell
git diff --check
git status --short
git diff --cached --name-only
git diff --cached
```

只按明确路径 `git add <paths>`，禁止 `git add .`。运行该提交影响范围的测试、typecheck/lint/build，并对 staged diff 做 secret scan。测试失败不提交。

### 14. 推荐执行节奏

按下面顺序工作并持续给用户简短进度，不要长时间无声：

1. 30–60 分钟：Git/PR/登录检查、代码地图、独立复跑。
2. 60–120 分钟：冻结自动分类变更，先让 contract 和所有测试重新绿。
3. 60–90 分钟：修复后端并发、容量和 session P0/P1。
4. 90–150 分钟：会话切换、任务提交、自动分类展示、刷新恢复。
5. 90–150 分钟：编辑结果、显式反馈、幂等和 post-run catch-up。
6. 60–90 分钟：fixture、契约、跨用户和 restart 测试。
7. 60–90 分钟：Docker migration/persistence 和 smoke。
8. 45–90 分钟：Chrome/Edge、文档、反向审查、验证报告和 Draft PR。

遇到一个问题时先缩小复现和写回归测试；不要同时大改前端、后端、migration 和 Docker后再一次联调。

### 15. 全量验证门禁

最终至少执行并记录退出码：

```powershell
apps/api/.venv/Scripts/python.exe -m ruff check apps/api/src apps/api/tests apps/api/scripts
apps/api/.venv/Scripts/python.exe -m ruff format --check apps/api/src apps/api/tests apps/api/scripts
apps/api/.venv/Scripts/python.exe -m pytest -W error apps/api/tests -q
apps/api/.venv/Scripts/python.exe -m pip check
Set-Location apps/web
npm ci
npm run typecheck
npm run lint
npm run test
npm run build
Set-Location ../..
```

还必须实际验证：

- 全新 SQLite migration；
- 24 条 fixture；
- Mock 创建任务、SSE、自动分类、正文完成；
- session A/B 隔离；
- feedback、job、persistent catch-up；
- 同 key 顺序和并发幂等；
- 进程 restart 恢复；
- Docker cold start/restart；
- Chrome/Edge 完整黄金流程；
- OpenAPI 与冻结契约一致；
- Git tracked/staged secret scan；
- `git status` 最终只出现预期文件或干净。

建议后端、前端全套各连续通过 2 次，关键 Mock 黄金流程连续通过 3 次；但不要用重复次数替代缺失的并发、隔离和恢复测试。

### 16. 反向审查问题

完成实现后，从四个视角复核：

产品视角：

- 用户是否仍在任何地方被要求选择类别？
- 自动分类是否真的参与后续反馈 scope，而非只显示标签？
- 低置信是否诚实呈现？
- feedback pending 是否被误称为已经学习？

后端视角：

- category 是否只有一个计算来源？
- DB、snapshot、event、OpenAPI 是否一致？
- 并发 idempotency 和 event seq 是否真是原子操作？
- durable 202 是否一定有可恢复运行状态？
- session A/B 是否能越权？

前端视角：

- 刷新、重连、重复事件、重复点击是否都不会重复状态？
- 失败是否保留用户编辑和反馈草稿？
- session 切换是否清除旧用户本地指针？

评委视角：

- 能否演示“第一次自动识别任务 -> 用户改结果/给反馈 -> 系统保存待学习证据”，而不是让用户配置系统？
- 是否清楚解释 Day 2 只是可靠采集，Day 3 才形成可审阅记忆？
- 是否有实际测试数字和失败案例，而非口号？

### 17. PR 与晚间合并流程

你的功能分支完成后 push 并建立 Draft PR，base=`integration/day2`。PR body 必须包含：

- 基线和最终 head；
- 自动分类设计变化；
- 队友 PR 中发现并修复/仍待修复的问题；
- 数据库和 migration 影响；
- 测试命令、退出码和实际数量；
- Docker image/volume/restart 证据；
- Chrome/Edge 手工结果；
- Secret 扫描；
- 未验证项与已知限制；
- 明确的 reviewer checklist。

由于你的分支从队友 PR head 派生，在 PR #2 尚未合并时，负责人 PR diff 可能暂时包含队友提交，这是预期的 stacked PR 状态。正确顺序：

1. 你完成对 PR #2 的 review，队友修复最后问题；
2. PR #2 通过 required approval 后 merge 到 `integration/day2`；
3. 更新/刷新你的 PR，确认 diff 只剩负责人提交；必要时只做普通 merge/rebase，禁止 force 重写已审查历史；
4. 第二成员 review 你的 PR，最后一次 push 后重新批准；
5. 负责人 PR merge 到 `integration/day2`；
6. 从 `integration/day2` 在干净环境跑完整验收；
7. 创建 `integration/day2 -> main` 的 Day 2 PR；
8. 第二成员 review/批准，解决全部 conversation，再用 merge commit 合并；
9. main 上复跑最小 smoke，最后才创建 Day 2 verified tag。

不得因为 branch protection 阻塞就临时关闭保护、管理员绕过、自批自合或直接 push main。

### 18. 遇到阻塞时的降级规则

- 自动分类某些边界不稳：保留规则式分类和低置信 `other`，不要增加未经评测的 LLM 分类调用。
- 前端组件过多导致进度风险：保留组件边界，但优先完成黄金流程；动画和视觉细节降为 P1。
- WebSocket/SSE 复杂：继续使用已冻结 SSE + post-run REST catch-up，不换协议。
- Docker migration 启动失败：修入口和 readiness，不能退回每次 `create_all`。
- 并发幂等未证明：不得标记 Day 2 完成。
- Chrome/Edge 只能验证一个：明确另一个未完成，不虚构结果。
- 队友无法及时 review：可以完成分支和 Draft PR，但 `integration/day2`、main 合并及“Day 2 完成”保持待验收。

### 19. 你的最终交付格式

完成后给用户一个简洁但可核对的中文报告：

1. 结果：完成 / 部分完成 / 阻塞；
2. 自动分类最终数据流，以及为什么不再让用户选 scenario；
3. Day 2 已实现功能和明确未实现的 Day 3 功能；
4. 每个提交 hash + message；
5. 测试命令、退出码、测试数量和关键 task/feedback ID（不含内容）；
6. Docker、restart、Chrome、Edge 证据；
7. PR URL、base/head、review/merge 状态；
8. 已知风险和下一位成员必须做的事；
9. 工作区是否干净。

不要只输出“全部通过”。如果某一项没有真实执行，就写“未验证”。

现在开始：先说明登录依赖，验证 GitHub，读取真实 PR 和仓库，给出不超过 10 步的本次执行计划；然后持续实施、测试、分步提交和汇报。不要一上来改代码。
```

---

## 本 Prompt 的设计结论摘要

- 删除的是“用户对任务类别的配置责任”，不是删除 Task Fingerprint。
- Day 2 负责自动识别任务类别并可靠采集反馈；Day 3 才自动提取偏好、规则、经验和一次性要求。
- `tasks.scenario` 暂时保留为数据库兼容列，但其值只能由服务端分类器产生。
- Day 2 采用可测试的本地规则分类器，避免每次任务多一次不稳定且昂贵的模型调用。
- 当前队友 PR 不能直接合并；交接报告有旧 head，且源码审查发现并发序号、容量 admission、session 切换和 Docker migration 等必须复核的问题。
