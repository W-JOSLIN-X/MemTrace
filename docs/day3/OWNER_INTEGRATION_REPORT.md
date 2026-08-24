# MemTrace Day 3 G2 Owner Integration 核验报告

> 状态：Day 3 已完成历史流程。PR #5 的最终 head `f922af399f8163aa660da3db63bb176149ab82d0`
> 已以 merge commit `2e2139eb3a9912198ac14db3ffbd9bc4ed0e4e67` 合入 `integration/day2`；
> PR #6 随后以 merge commit `34681a4082f52da3a67e784f348111f9d0e38044` 合入 `main`。
> 本文记录的是 D3 当时的实际核验证据，不是 D4 的当前测试结果。自 2026-08-24 起的 D4–D7
> 交付改用 `docs/OWNER_LED_COLLABORATION_WORKFLOW.md`，不再要求 PR 或同伴审批。

## 1. 分支与来源

- 核验日期：2026-08-23 至 2026-08-24（Asia/Shanghai）。
- Day 2 owner PR #3 head：`a668f8dc238835e773a882f9d40422bb24b72894`。
- Day 3 协作者 PR #4 head：`de1dd2e0689f46da4e16df3c6acb4a3ae83eb018`。
- 接管分支：`codex/day3-owner-integration`，从 PR #4 head 创建，保留全部协作者提交祖先。
- PR #3 已于 2026-08-24 由 `zlbk-wxy` 在 `a668f8d` 上审批，并以 merge commit
  `009ba872311e4a5b916fe8abe7929fd30730fe07` 合入 `integration/day2`。
- PR #4 仍为 Open，且不能直接合并；替代 PR #5 的 base 是 `integration/day2`。
- 接管分支通过普通 merge commit `6c63f0d` 引入最新 Day 2 基线，没有改写任一协作者提交。
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
| `6c63f0d` | 普通 merge 引入 PR #3 合入后的最新 Day 2 基线 |
| `68dba3e` | 修正独立 fixture validator 与成员 B 已复核标签的漂移，并加入 CLI 回归 |

最后已知通过全部实现门禁的代码 commit 为
`68dba3e91f8ad8334415c4a9c995bddad770a060`；本报告之后的提交只改文档。

## 6. 自动化门禁

| 门禁 | 实际命令 / 结果 |
|---|---|
| 后端完整测试 | 干净 checkout `python -m pytest tests -q` → exit 0，`353 passed in 147.57s` |
| Ruff | `python -m ruff check apps/api` → exit 0，0 errors |
| 格式 | `python -m ruff format --check apps/api` → exit 0，61 files already formatted |
| Python 依赖 | `python -m pip check` → exit 0，No broken requirements |
| 前端类型 | `npm run typecheck` → exit 0 |
| 前端 ESLint | `npm run lint` → exit 0，0 warnings |
| 前端测试 | `npm test` → exit 0，7 files / `42 passed` |
| 前端构建 | `npm run build` → exit 0，53 modules transformed |
| Fixture CLI | `python scripts/day1/validate_fixtures.py` → exit 0，5 组 PASS |
| Alembic | `python -m alembic -c apps/api/alembic.ini heads` → 唯一 head `003_g2_job_retryable` |
| REST Eval | 当前容器 → exit 0，`30/30 fixtures, 2/2 smoke checks` |
| Eval 失败语义 | 不可达 base URL → exit 1，`0/0`；证明失败不返回 0 |

完整 pytest 同时覆盖 Pydantic、规范 JSON Schema、实际 FastAPI OpenAPI、TypeScript 所消费
字段、唯一 Alembic head、空库/旧 revision readiness、worker 竞争、retry/resolve 幂等、事务
回滚、owner 404、持久事件 catch-up 与真实 provider fake-client。OpenAPI 已由实际应用重新导出。

## 7. Docker、迁移、重启与隐私证据

- 最终代码从干净 checkout 构建 `memtrace:day3-g2`，manifest list
  `sha256:0da26351a0b76e0aac7b0e082dd053229ae5d4df5e25e8a6bfc791b1809cb1a7`。
- 本轮 project 为 `memtrace-day3-pr5-68dba3e`，端口 18085，启动前确认没有同名容器或卷；
  Compose 创建三个任务专属新卷。
- 空卷 cold start 日志实际执行 `001_initial_g1_schema → 002_g2_memory_admission →
  003_g2_job_retryable`；`/ready` 的 config、session_secret、data_dir、database 与
  migration_revision 均 pass，provider 为 mock。
