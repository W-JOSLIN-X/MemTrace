# MemTrace Day 2–Day 7 双人执行与交付计划

> 状态：自 2026-08-22 起作为 D2–D7 的双人执行入口。  
> 成员 A：`zlbk-wxy`，后端、Agent 与记忆引擎主责。  
> 成员 B：`W-JOSLIN-X`，前端、产品、评测与集成主责。  
> D2 例外：成员 B 接管 PR #2 的剩余修复、自动分类、前端闭环、容器和整合；成员 A 负责最终复核与审批。

## 1. 使用方法与真相源

遇到描述不一致时，按下列优先级判断，不根据交接结论猜测：

1. 用户当前明确要求，尤其是“任务类别由系统自动识别，用户不选择”；
2. 可执行契约、OpenAPI、数据库约束和自动测试；
3. 本文与 `docs/day2/AUTO_CLASSIFICATION_DECISION.md`；
4. `Universal_Feedback_Memory_Agent_Project_Plan.md` 的已同步版本；
5. `docs/day2/HANDOFF.md` 等历史交接材料。

旧交接材料用于说明当时做过什么，不是“已经验收”的证明。每次交接都必须写明实际 head、命令、退出码、测试数量和仍未完成项。

## 2. 固定产品决策

### 2.1 自动识别任务类别

- 用户只提交任务正文、记忆开关和当前执行约束，不提交 `scenario`。
- 服务端用确定性、本地、无 I/O、无模型调用的 `auto_rule_v1` 分类器产生 domain。
- D2 固定四个 domain：`programming_learning`、`software_development`、`general_text`、`other`。
- 数据库 `tasks.scenario` 暂时保留旧列名，但值只能来自服务端分类结果。
- UI 只读显示“系统识别场景”、规则置信度和受控理由；低置信结果诚实显示，不提供类别下拉框。
- D3 的 Feedback Compiler 同样自动判断 preference、rule、experience 和 one-shot；这些结果仍只能先成为 candidate，经用户确认后才可 active。

### 2.2 D2 与 D3 的边界

D2 只完成可靠任务指纹、持久化、恢复、反馈采集和 pending MemoryJob。D2 不实现或暗示：

- MemoryCard 或候选记忆；
- embedding、检索、注入或使用凭证；
- “已经学习”“已经记住”；
- 让用户在任务创建时选择类别或记忆类型；
- 通过真实模型调用进行任务分类。

### 2.3 P0 和降级顺序

每日先保前一天黄金路径，再增加当天最小纵向闭环。P0 未连续通过时，不做动画、批量操作、动态评测 API、BGE、自动合并文案等 P1/P2。任何降级都必须可见且不伪造成功。

## 3. 长期角色和交叉职责

### 成员 A：后端、Agent、记忆引擎

- FastAPI、SQLAlchemy、SQLite、Alembic；
- Provider、Agent 编排、工具注册和 SSE 后端；
- 反馈提取、准入、检索、注入、冲突与使用验证；
- 后端契约测试、安全测试、指标日志；
- 容器内迁移、持久卷、备份与恢复。

### 成员 B：前端、产品、评测、集成

- React 页面、状态机、EventSource 和恢复；
- 编辑反馈、候选卡、使用凭证和记忆中心；
- Mock fixtures、JSON Schema 交叉验证、黑盒 EvalRunner；
- gold 标注、负例、Docker smoke、新设备验收；
- README、演示脚本、录屏、错误和降级文案；
- 分支整合、全栈回归和发布证据。

### 每日 70/30 交叉要求

- A 至少用 30% 的评审时间确认 UI 没有伪造后端状态。
- B 至少用 30% 的开发时间覆盖 API fixture、契约、失败路径和评测数据。
- 共享 Schema、事件枚举、MemoryCard、Pack 和黄金路径必须两人批准。
- A 不通过聊天口头改字段；B 不从 UI 自行推测后端状态。

