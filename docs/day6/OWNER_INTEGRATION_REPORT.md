# Day 6 所有者整合与验收报告

> 状态：整合进行中。本文先保存成员 A 分支的独立失败基线；修复后的证据只追加，不删除或覆盖本节。
>
> 所有者 / 最终发布者：`W-JOSLIN-X`
>
> 日期：2026-08-30

## 1. 接管事实

- 接管时 `origin/main`：`bb69aa90a9ddb3c0a84f02b5a58dd92b7094f922`
- 协作者分支：`origin/feat/a-d6-llm-memory-core`
- 远端实际协作者 head：`9ef1c6f8b276e7a267517e4ce5d811b66a4ae5ef`
- 实际 merge base：`bb69aa90a9ddb3c0a84f02b5a58dd92b7094f922`
- 分支关系：协作者领先 5 个提交、落后 0 个提交
- 所有者整合分支：`codex/day6-owner-integration`
- `--no-ff` merge commit：`9710467637f6698668dd181a971e955a56125abc`
- 已验证 main base 与协作者 head 都是 merge commit 的祖先；未 rebase、squash、amend 或改写协作者历史。

两份 handoff 均不是远端事实：`MEMBER_A_HANDOFF.md` 记录 head `89f70771...`，`MEMBER_A_FINAL_HANDOFF.md` 记录 head `c15dcb07...`，且都写着“尚未 push”；远端实际 head 是 `9ef1c6f8...`。本文和最终验收只使用远端 Git 对象作为证据，旧声明保留为历史并将在文档顶部追加更正。

## 2. 修复前独立失败基线（永久保留）

成员 A 的代码只能作为原型历史接纳，不能作为完成证据。所有者在只读快照中独立复测得到：

- `pip check`：通过。
- Ruff：55 个错误，其中包含未定义名称。
- `ruff format --check`：11 个文件需要格式化。
- pytest：434 collected，307 passed、110 failed、17 errors。
- Alembic 表面显示唯一 `006_conversation_first_memory` head，但 fresh upgrade 在 006 因缺失 `_rebuild_memory_versions_with_v2_actions` 直接 `NameError`；downgrade helper 同样缺失。
- `scripts/day6/engineering_tests.py`：2 passed、6 failed、1 warning；脚本的仓库根路径和 Alembic 参数错误。
- `scripts/day6/check_completeness.py`：在 Windows GBK 控制台崩溃，并含返回固定 `True` 的占位检查。
- committed OpenAPI 过时；重新导出会产生差异，第二次导出才稳定。
- A 没有新增或修改 `apps/api/tests`，不能用脚本存在代替正式测试。
- A 没有同步共享 JSON Schema、examples、TypeScript 类型或 runtime parser，也没有实现 Day 6 前端。
- 真实 DeepSeek 只由 handoff 声称运行过简单问候和 JSON greeting；16-case 真实语义评测没有运行，本轮尚未独立验证 Key、模型、额度或 usage。

代码审计还确认：

- Provider 使用宽松结构化解析，未知字段被丢弃；缺失 usage 被伪造为 0。
- Prompt hash helper 未实际使用，完整多轮 history 和受控工具调用未接入主链。
- Applicability Judge 与 Effect Judge 在 Orchestrator 中为 `None`，新 hybrid retrieval 未接入。
- 旧检索在 LLM 裁决前就持久化 selected/injected；旧 substring verifier 仍形成产品 effect 结论。
- Orchestrator 仍带固定目标、固定下一步和旧任务分类遗留行为，正常多轮对话尚未实现。
- Reflection worker 缺少完整 shutdown；claim、stale recovery、事件和变更事务不满足冻结边界。
- Worker 写入虚假 `fdbk_none` / `job_none` 外键，证据也未精确绑定当前 user turn。
- same-owner 复合外键、per-card judgment 唯一约束、prompt hash 长度和 job 状态字段存在错误。
- v2 memory list/edit/confirm/dismiss 查询或更新了错误的 legacy 状态/字段；缺少 `GET /api/v2/memories/{id}/events`。
- semantic runner 直接 import 后端、把后续用户轮次当 feedback、忽略 assistant 轮次、复用固定幂等 key、错误处理 memory-off，并会输出记忆正文。
- 当前 Chat 页面仍是编程任务表单和固定任务体验，没有普通多轮聊天与右侧实时记忆栏。
- 根目录 `LLM_FIRST_CONVERSATION_MEMORY_AGENT_REDESIGN.md` 是 `docs` 正式文件的重复非产品副本，后续由所有者提交删除。

## 3. 所有者修复结果

最后一项产品代码提交为
`d0d2658b47d5b1c06898fddffa7e5d7cd0fb8b46`。本报告提交只包含文档与历史更正，
因此它是“最后已验证代码 SHA”，不是最终远端 `main` SHA。

