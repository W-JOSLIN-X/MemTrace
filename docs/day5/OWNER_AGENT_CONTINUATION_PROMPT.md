# MemTrace Day 5 成员 B 第二阶段接管、G4 收口与直接发布计划

本文供仓库所有者 `W-JOSLIN-X`（成员 B）在成员 A `zlbk-wxy` 完整 push `feat/a-d5-memory-center` 并带回 handoff 后执行。当前阶段只冻结计划，不提前假装已取得协作者分支、完成测试或发布 Day 5。

## 1. 不可改变的执行规则

- 事实优先级：用户最新要求 > `AGENTS.md` > owner-led workflow > 远端 Git 对象/实际代码/契约/迁移/本轮测试 > G4 决策 > 总计划 > handoff/旧报告。
- 成员 A 只交付功能分支；成员 B 是唯一日常集成者和 main 发布者。
- 不开日常 PR，不要求 A 审批，不使用 `integration/day2`，不 rebase/squash/amend A 的已交接历史。
- 只普通 `git push origin HEAD:main`；永远不 force/force-with-lease，不绕过远端竞态或失败门禁。
- 默认 `MOCK_MODE=true`。Day 5 不需要 Provider 登录或真实 Key。
- 第二阶段开始会用 GitHub CLI，必须登录 `W-JOSLIN-X`；Docker 门禁前需要本机 Docker Desktop daemon。如果 Docker Desktop 或 GitHub要求登录，立即暂停并告诉用户，不改找免登录通道。Chrome/Edge 本地测试不要求浏览器账号。

## 2. 接管前的只读核验

收到 handoff 后先记录 A 声明的 branch/base/head，但一律以远端对象为准：

```powershell
git status --short --branch
git remote -v
gh auth status
gh api user --jq .login
git fetch --prune origin
git rev-parse origin/main
git rev-parse origin/feat/a-d5-memory-center
git merge-base origin/main origin/feat/a-d5-memory-center
git log --oneline --decorate origin/main..origin/feat/a-d5-memory-center
git diff --stat origin/main...origin/feat/a-d5-memory-center
```

必须处理以下分支条件：

- 工作区有用户改动：停止写操作，先保护并隔离，不能 reset/stash/覆盖。
- A 的远端 head 与 handoff 不同：审查 handoff head..remote head 的每个追加提交并记录；不能默默接受。
- A 的 base/head 或 commit 列表是示例/虚假 SHA：像 Day 4 一样在 owner report 保留原声明并写核验更正，不能用 handoff 数字当证据。
- `origin/main` 已移动：审查 planning base..最新 main；第二阶段从接管时精确最新 main 建分支，并重新核对 G4 契约兼容性。
- GitHub 登录不是 `W-JOSLIN-X`：立即暂停。

审计 `base..head`：提交作者、全部文件、contract/OpenAPI/schema、005 migration、requirements lock、测试真实性、fixture 状态、正文日志、`.env`/token/SQLite/Pack/preview token、浏览器或 IDE 权限产物。任何 `.claude/settings.json`、个人工具授权、数据库、output 或临时包都不是产品改动，应由 owner 在整合提交中移除，但不改写 A 历史。

## 3. 保留成员 A 历史的 owner integration

把本轮实际 SHA 写入 shell 变量，不使用本文示例值：

```powershell
$env:DAY5_MAIN_BASE = git rev-parse origin/main
$env:DAY5_A_HEAD = git rev-parse origin/feat/a-d5-memory-center
git switch -c codex/day5-owner-integration $env:DAY5_MAIN_BASE
git merge --no-ff $env:DAY5_A_HEAD
```

若冲突，逐文件依据 G4 contract 和当前 G3 代码解决；不能选择整个 ours/theirs 掩盖语义。合并后验证：

```powershell
git merge-base --is-ancestor $env:DAY5_MAIN_BASE HEAD
git merge-base --is-ancestor $env:DAY5_A_HEAD HEAD
git log --graph --oneline --decorate -30
git status --short
```

