# Day 5 所有者整合与发布报告

## 1. 不可删除的接管失败基线

本节记录成员 B 在修改成员 A 代码前，依据远端 Git 对象、成员 A handoff 与原始分支
内容独立核对得到的失败。后续修复结果只能追加，不能覆盖或删除这些事实。

- 2026-08-25 接管时 `origin/main` 为
  `b41afc51f1c0c2d43ebd3f61548e46faabb8d51d`，协作者远端 head 为
  `d40f01c448434afff12c1e0a7c939000f95f3f7c`，实际 merge base 与 main 相同；分支领先
  7 个提交、落后 0 个提交。
- `MEMBER_A_HANDOFF.md` 声明 base `47cfb07cb544267ab91acf18f30657c9500e6986`、
  head `fb8f2daf361c6fe9e7d4a760e62c5629147203c2`、5 个新增提交，均与远端 Git 对象不符。
  下文不把 handoff SHA 或提交数量当作完成证据，原声明保留为历史记录。
- handoff 自报后端 425 collected、354 passed、54 failed、17 errors；G4 integration
  6 collected、0 passed、6 errors。其 Ruff 结果只是“假设通过”，不是实际门禁证据。
- 协作者范围实际为 7 个提交、21 个变更文件；包含非产品产物 `fix_db_models.py` 和根目录
  重复的 `requirements.in`，且多处文档尾随空格导致 `git diff --check` 失败。
- `apps/api/requirements.in` 使用不存在的 `rfc8785==1.0.0`，未同步带 hash 的
  `requirements.lock`；当前官方可用版本为 `0.1.4`。
- 未发布的 005 使用随机 revision `0b5da423ff7c`，而不是冻结的
  `005_g4_memory_center_pack`；downgrade 先删 import batch 表再删 MemoryCard 外键，且尝试
  删除未创建的索引。tombstone 可空性、batch 字段及 relation same-owner DB 约束不完整。
- 实际 FastAPI 缺少 archive、restore、version-diff、conflict list/detail 路由，OpenAPI
  未随 G4 代码更新，契约投影不能视为同构。
- permanent delete 错误访问不存在的 `RetrievalTraceModel.memory_id`，并向非空正文列写
  `None`；source-task delete 只清空 task text，未执行冻结的依赖删除矩阵。
- conflict create/resolve 缺少完整 owner、version、state、scope-overlap 校验，四种裁决未
  真正执行相应状态与关系变更；manual merge 错误伪装为低信任 import。
- Pack external id 暴露本地 `mem_*`；datetime canonicalization、import provenance、raw-byte
  安全检查和二次校验不完整。preview token 使用 `sha256(secret:payload)` 并编码明文 payload，
  不是冻结的 owner-bound 43 字符 HMAC-SHA256 token。
- 新增 G4 integration 测试只直接调用 repository，缺少公开 API 证据，并存在缺少 import、
  不完整数据和错误预期；因此测试文件存在不能证明 G4 可用。

## 2. Git 接管证据

- 整合分支：`codex/day5-owner-integration`。
- 普通 `--no-ff` merge commit：
  `1f2bce8ebfde94c70458b3b2c95b2dc61b2e66f4`。
- main base 与协作者 head 均为 merge commit 的祖先；协作者作者和 7 个提交完整保留，未
  rebase、squash、amend，也未向协作者分支追加提交。
- 未创建日常 PR，未使用 `integration/day2`。

## 3. 原始命令复测

所有命令均在 merge commit `1f2bce8ebfde94c70458b3b2c95b2dc61b2e66f4` 加上本报告
初始文件、尚未修改产品代码时运行：

| 门禁 | 原始结果 |
|---|---|
| `python -m pip check` | exit 0；但 venv 尚未安装协作者新增且版本错误的 rfc8785，因此不能证明 lock 可安装 |
| `python -m ruff check apps/api` | exit 1；114 errors |
| `python -m ruff format --check apps/api` | exit 1；5 files would be reformatted，68 files already formatted |
| `python -m pytest apps/api/tests -q` | exit 1；425 collected，408 passed、17 failed，257.06s |
| `python -m alembic ... heads` | exit 0；但错误 head 为 `0b5da423ff7c` |
| fixture validator | exit 0；仅覆盖既有 Day 1–Day 4，尚无可执行 Day 5 fixture |
| `git diff --check origin/main..HEAD` | exit 1；`CONFLICT_FIXTURE_REVIEW.md` 多处尾随空格 |

