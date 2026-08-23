# MemTrace Day 3 G2 Owner Integration 核验报告

> 状态：本地 G2 实现与验收已收口，接管分支已推送；远端晋级被 PR #3 缺少
> `zlbk-wxy` 审批阻塞。本文只记录本轮实际执行证据，不从旧交接报告推断结果。

## 1. 分支与来源

- 核验日期：2026-08-23 至 2026-08-24（Asia/Shanghai）。
- Day 2 owner PR #3 head：`a668f8dc238835e773a882f9d40422bb24b72894`。
- Day 3 协作者 PR #4 head：`de1dd2e0689f46da4e16df3c6acb4a3ae83eb018`。
- 接管分支：`codex/day3-owner-integration`，从 PR #4 head 创建，保留全部协作者提交祖先。
- PR #3、PR #4 在接管开始时均为 Open、`REVIEW_REQUIRED`、`BLOCKED`。
- `integration/day2` 在接管开始时仍指向 Day 1 `0468904332ffa79512ac2319f9dfd81d1f67c4cd`。
- 本地 `TEAMMATE_AGENT_PROMPT.md` 接管前未被 Git 跟踪；原始 SHA-256 为
  `9E3B6114D9AABC63B4B536CB65E43CDD1D8E2A611075C0B6DC157858927136E2`。

## 2. PR #4 独立基线

在未改动的 `de1dd2e` 临时 checkout 上得到：

- 后端完整 pytest：260 passed；这只证明已有测试通过，不证明实际 G2 路由/worker 可用。
- `pip check` 和 fixture validator：通过。
- Ruff：97 errors。
- Ruff format check：9 files would be reformatted。
- 前端：TypeScript、ESLint、31 项 Vitest、production build 通过。
- Day 3 候选时间线、证据抽屉、resolve/retry、恢复与隔离 UI 测试：不存在。

## 3. 已独立复现的阻断问题

1. `MemoryJobWorker` 未接入 FastAPI lifespan，实际 feedback job 持续停留在 pending。
2. 审计 manifest 声明 retry，但 FastAPI route 和实际 OpenAPI 不存在该 endpoint。
3. worker 含缺失导入、不存在 repository 方法和错误参数，且绑定固定 owner。
4. `Durability.ONE_SHOT` 未进入正确 episode-only 分支。
5. worker 传 `fingerprint=None`；scope gate 读取错误层级，不能从服务端指纹收窄作用域。
6. Day 3 事件用错误 repository 签名和错误 stream ID；异常被吞掉，测试仍显示绿色。
7. job 响应不返回真实 candidate IDs，`retryable` 也未持久化。
8. resolve 使用不存在字段和函数、没有幂等处理/response model/Admission Guard，响应缺少 card。
9. 真实结构化 provider 引用未导入的 `AsyncOpenAI`。
10. `normalized_levenshtein` 实际是 SequenceMatcher 近似值，公式与已冻结指标不一致。
11. 现有 Day 3 测试主要验证纯函数和声明，不是 lifespan worker、真实路由和完整事务 E2E。
12. `MEMBER_A_HANDOFF.md` 的 head、fixture 数量、Gate 状态和“基本闭环”结论已经过时。
13. 双浏览器恢复验收发现两个旧测试未覆盖的问题：`one_shot` 刷新后退化为普通 rejected
    文案；进程重启后 SQLite-only SSE fallback 构造过时假 `TaskRecord` 并返回 500。

## 4. 冻结决策

- G2 contract 保持 `1.2.0`；精确语义见 `G2_CONTRACT_DECISION.md`。
- 本轮以 `MOCK_MODE=true` 为硬门禁；不读取或要求真实 Provider Key。
- 成员 B 全面接管后端、前端、EvalRunner、fixture、Docker 和整合。
- PR #4 不直接合并；由新的 owner integration PR 保留其历史并取代。
- Day 3 不实现 D4 检索、D5 Memory Center/冲突/Pack 或“已经用于后续回答”。

## 5. 最终实现提交与继承关系

接管分支保留 `de1dd2e` 及其全部协作者祖先；`git merge-base --is-ancestor de1dd2e HEAD`
退出码为 0。成员 B 的实现提交如下：

| Commit | 内容 |
|---|---|
| `811292b` | 接管记录与 G2 契约冻结 |
| `f5cce04` | worker、retry、resolve、读 API、事务与迁移 |
| `39edf07` | durable G2 lifecycle/API 回归 |
| `002524a` | 前端 job 监控、候选时间线、证据与处置 |
| `ec6321c` | 前端恢复、幂等与用户切换测试 |
| `a1f221a` | 受控 Mock 编译器模拟与 Admission 修复 |
| `4e64620` | REST-only EvalRunner、30 条已复核 fixture 与未来草案 |
| `79a25dc` | 持久 rejection reason、one-shot 刷新恢复与 G2 release shell |
| `58b6abb` | 进程重启后的 SQLite-only SSE cursor 恢复 |

最后已知通过全部实现门禁的 commit 为 `58b6abb`；本报告之后的提交只改文档。

## 6. 自动化门禁