merge commit、A 的作者和全部提交必须保留；不在 A 分支继续写 owner commit。

## 4. 先保存 A 的失败基线，再修复

先创建 `docs/day5/OWNER_INTEGRATION_REPORT.md`，记录：

- 实际 main base、A remote head、merge-base、A handoff 声明与实际差异；
- A 的 commit/file/schema/migration/lock 范围；
- A 声明的命令/数量只是 handoff 声明；
- owner 在未修改代码的 merge head 上实际运行的命令、退出码、文件数、测试数；
- OpenAPI 是否真有全部 G4 route；
- Pack preview 是否经过真实 HTTP、DB 是否零写/单事务；
- 删除是否只测 404 还是实际查了所有正文残留；
- relation same-owner DB constraint、migration downgrade、event/idempotency/privacy 是否真实成立。

原始失败一旦记录只能追加修复后结果，不删除或改写成“起初即通过”。

### 4.1 未改代码的独立复测

至少先跑：

```powershell
& 'apps/api/.venv/Scripts/python.exe' -m pip check
& 'apps/api/.venv/Scripts/python.exe' -m ruff check apps/api
& 'apps/api/.venv/Scripts/python.exe' -m ruff format --check apps/api
& 'apps/api/.venv/Scripts/python.exe' -m pytest apps/api/tests -q
& 'apps/api/.venv/Scripts/python.exe' -m alembic -c apps/api/alembic.ini heads
& 'apps/api/.venv/Scripts/python.exe' scripts/day1/validate_fixtures.py
git diff --check
```

再越过纯函数/manifest 测试，通过真实 TestClient/lifespan/SQLite 检查 list/filter、conflict/merge、Pack raw bytes、task/memory delete、owner 隔离、rollback、event seq 和进程恢复。空 `pass`、只 assert route 存在、直接调用内部函数或伪造 SQL row 都不算 G4 黄金路径。

### 4.2 P0 修复优先级

按以下顺序收口 A 的问题：

1. `1.4.0` Pydantic/JSON Schema/Memory Pack Schema/OpenAPI/examples/events/ErrorCode 同构；
2. 005 唯一线性迁移、fresh/004/downgrade/re-upgrade、owner composite constraint 与 G1–G3 index/check 不回退；
3. permanent memory delete、source task delete、idempotency/import正文清除和事务回滚；
4. archive/restore、immutable edit/Diff、conflict 四 action、merge/supersede 的状态与版本原子性；
5. RFC 8785 完整 payload hash、duplicate-key/size/depth/capability 安全门禁；
6. preview token、30 分钟 batch、commit 二次校验、TOCTOU、paused import、restart recovery；
7. metadata-only events/logs、owner isolation、严格 parser 和受控错误。

契约发现必须修改时，先在 `G4_CONTRACT_DECISION.md` 追加 change note，再同步全部投影和测试；不能只让前后端“暂时兼容”。

## 5. 成员 B 的 Day 5 前端与产品任务

### 5.1 TypeScript 契约、API 与状态隔离

- 完成 G4 ID/enum/request/response 类型和严格 runtime parser；拒绝 unknown field、非法 ID、非法 action、错误 nullable 和 Pack extra field。
- API client 接入全部 G4 routes，始终携带 cookie；edit/pause/resume/archive/restore/delete/conflict/merge/preview/commit/task-delete 各有独立幂等 key。
- 网络错误重试复用原 key；操作成功、用户修改请求或明确取消后才清 key。
- opaque preview token 只保存在当前 owner/batch 的内存状态和 commit body，不进 URL、localStorage、console、错误文本或截图。
- task/owner/session 切换、页面卸载时 abort 所有 list/detail/preview/commit 请求，清除 card detail、Diff、Pack 文本、draft、relation、token 和 pending keys；旧请求晚到不得写回新用户 UI。
- 恢复以 REST snapshot 为真：list/detail/versions/usages/relations/conflicts/import batch；不能依赖旧 React 状态或把 task SSE seq 用于 memory/import。

### 5.2 Memory Center 概览和搜索

