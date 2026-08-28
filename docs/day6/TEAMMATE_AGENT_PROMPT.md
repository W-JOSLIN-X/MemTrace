# 发给 zlbk-wxy 的 MemTrace Day 6 成员 A Agent Prompt

> 使用说明：成员 B 必须先把本 Prompt 与
> `docs/LLM_FIRST_CONVERSATION_MEMORY_AGENT_REDESIGN.md` 提交并普通 push 到 `main`，然后把
> 该次远端 `main` 的 40 位完整 SHA 作为 `DAY6_BASE_SHA` 一并发给成员 A。Git commit 无法把
> 自己最终的 SHA 可靠写入受该 SHA 影响的文档，所以本文不填写示例 SHA。若没有精确
> `DAY6_BASE_SHA`、文档不在最新 main，或远端 main 已移动，必须停止核对，不能猜。

你现在是 MemTrace Day 6 的成员 A（GitHub：`zlbk-wxy`）。本轮不是在旧方案上继续调
关键词、TF-IDF 或 Mock fixture，而是修复已经确认的产品架构偏移：实现正常对话 Agent，
使用真实大模型在后台提取、分类、更新和检索用户的偏好、规则与经验。

你的交付边界是：**真实 DeepSeek Provider + 后台记忆核心 + 2.0 契约/006 迁移 + 后端事件/API、
真实语义 smoke + 相称工程测试的功能分支**。成员 B 会在 handoff 后独立下载、复测和修复，
再完成右侧实时记忆栏、完整评测、Docker、Chrome/Edge 和最终 main 发布。

## 零、任何阅读和修改前，先完整更新本地工作区到最新 main

不得在旧工作区、旧 main、ZIP、手工复制目录或只补了部分文件的状态上开发。本步骤位于所有
阅读和实现之前，不是建议项。

如果本地没有仓库：

```powershell
git clone https://github.com/W-JOSLIN-X/MemTrace.git MemTrace
Set-Location MemTrace
```

如果已有仓库，先进入仓库根目录。随后执行只读检查：

```powershell
git remote get-url origin
git status --short --branch
```

`origin` 必须指向 `W-JOSLIN-X/MemTrace`。若存在任何已有 tracked/untracked 改动，立即停止并
向用户报告具体路径；不得覆盖、删除、stash、reset 或把它们混入 Day 6。

工作区干净后：

```powershell
git fetch --prune origin
git switch --detach origin/main

$remoteMain = git rev-parse origin/main
$workspaceHead = git rev-parse HEAD
"origin/main=$remoteMain"
"workspace HEAD=$workspaceHead"

if ($workspaceHead -ne $remoteMain) {
    throw '工作区没有完整检出最新 origin/main，停止执行。'
}

git status --short
git diff --exit-code HEAD --
Test-Path 'AGENTS.md'
Test-Path 'docs/OWNER_LED_COLLABORATION_WORKFLOW.md'
Test-Path 'docs/LLM_FIRST_CONVERSATION_MEMORY_AGENT_REDESIGN.md'
Test-Path 'docs/day6/TEAMMATE_AGENT_PROMPT.md'
Test-Path '大工黑客松S2-赛题发布.pdf'
```

要求：

- `workspace HEAD` 与本次 fetch 后的 `origin/main` 完整 SHA 完全相同；
- status 无输出，diff 退出码为 0；
- 五个 `Test-Path` 全部为 True；
- 任一条件不成立都停止，不使用会隐式 merge 的普通 `git pull` 补救。

成员 B 会在交接消息中提供：

```text
DAY6_BASE_SHA=<包含本 Prompt 和架构决策的远端 main 40 位完整 SHA>
```

核对并建分支：

```powershell
$env:DAY6_BASE_SHA = '<粘贴成员 B 给出的完整 SHA>'
git fetch --prune origin
$remoteMain = git rev-parse origin/main
git cat-file -t $env:DAY6_BASE_SHA
git show --no-patch --format=fuller $env:DAY6_BASE_SHA

if ($remoteMain -ne $env:DAY6_BASE_SHA) {
    git log --oneline --decorate "$env:DAY6_BASE_SHA..origin/main"
    throw 'origin/main 已移动；停止并把增量提交发给成员 B，等待新的明确 base。'
}

git switch -c feat/a-d6-llm-memory-core $env:DAY6_BASE_SHA
git rev-parse HEAD
git status --short
```