## 4. Day 2：任务记录、自动分类与反馈闭环

### 输入与当前基线

- Day 1 G0：`0468904332ffa79512ac2319f9dfd81d1f67c4cd`；
- 队友后端 PR #2：`feat/day2-backend-feedback`，核验时 head `d5afd441d11a84db85f7a434ea41a625703c097a`；
- 文档分支：`docs/day2-handoff`，核验时 head `451a452367110281da3d70dc1681a70c09fe3478`；
- 新设计：用户不选择 `scenario`，分类必须服务端自动完成。

### 成员 A

1. 保留并说明原 PR 中 SQLite/Alembic、DemoSession、owner 隔离、反馈、MemoryJob、event log 和幂等实现。
2. 不再向旧分支追加与整合分支冲突的提交。
3. 在成员 B 最后一次 push 后复核：自动分类只有一个来源、旧 `scenario` 被 422 拒绝、UI 没有虚假“已学习”。
4. 审批 D2 整合 PR和最终 `integration/day2 → main` PR。

### 成员 B

1. 保留 PR #1/#2 的完整提交祖先，建立绿色整合分支；不 squash、amend 或改写队友历史。
2. 更新 Pydantic、JSON Schema、OpenAPI、TypeScript 类型、runtime parser、fixtures 和文档到 contract `1.1.0`。
3. 实现一次性 `TaskAnalysis` 数据流：幂等重放 → store reservation → analyze once → DB/store 复用 → orchestrator 发布。
4. 修复 SQLite event seq 原子分配、store capacity 幽灵任务、session token 切换语义和 Alembic readiness。
5. 修复 Docker cold start、migration、`SESSION_SECRET` 注入和 SQLite 持久卷。
6. 实现 demo 用户切换、credentials、任务/反馈幂等、URL/sessionStorage 恢复和 SSE catch-up。
7. 实现系统分类只读展示、编辑稿、自然语言反馈、评分、采纳/拒绝和 pending MemoryJob 文案。
8. 建立 24 条 fixture，完成后端、前端、容器、Chrome、Edge 和跨用户验收。

### D2 接口冻结点

- `POST /api/v1/tasks` 请求不含 `scenario`；旧客户端发送该字段返回 422。
- `TaskFingerprint.schema_version="1.1"`，新增 `classification_source`、`classification_confidence`、`classification_reasons`。
- snapshot 的 `scenario` 明确为 server-derived；DB 同名列不迁移但只存检测值。
- Feedback、task restore、MemoryJob 最小状态在 G1 结束后冻结。

### 产出物

- contract `1.1.0` 和自动分类决策记录；
- 原子事件序号、可靠容量 admission、正确 session 切换、迁移 readiness；
- 可冷启动和重启恢复的单容器；
- demo 用户切换、恢复、编辑和显式反馈 UI；
- 24 条 fixture、全套自动测试和浏览器证据；
- D2 实际核验报告和 last-known-good commit。

### G1 门禁

`G0 + SQLite 恢复 + 自动分类一致性 + 编辑/反馈 + MemoryJob pending + 跨用户 404 + Docker cold/restart`

若任何并发、容量、session、migration、隔离或双浏览器验证失败，不得报告 D2 完成或合入 main。

## 5. Day 3：记忆提取和准入

### 输入

- D2 feedback、自动 TaskFingerprint 和任务轨迹；
- 24 条已双人复核的 learning fixtures；
- MemoryCard、MemoryVersion、Evidence 契约草案。

### 成员 A