- 替换 Day 4 最小页，提供 query、kind/status/domain/task_type/source_type、used_after、sort 和 cursor 分页。
- 显示 active/candidate/conflicted/paused/superseded/merged/archived/rejected 的准确文案；deleted 不显示。
- 可按 domain/project/source task 形成只读“任务集合”分组，但不引入新后端聚类或伪造关系。
- loading/empty/error/partial-page 状态明确；筛选改变时取消旧请求并重置 cursor。

### 5.3 卡片详情、编辑、状态和删除

- 详情显示 rule/scope/avoid/trigger/source/evidence_missing/effect counters/current version/relations，不把 imported 写成 user_confirmed。
- edit 支持受控字段，成功显示新 immutable version；409 stale 提示刷新，失败保留草稿。
- pause/resume/archive/restore 文案明确：restore 只回 paused，不会立即召回。
- permanent delete 使用独立危险确认：用户必须输入当前 title；显示将删除版本、usage、relation、evidence link且不可恢复。
- task 页/usage 跳转提供独立“删除来源任务及对话”确认，body 使用 task ID；说明卡片保留但证据缺失。两种删除不能合并成一个模糊按钮。

### 5.4 版本时间线、Diff 与 usages

- 版本按不可变顺序显示 created_by_action、时间和 current 标记；并排/逐字段展示服务端 `changed_fields`。
- 不提供 rollback 按钮，也不把选择历史版本改成 current。
- usages 显示 task/run、retrieved/selected/injected、verification/user effect、版本 ID并可跳转仍存在的 task；已删除 task 显示“来源已删除”，不构造失效正文。

### 5.5 Conflict 与 merge UI

- conflict overview 分 unresolved/resolved，显示两张 owner card 的完整当前版本、scope、来源和 relation，不显示自动“建议答案”。
- 四种固定操作：采用一方、分别设置不重叠 scope、人工编写 merged card、两者暂停。
- prefer 明确 winner/loser；scope action 在前端预校验但以后端 422/409 为真；merge 由用户编辑完整 rule，不调用模型自动写。
- 独立 manual merge 可选择两张同 owner card并预览结果；失败保留 merged draft。
- 成功后刷新两张旧 card、新 card、relation 和 list，不靠乐观 UI 把未提交状态写成 active/merged。

### 5.6 Memory Pack 导出、完整 preview 与 commit

- export 允许选择可导出 card、包名和描述；默认匿名不可关闭，下载名安全且扩展名固定 `.mempack.json`。
- 导入在浏览器先检查扩展名/大小以提供快速提示，但最终只信服务端 raw-bytes/schema/integrity 结果。
- preview 显示 pack 名/format/source/unverified、完整 rule/scope/avoid，以及 legal-new/duplicate/potential-conflict/suspicious 的数量、受控 reason 和实际 action。
- 文案必须写“潜在冲突、需人工检查”，不能写“系统已确认矛盾”；P0 只能确认“导入全部合法新增项为 paused”。
- Pack/HTML 全部 React 纯文本渲染，禁止 `dangerouslySetInnerHTML`；`<script>` fixture 不执行。
- token expired/tampered、batch committed、网络重试、commit rollback 都有可恢复 UI；commit 后清 Pack正文/token并跳到 imported paused cards。

### 5.7 只读结果页壳和产品标识

- 将 Evals 页从“Day 6 将实现”占位改为 Day 5 只读壳，只显示冻结 manifest 版本/hash/split/fixture review status和“实际指标尚未运行=N/A”。
- 不建立 POST eval-runs、实时进度、动态图或伪造分数；Day 6 才消费真实 CSV/JSON。
- 更新 AppShell、README、API README、Compose image tag 为 Day 5/G4；默认 Mock 标识继续显眼。

## 6. Fixture、manifest、validator 与 REST EvalRunner

### 6.1 保留历史、形成可执行 G4 fixture

