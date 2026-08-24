# MemTrace 所有者中心的双人协作与直接交付流程

> 状态：自 2026-08-24 起生效，是 Day 4–Day 7 的权威协作与 Git 交付流程。
>
> 仓库所有者 / 每日集成者：`W-JOSLIN-X`（成员 B）。
>
> 协作者：`zlbk-wxy`（成员 A）。
>
> 核心变化：取消日常 PR 和“必须由另一协作者审批”的完成前提；协作者只推功能分支，所有者在本地独立核验、修复、完成当日整合后直接非强制推送 `main`。

## 1. 为什么修改

Day 2 和 Day 3 使用过“协作者分支 → 替代 PR → integration/day2 → 晋级 PR → main，并在最终 head 上由另一人审批”的流程。它适合强制双人审查，但会让实际由仓库所有者负责验收和发布的每日开发反复等待两次审批，也使一个已经在本地完成全栈核验的交付被流程本身阻塞。

从 Day 4 起，实际责任链固定为：

```text
成员 A 在独立功能分支完成后 push
        ↓ 发送精确交接信息
成员 B fetch 并独立审查/测试
        ↓ 普通 merge，保留 A 的历史
成员 B 修复问题并完成自己的当日任务
        ↓ 完整 G1…Gx + 容器/浏览器/安全门禁
成员 B 再次核对远端 main 未漂移
        ↓ 普通非强制 direct push
远端 main = 本轮已验证 head
```

这不是“取消质量控制”，而是把最终质量责任和发布权限统一交给仓库所有者。取消的是 PR/同伴审批这一种机制，不是独立核验、回归、分支隔离、证据或 main 稳定性要求。

## 2. 文档优先级与废止范围

冲突时按以下顺序判断：

1. 用户当前明确要求；
2. 根目录 `AGENTS.md`；
3. 本文；
4. 可执行契约、实际代码、迁移和本轮实测；
5. `docs/MEMTRACE_D2_D7_TWO_PERSON_EXECUTION_PLAN.md` 与总计划；
6. 旧 HANDOFF、旧 Prompt、旧 PR 描述和历史核验报告。

以下旧规定自生效日起废止，仅保留为 Day 2/Day 3 历史证据：

- 每个目标必须开 PR；
- 所有共享契约必须先开 contract PR；
- 成员 B 最后 push 后必须由成员 A 审批；
- 所有代码必须先合入 `integration/day2`，再二次 PR 晋级 `main`；
- “所有人都禁止直接 push main”。

仍然有效的边界：

- 成员 A 禁止直接更新 `main`；
- 成员 B 只有在独立核验和完整门禁通过后才能直接更新 `main`；
- 不 force push、不改写协作者历史、不绕过失败测试、不删除不明工作；
- main 必须始终是当前 last-known-good；
- 共享契约必须先记录变化并同步全部实现投影，只是不再要求用 PR 承载。

## 3. 角色、责任与最终决定权

### 3.1 成员 A：后端、Agent 与记忆引擎协作者

成员 A 的长期技术主责不变：FastAPI、数据库和迁移、Provider、Agent/worker、提取/准入/检索/注入/冲突、后端事件、安全和指标字段。其交付边界是“可核验的功能分支”，不是 `main`。

成员 A 必须：

- 从成员 B 指定且已核对的 `origin/main` base 开分支；
- 只改 Prompt 分配的范围，不提前实现下一天功能；
- 对契约、迁移、数据隐私和失败路径写测试；
- commit 后 push 自己的远端分支；
- 提供精确 handoff 并停止追加，除非成员 B请求；
- 对不知道、没测试、失败或需登录的部分明确说明。

成员 A 不得：

- push/merge/force-push `main`；
- 修改仓库保护以获得 main 写入能力；
- 要求成员 B 把自己的“测试通过”当作验收；
- 在交接后静默改变 head；
- rebase、squash、amend 已推送并已交接的历史；
- 把 mock、声明式 manifest 或占位 UI 写成完成。

### 3.2 成员 B：仓库所有者、产品/前端/评测与唯一日常集成者

成员 B 继续主责 React、状态恢复、产品文案、fixtures、EvalRunner、浏览器/Docker、README 和演示；同时是每天的最终代码审查、缺陷修复、全栈整合与发布责任人。

