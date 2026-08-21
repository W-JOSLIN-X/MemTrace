# MemTrace Day 2：项目负责人接手、联调、合并与提交计划

本计划从第二成员提交 `feat/day2-backend-feedback` Draft PR 后开始。目标是你接手后完成
前端反馈体验、全链路 G1 验收，并通过受保护的 PR 把 Day 2 合入 `main`。为保持
`integration/day2` 始终接近可运行版本，你先从对方 PR head 继续开发，晚间才依次合并
后端和前端 PR。

## 1. 已固定的分支关系

```text
main                       # 只保存每日验收版本，当前为 Day 1
└── integration/day2       # 已创建，起点 0468904
    ├── feat/day2-backend-feedback   # 第二成员
    └── feat/day2-frontend-integration # 你
```

`main` 和 `integration/day2` 均已启用：

- 必须通过 PR；
- 至少 1 人批准；
- 新提交会使旧批准失效；
- 必须解决全部 review conversation；
- 禁止 force push；
- 禁止删除；
- 管理员同样不能绕过。

因此任何人都不得直接 push 这两个分支；只能 push 自己的 `feat/*` 分支并走 PR。后端
PR 由项目负责人批准，前端 PR 和最终 main PR 由第二成员批准，确保每次最后 push 后都
有另一人检查。

仓库只允许 merge commit，保留逐步提交。

交接前由你确认第二成员已经通过 GitHub 邀请并具有 Write 权限，但不要共享你的 GitHub
Token。要求对方在三个同步点留下可追溯记录：基线完成、G1 contract 冻结、最终 Draft
PR。除 P0 阻断外，开发中间不要通过聊天临时改字段；契约变化必须落在 PR commit 和
OpenAPI/Schema 中。

## 2. 你接手后的第一阶段：审核后端 PR

### 2.1 不要先合并

先执行：

```powershell
git switch main
git pull --ff-only origin main
git fetch origin --prune
gh pr list --base integration/day2 --state open
```

确认 PR：

- base=`integration/day2`
- head=`feat/day2-backend-feedback`
- 没有指向 main；
- 分支起点来自 `0468904`；
- 没有 merge commit 把无关分支带入；
- `.env`、SQLite、虚拟环境、node_modules 未进入 PR。

### 2.2 按提交顺序审核

依次审查：

1. Contract commit；
2. dependencies/lock；
3. migration/models；
4. session/owner；
5. G0 persistence；
6. feedback/idempotency；
7. tests/docs。

任何 API 含义问题先在 PR 中指出，不要合并后口头修改。

重点检查：

- rating 是否严格 1–5；
- edited_output 是否与 original message 分离；
- owner_id 是否只来自 Cookie UserContext；
- Repository SQL 是否每次带 owner；
- event_log 是否只存 metadata；
- feedback/job/event/idempotency 是否同事务；
- 重复 key 是否返回同一 IDs；
- migration 是否完全替代 create_all；
- Session 是否跨 await 泄漏；
- 日志是否可能输出代码、反馈、SQL、路径或 Secret。

### 2.3 在本机独立复跑

不要只看对方报告：