- 保留 `fixtures/day5/conflict_events.json` 原始 draft 和状态，不覆盖成 gold。
- 新建 `docs/day5/CONFLICT_FIXTURE_REVIEW.md`，保留 A 原 review并追加 owner 独立核验/修正。
- 新建结构化 `fixtures/day5/g4_conflict_cases.json`，8 cases 全部经公开 API 建卡、标 conflict、resolve 并验证状态/version/relation/retrieval；review status 只能按真实审查写，不自动声称双人批准。
- 新建 `fixtures/day5/g4_pack_security_cases.json`，冻结 G4 决策列出的 12 cases；覆盖非法文件零 batch/card、合法但 suspicious/manual skip、XSS纯文本、cross-owner、token/rollback。

### 6.2 24/60/12/8 manifest

新建 `fixtures/day5/g4_dataset_manifest.json`，精确引用：

- 24：`fixtures/day2/g1_classification_feedback_matrix.json`
- 60：`fixtures/day3/learning_events.json` 30 + `fixtures/day4/g3_retrieval_cases.json` 30
- 12：Day 5 Pack/security fixture
- 8：`fixtures/day1/demo_core.json`

每个 source 记录完整 SHA-256、case IDs、review status 原值、固定 train/validation/test assignment和生成算法版本。split 严格使用 G4 决策的 `g4_split_v1` hash 排序：24→14/5/5、60→36/12/12、12→6/3/3、8→4/2/2。Day 5 conflict 8-case 作为额外 G4 suite，不冒充 demo_core 8-case。manifest hash 覆盖 canonical manifest payload；一旦最终冻结，Day 6 不移动 case 以迎合 test 结果。

若 A 没有逐条审查某个 source，状态必须明确 `member_b_frozen` 或 `a_review_incomplete`，不能写 joint approved。存在分歧时在 `docs/day5/DATASET_ADJUDICATION.md` 列双方判断和 owner 最终冻结理由。

### 6.3 validator 与 REST-only runner

- 扩展 `scripts/day1/validate_fixtures.py`：Schema、exact count、唯一 ID、受控 enum、manifest source/hash/split 完整性、draft 不冒充 executable。
- 新建 `scripts/day5/eval_runner.py`，只通过公开 Session/G1/G2/G3/G4 HTTP API 建数据和验收；不得 import `memtrace_api` 内部模块或直接写 DB。
- runner 覆盖 list/filter/edit/Diff、archive/restore、四 conflict action、merge、export/preview/commit、invalid zero-write、paused import、memory/task delete、cross-owner和 restart 前后 GET 恢复。
- 输出只含 case ID、资源 ID、状态/action、受控 reason/error、count、hash、latency 和 pass/fail；不保存 task/rule/Pack card/evidence/answer/token/secret 正文。任一 case 失败退出非零。
- 继续运行 Day 3、Day 4 REST runner，确保 G2/G3 不回退。

## 7. 本地自动化、契约和迁移门禁

最终候选执行并记录命令、退出码、测试文件数、测试数、耗时：

```powershell
& 'apps/api/.venv/Scripts/python.exe' -m pip check
& 'apps/api/.venv/Scripts/python.exe' -m ruff check apps/api
& 'apps/api/.venv/Scripts/python.exe' -m ruff format --check apps/api
& 'apps/api/.venv/Scripts/python.exe' -m pytest apps/api/tests -q
& 'apps/api/.venv/Scripts/python.exe' -m alembic -c apps/api/alembic.ini heads
& 'apps/api/.venv/Scripts/python.exe' scripts/day1/validate_fixtures.py
```

在 `apps/web`：

```powershell
npm run typecheck
npm run lint
npm test
npm run build
```

另外必须实际完成：

- 导出真实 FastAPI OpenAPI，第二次导出零 diff；
- Pydantic/两个 JSON Schema/Pack Schema/OpenAPI/examples/TS parser 同构和 unknown-field negative tests；
- requirements.in/lock 可解释，Docker `--require-hashes --no-deps` 安装成功；
- fresh 005、现有 004→005、005→004、再升级；stale revision ready 503，唯一 head ready；
- DB foreign_keys=ON、same-owner relation/batch constraint、status/version/tombstone checks；
- concurrency、Idempotency-Key 同/异请求、transaction failure injection、event seq、restart、cross-owner；
- permanent delete 后用数据库只查 metadata，确认各正文表/idempotency/import staging 无残留；
- log capture 只输出 metadata，synthetic canary 未出现；
- `git diff --check`、secret scan、tracked/untracked artifact scan。

