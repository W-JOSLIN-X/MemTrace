# Day 4 所有者整合与发布报告

## 1. 不可删除的接管失败基线

本节记录成员 B 在修改成员 A 代码前独立复测得到的原始失败。后续通过结果只追加，
不覆盖这些事实。

- 2026-08-25 接管时 `origin/main` 为
  `32ea8b353bef4133851c5686e35de05022ae2147`，协作者远端 head 为
  `611034b779ed9e2e007981ca0a76d66f11f2f471`，实际 merge base 与 main 相同。
- `MEMBER_A_HANDOFF.md` 声明的 base `4a383...` 和 head `4879...` 与远端 Git 对象不符；
  下文所有结论均不使用该声明作为证据。
- 协作者范围共有 9 个提交、22 个变更文件。原始 `pytest` 为 402 passed，但新增证据
  主要是纯函数测试，且有空 `pass` 测试。
- `ruff check apps/api` 原始失败 73 项；`ruff format --check` 和 `pip check` 当时通过。
- Alembic 表面只有 `004_g3_retrieval_usage` 一个 head，但迁移移除了既有
  `uq_idempotency_owner_route_key` / `ix_idempotency_lookup`，约束与 downgrade 不完整。
- 实际 FastAPI OpenAPI 中 G3 路由数为 0；Orchestrator 未执行真实检索、持久化或
  Prompt 注入；`ProviderRequest` 没有 `memory_context` / `usage_ids`。
- G3 persistent event 使用 `event_seq=None`，与持久事件契约冲突。
- retrieval executor 存在空 fingerprint、query/card 向量语料不一致、Top-K reason、
  count 和 token budget 错误。
- owner 查询、事务、fixture、迁移和真实 API/Orchestrator 测试不足；verifier worker 与
  前端 G3 未接通。
- 协作者 handoff 文档尾随空格导致 `git diff --check` 失败；`.claude/settings.json`
  属于非产品权限产物。

## 2. Git 接管证据

- 整合分支：`codex/day4-owner-integration`。
- 普通 `--no-ff` merge commit：`3ef1df0`。
- main base 与协作者 head 均为 merge 后 head 的祖先；协作者作者、9 个提交及祖先关系
  保留，未 rebase、squash、amend，也未向协作者分支追加提交。
- 未创建日常 PR，未使用 `integration/day2`。

## 3. 所有者修复与成员 B 范围

- 契约投影统一到 `1.3.0`，使用冻结评分公式
  `.25 scope + .30 semantic + .15 provenance + .15 verified_effect + .15 recency`。
- 修复 004 迁移、owner 隔离、事务、连续事件序号、Prompt 预算、usage receipt、
  exact-substring verifier、worker recovery、G3 API、幂等冲突和 active edit/pause/resume。
- Orchestrator 在 Provider 前完成检索、持久化和注入；Mock/real adapter 使用相同的
  `memory_context` / `usage_ids` 接口，Mock actual prompt token 保持 `null`。
- 前端加入严格 G3 parser、snapshot/SSE 恢复、trace/usage reducer、Chat 证据面板和
  最小 active/paused 记忆详情、编辑、版本及 usages 页面。
- 原 Day 4 draft fixture 保持 draft；新增 owner-only review、30-case 可执行 fixture 和
  REST-only metadata EvalRunner，不声明两人联合批准。
- 删除 `.claude/settings.json` 和未使用的重复 G3 event 模块；修正 handoff 顶部事实，
  原始声明仍作为历史记录保留。
- 双浏览器验收中额外发现 G2 worker 的 canonical scope 没有投影 `language`、
  `framework`、`project_key` 和 `concepts`，使新确认的 active v1 在相似任务中只能得到
  `0.629–0.670`，无法跨过 `0.68` 阈值。所有者在 `e7c9b5c` 修复该 P0，并在
  `c321824` 加入真实的“feedback → candidate → active v1 → selected/injected”API 回归。

## 4. 本地门禁证据

| 门禁 | 本轮结果 |
|---|---|
| Day 4 REST EvalRunner（真实本地 API） | exit 0，30 passed / 0 failed；重复运行隔离已验证 |
| `pip check` | exit 0，No broken requirements found |
| Ruff check / format | exit 0；`All checks passed`，69 files formatted |
| 后端 pytest | exit 0；403 passed in 136.17s |
| Alembic | 唯一 head 004；fresh `->003->004->003->004` 全部 exit 0 |
| Fixture validator | exit 0；Day 1/2/3 与 Day 4 30-case 均通过 |
| OpenAPI 再导出 | SHA-256 前后均为 `2045BC8C3E9A91A9C25EC7997196E43F0981D6A05E6502E3A52B759FC6274B5A` |
| 前端 typecheck / lint / build | 均 exit 0；Vite 生产构建 53 modules |
| 前端 Vitest | exit 0，8 files / 49 tests passed |

