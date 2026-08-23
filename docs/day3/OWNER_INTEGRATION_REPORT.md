# MemTrace Day 3 G2 Owner Integration 核验报告

> 状态：接管中。本文件先记录进入接管分支时的独立基线；最终测试、容器、浏览器、PR 和
> main 合入证据将在对应步骤真实完成后更新。未列为“通过”的项目不能从旧交接报告推断。

## 1. 分支与来源

- 核验日期：2026-08-23（Asia/Shanghai）。
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

## 4. 冻结决策

- G2 contract 保持 `1.2.0`；精确语义见 `G2_CONTRACT_DECISION.md`。
- 本轮以 `MOCK_MODE=true` 为硬门禁；不读取或要求真实 Provider Key。
- 成员 B 全面接管后端、前端、EvalRunner、fixture、Docker 和整合。
- PR #4 不直接合并；由新的 owner integration PR 保留其历史并取代。
- Day 3 不实现 D4 检索、D5 Memory Center/冲突/Pack 或“已经用于后续回答”。

## 5. 最终证据占位

以下内容必须由最后一次 push 对应的真实命令填写，不能复制旧报告：

- 最终 head 与提交列表：待完成。
- Ruff / format / pip check / fixture / pytest：待完成。
- TypeScript / ESLint / Vitest / build：待完成。
- fresh/upgrade/restart migration：待完成。
- G2 API、事件 catch-up、owner isolation：待完成。
- Docker image、任务专属 project/volume、cold/restart：待完成。
- Chrome/Edge：待完成。
- secret/body-log scan：待完成。
- 替代 PR、审批、integration/main merge：待完成。
- last-known-good commit：待完成。