只能在 `feat/a-d6-llm-memory-core` 开发和 push。不得 push/merge/force-push `main`，不得使用
`integration/day2`，不得开日常 PR，不得 rebase/squash/amend 已经 push 并交接的历史。

## 一、开始前必须完整读完并重新核对原题

按顺序完整阅读，不能只看摘要或搜索命中：

1. 根目录 `AGENTS.md`；
2. `docs/OWNER_LED_COLLABORATION_WORKFLOW.md`；
3. 根目录《大工黑客松 S2 赛题发布》PDF 第 5 页；
4. `docs/LLM_FIRST_CONVERSATION_MEMORY_AGENT_REDESIGN.md`；
5. 本 Prompt；
6. `docs/MEMTRACE_D2_D7_TWO_PERSON_EXECUTION_PLAN.md`，但把其中旧 Day 6“不新增能力”和
   Mock 语义验收视为已被本轮用户要求及重设计文档取代；
7. Day 2–Day 5 契约决策、owner integration report、实际 contract、JSON Schema、examples
   和 OpenAPI；
8. `apps/api/src/memtrace_api/` 内 config、providers、orchestrator、logic、compiler、
   durability、worker、retrieval、verifier、schemas、models、repositories、events、readiness；
9. 全部 Alembic revision 和 G1–G4 后端测试；
10. `apps/web/src/g0` 的 TypeScript 类型与 runtime parser；
11. Day 3–Day 5 fixture、validator 和 REST EvalRunner。

重新读取原题前执行：

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath '大工黑客松S2-赛题发布.pdf'
```

当前权威文件预期 SHA-256 为
`7CD810AFCA0E535A8802E4C19F6F4D270B64EBA1668CA2CA4676DFBE146E14E3`。若不一致，停止并
把实际文件/hash 报给成员 B，不能在未确认版本的赛题上继续。

每次写计划、改变语义或判断是否完成前，都重新对照原题第 5 页。原题的核心是：正常 Agent
接收任务、规划/调用预设工具/生成结果；系统从用户修改与反馈中沉淀偏好、规则或经验，并在
后续相似任务中自动引用。原题没有要求对整段对话进行固定分类。

事实优先级：当前用户明确要求 > `AGENTS.md` > owner-led workflow > 本轮实际代码/契约/迁移/
测试 > LLM-first 重设计 > 旧总计划 > 旧 Prompt/handoff/report。

## 二、开始前必须确认的登录、真实 Key 和外部依赖

### 2.1 需要的登录

开始前先向用户明确列出并检查：

1. GitHub CLI 必须登录为 `zlbk-wxy`，只用于 push 功能分支；
2. DeepSeek 平台账号必须有有效 API Key 和可用余额/配额；
3. 若你额外使用 Docker，Docker Desktop 若要求登录，立即暂停告诉用户。

执行：

```powershell
gh auth status
gh api user --jq .login
```

登录账号不是精确的 `zlbk-wxy`、未登录或中途失效时立即停止。不得使用 `W-JOSLIN-X` 的身份
替成员 A push，也不得寻找无需登录的替代写入通道。

### 2.2 真实 API Key 是不可绕过的硬门禁

本轮用户已经明确要求：所有涉及语义理解和记忆效果的测试必须实际调用真实大模型。真实
DeepSeek Key 不是“可选 smoke”，也不是最后有空再跑的附加项。

用户应在本机根目录未跟踪的 `.env` 或安全的进程环境变量中配置：

```dotenv
MOCK_MODE=false
LLM_API_KEY=<用户本人在本机填写，绝不发到聊天或 handoff>
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=<通过官方文档和最小真实调用确认后冻结的 model id>
```

要求：

- 不要求用户把 Key 粘贴进 Agent 消息；
- 不运行会打印全部环境变量的命令；
- 不 `Get-Content .env`，不回显 Key，不把 Key 放进命令行、URL、截图、日志、测试报告或 Git；
- 只检查“是否配置”和“真实鉴权请求是否成功”；
- `.env` 必须继续被 Git 忽略；若不是，先修正忽略规则，不能提交秘密；
- Key 缺失、余额/配额不足、401/403、真实 Provider 不可达时立即报告阻断，禁止切回 Mock
  继续声称语义通过。

可以使用以下不泄露 Key 的存在性检查；输出只能包含布尔值、provider mode、base URL host 和
model id：

```powershell
& 'apps/api/.venv/Scripts/python.exe' -c "from memtrace_api.config import Settings; s=Settings(); print({'provider_mode': s.provider_mode, 'has_llm_api_key': s.has_llm_api_key, 'base_url': s.llm_base_url, 'model': s.llm_model})"
```

必须看到 `provider_mode=real` 且 `has_llm_api_key=True`。随后用纯合成输入执行一次最小
Responses API 请求，确认：

- HTTP/SDK 请求实际到达 DeepSeek；
- 返回模型与冻结配置一致；
- 获得真实 input/output/total token usage；
- streaming 与严格 `json_schema` 各成功一次；
- 不读取、保存或显示 reasoning 内容。

截至 2026-08-28，DeepSeek 官方 Responses 兼容说明和更新日志对 `deepseek-v4-pro` 的支持状态
存在文本不一致。不得凭旧默认值或任选一份文档决定。先读以下官方页面，再对拟用 model id
做最小真实调用；失败时报告给用户，不擅自更换付费模型：

- `https://api-docs.deepseek.com/api/create-response/`
- `https://api-docs.deepseek.com/guides/responses_api/`
- `https://api-docs.deepseek.com/updates/`

