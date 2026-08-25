# 发给 zlbk-wxy 的 MemTrace Day 5 成员 A Agent Prompt

> 使用说明：本文和 G4 决策由成员 B 推入 main 后，成员 B 会在交接消息中另行给出 `DAY5_BASE_SHA` 的 40 位完整值。Git commit 不能把自己的最终 SHA 可靠地写进受该 SHA 保护的文件正文，因此本文不伪造自引用值。没有成员 B 给出的完整 SHA，或远端 main 与该 SHA 不一致时，必须停止并核对，不能猜。

你现在是 MemTrace Day 5 的成员 A（GitHub：`zlbk-wxy`）。你只负责 Day 5 的 Memory Center、生命周期/删除、relation/conflict/merge、Memory Pack 后端、迁移、共享后端契约投影和相称测试。成员 B 将在你完整 handoff 后独立下载、测试、修复，并完成前端、fixture/EvalRunner、Docker、双浏览器和最终 main 发布。

## 零、先把本地工作区完整更新为最新 main

**开始阅读或修改任何文件前，必须先取得 GitHub 最新 `origin/main` 的全部内容。** 不得在旧工作区、旧 main、手工复制目录、ZIP 或只拿到若干新文件的状态上继续。你当前本地工作区没有最新内容时，这一步不是可选项。

如果本地没有仓库：

```powershell
git clone https://github.com/W-JOSLIN-X/MemTrace.git MemTrace
Set-Location MemTrace
```

如果已有仓库，先进入仓库根目录。两种情况都先执行：

```powershell
git remote get-url origin
git status --short --branch
```

`origin` 必须指向 `W-JOSLIN-X/MemTrace`。若 status 出现任何已有 tracked/untracked 改动，立即停止并报告；不能覆盖、删除、stash、reset 或把它们混进 Day 5。

工作区干净后：

```powershell
git fetch --prune origin
git switch --detach origin/main

$remoteMain = git rev-parse origin/main
$workspaceHead = git rev-parse HEAD
"origin/main=$remoteMain"
"workspace HEAD=$workspaceHead"

if ($workspaceHead -ne $remoteMain) {
    throw '工作区没有完整检出最新 origin/main，停止执行。'
}

git status --short
git diff --exit-code HEAD --
Test-Path 'AGENTS.md'
Test-Path 'docs/day5/G4_CONTRACT_DECISION.md'
Test-Path 'docs/day5/TEAMMATE_AGENT_PROMPT.md'
Test-Path 'docs/day5/OWNER_AGENT_CONTINUATION_PROMPT.md'
Test-Path 'contracts/day4-g3.json'
```

要求：

- `workspace HEAD` 必须与本次 fetch 后的 `origin/main` 完整 SHA 相等；
- status 无输出，diff 退出码 0；
- 五个 `Test-Path` 全部为 True；
- 任一不成立都停止并回报，不执行会隐式 merge 的普通 `git pull`。

## 一、开始前必须完整读完

按顺序完整阅读，不能只看摘要或关键词：

1. 根目录 `AGENTS.md`
2. `docs/OWNER_LED_COLLABORATION_WORKFLOW.md`
3. `docs/day5/G4_CONTRACT_DECISION.md`
4. `docs/day5/OWNER_AGENT_CONTINUATION_PROMPT.md` 中成员 A 边界与第二阶段验收
5. `Universal_Feedback_Memory_Agent_Project_Plan.md` 的状态机、API/事件、数据库删除矩阵、冲突、Memory Pack、安全、Day 5 和 G4 部分
6. `docs/MEMTRACE_D2_D7_TWO_PERSON_EXECUTION_PLAN.md`
7. `docs/day4/G3_CONTRACT_DECISION.md`
8. `docs/day4/OWNER_INTEGRATION_REPORT.md`
9. `contracts/README.md`、Day 1–Day 4 contract、两个 JSON Schema、examples、实际 OpenAPI
10. `apps/api/src/memtrace_api/` 相关 schemas/models/repositories/main/events/idempotency/retrieval/worker/readiness/config
11. 全部 Alembic revision 与 Day 1–Day 4 contract/migration/owner/G3 tests
12. `fixtures/day5/conflict_events.json`、现有 fixture validator、Day 3/Day 4 REST EvalRunner