1. migration：memory_cards、memory_versions、memory_evidence、links、relations。
2. SQLite job + 单 asyncio worker；启动时恢复 pending。
3. DiffService、normalized edit cost 和 deterministic durability detector。
4. Feedback Compiler 自动识别 preference/rule/experience/one-shot，限制每次 0–3 张卡。
5. Pydantic 校验，JSON 失败只修复重试一次。
6. 实现 Source、Reusability、One-shot、Atomicity、Scope、Evidence Gate。
7. scope 从服务端 fingerprint 派生；低置信 `other` 不得自动扩大作用域。
8. 只创建 candidate；one-shot 只存 episode disposition；resolve 后才能 active。
9. 实现 accept、edit_accept、reject、one_shot 和最小 memory list/detail。
10. 覆盖空 JSON、未知字段、证据真实性、未确认不可检索等测试。

### 成员 B

1. feedback 后的提取阶段时间线和逐卡插入。
2. candidate 卡展示 rule、scope、avoid、来源和真实状态。
3. 确认、编辑确认、拒绝、仅本次；无手工记忆类型下拉框。
4. 证据抽屉定位原反馈和 Diff。
5. 明确区分 candidate、active、episode_only、failed/retry。
6. Mock 播放成功、空结果和失败；编写状态转换 UI 测试。
7. 建立 EvalRunner REST 骨架、2 条 smoke、30 条检索 fixture 和 8 条冲突 fixture。

### 共同门禁与降级

- 13:30 用 Mock job 接通 UI；21:00 连跑 G2。
- G2：`G1 + feedback/Diff → candidate → evidence → accept/reject/episode_only`。
- worker 不稳时仍保留 DB job，可由显式继续处理触发；不得绕过状态机。
- 提取不稳时让用户编辑 candidate，不把未经确认内容写成 active。

## 6. Day 4：记忆检索和使用

### 成员 A

1. 默认 char n-gram TF-IDF；只有已有独立 smoke 证据才启用可选 BGE。
2. owner/status/validity/scope 硬过滤后再打分。
3. 实现相似度、分项得分、Top-3、当前任务覆盖和冲突排除。
4. Prompt Compiler 对全部 MemoryCard 使用 300 estimated-token 硬预算。
5. 记录 RetrievalTrace、编译文本 hash、实际 token、估算 token 和 retrieval latency。
6. 实现 UsageReceipt、exact-substring verifier 和用户“有帮助/误用/过时”接口。
7. 覆盖正例、近似负例、完全负例、paused、过期、跨用户和预算截断。

### 成员 B

1. 展示 retrieval candidate、selected、injected、excluded 及受控原因，不显示伪思维链。
2. 显示参考数、estimated memory tokens、actual prompt tokens 和 latency。
3. 展示 applied、violated、unknown；verifier 失败必须是 unknown。
4. 提供“有帮助 / 不该用 / 已过时”和 memory_mode on/off。
5. 建立 active 卡编辑、pause/resume、版本只读列表。
6. 准备不同状态卡、Pack fixtures 和凭证 UI 测试。

### 共同门禁与降级

- G3：`G2 + 相似任务 selected/injected → receipt + 无关负例 + 暂停后不召回`。
- 可选 BGE 失败时回到 TF-IDF；只有运行时回退才标 degraded。
- 检索误用高时加强 scope 和阈值，不增加未经评测的 LLM reranker。

## 7. Day 5：记忆中心、冲突和 Memory Pack

### 成员 A

1. Memory list/filter/detail/PATCH/DELETE、version Diff、usages。
2. pause/resume/archive/permanent delete 事务和来源任务删除矩阵。
3. relations、一次人工 merge、固定冲突裁决和 supersede。
4. 集成 B 提供的 Pack Schema 与纯函数校验器。
5. canonical JSON、完整 payload SHA-256、默认匿名导出。
6. import preview 校验大小、卡数、版本、恶意字段、duplicate/conflict 和 preview token。
7. commit 时重验 canonical payload/hash，单事务导入，新增卡全部 paused。

### 成员 B