成员 B 必须：

- 独立核验协作者分支，不直接相信 handoff；
- 保存协作者 commit 祖先和作者；
- 解决协作者实现中的阻断，再完成自身当日范围；
- 让代码、契约、迁移、前端 parser、fixtures 与文档一致；
- 从 G1 递增重跑到当天 Gx，不只运行新增测试；
- 在最后 push 前处理远端 main 漂移；
- 只把已经验证的 head 普通推送到 main，并核对远端结果。

成员 B 有最终决定权：

- 接受、修正或拒绝协作者实现；
- 冻结共享契约；
- 采用计划中已有降级；
- 判断当天是否达到完成定义；
- 在满足门禁后直接更新 main，无需协作者审批。

若成员 B 变更了协作者负责的后端设计，应在核验报告中说明原因、实测证据和兼容影响，不能只写“做了调整”。

## 4. 每天开始前：成员 B 先冻结任务 Prompt

每天必须先由成员 B 或成员 B 的 Agent完成只读核验，再生成协作者 Prompt。Prompt 至少包含：

1. 必须完整阅读的仓库文件和优先级；
2. 当前 `origin/main` 的完整 SHA，以及“执行时如变化必须重新核对”的要求；
3. 明确分支名和只能 push 该分支；
4. 成员 A 的 P0 范围、输入、接口冻结点、迁移和事件；
5. 明确不做的后续能力；
6. 单元、集成、迁移、并发、隔离、隐私和故障测试；
7. 需要的账号/环境变量；默认是否 Mock；
8. commit 建议和禁止改写历史；
9. handoff 格式；
10. “完成后停止，不开 PR、不推 main，等待成员 B 接管”。

不能从旧计划直接复制一个 Prompt 就发送。必须先检查实际代码、契约、测试、远端 head 和已实现能力，因为旧交接只能作为历史线索。

## 5. 阶段 A：成员 A 分支开发与交接

### 5.1 分支和提交

推荐分支：

```text
feat/a-d4-memory-retrieval
feat/a-d5-memory-center
feat/a-d6-evaluation-hardening
feat/a-d7-release-hardening
```

基本过程：

```powershell
git fetch --prune origin
git switch --create feat/a-dN-<scope> origin/main
# 实现、测试、检查
git status --short
git diff --check
git push --set-upstream origin feat/a-dN-<scope>
```

命令只是流程示例。执行 Agent必须先检查工作区、分支是否已存在和 remote 指向，不得覆盖用户已有工作。

提交应小而可解释，使用 `feat`、`fix`、`test`、`docs`、`chore` 前缀。共享契约可作为该功能分支上的先行 commit，不再要求单独 PR。

### 5.2 必填 handoff

成员 A 完成后发送：

```text
Day N 成员 A 交接

仓库：W-JOSLIN-X/MemTrace
分支：
base 完整 SHA：
head 完整 SHA：
提交列表：

实现内容：
-

契约/API/Event/Schema 变化：
-

迁移与数据兼容：
-

实际测试证据：
- 命令：
  exit code：
  数量/结果：

未通过或未运行：
-

已知限制与明确未实现：
-

需要成员 B 重点独立复核：
-

登录/密钥/外部依赖：
-

确认：没有 push main；没有提交 .env、token、数据库、用户正文或临时产物；交接后不再改变 head，除非成员 B 明确要求。
```

“已经完成”“所有测试通过”而没有 SHA、命令、退出码和数量，不构成可接管交接。

## 6. 阶段 B：成员 B 下载、独立核验和接管

### 6.1 只读核对

成员 B 收到消息后先核对：

- GitHub 登录账号确为 `W-JOSLIN-X`；
- 远端分支存在，head 等于 handoff；
- handoff base 是否为当时的 main，协作者是否混入无关祖先；
- `base..head` 的 commit、文件、契约、迁移和 lock 变化；
- 是否出现 `.env`、token、SQLite、日志、录屏、正文 fixture 或超范围功能；
- 若交接后 head 已变化，先审查增量并让记录对齐。

只读核验完成前不合并，不把协作者测试结果写成自己的结论。

### 6.2 建立 owner integration 分支