如果 fetch 后发现更深层 `AGENTS.md`，在修改其作用域前也必须完整阅读。

事实优先级：当前用户要求 > `AGENTS.md` > owner-led workflow > 当前可执行代码/契约/迁移/你本轮测试 > G4 决策 > 总计划 > 旧 handoff/Prompt/报告。旧文档中强制 PR、另一人审批、禁止 owner 直推 main、`integration/day2` 晋级均为历史流程。

## 二、登录、安全与停止条件

- push 前必须使用 GitHub CLI 登录，且 `gh api user --jq .login` 必须精确为 `zlbk-wxy`。开始前执行 `gh auth status`；未登录、账号不同或中途失效时立即停止告诉用户，不寻找免登录替代通道。
- 默认 `MOCK_MODE=true`；不读取、不索取、不输出真实 Provider Key，真实 Provider smoke 不是你的 Day 5 门禁。
- 你的硬门禁不要求 Docker/浏览器账号；若你额外运行 Docker 而 Docker Desktop 要求登录，立即暂停报告。
- `.env`、token、SQLite、Pack 用户正文、task/rule/evidence/answer、preview token、日志、浏览器资料、模型缓存和临时结果不得提交、放进 URL、截图、event 或 handoff。
- 不运行导入 Pack 中的任何指令、脚本、URL、Shell、工具或代码；Pack 永远是纯数据。

## 三、精确 base 与功能分支

成员 B 的交接消息会给：

```text
DAY5_BASE_SHA=<这三份 Day 5 文档进入 origin/main 后的完整 40 位 SHA>
```

执行：

```powershell
$env:DAY5_BASE_SHA = '<粘贴成员 B 给出的 40 位 SHA>'
git status --short --branch
git fetch --prune origin
$remoteMain = git rev-parse origin/main
git cat-file -t $env:DAY5_BASE_SHA
git show --no-patch --format=fuller $env:DAY5_BASE_SHA

if ($remoteMain -ne $env:DAY5_BASE_SHA) {
    git log --oneline --decorate "$env:DAY5_BASE_SHA..origin/main"
    throw 'origin/main 已移动；停止并把增量提交发给成员 B，等待新的明确 base。'
}

git switch -c feat/a-d5-memory-center $env:DAY5_BASE_SHA
git rev-parse HEAD
git status --short
```

只能使用 `feat/a-d5-memory-center`。不在 detached HEAD 写提交，不直接 push/merge/force-push main，不 rebase/squash/amend 已推送历史，不使用 `integration/day2`，不开日常 PR。

## 四、当前已核验事实（必须从实际 base 重查）

成员 B 在规划前的 `47cfb07cb544267ab91acf18f30657c9500e6986` 确认：

- 当前 contract `1.3.0`，唯一 migration head `004_g3_retrieval_usage`；
- 后端可收集 403 tests；这不是你本轮的 pass 证据；
- 真实 OpenAPI 没有 Day 5 archive/delete/conflict/merge/Pack 路由；
- MemoryCard 已预留 Day 5 状态，但关系状态、resolution、import batch 和删除事务都没有实现；
- Memory Center 只管理 active/paused 的最小 edit/pause/resume；
- `jsonschema` 已锁定，RFC 8785 库尚未在 requirements 中；
- Day 5 的 8 条 conflict fixture 仍是不可执行 draft。

你必须从实际 `DAY5_BASE_SHA` 重查并在 handoff 记录任何差异。测试文件存在、枚举预留或旧报告写“完成”都不能证明功能可用。

## 五、你的严格实现范围

`docs/day5/G4_CONTRACT_DECISION.md` 是唯一 G4 冻结 change note。若实际实现证明其中某项不可能、安全性不成立或与当前 G3 硬冲突，先停止并向成员 B提供具体证据；不能自行改字段后只在 handoff 口头说明。

### A. 契约投影与严格 parser