1. 记忆中心搜索、筛选、详情、任务集合和使用历史。
2. 编辑、暂停、恢复、归档、永久删除二次确认。
3. 版本时间线和 Diff；D7 前不提供 rollback 按钮。
4. merge 对比、冲突裁决、Pack 导出和完整 preview。
5. `memory-pack.schema.json`、恶意/超限/重复/冲突 fixture 和纯函数测试。
6. 冻结 24/60/12/8 数据集的 train/validation/test manifest 和 hash。
7. 建立只读结果页壳，不建立动态运行 API。

### 共同门禁与冻结

- 18:00 冻结完整 v1 API、Schema、Event、页面和 Gold manifest。
- G4：`G3 + 冲突裁决 + 版本查看 + Pack round-trip + seeded_demo 隔离`。
- 非法包不能写任何卡；外部合法卡默认 paused；冲突不得静默覆盖。

## 8. Day 6：评测、场景验证和部署预演

### 成员 A

1. 使用同一模型/config/Prompt 跑四基线和 case-level trace。
2. 计算 extraction、admission、retrieval、misuse、override、latency 和 token 指标。
3. 只在 validation 调 threshold，冻结后运行 test，不根据 test 回调。
4. 只修最严重且可复现的 P0 bug，不改变契约。
5. 跑 cross-user、Pack、delete、SSE reconnect 和分类一致性套件。
6. 构建 release 镜像，验证 healthcheck、持久卷和 blank_demo staging。

### 成员 B

1. 校验冻结 manifest/hash，通过 CLI 消费实际 CSV/JSON。
2. 把结果接入只读指标表和失败案例链接。
3. 准备三场景的冷启动、学习、复用、负例和漂移演示。
4. 只修空、加载、失败、超长、冲突等 UI P0 bug。
5. 完成三分钟/五分钟脚本、备用录屏和答辩材料。

### 共同门禁

- Day 6 不新增表、API、页面或能力。
- staging 黄金路径连续 3 次；全新目录可启动；容器重启数据不丢。
- 任何未实际测试的数字标为目标或 N/A，不写成实测。

## 9. Day 7：冻结、最终部署和提交

### 成员 A

1. 09:00 后只修 blocking/P0。
2. 锁定依赖并运行全套 backend、contract、security、eval、frontend 和 Docker 测试。
3. 最终容器、persistent volume、health/readiness、restart 和 SSE reconnect。
4. 从空库和演示库分别跑黄金路径。
5. 备份 golden DB、Memory Pack、eval raw results 和脱敏日志摘要。
6. 完成运行、故障恢复、数据恢复说明；全部验收后才建 release tag。

### 成员 B

1. 检查所有页面的空、加载、成功、失败、降级和冲突状态。
2. 核对每个指标的目标/实测/N/A 标记。
3. 完成 README、截图、最终录屏、主备设备和浏览器方案。
4. 核对提交链接、访问方式、演示账号、版本和 commit。

### 共同门禁

- 未参与开发的设备按 README 启动。
- 最终环境黄金路径连续 5 次。
- 模拟模型超时、SSE 断线、数据库恢复；若启用 BGE，再模拟 BGE 不可用。
- 对照赛题要求逐项签字，记录 final URL、tag、commit、DB hash 和视频路径。
- Day 7 不增加 P1；提交后不继续修改 final。

## 10. 递增黄金路径

| 门禁 | 最晚 | 必跑路径 |
|---|---|---|
| G1 | D2 | G0 + 自动分类 + SQLite 恢复 + 编辑/反馈 + pending job + 跨用户隔离 + Docker |
| G2 | D3 | G1 + feedback/Diff → candidate → evidence → resolve/episode_only |
| G3 | D4 | G2 + 相似任务检索/注入 → receipt；负例与 pause |
| G4 | D5 | G3 + 冲突、版本、Pack round-trip、seeded_demo 隔离 |
| G5 | D6–D7 | G4 + 四基线 CLI + 静态结果页 + 单容器 + 新设备启动 |

任一门禁失败，当天不得开始下一层。保存实际 task_id、run_id、事件序号、截图、测试结果和 commit；不保存正文或密钥。