### 3.1 契约、迁移和数据一致性

- G5 契约冻结为 `2.0.0`，同步了实际 FastAPI OpenAPI、Pydantic、
  `g0-api.schema.json`、`events.schema.json`、`g5-llm.schema.json`、严格
  TypeScript parser、audit manifest 和合成 examples。
- examples 明确标为 `synthetic_contract_examples_not_semantic_evidence`；其通过只能证明
  结构同构，不能证明语义能力。
- 修复未发布的 `006_conversation_first_memory`，补齐 upgrade/downgrade helper、复合 owner
  约束、per-memory judgment 唯一性、完整 prompt hash、reflection/evidence/message/event 数据。
- fresh DB、`005 → 006 → 005 → 006`、stale readiness 503 与唯一 006 head 均由正式测试覆盖。
- 旧 G1–G4 卡与 G5 conversation memory 通过显式字段和 v2 查询隔离，不会自动成为 G5
  active memory。

### 3.2 LLM-first 主链

- DeepSeek Provider 使用 Responses API 流、严格 `json_schema`、真实 usage、有限且受控的
  retry；缺 usage、非法 Schema、认证/额度/模型错误均 fail closed，不伪造零 token，也不回退
  Mock/关键词路径。
- `/api/v2` 每轮执行完整 history → LLM applicability → 100/300 token memory section →
  real chat → reflection → consolidation → effect。每一阶段保存 model、prompt hash、actual
  token、latency 和受控错误码，不保存 prompt、正文、答案或原始供应商错误。
- active memory 不超过 50 时全部交给 LLM applicability；超过 50 时 FTS/BM25 只缩减候选，
  不决定 applicable/injected/effect。
- 正则只用于危险内容 Admission Guard、ID/Schema、证据精确绑定和 FTS token 化；answer
  segment 只用于把 LLM 选择的 evidence ID 映射回连续原文。它们不替代 LLM 的语义结论。
- 旧 TF-IDF、substring verifier 和工程 Mock 仍保留在 G1–G4 兼容/故障测试路径，但不进入
  默认产品 `/api/v2` conversation 主链。v2 请求不接受 `scenario`；数据库中固定的
  `scenario=other` 只是旧非空列兼容值，不是对对话或记忆的分类结果。
- Worker 实现原子 claim、lease、stale recovery、有限 retry、shutdown、单事务状态变更和
  commit 后事件广播；证据精确绑定原始 user message，不再使用虚假 feedback/job ID。

### 3.3 API、恢复和前端

- 完成普通多轮 conversation/task/turn API、task/owner persistent events、memory
  list/detail/edit/confirm/dismiss/pause/resume/events、reflection job、stage usage 和 effect
  feedback；所有写接口幂等，跨 owner 与不存在统一 404。
- owner memory event 单页上限锁为 100，前端按 `next_seq` 连续 drain；修复 owner 超过 100
  events 时首次请求 500 的真实浏览器问题。
- task snapshot 增加持久化 `last_turn`，可恢复 decisions、effect、actual stage usage 和
  provider/model；修复刷新后只恢复消息/卡片、丢失本轮判定和 token 的问题。
- 默认 UI 是普通聊天 + 右侧实时记忆栏，支持 preference/rule/experience、pending/active、
  编辑 kind/content/applies_when 和 confirm/dismiss/pause/resume。用户、session、task 切换会
  取消旧请求/SSE并清空旧 owner 状态；模型文本全部按 React 纯文本渲染。
- 修复 coexist 提示词的作用域扩大问题：新 coexist 卡只保留候选自身的净新增 scope，不复制、
  拼接或扩张旧卡；Applicability 明确要求 `applies_when` 中每个正向限定条件都满足。

## 4. 确定性工程证据

以下均在最后产品代码候选上实际运行；Fake/Mock 结果只算工程证据。

| 命令 | 退出码 | 实际结果 |
| --- | ---: | --- |
| `python -m pip check` | 0 | `No broken requirements found` |
| `python -m ruff check apps/api` | 0 | all checks passed |
| `python -m ruff format --check apps/api` | 0 | 82 files formatted |
| `python -m pytest apps/api/tests -q` | 0 | 首轮 465 passed；随后新增 1 个 G5 example 合同测试并单独通过，报告提交后的最终全量复跑见第 9 节 |
| `python -m pytest test_day3_migration.py test_health.py -q` | 0 | 16 passed，覆盖 fresh/cycle/stale readiness |
| `python -m alembic -c apps/api/alembic.ini heads` | 0 | `006_conversation_first_memory (head)` |
| `python scripts/day1/validate_fixtures.py` | 0 | G1–G5 fixtures、16 semantic、8 A/B 和 G5 examples 全部通过 |
| `npm run typecheck` | 0 | TypeScript project build passed |
| `npm run lint` | 0 | zero warnings/errors |
| `npm test` | 0 | 12 files、63 tests passed |
| `npm run build` | 0 | 53 modules，production build passed |