```powershell
git switch --detach origin/feat/day2-backend-feedback

python -m venv apps/api/.venv
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

再用全新临时 DB 验证 migration、session A/B、反馈幂等、restart restore。不要删除已有
`data/` 数据库来伪装干净环境。

若通过，在 GitHub PR 正式 review；若有 P0/P1，要求第二成员在原分支追加 fix commit，
不要由你直接在他的分支重写历史。

### 2.4 从已验证的后端 head 创建你的分支

确认后端 P0/P1 已解决、测试通过后，先把 Draft PR 标记 ready，但暂不合并：

```powershell
gh pr ready <后端PR编号>
git fetch origin --prune
git switch -c feat/day2-frontend-integration origin/feat/day2-backend-feedback
git push -u origin feat/day2-frontend-integration
```

原因：此时后端已经强制 Demo Session，而旧前端尚不会创建 Session。若现在单独合到
`integration/day2`，集成分支的浏览器黄金流程会暂时失效。你从已验证的 backend head
继续开发，既能使用真实契约，也不污染集成分支。

若第二成员随后给后端 PR 追加 fix commit，不要 reset 或 rebase 你的工作。先 review 新
commit，再在你的分支执行：

```powershell
git fetch origin
git merge --no-ff origin/feat/day2-backend-feedback
```

## 3. 你的开发范围

### 3.1 Demo Session

实现：

- 首次打开若无 Session，显示 `blank_demo` / `seeded_demo` 选择；
- POST `/session/demo`；
- GET `/session` 恢复当前 alias；
- Cookie 由浏览器自动携带，前端不读取 Cookie；
- fetch 必须 `credentials: 'same-origin'`；
- 切换用户前关闭 EventSource、取消 fetch、清空 task/feedback 缓存；
- 用户 B 不得看到用户 A 的 task ID、回答或反馈。

提交：

```text
feat(web): add demo session switching and isolation
```

### 3.2 Idempotency 与 Task restore

实现：

- 每个用户动作生成一次 `crypto.randomUUID()` 作为 Idempotency-Key；
- 网络重试复用同一个 key，用户主动发起新动作生成新 key；
- 创建 task、提交 feedback 均带 header；
- 保存当前 task_id 到 URL 查询参数或 sessionStorage；
- 刷新后 GET task 恢复 task_text、messages、feedback、run 状态；
- 恢复终态任务不重新启动 SSE；非终态先 snapshot 后双游标 SSE；
- 旧用户缓存不能在切换后重新写入 state。

提交：

```text
feat(web): restore persisted tasks and idempotent writes
```

### 3.3 结果编辑与显式反馈

在 Agent 回答下增加：

- “编辑结果”按钮；
- 原稿只读；
- 修改稿 textarea；
- 显示字符变化数量，不做 Day 3 偏好推断；
- 自然语言反馈输入；
- 1–5 评分；
- “采纳”与“拒绝”；
- 至少一个字段后才允许提交；
- 提交 loading、成功、失败、原 key 重试；
- 失败不清空用户输入；
- 成功后显示 feedback_id 和 pending MemoryJob，但不要显示候选记忆。

提交：

```text
feat(web): add editable result and explicit feedback controls
```

### 3.4 实时反馈事件

原 run 的 EventSource 已在 `stream.done` 后关闭。不要把反馈 UI 建立在“旧连接还活着”
这个错误假设上。实现一次性 post-run catch-up：

- 注册 `feedback.recorded` 命名事件；
- Feedback 202 后，以本地保存的 `stream.done` event_seq 和最终 offset 调用
  `/events?after_event_seq=...&after_offset=...` 打开 one-shot SSE；
- 收到 `feedback.recorded` 后连接自然关闭，不期待第二个 `stream.done`；
- catch-up 失败则 GET task，从 `feedback_events[]` 恢复；
- reducer 按 event_seq 去重；
- 显示“反馈已记录，等待后续提取”；
- 不把 pending 说成“记忆已学会”；
- feedback event 只有 ID/类型，不期待正文；
- task refresh 后从 REST 获取反馈正文。

提交：

```text
feat(web): render feedback lifecycle and retry states
```

### 3.5 Fixture 与前端测试

现有仓库只有 `fixtures/day1/feedback_drafts.json`，没有现成的 `learning_events` 文件。
保留 Day 1 fixture 原样不改，在 `fixtures/day2/learning_events.json` 新建 24 条独立标注
数据（三场景各 8），其中可引用或改写那 8 条草案，但不能假装已有 Day 2 数据集：

- 文本偏好；
- 编程/调试；
- 冲突/一次性/漂移负例。

Day 2 只完成独立标注，不实现 extraction。

前端至少测试：

- Session 初始化/切换；
- Cookie 由浏览器管理；
- Task create Idempotency-Key；
- feedback payload null/空值边界；
- 编辑稿不改原稿；
- accepted true/false；
- 1–5 rating；
- 失败保留输入并复用 key；
- feedback.recorded 去重；
- 刷新 restore；
- 用户切换隔离旧异步 callback；
- 不显示 reasoning_content；
- pending job 不显示为已学习。

提交：

```text
test(day2): add G1 frontend and feedback fixtures
```

## 4. 你这边的建议时间表

| 时间盒 | 你的工作 | 验收门槛 |
|---|---|---|
| 接手后 0–60 分钟 | 审 PR、逐提交看 contract/migration/security | 明确 P0/P1；不凭对方报告合并 |
| 60–120 分钟 | detached 环境复跑后端、迁移、A/B 隔离和幂等 | 后端证据真实可复现 |
| 第 3–4 小时 | Session、Task restore、Idempotency 前端 | 刷新/切用户不串状态 |
| 第 5–6 小时 | 编辑、反馈、one-shot event、fixtures/tests | “生成→编辑→202→恢复”跑通 |
| 19:30 前 | Docker/migration/smoke 收口 | 两个功能分支均可 review |
| 19:30–21:30 | 按序合 PR、全链路复测、main PR | 全部硬门禁通过才请求最终批准 |

若实际接手时间较晚，保持相同的相对顺序。优先删装饰性 UI，不删 Session 隔离、幂等、
原稿/修改稿分离、迁移和重启恢复。

## 5. Docker 和 G1 smoke

你负责把 SQLite 和 migration 接入最终单容器流程：

- Day 2 全程使用 `MOCK_MODE=true`，不再次调用真实 DeepSeek；
- 本地忽略的 `.env` 需要非空 `SESSION_SECRET`，但不得在终端输出、截图、日志或 Git
  diff 中出现其值；`.env.example` 只保留空占位符；
- Compose 显式传入 `SESSION_SECRET`、`COOKIE_SECURE=false` 和容器数据库 URL；部署到
  HTTPS 环境才改为 `COOKIE_SECURE=true`；
- `/app/data` 命名卷；
- 容器启动前安全执行 `alembic upgrade head`；
- migration 失败时容器不能继续启动 Uvicorn；
- 单 worker；
- `/ready` 显示数据库可写和 migration head；
- restart 后 task/feedback 可恢复；
- 不把 SQLite 放入镜像层或 Git。

新增 `scripts/day2/smoke.ps1`，至少验证：

1. health/ready；
2. demo A session；
3. 创建 task + SSE 完成；
4. 提交 explicit/edit/rating/accepted feedback；
5. 同 key 重放不重复；
6. 同 key 不同 body 为 409；
7. feedback.recorded；
8. 原稿和修改稿同时存在；
9. restart；
10. task/messages/feedback/event restore；
11. demo B 对 A task/feedback/job/SSE 全 404；
12. event_log 无正文；
13. Day 1 AST、失败流和双游标恢复仍通过。

提交：

```text
build(day2): add migration-aware persistent container
test(day2): add G1 full-chain smoke
```

## 6. 晚间完整验收

### 6.1 静态和单元测试

后端：Ruff、format、全部 pytest、contract/security marker。

前端连续三轮：

```powershell
npm run typecheck
npm run lint
npm run test
npm run build
```

### 6.2 数据库测试

- 空库 upgrade head；
- current=head；
- disposable DB downgrade/upgrade；
- foreign key 检查；
- 无悬空 feedback/job/event；
- 不使用真实用户数据库做破坏性 migration 测试。

### 6.3 全链路

- G1 smoke 连续 3 次；
- Docker cold start 2 次；
- Docker restart 3 次；
- Chrome 与 Edge 各一次；
- Mock 标识可见；
- 日志 credential/content pattern 0；
- `pip-audit` 和 `npm audit`；
- 记录实际结果，不能估计。

### 6.4 人工数据库核对

共同查看一条任务：

- user message；
- original assistant message；
- edited_output；
- explicit_text；
- rating；
- accepted/rejected；
- pending memory_job；
- metadata-only event_log。

确认原稿没有被修改稿覆盖。

## 7. 你的 PR 和最终 integration PR

你的分支完成后先创建/更新 Draft PR。因为它以 backend head 为祖先，在后端 PR 尚未
合并时，GitHub 暂时会显示两部分提交，这是预期现象：

```powershell
git push
gh pr create --draft `
  --base integration/day2 `
  --head feat/day2-frontend-integration `
  --title "feat: complete Day 2 G1 feedback persistence" `
  --web