17 个 pytest 失败包括 4 个迁移/旧 head 断言、6 个 G2 Memory API 回退、4 个 G4
repository 测试以及 3 个 OpenAPI 测试。OpenAPI 失败的直接原因是 `used_after` 使用未解析的
`datetime` ForwardRef；G4 测试还暴露 permanent delete、source-task delete、Pack
canonicalization 和 Admission Guard 测试构造错误。修复后结果将在第 5 节追加，不能替换本节。

## 4. 所有者修复与成员 B 范围

- `d84c2d8`（`fix(day5)`）同步并冻结 1.4.0 契约投影，修复 005 线性迁移、
  owner-scoped 约束、删除矩阵、四种 conflict 裁决、manual merge、Pack RFC 8785/HMAC
  preview/commit、安全限制和公开 API；恢复并验证 G1–G3 约束。删除非产品产物
  `fix_db_models.py` 与根目录重复 `requirements.in`。
- `3b75c09`（`test(day5)`）补齐 G4 API、事务回滚、迁移、owner 隔离、Pack 安全和
  G1–G3 回归测试，原空缺不再由 repository-only 测试冒充端到端证据。
- `ab47532`（`feat(web)`）完成 Memory Center 搜索/筛选/分页/详情、版本 Diff、生命周期、
  两类删除、四种 conflict、用户填写 manual merge、Pack round-trip 与只读 Evals manifest；
  新增严格 G4 parser、API/reducer 状态恢复和按操作隔离的幂等 key。浏览器实测后又修复了
  新任务残留 usage-effect 错误，以及 Pack export 误包含 candidate/deleted 卡导致 404 的问题。
- `2eec457`（`test(eval)`）保留原 draft，新增 8 条 conflict、12 条 Pack/security 可执行
  fixture，冻结 24/60/12/8、源 SHA-256 与 `g4_split_v1`，并提供只经公开 REST API 的
  Day 5 EvalRunner；没有把成员 B 核验写成双方联合批准。
- Dockerfile/Compose 更新为 `memtrace:day5-g4`，Docker lock 安装仍使用
  `--require-hashes --no-deps`；默认门禁保持 `MOCK_MODE=true`。

## 5. 本地门禁证据

最终产品候选（报告提交前）上的独立结果如下，命令均 exit 0：

| 门禁 | 实际结果 |
|---|---|
| `apps\\api\\.venv\\Scripts\\python.exe -m pip check` | No broken requirements found |
| `... -m ruff check apps/api` | All checks passed |
| `... -m ruff format --check apps/api` | 75 files already formatted |
| `... -m pytest apps/api/tests -q` | 434 passed，34 个 test files，282.08s |
| `... -m alembic -c apps/api/alembic.ini heads` | 唯一 `005_g4_memory_center_pack (head)` |
| `... scripts/day1/validate_fixtures.py` | Day 1/2/3、Day 4 30、Day 5 conflict 8 + Pack 12 全部通过 |
| `npm run typecheck` | exit 0 |
| `npm run lint` | exit 0 |
| `npm test` | 9 files、53 tests passed |
| `npm run build` | exit 0；生产 bundle 构建成功 |

- fresh DB、`004 -> 005 -> 004 -> 005`、stale revision readiness 503 和唯一 current head
  readiness 已由迁移/应用测试覆盖并通过。
- Pydantic、JSON Schema、examples、OpenAPI 与 TypeScript strict parser 已同步；OpenAPI 和
  G0 schema 连续导出两次均为零 diff。最终 SHA-256 分别为
  `F5867C723C27FEFF5177E92C978ACC91473201A7A8B21C1A4E4E0F2BAACFB622` 和
  `F6A7D2FC25A41496441A2F2CB2F64092791F757ADA03EBBF28DE586C72B1A9FF`。
- 本地真实 REST API 上 Day 3 Eval 为 30/30 + 2/2、Day 4 为 30/30、Day 5 为 20/20；
  runner 只输出 ID、受控状态/计数/分数和失败码，不输出正文或 token。