Vitest/Vite 第一次在文件系统沙箱内因 esbuild `spawn EPERM` 启动失败；同一命令在获准的本机
子进程权限下为 63/63 和 build 0 退出。该失败没有通过改配置或跳过测试掩盖。

真实 OpenAPI 使用实际路径 `apps/api/scripts/export_openapi.py` 连续导出两次，并在每次之后
运行 `scripts/day6/sync_g5_contracts.py`：

- OpenAPI SHA-256：`EF97AFAD2461314B47D74805AF1F1922DBFD38D8D5C454454FB11BE587688380`
- REST Schema SHA-256：`552E3261EC5BFD2AAA64921149E91C0D14CD0A3087408832AC6BD8E0417F0FA1`
- LLM Schema SHA-256：`038B15D48953CC748224B153200481111BEE4C622A8528B12927E513C89357D3`
- 第二次导出：三者全部零 diff。

旧 handoff 写的根路径 `scripts/export_openapi.py` 实际不存在；第一次照抄旧路径得到 exit 2，
因此不作为证据，上述实际路径的两次 exit 0 才是证据。

## 5. 真实 DeepSeek 语义证据

### 5.1 配置与检查点 A

本地 `.env` 有真实 Key/模型，但当时 `MOCK_MODE=true`；首次 preflight 因此按设计返回
`REAL_PROVIDER_NOT_CONFIGURED`。所有真实门禁均在当前进程显式设置 `MOCK_MODE=false`，且只输出
`has_llm_api_key=true`，没有修改、打印或提交 Key。没有在失败后回退 Mock。

修正进程配置后：

- `GET https://api.deepseek.com/models`：200；可用模型包含并实际选中
  `deepseek-v4-flash`。
- 最小严格 Responses：real，actual input/output/total 为 `125/5/130`，latency 4320 ms，
  prompt hash 存在。

组件探针全部使用同一真实模型和 actual usage：

| 阶段 | 受控结果 | total tokens | latency ms |
| --- | --- | ---: | ---: |
| chat | succeeded | 600 | 8427 |
| reflection | mutate / 1 preference | 1393 | 1455 |
| consolidation | add | 1066 | 1314 |
| applicability | applicable / semantic_match | 769 | 1170 |
| effect | applied / exact segment | 718 | 1040 |
| scope reflection | one atomic scoped operation | 1437 | 1778 |
| scope consolidation | coexist | 1183 | 1430 |
| mismatched scope | irrelevant | 869 | 998 |
| matched scope | applicable | 861 | 1149 |

### 5.2 16-case × 2 与 A/B

- 最早完整本地 semantic：21/32，且安全项 1 次失败；修复 extraction、event buffer、严格
  Schema repair、coexist scope 和 runner 后，本地最终为 32/32、precision 1.0、安全失败 0。
- 最早完整 A/B 只有 3/8 memory-on 胜出；修复真实主链与 effect/盲评后，本地最终 8/8，
  关键回退 0。
- Docker 在复用浏览器污染卷时一度只有 2/32；原因是 runner 没有拒绝 owner 既有 active
  memory。现 runner 开始前检查两个 demo owner 的 active baseline，非空时以
  `ACTIVE_MEMORY_BASELINE_NOT_EMPTY` fail-fast。只删除标签属于专属测试项目的三个卷并 cold
  start 后，最终 Docker semantic 为 32/32、precision 1.0、安全失败 0。
- Docker semantic actual total tokens 为 236644，累计 stage latency 482317 ms。
- Docker A/B 为 8/8 memory-on 胜出、关键回退 0；workflow actual tokens 65000、blind judge
  actual tokens 14164，对应累计 latency 169658/14971 ms。
- `g5-12` 额外锁定 injected=1、applicable=1、irrelevant=1，防止 coexist 两个 scope 同时误激活。
- runner 无法连接 API 时现输出 `overall_status=failed`、
  `run_failure_code=REST_TRANSPORT_ERROR` 并返回 1，不再用 0/0 摘要造成“看似通过”。

原始合成对话和盲评材料只存在于 Git 忽略的 `output/day6`，仓库只提交 case、允许集合和
metadata-only runner。

## 6. G1–G5 递增与 Docker 证据

专属 Compose 项目为 `memtrace-d6-g5-real-gate`，镜像 `memtrace:day6-g5-real`，端口 18060，
`provider_mode=real`，数据库唯一 head 为 006。`SESSION_SECRET` 为当前进程随机值，Key/secret
只经进程环境进入容器。

- G1 real smoke：exit 0，model `deepseek-v4-flash`，actual input/output 为 85/65，
  first-token 1601.70 ms。