前端新增真实测试至少覆盖：strict G4 parser；filter/cursor cancellation；edit draft/stale；archive/restore；delete 两种确认；version Diff；四 conflict action；merge draft；export download；preview 四分类；token retry/clear；XSS纯文本；owner/session 切换清理；只读 Evals N/A。不能把既有 G3 测试数量当 G4 证据。

## 8. G1 → G4 递增黄金路径

### G1

- 服务端自动分类，旧 `scenario` 请求 422；
- task/feedback 幂等、session/owner 隔离、task event seq、刷新恢复。

### G2

- feedback → worker → candidate/evidence → accept/edit_accept/reject/episode_only；
- candidate 不冒充 active，one-shot 不建长期版本；
- Day 3 REST Eval 全绿。

### G3

- active v1 → 相似任务同 owner selected/injected → provider memory context → receipt/verifier；
- 近似/完全负例、override、memory off、pause/resume、100/300 token、restart、cross-owner；
- Day 4 30-case REST Eval 全绿。

### G4

1. 至少 20 张多状态 synthetic cards可搜索/筛选/分页；
2. edit 产生 v2，版本 Diff 正确，旧 v1 不变；
3. pause 不召回、resume 恢复；archive 不召回、restore 后仍 paused；
4. unresolved conflict 两端不召回；prefer/separate_scopes/merge/pause_both 四 action 各真实通过；
5. manual merge 创建新 active v1，旧两卡 merged；
6. export 默认匿名、完整 payload hash 正确；blank_demo export 在 seeded_demo 不可见；
7. valid Pack preview 不写 card，commit 后 legal-new 全 paused且 relation remap正确；
8. duplicate/potential conflict/suspicious 不写 card、不静默覆盖；
9. 12 类恶意/超限/损坏 Pack 按冻结语义拒绝或 skip，任何失败无半批写入；
10. permanent memory delete 后正文/version/usage/relation/evidence/idempotency残留为零；
11. source task delete 后 task正文链净化，card 保留且 evidence_missing；
12. task/memory/relation/conflict/batch/event/export 在两 demo owner 间统一不可见；
13. 页面刷新、API 进程重启、容器 restart/down-up 后 card/version/relation/import status/tombstone可恢复；
14. Day 5 conflict/security 和 REST Eval 全绿，旧 G1–G3 均不回退。

任一层失败，不能用更高层截图掩盖，修复后从受影响的最低层重跑。

## 9. Docker G4 门禁

先启动 Docker Desktop，执行 `docker version` 确认 client/server 都可用；若 Desktop 要求账号登录，立即暂停告诉用户。

使用专属项目，绝不碰用户其他容器/卷：

- project：`memtrace-d5-g4-gate`
- port：`18050`
- image：`memtrace:day5-g4`
- `MOCK_MODE=true`
- `SESSION_SECRET` 在当前 PowerShell 进程随机生成，不写 `.env`、不回显、不提交。

示例环境设置（不要打印 secret）：

```powershell
$env:COMPOSE_PROJECT_NAME = 'memtrace-d5-g4-gate'
$env:MEMTRACE_PORT = '18050'
$env:MOCK_MODE = 'true'
$bytes = New-Object byte[] 48
[System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
$env:SESSION_SECRET = [Convert]::ToBase64String($bytes)
docker compose up --build -d
```

门禁：

