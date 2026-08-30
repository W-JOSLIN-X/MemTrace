# MemTrace（忆迹）

MemTrace 是一个普通多轮对话 Agent，同时在后台提取、审阅和复用用户的偏好、规则与经验。用户不选择 `scenario` 或任务类别；真实模型负责 G5 的提取、分类、适用性、冲突/合并和效果判断，确定性代码只负责鉴权、隔离、Schema、事务、幂等、预算、状态机和安全工具边界。

当前 release 版本为 `0.1.0`，公开 wire contract 为 `2.1.0`，数据库 head 为 `007_day7_public_release`。Day 7 的本地真实 DeepSeek 语义门禁已经生成脱敏制品，但 Docker、双浏览器、第二设备和最终 tag 必须全部通过后，才能把本版本标记为完成。权威进度见 `docs/day7/OWNER_RELEASE_REPORT.md`。

## 产品页面

- `/login`：用户名和密码登录、统一失败语义、注册与恢复入口。
- `/register`：一次性邀请码注册，并只展示一次恢复码。
- `/recover`：使用恢复码设置新密码、轮换恢复码并撤销旧会话。
- `/`：普通多轮聊天、真实 SSE 增量回答、工具状态、usage、TTFT、记忆效果与实时记忆侧栏。
- `/memories`：G5 记忆搜索、筛选、版本、Diff、生命周期、冲突、Pack 和安全删除。
- `/evals`：只读展示冻结的真实模型评测制品，不提供会产生模型费用的运行按钮。
- `/settings`：账号、每日额度、默认 memory mode、Provider 诊断、密码、恢复码、会话和账号删除。

生产页面只使用 `/api/v2` 的 `kind/content/applies_when` 投影。`/api/v1` 保留给 G1–G4 兼容测试；共享 demo owner 只有在 `ALLOW_DEMO_SESSIONS=true` 时可用。

## 目录

```text
apps/api/                     FastAPI、Alembic、后台 worker 和测试
apps/web/                     React/Vite 产品页面和 Vitest
contracts/                    OpenAPI、JSON Schema、examples 与契约说明
fixtures/day3..day7/          冻结的工程/语义评测输入
scripts/day3..day7/           REST Eval、Provider 预检、评测和运维脚本
docs/day7/                    Day 7 决策、发布报告和部署手册
compose.yaml                  本地开发/兼容环境
compose.release.yaml          runtime-only 公开发布环境
```

## 本地开发

### 前置条件

- Python 3.11；
- Node.js 22 与 npm；
- Docker Desktop（仅容器门禁需要）；
- 真实语义测试需要可用的 DeepSeek Key、额度和实时验证后的模型 ID；
- GitHub 发布需要 `gh` 登录为 `W-JOSLIN-X`。

Windows PowerShell：

```powershell
python --version
node --version
npm --version
docker version
gh auth status
```

### 安装

```powershell
python -m venv apps/api/.venv
apps\api\.venv\Scripts\python.exe -m pip install --require-hashes --no-deps -r apps/api/requirements.lock
Set-Location apps/web
npm ci
Set-Location ../..
```

复制 `.env.example` 为 Git 忽略的 `.env`。不要把 Key、密码、邀请码、恢复码、session secret、数据库或真实对话提交到 Git。

工程测试可以使用：

```dotenv
MOCK_MODE=true
ALLOW_DEMO_SESSIONS=true
COOKIE_SECURE=false
```

真实语义测试必须使用：

```dotenv
MOCK_MODE=false
LLM_API_KEY=<仅在本地忽略文件中填写>
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=<通过六项预检确认的精确模型 ID>
ALLOW_DEMO_SESSIONS=false
PUBLIC_ORIGIN=http://127.0.0.1:8000
COOKIE_SECURE=false
```

`SESSION_SECRET` 至少使用 32 字节随机值。本地可只放在当前进程；release Compose 必须改用只读 `SESSION_SECRET_FILE` 和 `LLM_API_KEY_FILE`。

### 启动 API 和 Web

```powershell
apps\api\.venv\Scripts\python.exe -m alembic -c apps/api/alembic.ini upgrade head
apps\api\.venv\Scripts\python.exe -m uvicorn memtrace_api.main:app --app-dir apps/api/src --host 127.0.0.1 --port 8000
```

另开 PowerShell：

```powershell
Set-Location apps/web
npm run dev
```

开发服务器默认使用 Vite 地址；`PUBLIC_ORIGIN` 必须与浏览器实际 origin 完全一致。生产单容器由 FastAPI 提供构建后的静态页面。

## 公开账号管理

管理命令直接连接当前 `MEMTRACE_DATABASE_URL`，数据库必须已经升级到唯一 `007_day7_public_release`。创建邀请码会把 secret 只打印一次；应立即保存到安全通道，之后只能查看元数据。