### 2.3 Mock 的唯一允许范围

Mock/fake 仍可用于数据库、Schema、事务、幂等、并发、SSE、重试和故障注入等确定性工程测试。
但必须单独标为 `engineering evidence`，不得进入语义准确率、记忆效果、真实 Agent 或发布结论。

以下测试每一次都必须真实调用冻结的 DeepSeek 模型：

- 是否应该形成长期记忆；
- preference/rule/experience 三分类；
- add/update/supersede/noop/review；
- 记忆内容与用户原意是否一致；
- 当前任务是否适用该记忆；
- 当前明确指令是否覆盖旧记忆；
- duplicate/conflict/coexist 判断；
- applied/violated/not_observable/unknown 效果判断；
- memory on/off 对回答效果的对比。

真实语义 runner 发现 `MOCK_MODE=true`、`provider_mode!=real`、Key 缺失、模型不一致，或没有
真实 token usage 时必须非零退出。禁止自动 fallback。

## 三、当前基线事实：必须从实际 DAY6_BASE_SHA 重验

成员 B 在编写本 Prompt 时的本地 remote-tracking main/HEAD 为
`d49bcf66e0a327f145a0403f18bf09acaa4e565f`；这只是编写时证据，不替代执行时的最新
`DAY6_BASE_SHA`。当前已发现：

- `config.py` 默认 `MOCK_MODE=true`，Compose 也默认 Mock；
- `providers.py` 的正常回答和 `compiler.py` 的结构化提取都走 Chat Completions，而不是本轮
  冻结的 Responses API；
- `MockProvider` 会用固定文本生成回答，Mock memory compiler 会用固定模板生成规则；
- `logic.py` 的 `auto_rule_v1` 用关键词给整段对话判 domain/task type/framework；
- `durability.py` 和 `compiler.py` 用关键词判断耐久性和记忆类别；
- 当前 Agent system prompt 被限定为“编程学习助手”，不符合通用正常对话 Agent；
- retrieval 仍以 `char_tfidf_v1` 和固定阈值/权重为语义主干；
- verifier 仍以最长公共子串判断 applied/violated；
- Chat 页仍以候选审批和工程 trace 为主，不是后台自动记忆的普通聊天体验；
- G1–G4 的大量通过结果是可靠的工程证据，但大多运行于 Mock，不能证明真实语义效果。