- cold start 自动迁移唯一 005，health/ready/container health/provider_mode=mock；
- 在容器真实 API 上重跑 G1/G2/G3/G4 与 Day 3/4/5 REST Eval；
- preview 后 `docker compose restart app`，确认 batch仍可 GET/commit；
- 创建 card/version/relation/import/tombstone 后 restart，确认恢复；
- `docker compose down`（不加 `-v`）后再 up，确认专属卷持久化；
- 扫描 logs，synthetic task/rule/Pack/token/secret canary 命中数必须 0，只记录 metadata scan result；
- 双浏览器结束后回读 Compose project label、volume label/前缀，确认全都属于 `memtrace-d5-g4-gate`，才执行该项目的 `down -v`；不枚举后跨 shell 删除，不触碰其他卷。

## 10. Chrome 与 Edge 双浏览器

使用 Playwright CLI，实际指定本机 Google Chrome 和 Microsoft Edge executable/channel，两个独立 browser profile/session；URL `http://127.0.0.1:18050/`。浏览器资料、trace、截图只放忽略目录：

- `output/playwright/day5/chrome`
- `output/playwright/day5/edge`

两者都完成核心链路：demo 用户切换、G2 建卡确认、G3召回 receipt、Memory Center filter/detail/edit/Diff、pause/resume/archive/restore、Pack export/preview/commit、刷新恢复、cross-owner UI 清空与服务端 404、permanent delete 或 source task delete之一。

扩展 action 分配：

- Chrome：blank_demo 主用户、seeded_demo 隔离；覆盖 conflict `prefer` 和 `separate_scopes`、single memory permanent delete。
- Edge：seeded_demo 主用户、blank_demo 隔离；覆盖 conflict `merge` 和 `pause_both`、source task delete。
- 两者都验证 imported card 是 paused，duplicate/potential conflict 不静默写入，`<script>` Pack 文本不执行。

分别记录浏览器名称/版本/user agent、console error、network failure、预期 owner 404、关键截图和 Playwright trace。只用 synthetic 正文；截图不得含 secret/token/真实用户材料。任何非预期 console error、5xx、卡死、旧 owner UI 泄漏都阻断发布。

## 11. 提交边界、报告与最终 direct push

建议提交：

1. merge commit：完整引入 A remote head；
2. `fix(day5)`：contract/migration/delete/conflict/Pack P0；
3. `test(day5)`：API/DB/rollback/isolation/migration regressions；
4. `feat(web)`：Memory Center/conflict/Pack/Evals shell；
5. `test(eval)`：8 conflict、12 security、manifest、validator、REST runner；
6. `docs(day5)`：handoff核验更正、adjudication、README、owner report。

最终 report 写真实 base/A head/merge commit/fix commits、所有命令和数量、migration/contract证据、Docker project/恢复边界、Chrome/Edge版本与证据目录、失败基线、限制、最后已验证 SHA。真实 Provider、BGE、自动 conflict 文案、rollback、逐卡 import、Day 6动态 eval 都明确为非范围/未验证。

报告提交后：

1. 重新运行完整本地后端/前端/fixture/Eval 自动化、OpenAPI zero-diff、`git diff --check`、secret/artifact scan；
2. 验证 A handoff head 是当前 HEAD 祖先；
3. 确认工作区干净，无 `.env`、SQLite、Pack下载、token、output/profile、volume内容或正文日志；
4. 再次 `git fetch --prune origin`；
5. 若 `origin/main` 不等于 `$env:DAY5_MAIN_BASE`，禁止直接 push：普通 `--no-ff` merge 新 main，审查冲突并重跑所有受影响门禁；
6. 只有当前 GitHub登录仍为 `W-JOSLIN-X` 才执行：

```powershell
git push origin HEAD:main
```

7. 不使用 force，不创建日常 PR，不要求 `zlbk-wxy` 审批，不删除 A 远端分支；
8. push 后读取远端 `refs/heads/main`，确认完整 SHA 等于本地已验证 head，再检查工作区；
9. 只有远端 SHA 相等且 G1–G4、Docker、Chrome、Edge、隔离、隐私和普通 push 都有本轮实际证据，才报告“Day 5 完成”。

任何登录、网络、远端竞态、自动化、Docker、浏览器、隐私或 push 失败都停止发布并报告具体阻断，不能把“本地代码完成”写成“Day 5 已完成”。