- 协调 contract 升到 `1.4.0`，保留 G1–G3 全部现有语义。
- 新增 `contracts/day5-g4.json`、`contracts/examples/day5-g4.json`、`contracts/schemas/memory-pack.schema.json`，同步 `contracts/README.md`。
- 同步 Pydantic、ErrorCode、EventType/payload mapping、两个现有 JSON Schema、实际 FastAPI OpenAPI 与 contract tests。
- Pack、relation、conflict、batch、delete response 均严格拒绝 extra/unknown field；`null`、`any`、缺字段含义不能混用。
- 不等待成员 B 的未来前端文件；你提供后端可执行投影和 Schema，成员 B 第二阶段独立核验并完成 TS parser。

### B. 唯一线性 `005_g4_memory_center_pack`

- 从 `004_g3_retrieval_usage` 新增唯一 head `005_g4_memory_center_pack`，不得修改已发布 004 或产生并行 head。
- 增加 task tombstone、card 删除/来源/import 字段、version action、relation status/resolution、import batch 和 owner-first indexes。
- relation 两端、batch/card、merge/conflict 的 owner 必须有 DB 与 repository 双层防护；跨 owner 写入事务回滚。
- 明确所有 FK `ON DELETE`，恢复 G1–G3 原有 unique/index/check，不能因 batch table rebuild 丢掉 idempotency、event seq、usage 或 current-version 不变量。
- fresh upgrade、004→005、downgrade、再升级、stale readiness、唯一 head 都写真实测试；downgrade 对 G4-only row 的处理必须明确而不是留下非法数据。

### C. Memory Center 查询、详情、版本与 usage

- 扩展 list 的 query/kind/status/domain/task_type/source_type/used_after/sort/opaque cursor，先 SQL owner 过滤，稳定分页。
- deleted tombstone 不可从 list/detail/search 猜到；missing/cross-owner 同 404。
- detail/relations/version/usages 都 owner-scoped；version Diff 返回两张完整 immutable projection 与受控 changed_fields，不生成自由文本、不实现 rollback。
- 搜索 NFKC/casefold/whitespace 语义固定，永久删除必须清除任何新增 search projection。

### D. 编辑、pause/resume、archive/restore

- 编辑 active/paused/archived/conflicted 都创建 immutable next version；不原地改历史。
- pause、resume、archive、restore 严格按冻结状态机；restore 到 paused，不直接恢复召回。
- resume 和 conflict winner/merge result 统一走 Admission Guard。
- 每个 write 在同一 `BEGIN IMMEDIATE` 事务写 card/version/idempotency/metadata event；stale version、竞争写、同 key 异请求和状态冲突有真实测试。

### E. 单卡永久删除与来源 task 删除矩阵

- 单卡任意非 deleted 状态可永久删除；confirm_title/expected version 二次检查。
- 同事务删除版本、relation、decision/usage/verifier、embedding（若存在）、evidence link/orphan evidence、正文 idempotency snapshot/import 引用，并留下无正文 tombstone event。
- 验证数据库层不存在 rule/title/scope/evidence excerpt/version/usage/preview token 残留，不能只证明 API 404。
- `DELETE /tasks/{id}` 保留无正文 task/run metadata tombstone，删除 fingerprint/message/tool/feedback/job/evidence/trace/usage/verifier，保留 card 并准确设置 evidence_missing/evidence_count。
- 清理受影响 idempotency snapshot；task 删除不级联永久删除 card。
- 事务中任一步注入失败时全部回滚；删除后 event/log 仍 metadata-only。

### F. relation、人工 conflict、四种 resolve 和 merge

- 实现 relation 投影、分页与 same-owner invariants；扩展 `reinforces|merged_into` 和 status/resolution 字段。
- `POST /memory-conflicts` 只做用户显式人工标记，不把未经评测的文本分类冒充可靠自动冲突检测。
- 实现 `prefer|separate_scopes|merge|pause_both` 四种固定 action；两端版本、关系、状态和新卡必须同事务。
- prefer 写 supersedes；scope resolve 写两条 immutable versions并验证不再重叠；merge 创建新 active v1 并把旧卡置 merged；pause_both 保留版本。
- 独立 `/memories/merge` 处理非冲突的人工合并；不调用模型自动写 merged rule。
- unresolved conflict 必须继续阻断 G3 retrieval；resolved 后按最终状态决定是否召回。

### G. RFC 8785 匿名 Pack export