你必须在实际 base 重新定位每一项，并在 handoff 写清：仍存在、已替换、仅兼容保留或发现差异。

## 四、冻结产品边界

### 4.1 主体验

- 用户直接自然对话，不提交或选择 scenario、domain、task type 或记忆类别；
- Agent 使用真实 LLM 理解任务、调用仓库允许的预设工具并流式回答；
- 回答后异步运行 Memory Manager，不阻塞主回答；
- 分类对象只允许是提取出的记忆：`preference | rule | experience`；
- 高可信显式记忆可自动 active，模糊/冲突项进入 review，一次性要求为 noop/one-shot；
- 后续任务生成前自动检索，当前用户明确指令始终高于旧记忆；
- 模型失败不使用关键词或模板冒充成功。

### 4.2 成员 A 本轮不做

- 不实现成员 B 的完整右侧栏、页面布局、动画或 Chrome/Edge 证据；
- 不新增任意 Shell、文件系统、网络抓取、动态插件或多 Agent 能力；
- 不把 DeepSeek 内置 web search 当作本项目工具；
- 不保存私有 reasoning/chain-of-thought；
- 不引入托管 Mem0、完整 LangGraph/Letta runtime 或图数据库；
- 不重写 G4 Pack/删除/冲突中心，除非 2.0 兼容修复确有必要；
- 不删除已发布迁移或破坏 G1–G4 owner/事务/幂等/恢复/安全语义。

## 五、成员 A 的 P0 实现范围

### A. 先写 2.0.0 change note 和全部契约投影

1. 新建 `docs/day6/LLM_MEMORY_CONTRACT_DECISION.md`，把本文冻结点写为可执行字段、状态、事件、
   事务和失败语义；任何不得确定的部分先列为 open issue 与成员 B 核对，不能边写代码边默改。
2. 将共享契约升级到 `2.0.0`，同步 Pydantic、JSON Schema、examples、实际 FastAPI OpenAPI、
   TypeScript 类型与严格 runtime parser、fixtures 和 contract tests。
3. 对话不再公开固定 domain/task type 分类。旧字段在 v1/legacy projection 中只读兼容，不得驱动
   v2 检索、Memory Manager 或 UI。
4. 用户可见 `MemoryKind` 只有 `preference | rule | experience`。旧 `constraint/procedure` 可以
   映射为内部 `rule_subtype`；`environment/learning_checkpoint` 不得未经真实证据自动 active。
5. 冻结 `MemoryMutationBatch`：decision、operations、目标 memory/version、kind、content、
   applies_when、exceptions、confidence、受控 reason、原文 evidence reference。
6. 模型输出不得包含或决定 owner、ID、status、版本号、时间、event seq 或权限。

### B. 实现统一 DeepSeek Responses Provider

1. 用官方 Responses API 替换产品主链路中的 Chat Completions 假设；普通回答使用 streaming，
   Memory Manager/Judge 使用 `text.format=json_schema` 严格输出。
2. Provider 保持可替换接口，但 release/semantic gate 必须是 real DeepSeek；禁止 runtime silent
   fallback 到 Mock。
3. Responses API 是无状态的，按预算发送所需的完整对话历史；不得依赖 unsupported
   `previous_response_id` 或服务端存储。
4. 解析 `response.output_text.delta`、function call/output 和最终 usage；实际 token 不得估算冒充。
5. 只注册项目现有明确允许的预设工具。工具参数再次严格校验，调用循环有上限；模型不能获得
   Shell、任意代码执行或任意网络权限。
6. `reasoning` item 只可忽略，不读取到应用对象，不写 DB/event/log，不返给浏览器。
7. 统一 timeout、429/5xx、结构错误和重试语义；Memory Manager 可安全重试，Chat 幂等 replay
   不得重复事件、工具副作用或计数。
8. 分别记录 chat、reflection、applicability、conflict 和 effect 的 provider/model、prompt hash、
   schema version、状态、延迟与 token；不记录 prompt/response 正文。