```powershell
$env:PYTHONPATH='apps/api/src'
apps\api\.venv\Scripts\python.exe -m memtrace_api.admin_cli invite-create --max-uses 1 --expires-hours 168
apps\api\.venv\Scripts\python.exe -m memtrace_api.admin_cli invite-list
apps\api\.venv\Scripts\python.exe -m memtrace_api.admin_cli account-list
apps\api\.venv\Scripts\python.exe -m memtrace_api.admin_cli account-disable <username>
apps\api\.venv\Scripts\python.exe -m memtrace_api.admin_cli account-enable <username>
apps\api\.venv\Scripts\python.exe -m memtrace_api.admin_cli sessions-revoke <username>
```

容器内对应命令：

```powershell
docker compose -p memtrace-release -f compose.release.yaml exec app python -m memtrace_api.admin_cli invite-create --max-uses 1 --expires-hours 168
```

账号规则：用户名经 NFKC + casefold 后唯一；密码 12–128 字符并使用 Argon2id；登录、注册和恢复有限流；每账号 UTC 每日最多 50 个真实模型轮次，同时最多运行 1 轮。失败的真实 Provider 尝试也消耗已预留额度。

## 测试

### 确定性工程门禁

```powershell
apps\api\.venv\Scripts\python.exe -m pip check
apps\api\.venv\Scripts\python.exe -m ruff check apps/api scripts/day1 scripts/day3 scripts/day4 scripts/day5 scripts/day6 scripts/day7
apps\api\.venv\Scripts\python.exe -m ruff format --check apps/api scripts/day1 scripts/day3 scripts/day4 scripts/day5 scripts/day6 scripts/day7
apps\api\.venv\Scripts\python.exe -m pytest apps/api/tests -q
apps\api\.venv\Scripts\python.exe -m alembic -c apps/api/alembic.ini heads
apps\api\.venv\Scripts\python.exe scripts/day1/validate_fixtures.py

Set-Location apps/web
npm run typecheck
npm run lint
npm test
npm run build
```

Fake/Mock Provider 只证明错误映射、重试、Schema 拒绝、事务、worker 和 UI reducer，不是语义或产品效果证据。

### 真实 DeepSeek 门禁

先在当前进程或忽略的 `.env` 配置真实 Key，再运行六项预检：模型列表、最小调用、streaming、strict schema、function calling 和 actual usage。

```powershell
apps\api\.venv\Scripts\python.exe scripts/day7/provider_preflight.py --output output/day7/provider-preflight.json
```

任何 Key、认证、额度、模型、网络、function calling 或 usage 失败都必须停止；不得回退到 Mock、关键词、TF-IDF 最终判定或固定答案后宣布通过。

真实语义 runner 只通过公开 REST/SSE API：

```powershell
apps\api\.venv\Scripts\python.exe scripts/day6/eval_runner.py --base-url http://127.0.0.1:8000 --auth-mode public --origin http://127.0.0.1:8000 --primary-username <primary> --primary-password-file <ignored-password-file> --secondary-username <secondary> --secondary-password-file <ignored-password-file> --mode semantic --repeat 2 --output output/day7/semantic.json

apps\api\.venv\Scripts\python.exe scripts/day7/baseline_runner.py --base-url http://127.0.0.1:8000 --origin http://127.0.0.1:8000 --username <username> --password-file <ignored-password-file> --repeat 2 --output output/day7/four-baselines.json
```

Release 容器固定 `ALLOW_DEMO_SESSIONS=false`。G2–G4 兼容回归也必须使用公开账号；涉及 owner isolation 的 runner 要传入两个独立账号，不能临时开启共享 demo owner：

```powershell
apps\api\.venv\Scripts\python.exe scripts/day3/eval_runner.py --base-url http://127.0.0.1:8000 --fixture fixtures/day3/learning_events.json --output output/day7/day3.json --expectation-profile real-provider --auth-mode public --origin http://127.0.0.1:8000 --username <primary> --password-file <ignored-password-file>

apps\api\.venv\Scripts\python.exe scripts/day4/eval_runner.py --base-url http://127.0.0.1:8000 --output output/day7/day4.json --auth-mode public --origin http://127.0.0.1:8000 --primary-username <primary> --primary-password-file <ignored-password-file> --secondary-username <secondary> --secondary-password-file <ignored-password-file>

apps\api\.venv\Scripts\python.exe scripts/day5/eval_runner.py --base-url http://127.0.0.1:8000 --output output/day7/day5.json --auth-mode public --origin http://127.0.0.1:8000 --primary-username <primary> --primary-password-file <ignored-password-file> --secondary-username <secondary> --secondary-password-file <ignored-password-file>
```