```

必须由第二成员 review。对方需要检查前端是否正确消费他的契约，尤其是 null、401/404、
幂等和 feedback.recorded。

晚间按以下固定顺序操作：

1. 后端 PR 转 ready，负责人 approve 后用 merge commit 合入 `integration/day2`；
2. `git fetch origin --prune`，确认前端 PR diff 自动缩小为前端/容器/测试提交；
3. 前端 PR 转 ready，第二成员在最后一次 push 后 approve，再用 merge commit 合入
   `integration/day2`；
4. 拉取集成分支并从零复跑第 6 节全套门禁；
5. 才从集成分支创建 PR 到 main。

命令骨架：

```powershell
gh pr ready <后端PR编号>
gh pr review <后端PR编号> --approve
gh pr merge <后端PR编号> --merge

git fetch origin --prune
gh pr diff <前端PR编号> --name-only
gh pr ready <前端PR编号>
# 第二成员在最后一次 push 后完成 approve：
gh pr merge <前端PR编号> --merge

git switch integration/day2
git pull --ff-only origin integration/day2
```

全套复测通过后，从集成分支创建 PR 到 main：

```powershell
gh pr create --draft `
  --base main `
  --head integration/day2 `
  --title "feat: complete MemTrace Day 2 G1" `
  --web