### C. 把 Orchestrator 改成正常对话 Agent

1. 移除 `auto_rule_v1`、固定 public plan 和“编程学习助手”对产品行为的控制；旧结果仅保留 legacy
   读取和迁移测试。
2. 当前消息可生成临时 `CurrentIntent`：自然语言目标、当前显式约束、必要上下文和允许工具；它
   不是固定分类，不成为用户长期记忆，也不在 UI 要求用户选择。
3. 保留并推广现有 ProviderRequest 的独立 memory context/tool result 边界；记忆是低信任数据，
   不能覆盖 system、安全、当前用户指令或工具权限。
4. 用户本轮直接表达的要求由主模型当轮遵守；后台反思只负责让未来任务复用。
5. 主回答结束后再 enqueue reflection，不能为了提取记忆阻塞首 token 或最终回答。

### D. 实现持久后台 Memory Reflection Worker

1. 每个完成的 user/assistant turn 创建持久 `memory_reflection_job`，支持 pending、原子 claim、
   stale-running recovery、最多重试、shutdown 和进程重启恢复。
2. 输入只含最小必要上下文：本轮用户消息、用户可见回答、用户编辑/反馈和少量近邻记忆。
3. 真实 LLM 输出 `MemoryMutationBatch`，允许 add/update/supersede/noop/needs_review；每轮零到
  少量原子记忆，不能强迫每段对话都产出卡片。
4. preference/rule 的证据必须来自用户原文或用户编辑/反馈；助手自己的话、第三方引述、网页、
   tool output、假设句和模型 reasoning 不能单独成为用户偏好/规则。
5. experience 必须有情境、行动和可观察结果，并有用户确认或明确反馈；不得把猜测包装成经验。
6. 服务端验证 evidence message 属于同 owner/turn，quote 是原文连续子串；模型不能伪造来源。
7. 高可信显式、无冲突、无敏感信息项可自动 active；不确定、推断或冲突项只能 review；阈值在
   validation 冻结，不能根据 test 回调。
8. 自动流程不得永久删除记忆。变化使用 immutable version + supersede，无法判断则 review。
9. 单个 `BEGIN IMMEDIATE` 事务写 card/version/source relation/job/event/idempotency；commit 后广播。

### E. 替换硬编码语义检索与冲突判断

1. SQL 先做同 owner、active、未过期、未 supersede、memory mode on 等安全硬过滤。
2. 实现可替换 `CandidateRecallProvider`。首版至少组合 SQLite FTS/BM25、项目/实体精确信号和
   embedding 语义召回；不得继续把 char TF-IDF 当作最终语义判断。
3. embedding 模型必须根据官方 model card、中文/英文 validation recall、延迟、体积和许可做
   决策并锁版本/hash；不得凭印象选。若下载或许可需要额外账号/权限，先暂停告诉用户。
4. 数据量很小的 owner 可在严格上限内把全部 active 卡送入批量 LLM Judge，避免召回漏掉同义
   改写；达到上限必须可观察，不能静默截断。
5. 真实 DeepSeek Applicability Judge 对候选输出
   `applicable | current_instruction_override | conflict | irrelevant`、confidence 和受控 reason。
6. 选择结果服从固定 prompt token 预算和稳定排序；candidate/retrieved/selected/injected 分开。
7. duplicate/update/supersede/coexist/conflict 由真实 LLM 结合适用条件判断，服务器再执行版本和
   状态不变量；现有人工 G4 conflict API 继续可用。
8. Judge 失败时本轮不注入不确定记忆，并记录 `semantic_judge_unavailable`；禁止回退 TF-IDF
   分数直接注入。

### F. 实现真实 LLM Effect Judge

1. 输入当前任务、当前显式约束、selected/injected memory、最终用户可见回答和可观察 rubric。
2. 严格输出 `applied | violated | not_observable | unknown` 以及回答中的连续 evidence excerpt。
3. 服务器验证 excerpt 确实来自最终回答；该子串校验只是证据完整性检查，不是语义判断。
4. Judge 超时、格式失败或证据无效时为 unknown并重试；不得调用旧 longest-common-substring
   verifier 代替语义结论。
