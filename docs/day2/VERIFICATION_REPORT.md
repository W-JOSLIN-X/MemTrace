# MemTrace Day 2 G1 独立核验报告

> 状态：本机实现与门禁已通过；GitHub 整合 PR、`zlbk-wxy` 在最终 push 后的审批、
> `integration/day2` 与 `main` 合并尚未在本报告生成时完成。因此此处只能称为
> “本机绿色 / PR 待创建”，不能提前称为“Day 2 已合入 main”。

## 1. 核验范围与证据优先级

- 核验日期：2026-08-23（Asia/Shanghai）。
- PR #2 历史基线：`d5afd441d11a84db85f7a434ea41a625703c097a`。
- 旧负责人文档分支基线：`451a452367110281da3d70dc1681a70c09fe3478`。
- 最后通过完整代码门禁的实现 commit：
  `06597084933fc1f9b5d21eb9e55ac0c65f26430b`。
- 当前整合分支：`codex/day2-owner-integration`。
- 自动分类和本轮实际测试优先于旧 `HANDOFF.md`、旧 Day 2 计划中的历史判断。
- Day 2 固定使用 `MOCK_MODE=true`，未调用真实模型，也未使用模型 API Key。

## 2. 独立复核发现并修复的问题

| 问题 | 独立复现 | 修复与回归证据 |
|---|---|---|
| 客户端可手工提交 `scenario` | PR #2 请求模型仍接受用户场景 | 请求契约删除该字段，`extra=forbid`；live smoke 明确验证旧字段返回 422 |
| SQLite 事件序号存在竞争 | 旧实现依赖 SQLite 不提供的有效行锁语义 | 单语句 `UPDATE ... RETURNING`；8 并发分配连续且无重复 |
| 容量拒绝可能留下幽灵 durable row | 先写 DB、后发现内存容量已满 | TaskStore reservation/commit/release；503 后 task/run/idempotency/worker 均不增加 |
| 同一幂等键并发可能重复建任务 | 查找与插入之间存在窗口 | 数据库唯一约束与事务冲突重放；同 key 同 body 只产生一个 task，不同 body 返回冲突 |
| Demo session 切换未精确撤销旧 token | 旧逻辑按 owner 猜最新 session | 切换撤销当前 Cookie 对应 token；旧 Cookie 401，`GET /session` 返回当前 token 自身 expiry |
| readiness 未验证迁移 revision | 可连接空库也可能被误报 ready | `/ready` 检查数据库与唯一 Alembic head；空库/旧 revision 503，正确 head 200 |
| Docker 空卷启动失败 | 镜像缺少 Alembic 配置与迁移 | 镜像复制 migration，入口先 `alembic upgrade head`，再启动 Uvicorn |
| 前端缺少 G1 owner/恢复/反馈闭环 | 旧 UI 仍依赖手工场景或仅呈现 G0 | 完成 Demo 用户切换、Cookie、独立幂等键、URL/sessionStorage 恢复、自动分类、编辑稿与显式反馈 |
| 浏览器中终态快照 200 但前端拒绝 | SQLite 时间戳返回无时区字符串，严格 parser 显示 `FINAL_SNAPSHOT_UNAVAILABLE` | 所有契约模型 JSON 统一输出 RFC 3339 UTC `Z`；HTTP 回归测试覆盖 snapshot/message/feedback/job 时间戳 |
| UTC serializer 一度破坏 OpenAPI 输出约束 | 最终全量首次为 `122 passed, 1 failed`，确定性 OpenAPI 不一致 | 移除 serializer 的宽泛返回类型，保持原字段 serialization schema；随后全量 `123 passed` |
| smoke 固定幂等键会让第二次运行假重放 | 连续执行脚本可能不创建新任务 | 每次脚本运行生成新 nonce，单次操作内部仍复用自己的 key；最终 smoke 得到全新 task ID |

## 3. 最终自动化门禁

### 3.1 环境

| 工具 | 实测版本 |
|---|---|
| Python | 3.11.4 |
| Node.js | v22.15.0 |
| npm | 10.9.2 |
| Docker client/server | 29.6.1 / 29.6.1 |
| Docker Compose | v5.2.0 |

### 3.2 后端、契约与 fixture

以下命令均从仓库根目录运行，最终退出码均为 0：

```powershell
.\apps\api\.venv\Scripts\python.exe -m ruff check .\apps\api\src .\apps\api\tests .\apps\api\scripts .\scripts\day1
.\apps\api\.venv\Scripts\python.exe -m ruff format --check .\apps\api\src .\apps\api\tests .\apps\api\scripts .\scripts\day1
.\apps\api\.venv\Scripts\python.exe -m pip check
.\apps\api\.venv\Scripts\python.exe .\scripts\day1\validate_fixtures.py
.\apps\api\.venv\Scripts\python.exe -m pytest -W error .\apps\api\tests -q
```

最终结果：

- Ruff：全部通过，42 个 Python 文件已格式化；
- `pip check`：`No broken requirements found`；
- fixture/schema：2 份 Draft 2020-12 schema、8 个 demo_core、8 个 feedback draft、
  24 条 Day 2 G1 分类矩阵、3 份 SSE fixture 全部通过；
- pytest：`123 passed in 125.46s`，并启用 `-W error`；
- 确定性 OpenAPI、Pydantic、JSON Schema、TypeScript runtime parser 的当前字段集合一致。