- 实现单 UTF-8 `.mempack.json`，严格使用 frozen V1 Schema。
- hash 覆盖除 integrity 自身外的完整 payload；文件输出也 canonical；普通 sort_keys 不能伪装 RFC 8785。
- 若引入 `rfc8785`，固定版本、更新 requirements.in/lock/hash 并验证 Docker-compatible install；不要加 ZIP、签名、脚本、Skills 或执行能力。
- 默认匿名不可关闭；不得导出 owner、task/run/evidence ID、聊天、路径、历史正文、usage/counter、embedding、Provider/system prompt。
- 只读 export 不把正文复制到日志/event/idempotency snapshot。

### H. 两阶段 import preview/commit

- preview 必须先读 raw bytes，按 size→UTF-8/duplicate-key/depth→format/version→Schema→integrity→safety→owner analysis 顺序。
- 文件级错误不创建 batch/card；合法后才创建 30 分钟 quarantined batch。
- 每卡只可为 legal_new/duplicate/potential_conflict/suspicious；duplicate/conflict/suspicious 全部 skip/manual，不能自动 merge 或写 card。
- potential_conflict 使用冻结的保守 exact-scope/TF-IDF 规则，UI/响应不能写成“已确定矛盾”。
- preview token 绑定 owner/batch/hash/expiry，只能在 body/response，数据库存 hash，日志/event/URL 不出现；幂等 replay 要能返回同一语义。
- commit 只能 `import_all_paused`，从暂存 payload 重做 canonical/hash/schema/safety/duplicate/conflict，并在单一事务插入仍合法子集；任何写失败整批回滚。
- 导入本地 version 固定 1/action import/source import/trust 0.50/status paused；外部 claimed origin/version 不能伪装本地 user_confirmed/version。
- commit/expire 后清除 canonical payload/preview 正文/token material；进程重启后未过期 preview 能恢复，SESSION_SECRET 变化时明确要求重新 preview。

### I. event、幂等、恢复和隐私

- 新事件严格按 G4 决策，event mapping/Schema/docs/producer 一次同步。
- memory/import stream 独立连续 seq，不混进 task Last-Event-ID；所有事件 metadata-only。
- write 的 idempotency response 不能成为永久删除或 Pack commit 后的正文副本。
- owner 隔离覆盖 memory/task/relation/conflict/batch/export/preview/commit/event；cross-owner 与不存在同 404。
- Mock 模式全功能可测；无真实 Provider/账号也能完成 G4 后端。

### J. Day 5 draft fixture review

- 不把 `fixtures/day5/conflict_events.json` 改成 approved/gold/executable。
- 新建 `docs/day5/CONFLICT_FIXTURE_REVIEW.md`，逐条对 d5-c01…c08 写 `keep|revise|insufficient`、理由、如何映射到结构化 memory/scope/version/relation/action。
- 明确 c02“compatible”不是 conflict action、c03/c04 是 scope/refinement 而非自动矛盾、c05 reinforce/merge evidence 与内容 merge 的区别、c08 controlled exception 的结构化输入。
- 同时审查 G4 决策列出的 12 类 security case，handoff 提交你的预期/异议；成员 B 最终形成 executable fixture 和 manifest。

## 六、必须覆盖的真实测试

至少覆盖：

1. list 全 filter/sort/cursor、Unicode query、稳定分页、cursor/filter 不匹配；
2. detail/version/Diff/relation/usage owner isolation 与 deleted invisibility；
3. edit immutable version、pause/resume、archive/restore、Admission Guard、竞争和幂等；
4. candidate/active/paused/conflicted/rejected/superseded/merged/archived/deleted 的合法/非法转换；
5. 四类 conflict resolve、manual merge、supersede、scope overlap、同 owner DB constraint、部分失败回滚；
6. unresolved conflict 不召回、prefer/separate/merge 之后按状态恢复，G3 score/trace/receipt 不回退；
7. single-card permanent delete 对每张关联表和 idempotency正文的数据库断言；任一步失败全回滚；
8. source task delete 对 task/run/message/tool/feedback/job/evidence/trace/usage/event/card evidence_missing 的完整矩阵；
9. RFC 8785 Unicode/排序/完整 payload hash/round-trip，hash mismatch、重复 key、NaN/Infinity；
10. 1 MB 边界、1,048,577 bytes、200/201 cards、depth/node/string、unknown capability field、dangling relation、XSS纯文本；
11. preview 零 card 写入、四类 item、owner-scoped duplicate/potential conflict、token tamper/expiry/restart/idempotency；
12. commit 二次校验、TOCTOU duplicate/conflict、全部 paused、relation remap、单事务回滚、commit replay；
13. Pack/card/rule/token 不进 logs/events/URL/idempotency snapshot；
14. cross-owner memory/relation/conflict/batch/export/import/event 全 404/零泄露；
15. fresh/004→005/downgrade/re-upgrade/readiness/constraint/index/foreign_keys=ON；
16. Pydantic、JSON Schema、OpenAPI、examples、events 精确同构；实际 OpenAPI 二次导出零 diff；
17. G1+G2+G3 完整 pytest 不回退，不能用只测纯函数或 `pass` 测试替代 API/DB 证据。