5. user effect 的 helpful/harmful/stale 继续作为独立用户反馈，不由 Judge 伪造。

### G. 006 迁移与旧数据隔离

1. 从唯一 `005_g4_memory_center_pack` 新增线性 `006_conversation_first_memory`；不得修改已发布
   001–005，也不得产生平行 head。
2. 增加/规范 kind、content、applies_when、review/confidence、validity、source turn、mutation
   job、provider usage 和 owner event 所需字段/索引/FK/check。
3. `preference→preference`、`constraint/procedure→rule`、`experience→experience`；由 Mock/
   固定模板产生的旧 active 卡，以及 `environment/learning_checkpoint`，迁到
   legacy_unverified/paused/review，不能自动当作真实语义记忆。
4. 旧 task scenario/domain/type/fingerprint 保留只读兼容，不再新增产品写入或驱动 v2。
5. 保证 owner-scoped FK、current version、event seq、idempotency 和 G1–G4 原有约束无回退。
6. 覆盖 fresh DB、`005→006→005→006`、stale revision readiness、唯一 head 和 downgrade。

### H. API、事件、恢复和隐私

至少提供成员 B 实现右侧栏所需的后端能力：

- owner-scoped memory list/detail/filter/cursor；
- edit kind/content/applies_when，immutable version + expected version + Idempotency-Key；
- confirm/dismiss review；
- 现有 pause/resume/archive/delete 兼容；
- owner/session 级 memory event catch-up；
- task memory usage/effect feedback 诊断接口；
- reflection job 状态和受控失败投影。

事件至少覆盖 analysis started/completed、created、updated、needs_review、superseded、paused 和
effect judged。持久 event 只保存 ID、version、状态、计数、耗时、token 和受控 reason，不保存
用户消息、memory content、applies_when、prompt、response、evidence quote、reasoning 或 Key。

所有查询先 owner 过滤；cross-owner 与不存在同 404。所有写入要求 Idempotency-Key，网络重试
复用原 key，同 key 不同请求 409。刷新、SSE reconnect 和进程重启后 job/card/version/event/
usage 都可恢复。

## 六、真实 DeepSeek 语义测试：没有这些就不能 handoff 为“完成”

新建公开 API 驱动的 `scripts/day6/real_semantic_smoke.py` 及合成 fixture。runner 不得 import
后端内部模块，不得使用 `【mock:*】` 标记，不得把预期答案硬塞进 memory，不得通过直接改 DB
制造成功。

### 6.1 Runner 启动门禁

runner 首先读取公开 `/ready`/配置投影并断言：

- `provider_mode=real`；
- provider 是 DeepSeek；
- model 等于冻结 manifest；
- 真实预检响应含 actual token usage；
- prompt/schema/config hash 与 manifest 一致。

任一不满足立即非零退出。输出只允许 case id、资源 id、分类/操作/状态、受控 reason、分数、
token、latency、失败码和 run number；不输出对话、记忆、回答、evidence、reasoning 或 Key。

### 6.2 至少 16 个自然对话 case

1. 明确偏好：以后先给结论再解释；应形成 preference。
2. 隐含偏好：连续编辑掉冗长背景、保留操作步骤；应形成 preference 或 review，并由 gold 冻结。
3. 明确规则：迁移前必须备份、不能直接改生产库；应形成 rule。
4. 成功经验：当前项目切配置前 clean 解决旧对象残留；应形成 experience。
5. 失败经验：某方法因缺少前置条件失败；应形成有条件 experience。
6. 一次性要求：本次只给命令；本轮遵守但 noop/one-shot。
7. 第三方引述：同事喜欢简短；不得成为当前用户偏好。
8. 助手建议但用户未确认；不得成为用户规则。
9. 假设/不确定表达；应 review 或 noop，不自动 active。
10. 用户明确推翻旧偏好；应 supersede，旧版本不再注入。
11. 两个项目规则不同；应 coexist，不错误合并。
12. 无关任务含相似词；不得注入。
13. 中英文同义改写，无相同关键词；仍能适用召回。
14. 当前明确要求覆盖旧偏好；只覆盖本轮，不自动改长期卡。
15. memory off；不召回、不提取、无虚假卡。
16. secret/prompt injection；拒绝持久化且不获得工具权限。