```

第二成员必须批准最后一个 PR；main 保护不允许你自己绕过。

最终 PR 描述包含：

- 后端 PR；
- 前端 PR；
- migration revision；
- 测试数；
- 3 次 G1 smoke task IDs；
- restart restore task ID；
- 两用户隔离证据；
- Docker image ID；
- 已知风险和降级；
- 明确说明 Day 2 只记录反馈，不提取长期记忆。

最终 PR 的证据填写完且不再 push 后：

```powershell
gh pr ready <最终main PR编号>
# 第二成员完成最后一次批准后：
gh pr merge <最终main PR编号> --merge
```

合并使用 merge commit。合并后：

```powershell
git switch main
git pull --ff-only origin main
git tag -a day2-g1-verified -m "MemTrace Day 2 G1 verified"
git push origin day2-g1-verified
```

## 8. 合并失败时的处理顺序

1. Contract 冲突：先解决 Pydantic/EventType/Schema，再处理实现；
2. migration 冲突：不能手工改 `alembic_version`，重新明确 revision graph；
3. 后端/前端字段冲突：以已 review 的 contract commit 为准；
4. SSE 冲突：保留 Day 1 双游标、UTF-8 offset 和 terminal final GET；
5. Cookie 问题：不退化为请求体 owner_id；
6. 时间不足：保留 textarea、两个 demo user、pending job，删除装饰性 UI；
7. 任意 P0 未通过：不得合 main，不得打 verified tag。

## 9. Day 2 最终完成定义

只有以下全部成立才叫 Day 2 完成：

- 一次任务、原结果、修改稿和反馈进入 SQLite；
- 刷新和容器重启后可恢复；
- 重复 feedback 不重复写；
- 用户 B 无法读取用户 A 数据；
- feedback.recorded 实时可见；
- MemoryJob 明确 pending，不伪称已学习；
- Day 1 G0 全部能力没有回归；
- Docker、Chrome、Edge 和 smoke 有实际证据；
- 第二成员完成 review；
- integration/day2 通过受保护 PR 合入 main。