- REST Eval 后重启前后计数完全一致：30 tasks、30 feedback、30 jobs、16 cards、18 evidence、
  1 immutable version、499 events；重启后 readiness 再次成功。
- Chrome/Edge 验收后共有 32 个 task stream，`non_contiguous_task_streams=0`；
  metadata forbidden key hits=0。最终 card 投影为 2 active、15 candidate、1 rejected，
  rejected reason 仅 `episode_only`，2 个 immutable version，证明 one-shot 未创建版本。
- 容器日志扫描得到 0 ERROR/Traceback、0 正文键模式、0 token 模式；Eval 输出也不含
  `task_text/explicit_text/edited_output/evidence_quote/rule/avoid/trigger_text` 键。
- Git tracked 文件中没有运行时 `.env`、SQLite/DB 或 token 模式；`.env.example` 是公开模板。
  本轮未读取本地 `.env`，Mock 是唯一硬门禁。

## 8. Chrome 与 Edge 实测

Chrome 与 Microsoft Edge 均针对 `68dba3e` 构建的最终容器，以隔离 Playwright session
实际完成产品路径；没有复用旧浏览器报告作为本轮结论。

1. Chrome：blank demo 创建 Python 调试任务，服务端自动分类为 programming learning 90%，
   界面无手工 scenario；SSE 完成后提交修改稿、长期反馈、5 分与采纳，MemoryJob done，
   打开 evidence drawer 后 accept，形成 active v1；刷新后 task、feedback、job、card、证据和
   “已确认保存，但 Day 4 才接入检索”文案全部恢复。
2. Chrome：切到 seeded demo 后 URL task 指针、候选、证据和草稿清空；再访问 blank demo
   原 task URL，页面清除 query 并显示 `TASK_NOT_FOUND`，对应 snapshot API 返回 404。
3. Edge：创建 TypeScript 重构/部署任务，服务端自动分类为 software development 95%；
   提交长期反馈后恢复候选与 evidence drawer，执行 one_shot；刷新后仍显示“仅本次，不进入
   长期记忆”，数据库 reason 为 `episode_only` 且没有新增 version。
4. accept/edit_accept/reject/one_shot 四种动作、失败草稿保留、幂等键重用与用户切换取消监控
   另由 42 项完整前端测试和 353 项后端测试覆盖。

两种浏览器各出现 1 条预期的首次 `GET /session` 401；Chrome 的跨 owner 探测另产生 1 条
预期 404。没有其他 console warning/error，验收后两个隔离浏览器 session 均已关闭。

## 9. GitHub 与最终合并结果

2026-08-24 本轮在线核验：

- `gh auth status`：活动账号 `W-JOSLIN-X`，认证有效；
- PR #3：`MERGED / APPROVED`，approval author=`zlbk-wxy`，review commit=`a668f8d`，
  merge commit=`009ba872`；远端 `integration/day2` 已指向该 commit；
- PR #4：协作者原始 head=`de1dd2e`；其提交历史已由替代 PR #5 保留并合入；
- PR #5：最终 head=`f922af399f8163aa660da3db63bb176149ab82d0`，已于 2026-08-24 以
  merge commit `2e2139eb3a9912198ac14db3ffbd9bc4ed0e4e67` 合入 `integration/day2`；
- PR #6：以 `2e2139eb3a9912198ac14db3ffbd9bc4ed0e4e67` 为 head，已于 2026-08-24
  以 merge commit `34681a4082f52da3a67e784f348111f9d0e38044` 合入 `main`；
- 本报告更新前的远端 `integration/day2` 为 `2e2139e`，远端 `main` 为 `34681a4`；
- 没有向协作者分支、`integration/day2` 或 `main` 直接推送，也没有删除远端分支。

上述最后一条只描述 D3 当时遵循的历史流程。Day 3 已实际进入 main；D4 起按根目录
`AGENTS.md` 和 `docs/OWNER_LED_COLLABORATION_WORKFLOW.md` 执行：成员 A 只 push 功能分支，
成员 B 独立核验和收口后普通非强制直接 push main，不再经过 `integration/day2` 或强制同伴审批。

## 10. 本轮新增发现与修复

独立执行 `scripts/day1/validate_fixtures.py` 时发现它仍要求历史状态
`member_a_initial_labeling`，而已经双人复核的 fixture 正确声明
`member_b_approved_2026-08-24`。因此旧完整 pytest 的绿色不能证明 CLI 门禁可用。

`68dba3e` 将 validator 对齐到冻结状态，并新增从 pytest 实际启动 repository fixture CLI
的回归测试。修复前 CLI exit 1；修复后 CLI exit 0，完整 pytest 从 352 增加为 353 项。