- G2 Day 3 REST Eval：21/21 fixture、2/2 smoke，9 项明确标记 engineering-only skipped。
- G3 Day 4 REST Eval：30/30。
- G4 Day 5 REST Eval：20/20；安全拒绝 case 的 failure code 是预期结果，顶层 failed=0。
- G5：Docker 32/32 semantic 和 8/8 A/B，见第 5 节。

持久化与恢复：

1. restart 前关键表计数为 tasks 152、runs 156、reflection jobs 82、judgments 108、cards 72、
   events 1491；restart 后完全相同，随后新 real G5 case 1/1。
2. `docker compose down` 不带 `-v` 后三个专属卷仍全部存在；up 后关键表计数逐项不变。
3. 第一次 up 漏传 `MEMTRACE_PORT`，容器按 Compose 默认绑定 8000，导致 18060 连接拒绝；确认卷和
   数据无损后，保卷 force-recreate 到 18060。该过程错误作为操作证据保留，未伪装为 readiness
   通过。
4. 恢复到 18060 后 host `/ready` 为 ready/real，再运行新的 real G5 case 1/1。
5. 最终关键表计数为 tasks 156、runs 160、reflection jobs 86、judgments 114、cards 74、
   events 1509；精确 Key 日志命中 0，正文/secret marker 命中 0。

所有 REST runner 访问显式本机 API 时禁用工作站系统代理。此前 `httpx` 自动读取 Windows 系统
代理，导致健康的 `127.0.0.1` 被代理成 502；`trust_env=false`/空 ProxyHandler 后，同一 G1
真实 smoke 通过。DeepSeek 外网请求未使用这项本机 API 设置。

## 7. Chrome 与 Edge 真实浏览器证据

两套浏览器均连接 18060 的真实 Provider 容器；没有预置模型响应。

- Chrome `151.0.7922.174`，UA 为 Chrome/151；`blank_demo` 为主 owner。验证普通多轮对话、
  后台提取、编辑 kind/content/scope、跨语言复用、override、irrelevant、memory off、
  pause/resume、刷新恢复、owner 切换和跨 owner 404。
- Edge `152.0.4191.53`，UA 为 Edg/152；`seeded_demo` 为主 owner。验证真实 supersede、
  coexist、关系型/NoSQL scope 隔离、memory off、刷新恢复、owner 切换和跨 owner 404。
- 最终两份 console 各只有 2 条预期网络错误：无 cookie 的初始 401 和刻意发起的跨 owner 404；
  没有未解释 5xx。
- Chrome 刷新前后保持 `applicable / injected / applied` 与 actual token 2268；Edge 修复后的
  scope probe 恰有一张 applicable/injected/applied、一张 irrelevant/not injected，并在刷新后
  保持 actual token 4452。
- Edge 的早期真实流程暴露 coexist 合并旧 scope 的错误；修复 prompt 和 extraction 后重新跑完整
  scope 流。含正文的失败截图被隐私审查拒绝保存，没有绕过；最终受控枚举、network trace 和
  metadata 作为证据。

截图、console 和 trace 位于 Git 忽略的 `output/playwright/day6/chrome` 与
`output/playwright/day6/edge`，不会提交浏览器 profile、合成正文或网络 body。

## 8. 提交、隐私与范围

所有者提交边界：

1. `9710467637f6698668dd181a971e955a56125abc` — merge：保留 A 的精确历史；
2. `5c4b71a` — `fix(day6)`：Provider、LLM 主链、契约、006 和数据一致性；
3. `eae4b1a` — `test(day6)`：正式测试、strict examples、16/8 fixtures 和 real runners；
4. `d0d2658` — `feat(web)`：普通对话、实时记忆侧栏、严格 parser 和恢复。

删除的根目录设计文档是 `docs/LLM_FIRST_CONVERSATION_MEMORY_AGENT_REDESIGN.md` 的重复副本；
两份成员 A handoff 只在顶部追加真实 base/head/push 状态更正，原错误声明保留为历史。已验证 A
实际 head 是当前候选的祖先。

秘密扫描中 README 的 Key 行均是明确占位符，测试文件只含 fake/test 值，handoff 命中的是
`has_llm_api_key=True` 字段名；没有 `sk-*`、Bearer、`.env`、SQLite、浏览器 profile、output、
模型正文或 secret 被纳入 Git。

Day 6 明确不声称完成真实 Provider 之外的模型兼容、自动生成 merge 文案、逐卡 import、动态 eval
API 或 Day 7 能力。真实模型有统计波动，因此 16×2、A/B 和安全 case 是发布门禁而不是“一次 smoke
即可”的保证。

## 9. 报告提交后的最终发布门禁

本节将在本报告首次提交后追加最终全量复跑、竞态 fetch、普通 push 与远端 SHA。只有该节记录的
所有命令退出 0，且远端 `main` 等于本地已验证 HEAD，状态才可改为“Day 6 完成”。