最终本地命令均在 `c321824` 代码候选上执行。首次在受限沙箱内运行 Vitest 时，
esbuild 子进程得到 Windows `spawn EPERM`；使用同一 `npm test` 命令在获准环境复核后，
49/49 全绿，因此不把沙箱错误算作产品失败。

## 5. Docker、Chrome、Edge 与隐私证据

### 5.1 Docker

- Docker Desktop daemon 未要求账号登录。最终镜像为 `memtrace:day4-g3`，Compose project
  为 `memtrace-d4-g3-gate`，宿主端口 `18040`；构建继续使用
  `pip --require-hashes --no-deps`，exit 0。
- cold/recreate 后 `/health` 为 `ok`，`/ready` 为 `ready`，`provider_mode=mock`，
  readiness 的 config/session/data/provider/database/migration 检查全部符合 Mock 门禁；
  容器内 Alembic current 为唯一 `004_g3_retrieval_usage (head)`。
- 最终镜像上 G1 `scripts/day1/smoke.ps1` exit 0；Day 3 REST Eval 为
  30/30 fixtures、2/2 smoke；Day 4 REST Eval 为 30 passed / 0 failed。
- `docker restart` 后 readiness 恢复，持久计数可读；随后不删除卷执行 `compose down/up`，
  前后 `(tasks, traces, usages, events)` 均为 `(156, 156, 51, 2116)`。恢复后再次运行
  G1、Day 3 Eval 和 Day 4 Eval，三者均 exit 0。
- 容器日志按合成正文、memory section、task/feedback/rule/output 字段、cookie、auth 和
  secret 标记扫描，exit 0，仅保留 metadata。`SESSION_SECRET` 每次在进程内随机生成，
  未写 `.env`、未提交；测试期间一次诊断命令误把当时的容器环境输出到本地工具结果，
  随后立即以新随机 secret 重建容器使旧值失效，且该值未进入文件、日志、截图或 Git。

### 5.2 Chrome 与 Edge

- Chrome：Google Chrome `151.0.7922.174`，UA 为 Chrome `151.0.0.0`；主用户
  `blank_demo`，隔离用户 `seeded_demo`。
- Edge：Microsoft Edge `151.0.4129.101`，UA 为
  `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)
  Chrome/151.0.0.0 Safari/537.36 Edg/151.0.0.0`；主用户 `seeded_demo`，隔离用户
  `blank_demo`。
- 两套真实浏览器均完成 demo 用户切换、服务端自动分类、G2 feedback/evidence/active、
  相似任务 trace、selected/injected、receipt、verification、user effect、memory off、
  pause/resume、刷新恢复、版本/usages 和跨用户 UI 清理。Edge 还在修复前诚实复现
  `below_threshold`，修复后同路径得到 `scope=0.850`、`semantic=0.746`、
  `final=0.811`、selected/injected 1 和 applied receipt；pause 后为
  `status_not_active` 且 selected/injected 0，resume 后恢复。
- Chrome 最终 console 只有首次无 cookie 的预期 session bootstrap 401；Edge 最终复核
  console 为 0 error/0 warning。Edge trace 中另有容器刻意重建、secret 轮换时产生的
  session 401 和旧 task 隔离 404，重新登录后恢复；未发现非预期 network 失败。
- 合成截图与 trace/network 保存在本机忽略目录
  `output/playwright/day4/{chrome,edge}`；`.playwright-cli/`、`output/` 已加入
  `.gitignore`，浏览器 profile、截图、trace、network 和评测输出不提交 Git。

## 6. 最终候选、竞态检查与发布

- 最后已验证代码提交为 `c321824`；本报告提交仅包含文档、Compose/README 标识和本地
  证据忽略规则，不改变已验证的产品逻辑。
- 协作者精确 head `611034b779ed9e2e007981ca0a76d66f11f2f471` 必须在最终 head 的
  祖先链中；最终 fetch 后 `origin/main` 必须仍等于已审查 base
  `32ea8b353bef4133851c5686e35de05022ae2147`，否则不得直接推送。
- 发布只能由已登录的 `W-JOSLIN-X` 使用普通 `git push origin HEAD:main`；不 force、
  不创建日常 PR、不要求协作者审批、不删除协作者分支、不使用 `integration/day2`。
- 报告提交后的复跑、秘密扫描、Docker 专属项目清理、最终 fetch、普通 push 和远端 SHA
  核验将追加到发布操作的终端证据；在远端 SHA 相等前，本节不宣称 Day 4 已发布。

## 7. 明确非范围

BGE、真实 Provider smoke、Day 5 搜索/冲突裁决/merge/Pack/归档/永久删除、Day 5
60 条最终数据集均不是 Day 4 Mock G3 门禁，本文不把它们表述为已完成。