校准和静态评测制品只保存 case ID、受控判定、token、TTFT、时延、hash 与 failure code；原始对话和盲评材料必须留在 `output/`。

## Release 容器

`Dockerfile` 只安装 `apps/api/requirements.runtime.lock`，不安装 pytest、Ruff 或前端构建依赖。镜像以 UID/GID 10001 非 root 运行，并带 OCI version/revision/source labels。

本地门禁可从忽略的 `.env` 排他创建两个 secret 文件；脚本只输出布尔状态并拒绝覆盖：

```powershell
apps\api\.venv\Scripts\python.exe scripts/day7/prepare_release_secrets.py --env-file .env --output-dir output/day7/release-secrets
```

生产环境应由秘密管理系统提供等价的只读文件。只通过路径传给 Compose：

```powershell
$env:APP_REVISION=(git rev-parse HEAD)
$env:PUBLIC_ORIGIN='https://your-domain.example'
$env:LLM_MODEL='<已实时验证的模型>'
$env:LLM_API_KEY_FILE='<绝对路径>\llm_api_key'
$env:SESSION_SECRET_FILE='<绝对路径>\session_secret'
$env:COOKIE_SECURE='true'
$env:MEMTRACE_PORT='18070'

docker compose -p memtrace-release -f compose.release.yaml config
docker compose -p memtrace-release -f compose.release.yaml build
docker compose -p memtrace-release -f compose.release.yaml up -d
docker compose -p memtrace-release -f compose.release.yaml ps
```

本机 HTTP 浏览器门禁只能显式临时设置 `COOKIE_SECURE=false`，生产 HTTPS 必须为 `true`。release 环境固定 `MOCK_MODE=false`、`ALLOW_DEMO_SESSIONS=false`；Key 与 session secret 不进入 Compose environment、镜像或日志。

验收：

```powershell
Invoke-RestMethod http://127.0.0.1:18070/api/v1/health
Invoke-RestMethod http://127.0.0.1:18070/api/v1/ready
Invoke-RestMethod http://127.0.0.1:18070/api/v2/system
```

## SQLite 备份与恢复

备份脚本使用 SQLite backup API，并在前后运行 `PRAGMA quick_check`。它拒绝覆盖已有目标：

```powershell
apps\api\.venv\Scripts\python.exe scripts/day7/backup_sqlite.py --source data/memtrace.sqlite3 --output output/backups/memtrace-20260830.sqlite3
```

记录命令返回的 SHA-256，再恢复到全新且不存在的文件：

```powershell
apps\api\.venv\Scripts\python.exe scripts/day7/restore_sqlite.py --backup output/backups/memtrace-20260830.sqlite3 --destination output/restore/memtrace.sqlite3 --expected-sha256 <sha256>
```

不得在运行中的数据库文件上做文件复制恢复。完整容器卷切换、回滚和验证步骤见 `docs/day7/SERVER_DEPLOYMENT_RUNBOOK.md`。

## 安全与隐私边界

- 生产 Cookie：`Secure + HttpOnly + SameSite=Lax`；所有认证写请求同时验证 Origin、CSRF 与幂等键。
- 跨 owner 与不存在统一 404；owner ID 只来自已验证 session。
- 用户正文、模型答案、memory section、密码、邀请码、恢复码、Key 和原始供应商错误不得进入日志、事件、URL、截图或 Git。
- 模型只能选择服务端编号的 `python_ast_check` 候选；工具只执行 `ast.parse`，不能执行代码、Shell、文件、import 或网络。
- `assistant.delta` 是临时 SSE，不进入持久事件；完成或失败后以 snapshot 为权威状态。
- 所有用户/模型文本使用 React 纯文本渲染；Pack preview 在 raw bytes 阶段执行大小、UTF-8、重复 key、深度、Schema、integrity 和危险内容校验。
- 反向代理必须支持 SSE 禁用 buffering、请求体上限、可信代理边界和 HTTPS。

## 发布边界

Day 7 只冻结本地产品和可部署制品，不执行 SSH、DNS、证书、防火墙或服务器数据迁移。只有本地工程、真实 DeepSeek、Docker、Chrome、Edge、第二干净设备、备份恢复、隐私扫描全部有实际证据后，所有者才能普通 push `main` 并创建指向同一 commit 的 annotated `v0.1.0`。不得 force push 或移动已发布 tag。

服务器阶段只能部署精确 `v0.1.0`；若发现缺陷，发布 `v0.1.1`，不能改写旧 tag。服务器参数和逐步操作见 `docs/day7/SERVER_DEPLOYMENT_RUNBOOK.md`。