从接管时的精确 `origin/main` 建立：

```text
codex/dayN-owner-integration
```

然后使用普通 merge commit引入成员 A 分支。推荐使用 `--no-ff`，让每天的协作者边界和 head 可追溯。不得 rebase、squash、amend 或复制粘贴后假装没有协作者历史。

若成员 A base 落后但没有真正冲突，由 merge commit统一合入；若存在语义冲突，成员 B 解决并记录理由。不得让成员 A 去直接操作 main“省一步”。

### 6.3 先测协作者，再做成员 B 工作

顺序固定为：

1. 运行协作者声明的测试，确认能否复现；
2. 运行真实路由/lifespan/数据库/迁移/并发/隔离等越过纯函数和 manifest 的测试；
3. 记录新增失败，不被既有绿色测试掩盖；
4. 修复 P0 阻断并补回归；
5. 完成成员 B 当日前端、产品、评测、恢复和集成任务；
6. 同步公开契约与文档；
7. 跑完整递增门禁。

## 7. 阶段 C：合并门禁与所有者直接推 main

### 7.1 递增门禁

- Day 2：G1；
- Day 3：G1 + G2；
- Day 4：G1 + G2 + G3；
- Day 5：G1–G4；
- Day 6/7：G1–G5 与发布门禁。

每天的实际命令以仓库配置为准，至少覆盖：

- Python Ruff、format check、完整 pytest、依赖一致性；
- Pydantic、JSON Schema、实际 FastAPI OpenAPI、TypeScript runtime parser；
- 唯一 Alembic head、空库/旧库升级、readiness；
- TypeScript、ESLint、完整 Vitest、production build；
- 幂等、事务回滚、事件序号、刷新/进程重启和跨用户不可见；
- 任务专属 Docker cold start/restart/persistent volume；
- Chrome 与 Edge 的当天黄金路径；
- metadata-only 日志、secret scan 和工作区产物检查。

不可用旧报告中的数量代替本轮结果。Mock 是默认硬门禁；真实 Provider 只有在当天计划明确要求、账号已登录且有独立实测证据时才算额外证据。

### 7.2 直接 push 前的竞态检查

成员 B 最后一轮测试后：

1. 记录当前 integration head 和本轮使用的 main base；
2. `git fetch origin main`；
3. 若 `origin/main` 不再等于已核验 base，禁止直接推；
4. 把新的 `origin/main` 普通 merge 进整合分支，处理冲突并重跑受影响测试；
5. 确认协作者 head 和新 main 都是整合 head 的祖先；
6. `git status --short`、`git diff --check`、秘密/产物检查通过；
7. 普通 `git push origin HEAD:main`，不使用任何 force 选项；
8. 再 fetch/读取远端，确认 `origin/main` 等于已验证 head。

若普通 push 因保护规则被拒绝，不得临时关闭所有保护或使用 admin bypass。应检查“所有者直推、协作者禁推”的规则配置是否正确；需要登录或平台设置时暂停并告诉用户。

## 8. GitHub 技术约束

仓库是个人账号下的 public repository，协作者拥有 `write`。仅仅移除旧 PR 保护会让有 write 权限的协作者也能 push main，因此不能把“取消 PR 审批”误写成“main 没有任何限制”。

目标配置为：

- repository ruleset 精确匹配 `refs/heads/main`；
- `Restrict updates` 只允许明确列出的 bypass actor 更新；
- bypass actor 只列仓库所有者 `W-JOSLIN-X`，模式为 always；
- 同一规则阻止 deletion 与 non-fast-forward；
- 旧 classic protection 中的 required pull request reviews 从 main 移除；
- `zlbk-wxy` 仍保留 write 权限用于自己的功能分支，但不能更新 main。

这使平台约束与流程一致：成员 B 可普通直推 main，成员 A 只能 push 功能分支。由于不能在不使用协作者账号的情况下实际模拟其 push，配置后应以规则 API 的 actor/target/rules 回读作为自动证据；若以后由成员 A 实测，应只尝试一个无破坏的正常 push，并预期被拒绝，绝不提供或交换 token。

### 8.1 2026-08-24 实际配置记录