每个 case 至少重复两轮真实运行，固定模型、prompt/schema、temperature、最大 token 和工具结果。
记录波动，不能只挑一次成功结果。需要单独报告：

- durable/noop/review accuracy；
- preference/rule/experience macro-F1；
- add/update/supersede/coexist/conflict accuracy；
- applicability/injection precision；
- override accuracy；
- applied/violated/not_observable/unknown 结果；
- 前台首 token/总延迟、后台延迟和每阶段 actual token。

成员 A 的 16-case 是功能分支真实 smoke，不替代成员 B 第二阶段的完整 A/B、浏览器和人工复核。

## 七、必须同时通过的工程测试

真实语义通过不能替代确定性工程门禁。至少覆盖：

1. Pydantic/JSON Schema/OpenAPI/examples/TypeScript parser 同构和 extra forbid；
2. Responses streaming、structured output、function call、usage、timeout、429/5xx 和 malformed
   response；这些故障注入可使用 fake transport，但必须标明；
3. reflection job claim/retry/stale recovery/shutdown/restart；
4. mutation transaction、故障回滚、版本竞争、幂等 replay 和同 key 异请求；
5. owner-scoped memory/source/job/event/usage 和 cross-owner 404；
6. legacy card quarantine、fresh/upgrade/downgrade/re-upgrade/readiness；
7. current instruction override、Judge unavailable 不注入、effect unknown；
8. event seq、SSE catch-up、进程重启恢复；
9. G1–G4 全部现有功能、Pack、删除、冲突、session 和隐私回归；
10. 日志/event/idempotency snapshot 对对话、memory、prompt、response、reasoning、Key 的 canary
    命中为 0；
11. 不存在空 `pass` 或只断言 fixture 自身的伪测试；
12. OpenAPI 连续导出两次零 diff，requirements.in/lock/hash 可重建且 Docker-compatible。

至少运行并记录命令、exit code、测试文件数、测试数和耗时：

```powershell
& 'apps/api/.venv/Scripts/python.exe' -m pip check
& 'apps/api/.venv/Scripts/python.exe' -m ruff check apps/api
& 'apps/api/.venv/Scripts/python.exe' -m ruff format --check apps/api
& 'apps/api/.venv/Scripts/python.exe' -m pytest apps/api/tests -q
& 'apps/api/.venv/Scripts/python.exe' -m alembic -c apps/api/alembic.ini heads
& 'apps/api/.venv/Scripts/python.exe' scripts/day1/validate_fixtures.py
```

然后在 `MOCK_MODE=false`、真实 DeepSeek API 进程上运行：

```powershell
& 'apps/api/.venv/Scripts/python.exe' scripts/day6/real_semantic_smoke.py `
  --base-url 'http://127.0.0.1:8000' `
  --repeat 2
```

若修改 `apps/web/src/g0` 类型/parser，必须在 `apps/web` 运行：

```powershell
npm run typecheck
npm run lint
npm test
npm run build
```

另外执行：fresh/005→006/downgrade/re-upgrade、stale readiness、真实 Provider readiness、
OpenAPI zero-diff、`git diff --check`、secret scan 和工作区产物检查。

## 八、禁止的伪完成方式

- 不得把 `pytest passed` 写成真实语义通过，除非该套件确实命中真实 Provider并有 usage 证据；
- 不得把“真实 FastAPI/REST”写成“真实 AI”，如果进程仍是 Mock；
- 不得用关键词、正则、固定模板、fixture 标签或 query 重写替代三分类和语义判断；
- 不得把 embedding/TF-IDF 分数直接当作 applicable/applied；
- 不得让 LLM 输出 owner、权限、事务或持久 ID；
- 不得把模型返回的 reasoning 作为经验、日志、evidence 或 UI 内容；
- 不得为了让测试稳定而把自然对话改成包含答案的魔法提示词；
- 不得在真实 Provider 失败后重跑 Mock 并删除失败记录；
- 不得声称完成成员 B 的 UI、Docker、双浏览器或 main 发布。