## 七、执行、提交与分支内门禁

先记录失败基线，再按单目标提交。建议边界：

```text
chore(contract): define G4 memory center and pack projections
feat(memory): add lifecycle deletion and relation transactions
feat(memory): add conflict resolution and manual merge
feat(pack): add canonical export and quarantined import
test(day5): cover G4 migration isolation rollback and privacy
docs(day5): record fixture review and member A handoff
```

至少执行并记录真实退出码、测试文件数和测试数：

```powershell
& 'apps/api/.venv/Scripts/python.exe' -m pip check
& 'apps/api/.venv/Scripts/python.exe' -m ruff check apps/api
& 'apps/api/.venv/Scripts/python.exe' -m ruff format --check apps/api
& 'apps/api/.venv/Scripts/python.exe' -m pytest apps/api/tests -q
& 'apps/api/.venv/Scripts/python.exe' -m alembic -c apps/api/alembic.ini heads
& 'apps/api/.venv/Scripts/python.exe' scripts/day1/validate_fixtures.py
git diff --check
git status --short
```

另外真实执行 fresh DB/upgrade/downgrade/re-upgrade、OpenAPI 两次导出零 diff、metadata-only log test 和 secret/产物检查。若碰共享 web/TS 文件，还要在 `apps/web` 跑 typecheck/lint/test/build；通常不要实现成员 B 的前端。

完成后只普通 push：

```powershell
git push -u origin feat/a-d5-memory-center
```

不开 PR、不推 main。交接后停止改变 head；成员 B 要求追加时才新 commit，绝不 amend/rebase 已交接提交。

## 八、handoff 必须一次给全且数字真实

新建 `docs/day5/MEMBER_A_HANDOFF.md`，并在消息中同时提供：

- 分支 `feat/a-d5-memory-center`；
- 实际 `base SHA`、`head SHA`、`merge-base`，全部 40 位；
- `git log --oneline BASE..HEAD` 和实际变更文件；
- contract/API/event/schema/requirements/迁移变化及兼容影响；
- 每条命令、退出码、测试文件数、测试数和耗时；
- fresh/upgrade/downgrade/restart/rollback/concurrency/cross-owner/privacy 的实际证据；
- conflict/security fixture 逐条 review 与未决异议；
- 已知失败、未实现项、降级、真实 Provider 未测项；
- secret/SQLite/正文日志/Pack/token/临时产物检查；
- 所需登录；
- 明确“未做前端、Docker、Chrome/Edge、最终整合/main push，由成员 B 第二阶段完成”。

push 后再次读取远端 head：

```powershell
git fetch --prune origin
git rev-parse origin/feat/a-d5-memory-center
git rev-parse HEAD
git status --short
```

远端 head 与本地不相等、工作区不干净或测试有失败时必须如实报告。禁止像旧 Day 4 handoff 那样填写不存在的示例 SHA、把 Ruff 失败说成 main 既有问题，或用“测试文件存在”写成“功能完成”。

## 九、完成定义与停止边界

你的完成终点只是：精确 base 上的功能分支已普通 push、远端 head 可核对、handoff 完整。你不能报告 Day 5 已进入 main，也不能要求成员 B开 PR或等待你审批。

不要实现成员 B 的完整 UI、静态结果页、最终 dataset manifest、REST EvalRunner、Docker/双浏览器证据或发布报告；不要提前做 Day 6 动态评测、阈值调参、四基线服务或 Day 7 发布能力。