- 并发幂等、冲突、事务回滚、event seq/SSE、worker recovery、cross-owner 与
  metadata-only 边界均由本轮通过的测试覆盖。构建通过不替代下面 Docker 与浏览器证据。

## 6. Docker、Chrome、Edge 与隐私证据

### Docker

- Docker Desktop client/server 正常，未要求额外登录。使用唯一 Compose project
  `memtrace-d5-g4-gate`、端口 `18050`、镜像 `memtrace:day5-g4`、专属新卷和仅在当前进程
  生成且未回显/落盘的 `SESSION_SECRET`。
- cold build 的 hashed lock 安装、自动迁移、容器 health、`/api/v1/health`、
  `/api/v1/ready` 全部通过，ready 报告唯一 005 head 且 `provider_mode=mock`。
- 容器真实 API 上两轮（前端浏览器修复前与最终重建后）均得到 Day 3 30/30 + 2/2、
  Day 4 30/30、Day 5 20/20。
- `docker compose restart app` 和 `down` 后保留专属卷再 `up -d` 均恢复相同数据：
  event_log 1282、import_batches 5、memory_cards 37、memory_relations 12、memory_usages 54、
  memory_versions 26、retrieval_traces 72、tasks 72。
- 对 synthetic canary、query、memory title、`preview_token`、`SESSION_SECRET`、`task_text`
  和 memory section 的日志扫描命中均为 0。最终只删除该 project 及其专属卷。

### Chrome 与 Edge

- 真实 Google Chrome 151（UA `Chrome/151`）和 Microsoft Edge 151（UA `Edg/151`）使用
  独立 session 访问 `http://127.0.0.1:18050/`；截图和 trace 保存在忽略目录
  `output/playwright/day5/chrome` 与 `output/playwright/day5/edge`，未提交 Git。
- Chrome 以 `blank_demo` 为主：完成 G2 candidate/evidence/active、G3 同 owner 检索与
  selected/injected/receipt、applied/not_observable/unknown、helpful/harmful、memory off
  零计数、edit v2、pause/resume、archive/restore、prefer、separate_scopes 和跨用户清理。
  对 unknown receipt 提交 stale 得到契约预期 409；随后已修复该错误跨任务残留。
- Edge 以 `seeded_demo` 为主：完成匿名 Pack 下载、同 owner duplicate 分类、XSS suspicious
  纯文本渲染、合法 unique Pack preview/commit（imported paused）与永久删除；通过公开 API
  建立两组同 owner 冲突后，在 UI 完成用户填写正文的 merge 和 pause_both；完成来源任务删除
  并核得仅受影响卡 `evidence_missing`，Evals 显示 24/60/12/8 且未运行指标为 N/A。
- 两浏览器均验证刷新/导航恢复、用户切换后旧 preview/token/draft 状态清除与跨 owner 404。
  Chrome 最终 console 无非预期错误；Edge 在为冲突造数时出现受控 409，成功造数后的最终页面
  无静态资源或运行时 console 错误。以上 409 保留为真实测试事实，不写成全程零失败。

## 7. 最终候选、竞态检查与发布

- 协作者 head `d40f01c448434afff12c1e0a7c939000f95f3f7c` 必须是最终 HEAD 祖先；本报告
  提交后将重新运行完整本地自动化、OpenAPI zero-diff、`git diff --check`、秘密与产物检查。
- 随后重新 `git fetch --prune origin`。若 `origin/main` 不再等于已审查 base
  `b41afc51f1c0c2d43ebd3f61548e46faabb8d51d`，先普通 `--no-ff` merge 并重跑受影响门禁；
  绝不 force。
- 报告提交前最后一个产品/测试代码 SHA 为
  `2eec457`（完整 SHA 由本仓库 Git 对象保存）；报告提交本身只增加/更正文档。push 命令
  退出码与推送后远端 SHA 由发布操作的终端证据记录。远端 `main` 与本地最终已验证 HEAD
  完全一致前，不宣称 Day 5 完成。

## 8. 明确非范围

真实 Provider、BGE、自动 merge 文案、rollback、逐卡 import 和动态评测 API不属于 Day 5
Mock G4 门禁，本文不把它们表述为已完成。