- 仓库：`W-JOSLIN-X/MemTrace`，个人账号下的 public repository；
- `zlbk-wxy` 保留 repository `write`，用于创建和 push 功能分支；
- active repository ruleset：`main-owner-only-direct-delivery`，ID `21276272`；
- target：`refs/heads/main`；
- rules：`update`、`deletion`、`non_fast_forward`；
- 唯一 always bypass actor：User `W-JOSLIN-X`，numeric ID `173425478`；
- 旧 classic `required_pull_request_reviews` 已从 main 删除；classic force push 和 deletion 仍保持禁用；
- API 回读显示当前 `W-JOSLIN-X` `current_user_can_bypass=always`。

这份记录证明平台配置语义已经对齐，但没有冒用协作者账号实际尝试 push。后续 Agent必须重新回读当前配置，因为 GitHub 设置属于会变化的外部状态。

## 9. 登录、阻塞与恢复

### 9.1 登录规则

- 开始前列出当天会用到的 GitHub、Docker、浏览器和 Provider 登录。
- 发现真实登录失效时立即停止相关执行并准确告诉用户需要登录什么。
- 不因未登录改用绕过身份的方式，不从日志、系统凭据或他人分支提取 token。
- 沙箱网络失败应先通过获准的官方命令做最小复核；不能把网络错误直接当成用户未登录，也不能在确认未登录后继续外部写操作。

### 9.2 30 分钟阻塞交接

```text
目标：
当前分支/head：
复现步骤：
期望：
实际错误：
已尝试及结果：
受影响契约/迁移/黄金路径：
能否按计划降级：
需要另一人的最小动作：
```

阻塞 60 分钟仍无法解决时，采用已有降级、记录风险并继续不依赖该阻塞的 P0。需要新增权限、真实账号、付费资源或改变产品边界时，必须由用户决定。

## 10. 安全、隐私与不做边界

- 日志和 event log 只保存 ID、状态、计数、时间、domain、分数、hash 和受控 reason code；不保存任务正文、反馈正文、编辑稿、rule、avoid 或 evidence quote。
- `.env`、Provider key、GitHub token、数据库、持久卷、浏览器 profile 和用户材料不进入 Git。
- owner/session 隔离、幂等和事务不能为了演示降级。
- 不运行任意用户代码，不增加 shell/文件系统/联网能力，不使用动态插件或多 Agent，除非用户后续明确扩大范围。
- Day 4 不提前实现 Day 5 的完整冲突中心或 Memory Pack 流程，也不提前实现 Day 6 的动态评测服务。

## 11. 每日完成定义

只有同时满足以下条件才能报告“Day N 完成”：

1. 成员 A 的交接 head 已保留为最终代码祖先，或成员 B 有证据说明为何拒绝其中部分实现；
2. 成员 B 已独立复现并修复阻断，不直接采用旧 handoff 结论；
3. 当日双方 P0 均完成，契约和全部实现投影一致；
4. 成功、失败、重试、恢复、重启、隔离和当天关键负例有本轮证据；
5. G1 到当天 Gx、Docker 和双浏览器按风险实际通过；
6. 没有秘密、数据库、正文日志或意外产物；
7. 已记录最后已知可用完整 SHA、命令、退出码、数量、限制和降级；
8. 远端 `main` 已由成员 B 普通非强制 push 到该已验证 SHA；
9. 推送后远端核对正确，工作区没有意外改动。

不再要求 PR、成员 A 审批或 `integration/day2` 二次晋级。若只完成本地代码或只推到 owner integration 分支，应报告“本地/分支已就绪”，不能报告“已完成并进入 main”。

## 12. Day 4 的具体接续入口

新对话必须从 `docs/day4/OWNER_AGENT_CONTINUATION_PROMPT.md` 开始。该 Agent的第一个交付不是立刻写 Day 4 代码，而是：

1. 完整阅读规定文档和实际代码；
2. 独立核对远端 main、契约、迁移、测试和 Day 4 fixture；
3. 向用户输出一份可直接发送给成员 A Agent的详细 Day 4 Prompt；
4. 等成员 A push 功能分支并由用户返回 handoff；
5. 再按本文执行 fetch、独立测试、修复、成员 B 工作、G3 合并测试和 direct main delivery。