| 门禁 | 实际命令 / 结果 |
|---|---|
| 后端完整测试 | `python -m pytest apps/api/tests -q` → exit 0，`352 passed in 197.83s` |
| Ruff | `python -m ruff check apps/api` → exit 0，0 errors |
| 格式 | `python -m ruff format --check apps/api` → exit 0，61 files already formatted |
| Python 依赖 | `python -m pip check` → exit 0，No broken requirements |
| 前端类型 | `npm run typecheck` → exit 0 |
| 前端 ESLint | `npm run lint` → exit 0，0 warnings |
| 前端测试 | `npm test` → exit 0，7 files / `42 passed` |
| 前端构建 | `npm run build` → exit 0，53 modules transformed |
| REST Eval | 当前容器 → exit 0，`30/30 fixtures, 2/2 smoke checks` |
| Eval 失败语义 | 不可达 base URL → exit 1，`0/0`；证明失败不返回 0 |

完整 pytest 同时覆盖 Pydantic、规范 JSON Schema、实际 FastAPI OpenAPI、TypeScript 所消费
字段、唯一 Alembic head、空库/旧 revision readiness、worker 竞争、retry/resolve 幂等、事务
回滚、owner 404、持久事件 catch-up 与真实 provider fake-client。OpenAPI 已由实际应用重新导出。

## 7. Docker、迁移、重启与隐私证据

- 最终镜像：`memtrace:day3-g2`，manifest list
  `sha256:80a254a351dd4044dd21e6f890dec816a3f7fb02ee48674e38ec6e18b544e53a`。
- 主验收 project：`memtrace-day3-codex`，本机端口 18080，使用任务专属卷。
- 最终镜像在独立 `memtrace-day3-cold-final` 全新卷 cold start；入口自动迁移，`/ready`
  的 config/session/database/migration 均 pass。核验后已 `down -v` 删除这三个纯测试卷。
- 主验收容器重启前后计数完全一致：32 tasks、33 completed jobs、5 active cards、
  2 user-rejected cards、2 episode-only cards、26 evidence、5 immutable versions。
- 精确复现旧 500 的 task cursor：`after_event_seq=32&after_offset=74`。修复后在进程重启、
  空 live store 下返回 HTTP 200、0 bytes；新容器日志 0 ERROR / 0 Traceback。
- 563 条 event_log 分属 32 个 task stream，`non_contiguous_streams=0`。只输出字段名的扫描
  未发现 `task_text/explicit_text/edited_output/evidence_quote/output/rule/avoid/trigger_text`。
- Eval 输出扫描未发现正文 key 或正文样例；容器日志正文模式和 token 模式均为 0。
- Git tracked 文件中没有运行时 `.env`、SQLite/DB 或 `gho_`/`sk-` token 模式；本轮未读取
  本地 `.env`，Mock 是唯一硬门禁。

## 8. Chrome 与 Edge 实测

Chrome 与 Microsoft Edge 均以 `79a25dc` 对应的最终前端完成以下产品路径；`58b6abb`
之后只修改后端 SQLite-only SSE fallback，重建镜像后又以同一浏览器产生的真实 cursor
通过 HTTP 精确复验该恢复请求：

1. blank/seeded demo 双向切换，切换后 URL task 指针、候选、证据和草稿清空；
2. 创建任务并由服务端自动分类：Chrome 为 programming learning 95%，Edge 为 software
   development 95%，界面没有手工 scenario；
3. 等待 SSE 完成，提交真实修改稿、自然语言反馈、评分与采纳；
4. 观察 MemoryJob done，恢复 1–3 张候选并打开 evidence drawer；
5. 分别执行 accept、edit_accept、reject、one_shot 四条路径；
6. 刷新后恢复 task、feedback、job、candidate、evidence、version 与 one-shot 文案；
7. 切换 owner 后旧 task/candidate UI 消失；跨 owner API/SSE 404 另由完整后端测试覆盖。

两种浏览器各出现 1 条预期的首次 `GET /session` 401 网络记录（自动创建 demo session 前的
认证探测），没有前端 JavaScript exception 或 warning。Chrome 首轮刷新暴露的 one-shot
退化问题和容器重建后的 SSE 500 均已修复并在相同路径复验。

## 9. GitHub 与合并状态

2026-08-24 最终在线核验：

- `gh auth status`：活动账号 `W-JOSLIN-X`，认证有效；
- PR #3 head 仍为 `a668f8d`，`OPEN / REVIEW_REQUIRED / BLOCKED`，reviews 为空；
- PR #4 head 仍为 `de1dd2e`，`OPEN / REVIEW_REQUIRED / BLOCKED`；
- `origin/integration/day2` 与 `origin/main` 均仍为 `0468904`；
- `codex/day3-owner-integration` 已推送到 origin；没有向协作者分支或受保护分支直接推送。

因此本轮不能创建 base 正确的替代 PR、不能在最终 head 后取得 `zlbk-wxy` 审批，也不能
合入 `integration/day2` 或 main。下一步必须先由 `zlbk-wxy` 审批并合并 PR #3，再按计划
merge 最新 `origin/integration/day2`、重跑干净 checkout 门禁、创建替代 PR 并完成两级审批。
在此之前只能报告“Day 3 实现分支已就绪”，不得报告“Day 3 已合入 main”。