后端测试中实际覆盖：自动分类中英文/模糊/确定性、旧 `scenario` 422、DB/fingerprint/
snapshot 一致、8 并发事件序号、任务与反馈幂等、容量无幽灵记录、session 撤销与
owner 隔离、readiness 三态、feedback 事务回滚、进程重启 `RUN_INTERRUPTED`、
持久事件 catch-up。

### 3.3 前端

以下命令最终退出码均为 0：

```powershell
Set-Location .\apps\web
npm run typecheck
npm run lint
npm run test -- --run
npm run build
```

最终结果：

- TypeScript：通过；
- ESLint：0 warning；
- Vitest：6 个文件、31 项测试全部通过；
- production build：53 modules transformed，生成约 291.82 kB JS（gzip 92.52 kB）。

第一次在受限沙箱运行 Vitest 时，esbuild 子进程因 `spawn EPERM` 无法启动；按权限规则
在沙箱外重跑后通过。这是执行环境权限失败，不计为产品测试通过，报告采用放行后的
真实退出码与测试结果。

## 4. 容器与持久化验收

- 专属 Compose project：`memtrace-d2-codex-20260823`；端口 `18080`。
- cold start 从不存在的三个专属命名卷开始；容器入口自动迁移后 healthy。
- Alembic 唯一 head：`001_initial_g1_schema`。
- live `/ready`：`status=ready`，database 与 migration_revision 均为 `pass`，
  Provider 为 `mock`。
- 最终镜像：
  `sha256:21dfbe17bfca19dc35d6d79fcf74790632972e57ebc735cac66f3b3cd786e26b`。
- live smoke：9/9 通过；最终一次使用全新幂等键生成：
  - Python：`task_01M0N9FAX8J27QTD1NBTWDZKK1`
  - forced failure：`task_01M0N9FC6TX1K39S83YSN9PZD1`
  - reconnect：`task_01M0N9FD6JJ5W5EV1QA18GQBZG`
- 持久性任务：`task_01M0N5J0Z5WDXM2NY6DPHGVX8K`；对应 feedback
  `feedback_01M0N5J21NSM4224T3NFBX5K0S`、job
  `job_01M0N5J21NJAB2CFKHT18BTQT7`。
- 上述 task/feedback/pending job 在 container restart 后恢复，并在保留同一卷的
  `compose down` / `up -d` 后再次恢复；最终镜像重建后仍恢复 1 条 feedback。
- 独立 `seeded_demo` 对该 blank owner task 的 REST 访问返回 404。
- 最终 500 行容器日志不包含运行时 `SESSION_SECRET`、固定测试任务正文或反馈正文。

## 5. Chrome 与 Edge 实测

### Chrome

- 官方 Chrome channel，独立 Playwright profile；
- task：`task_01M0N63RW1V8G55X49REJ4TCZA`；
- 自动识别：`software_development`，规则置信度 89%，理由为技术语境/开发动作；
- 验证 SSE 完成、原始输出只读、独立修改稿、字符变化、自然语言反馈、评分 4、采纳；
- feedback 后界面显示“反馈已记录，等待 Day 3 处理”和 pending MemoryJob；
- 刷新恢复 task 与 1 条 feedback；切 seeded 清空 URL/任务/草稿，切回 blank 再恢复；
- 证据：[Chrome G1 feedback](../../output/playwright/chrome-g1-feedback.png)。

### Microsoft Edge

- 官方 `msedge` channel，独立 Playwright profile；
- task：`task_01M0N7ZW741SN9AZ3RX59R85NH`；
- 无信号文本自动识别为 `other`，显示“暂未明确识别”、20% 规则分数、低置信提示，
  且没有人工类别输入；
- 验证单一“拒绝”反馈派生、pending MemoryJob、刷新恢复、切 seeded 清空；
- 证据：[Edge G1 other feedback](../../output/playwright/edge-g1-other-feedback.png)。

两个浏览器首次无 Cookie 时都会先请求 `GET /api/v1/session` 并得到预期 401，随后
`POST /api/v1/session/demo` 为 200；因此 DevTools 各保留 1 条预期的 401 resource
console 记录。会话初始化和后续流程没有失败。这是当前 GET-first bootstrap 的可观测
噪声，未伪装为“零 console error”。

## 6. 安全、登录与不做边界

- GitHub CLI 当前登录账号为 `W-JOSLIN-X`；本地实现阶段没有新的登录要求。
- tracked token pattern 扫描通过；未跟踪 `.env`、SQLite/DB 文件，`.env.example`
  仅保留变量名和非密钥说明。
- 未把 Cookie、幂等键请求头、`SESSION_SECRET` 或模型 Key 写入报告/截图/仓库。
- Day 2 未实现 MemoryCard、候选卡、长期记忆提取、embedding、检索、Memory Pack，
  也未把 pending MemoryJob 描述成“已学习”或“已记住”。
- 真实 Provider 没有运行；它不属于本次 `MOCK_MODE=true` 的 Day 2 门禁。

## 7. 尚未完成与最终判定

- 第二台电脑启动：未验证。
- GitHub 整合 PR：待 push/创建。
- `zlbk-wxy` 在最后一次 push 后审批：待执行，不能由作者账号自批。
- `integration/day2` 合并、干净 checkout 重跑、`integration/day2 -> main` PR、最终审批
  与 main merge：待执行。

在上述 GitHub 保护流程完成前，准确状态是“Day 2 本机绿色，整合 PR 待审批”，不是
“Day 2 已完成并合入 main”。
