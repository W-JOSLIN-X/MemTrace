# MemTrace Day 2 后端交接报告（feat/day2-backend-feedback）

> 生成时间：2026-08-22
> 角色：Day 2 后端负责人
> 本报告只记录有证据的通过项；未实测的明确标注「未验证」。

## 分支与 HEAD

- 分支：`feat/day2-backend-feedback`
- 起点：`0468904`（merge: complete MemTrace Day 1 G0）
- 交接时 HEAD：`dc2fe38`（chore(contract): freeze G1 session feedback and restore APIs）
- 注意：网络不可达（`git fetch origin` 报 `Connection was reset`），`gh auth status` 与 push 权限未验证。

## 交付范围结论

Day 2 G1 后端主链已跑通并可验证：**Session → owner 隔离 → 任务持久化 → 重启恢复 → 反馈 → 幂等 → MemoryJob 占位 → SSE catch-up 回放**。原有 6 个路由级 `NameError` 已修复，Day 1 回归已恢复为带鉴权的隔离测试。

## 迁移 revision/head

- `001_initial_g1_schema`（head）
- 空库 `alembic upgrade head` + `alembic current` 均通过（独立临时 SQLite 验证）。
- 禁止 `create_all()`：Schema 只由 Alembic migration 创建。

## 新增 API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/session/demo` | demo 登录，返回 200 + opaque Cookie |
| GET | `/api/v1/session` | 返回当前会话；无有效 Cookie 401 |
| POST | `/api/v1/session/logout` | 恒 204 + 清除 Cookie |
| GET | `/api/v1/tasks/{task_id}` | owner 检查后可恢复的 G1 快照（含 task_text/scenario/messages[]/feedback_events[]） |
| GET | `/api/v1/tasks/{task_id}/events` | SSE，支持重启后 event_log 回放 |
| POST | `/api/v1/tasks/{task_id}/feedback` | 幂等反馈，202 |
| GET | `/api/v1/memory-jobs/{job_id}` | owner 自己的 job |

写接口 `POST /tasks` 与 `POST /tasks/{id}/feedback` 要求 `Idempotency-Key`（8–128 ASCII，`[A-Za-z0-9._:-]`）。

## 新增/修改表（11 张）

`users`、`demo_sessions`、`tasks`、`task_fingerprints`、`agent_runs`、`messages`、`tool_calls`、`feedback_events`、`memory_jobs`、`event_log`、`idempotency_keys`。关键约束：`event_log(owner_id, stream_type, stream_id, seq)` 唯一，`idempotency_keys(owner_id, route, key)` 唯一，feedback→task/run、job→feedback 显式外键 + ON DELETE CASCADE/SET NULL，enum 用 DB CHECK + Pydantic 双重校验。

## 契约变化

- 新增 Pydantic：`DemoSessionResponse`、`FeedbackCreateRequest/Accepted`、`MemoryJobResponse`、`TaskSnapshot.messages[]/feedback_events[]`。
- 新增 EventType `feedback.recorded` 及 payload。
- 新增 ErrorCode：`SESSION_REQUIRED`、`IDEMPOTENCY_CONFLICT`、`FEEDBACK_NO_CHANGES`、`TASK_NOT_READY_FOR_FEEDBACK`。
- `contracts/openapi.json` 已重新导出并与路由同步（`export_openapi.py` 确定性生成）。
- `contracts/day2-g1.json` audit manifest 已落地（Step 1 commit）。
- 前端 `g0/types.ts`、`runtime.ts` 已接受 G1 字段与 `feedback.recorded`（Step 1 commit）。

## 测试命令与退出码

后端（隔离临时库 + 鉴权）：

```text
apps/api/.venv/Scripts/python.exe -m pytest -W error apps/api/tests -q
99 passed in ~45s（退出码 0）
```

前端：

```text
npm run typecheck  → 退出码 0
npm run lint       → 退出码 0
npm run test       → 25 passed（4 files），退出码 0
npm run build      → 退出码 0
```

门禁：

```text
ruff check    → All checks passed!
ruff format --check → 34 files already formatted
git diff --check → 通过
pip check     → No broken requirements found.
```