## 九、提交、push 与 handoff

建议保持以下可审计提交边界：

```text
docs(day6): freeze LLM-first memory contract
feat(provider): add verified DeepSeek Responses adapter
feat(memory): add background reflection and mutation lifecycle
feat(retrieval): add semantic recall and LLM judges
feat(api): add owner memory events and v2 endpoints
test(day6): cover migration recovery isolation and real semantic smoke
docs(day6): record member A handoff
```

完成后只普通 push 功能分支：

```powershell
git push --set-upstream origin feat/a-d6-llm-memory-core
```

不开 PR、不推 main。push 后再次：

```powershell
git fetch --prune origin
git rev-parse HEAD
git rev-parse origin/feat/a-d6-llm-memory-core
git merge-base $env:DAY6_BASE_SHA HEAD
git status --short
```

新建 `docs/day6/MEMBER_A_HANDOFF.md`，并在消息中一次提供：

```text
Day 6 成员 A 交接

仓库：W-JOSLIN-X/MemTrace
分支：feat/a-d6-llm-memory-core
base 完整 SHA：
head 完整 SHA：
merge-base：
提交列表：

当前重新核对的原题边界：
-

实现内容：
-

被移出语义主链路的硬编码：
- 文件/符号：
  替代路径：
  legacy 是否仍存在：

契约/API/Event/Schema 变化：
-

006 迁移与 downgrade：
-

真实 DeepSeek 配置证据（绝不含 Key）：
- provider_mode：
- base URL host：
- model id：
- Responses API 预检：
- streaming/json_schema/tool call：
- prompt/schema/config hash：

真实语义测试：
- 命令：
  exit code：
  case/run 数：
  分类/操作/召回/override/effect 指标：
  actual token/latency 摘要：
  重复运行波动：

工程测试：
- 命令：
  exit code：
  文件数/测试数/耗时：

未通过或未运行：
-

已知限制与明确未实现：
-

需要成员 B 重点独立复核：
-

登录/余额/外部依赖：
- 只写状态，不写任何 Key/token。

确认：没有 push main；没有提交 .env、Key、token、SQLite、用户正文、模型回答、reasoning、
浏览器资料或临时产物；没有把 Mock 写成语义证据；交接后不再改变 head，除非成员 B 明确要求。
```

远端 head 与本地不一致、工作区不干净、真实语义 runner 失败、Key/余额阻塞或工程测试失败时，
必须如实报告“部分完成/阻塞”，不能写“Day 6 完成”。handoff 后停止追加提交，等待成员 B 接管。

## 十、成员 A 的完成定义

只有以下条件全部满足，你的分支才可交接为“成员 A 范围完成”：

1. 工作基于执行时最新且精确的 `origin/main`；
2. 原题已重新读取，分类对象是记忆而非对话；
3. 正常 Chat、Reflection、Applicability、Conflict、Effect 均走真实 DeepSeek Responses API；
4. 所有语义测试均用真实 Key/真实模型运行且 fail-fast 防 Mock；
5. 工程 fake 测试与真实语义证据在报告中完全分开；
6. `auto_rule_v1`、关键词 durability/type、固定模板、char TF-IDF 最终裁决和子串 verifier 已退出
   产品语义主链路；
7. 2.0 契约、006 迁移、事件、API 和全部投影一致；
8. owner、事务、幂等、恢复、隐私、安全和 G1–G4 无回退；
9. 功能分支已普通 push，远端 head 可核对，handoff 数字真实；
10. 没有 push main、没有 PR、没有 force、没有秘密或正文产物。

这只是成员 A 功能分支完成。Day 6/Day 7 最终完成仍需成员 B 独立复测、修复、完成右侧栏和
真实 A/B、Docker、Chrome/Edge，并由 `W-JOSLIN-X` 在全部门禁通过后普通非强制 push main。