## 11. Git、PR 和审批

### D2 特殊整合

1. `codex/day2-owner-integration` 同时保留 PR #1/#2 的提交祖先。
2. 新整合 PR 以 `integration/day2` 为 base，先 Draft，最后一次 push 后由 `zlbk-wxy` 审批。
3. 通过后用 merge commit 合入；不得 squash 队友历史。
4. 干净 checkout 重跑 G1，再创建 `integration/day2 → main` PR。
5. 最终 PR 同样由 `zlbk-wxy` 在最后 push 后审批，再以 merge commit 合入 main。
6. 只有新整合 PR 合入后才把 PR #1/#2 标记为 superseded 并关闭。

### D3–D7 常规规则

- A 使用 `feat/a-dN-*`，B 使用 `feat/b-dN-*`；修复使用 `fix/*`，契约使用 `chore/contract-*`。
- 共享契约先单独 PR，再实现后端和前端；每个 PR 一个目标。
- main 永远可启动并通过当前黄金路径；禁止直接 push、force push、自批或临时关闭保护。
- 共享分支不 rebase；合并使用 merge commit并保留作者。
- 每晚记录 last-known-good commit，不滥用 release tag。

## 12. 每日节奏和阻塞协议

| 时间 | 动作 |
|---|---|
| 09:00 | 昨日可运行 commit、今日 P0、风险、登录/外部依赖检查 |
| 13:30 | 集成 1：接通当天最短纵向链路 |
| 21:00 | 集成 2：全套自动测试、API smoke、手工黄金路径、交叉 review |
| 21:45 | 记录失败案例、证据和 last-known-good commit |

阻塞 30 分钟时写：

```text
目标：
复现步骤：
期望：
实际错误：
已尝试：
相关 commit：
能否按本文降级：
需要另一人的最小动作：
```

阻塞 60 分钟时，两人共同处理不超过 20 分钟；仍无解则采用本文降级、更新风险登记，一人继续黄金路径，另一人不得无任务等待。

## 13. 测试和交接证据

每次 PR handoff 必须包含：

- base/head 完整 commit；
- 文件和公开契约变化；
- migration 及回滚影响；
- 命令、退出码、实际测试数量；
- Docker image、专用 volume、cold start/restart 证据；
- Chrome/Edge 验证项；
- 已知限制和明确未实现功能；
- 不含正文的 task/feedback/run ID；
- 下一人只需执行的最小步骤。

不得只写“测试通过”“应该可用”或复制旧交接数字。

## 14. 登录、秘密、隐私和安全边界

- 开始需要登录工具前先告知两人；执行中首次发现登录要求时立即暂停，不绕过登录寻找替代方案。
- D2 默认 `MOCK_MODE=true`，不需要 Provider 登录或 API Key。
- GitHub PR 审批必须由不是最后推送者的另一成员完成。
- `SESSION_SECRET`、Provider key 只进入环境变量或 Secret，不进入 Git、日志、URL、截图或 Pack。
- 日志和 event_log 只保存 ID、长度、状态、domain、规则分数和受控 reason code，不保存完整用户正文、编辑稿、代码或密钥。
- owner_id 只能来自验证后的 session；不能从请求体接受。
- Day 7 前不增加 shell、任意代码执行、文件系统、网络抓取、动态插件、多 Agent、向量数据库或企业认证。

## 15. “完成”的统一定义

一项工作只有同时满足以下条件才可标记完成：

1. 真实路径实现，不是占位、Mock 冒充或仅有类型；
2. 契约、后端、前端和 fixture 同步；
3. 成功、失败、重试、刷新、重启和隔离路径有测试；
4. Docker 与当天黄金路径实际通过；
5. 文档记录真实 head、命令、数量、限制和证据；
6. 另一人已在最后 push 后 review；
7. 受保护分支按规则合入，工作区干净。