## 后端通过数

- 后端：99 passed（含 14 个 Day 2 集成测试）。
- 前端：25 passed。

## 关键修复（相对上一个半成品状态）

1. 修复 16 个未定义符号（`select`/`and_`/`DemoSessionModel`/`MessageModel`/`MessageRole`/`verify_cookie_value`/`TaskRecord` 等），Session 查询、feedback、重启回放路由不再 `NameError`。
2. 移除 import-time DB 副作用：`app = create_app()` 不再在导入期访问数据库，bootstrap 移到 lifespan。
3. `_db_subscription` 从 task 的 latest run 重建 `run_id`，重启后 SSE 回放生成合法 `EventEnvelope`。
4. 幂等并发原子语义：`IntegrityError` → 新事务读取已提交记录 → 同 hash 重放 / 异 hash 409。
5. 失败 run 持久化 partial assistant message，重启恢复后 `partial_output` 不再丢失。
6. `memory.retrieval.started` 瞬态事件仅在客户端 cursor 尚未越过其后第一个持久事件时重放，避免 catch-up 时重复。

## 从空库升级结果

通过：`alembic upgrade head` → `001_initial_g1_schema`，`alembic current` = head。

## 重启恢复 / 跨用户 / 幂等证据

- 重启恢复 task_id：`test_terminal_task_restarts_and_recovers_messages` 通过（同 DB 新建 app 后 GET 仍返回 succeeded、messages 含 user/assistant）。
- 跨用户 404：`test_owner_isolation_across_task_feedback_and_sse`（GET/SSE/feedback 全 404）、`test_other_owner_job_returns_404` 通过。
- 幂等：`test_idempotent_replay_returns_same_ids_and_does_not_create_rows`、`test_idempotent_conflict_same_key_different_body` 通过。
- `agent.chunk` 不在 event_log、event_log 不含正文：`test_agent_chunk_not_in_event_log`、`test_event_log_excludes_task_answer_and_feedback_body` 通过。
- 终态 catch-up 只回放一次 `feedback.recorded`：`test_post_run_metadata_catchup_replays_feedback_recorded_once` 通过。

## secret scan

- 无 `sk-...`、无 Bearer Token、无非空 API Key / Session secret。
- `.env` 未被 git 跟踪；无 `.sqlite`/`.db` 入库。
- `.env.example` 只含空 `SESSION_SECRET=`、`COOKIE_SECURE=false` 与数据库 URL 示例。
- `.claude/` 为本地工具配置，不纳入提交。

## 未完成功能（不在 Day 2 交付范围）

- 前端反馈页面 / 结果编辑器（由项目负责人继续）。
- `memory_jobs` 永远 pending（Day 2 占位，不启动提取器）。
- 从反馈提取 MemoryCard / 记忆注入 / 检索（Day 3+）。
- 真实 DeepSeek 调用 smoke（本任务只允许 `MOCK_MODE=true`）。
- Docker 镜像重建与 Day 1 smoke 独立证据（网络不可达，未运行）。

## 已知风险

- 网络不可达：未能 `git fetch`、`gh auth status`、`git push`、`gh pr create`，Draft PR 尚未创建。恢复网络后需执行第 14 节推送步骤。
- SQLite 并发幂等依赖唯一约束竞争，SQLite 单写者下已可工作；未做多进程并发压测。
- 基础镜像 OS 扫描项（2 Critical + 3 High）沿用 Day 1 接受状态，Day 2 未更换。

## 项目负责人接手的第一步

1. 恢复网络后：`git fetch origin --prune` 核对远端，`gh auth status` 确认自己账号有 Write 权限。
2. `git push -u origin feat/day2-backend-feedback`，`gh pr create --draft --base integration/day2 --head feat/day2-backend-feedback`。
3. 从该 PR head 创建前端分支，实现反馈页面（textarea 结果编辑器 + 1–5 评分 + 采纳/拒绝 + feedback.recorded 展示）。
4. 后端 PR 暂不单独合入 `integration/day2`，等晚间完整链路（登录 → 任务 → 反馈 → 重启恢复）通过后按「后端 PR → 前端 PR」顺序合入。
