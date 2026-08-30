# MemTrace（忆迹）

MemTrace 是一个面向黑客松第四赛道的对话 Agent 原型。当前 Day 6 G5 主体验与普通
对话 Agent 一致：用户直接进行多轮对话，真实大模型在后台提取并分类
`preference | rule | experience`，右侧记忆栏实时展示 pending/active 状态，并允许用户
修改类型、内容和适用范围。后续轮次由真实大模型分别完成适用性、冲突/合并和效果判断，
当前明确指令始终优先于长期记忆。

G1–G4 的 owner 隔离、幂等、事务、持久事件、恢复、Memory Center、版本 Diff、冲突裁决、
匿名 Memory Pack 和安全删除仍保留。旧 `/api/v1` 自动分类与 TF-IDF 能力只作为兼容路径；
G5 `/api/v2` 产品主链不使用关键词、正则、TF-IDF 或 substring verifier 作语义最终判定。
Fake/Mock 只用于事务、错误映射和前端 reducer 等工程测试，不能作为 G5 语义验收证据。

## 当前验收状态

Day 1–Day 5 历史证据分别保留在对应文档目录；Day 6 的工程测试、真实 DeepSeek 语义
评测、容器与双浏览器结果以 `docs/day6/OWNER_INTEGRATION_REPORT.md` 为准。只有该报告
记录的本轮实际命令可作为验收证据。

| 项目 | 当前状态 |
|---|---|
| 前后端入口和 lock 文件 | 已存在 |
| Fixture、Schema 与工程测试 | 包含 G1–G5、会话 Cookie、owner 隔离、幂等写入和 metadata-only Eval |
| G5 真实模型语义门禁 | 必须 `MOCK_MODE=false`、固定实际模型、非零供应商 usage 且无 Mock fallback |
| Docker/Compose 与双浏览器 | 以 Day 6 所有者报告的本轮 cold start、恢复和真实 Provider 证据为准 |
| 第二台电脑启动 | 未验证 |

## 目录

```text
apps/api/        FastAPI 后端，入口 memtrace_api.main:app
apps/web/        React/Vite 前端，生产构建输出 apps/web/dist
contracts/       G1–G5 REST、事件、Pack、对话与 LLM 记忆规范
fixtures/day1/   Day 1 确定性 QA 输入
fixtures/day2/   24 条自动分类、反馈能力和持久事件标注
fixtures/day4/   Day 4 draft 审阅源与 30 条 G3 可执行 fixture
fixtures/day5/   Day 5 draft 审阅源、8 条冲突与 12 条 Pack/security fixture
fixtures/day6/   16 条真实语义 case 与 8 条 memory-off/on A/B case
scripts/day1/    Fixture 校验和全链路 smoke
scripts/day4/    REST-only G3 EvalRunner
scripts/day5/    REST-only G4 EvalRunner 与契约投影工具
scripts/day6/    真实 Provider 预检、组件检查和 REST-only G5 EvalRunner
Dockerfile       Node 构建 + Alembic migration + Python 单进程运行
compose.yaml     单容器、SQLite 持久卷和必填 SESSION_SECRET
```

## 1. 安装前检查（Windows PowerShell）

需要：

- Python 3.11.x；
- Node.js 22.12 或更高的 22.x；
- npm；
- Git；
- Docker Desktop + Compose v2（仅容器流程需要）。

在仓库根目录运行：

```powershell
python --version
Get-Command python
node --version
npm --version
docker --version
docker compose version
```

本机曾出现 `py -3.11` 指向不存在安装的问题。因此本文统一使用实际可工作的
`python`。如果 `python --version` 不是 3.11.x，先修正 PATH；不要在错误解释器下
继续安装依赖。

## 2. 本地配置与密钥

复制配置模板：

```powershell
Copy-Item -LiteralPath '.\.env.example' -Destination '.\.env'
git check-ignore -q .env
if ($LASTEXITCODE -ne 0) { throw '.env 没有被 Git 忽略，请停止操作' }
```

纯工程开发可以保持安全默认值：

```dotenv
MOCK_MODE=true
LLM_API_KEY=
```

同时必须在本地 `.env` 写入一个随机、至少 32 bytes 的 `SESSION_SECRET`。该值只能
来自环境或本地被忽略的 `.env`，不得使用 README 示例值、提交到 Git 或出现在日志和
截图中。`MOCK_MODE=true` 不需要模型平台登录，但只能生成工程证据；G5 语义、Docker 和
双浏览器验收必须显式改为 `MOCK_MODE=false` 并使用真实 Provider。Demo 会话仍需要该
本地签名密钥。

真实模式只能把新生成的 Key 写入本地 `.env`，不能写进 README、源代码、fixture、
命令参数、日志、截图或 Git。先前在聊天中出现过的 Key 已经暴露，应撤销后再生成，
不能当成正式开发凭据。

## 3. 启动后端

在仓库根目录执行，无需激活虚拟环境：

```powershell
python -m venv .\apps\api\.venv
.\apps\api\.venv\Scripts\python.exe -m pip install --require-hashes -r .\apps\api\requirements.lock
.\apps\api\.venv\Scripts\python.exe -m alembic -c .\apps\api\alembic.ini upgrade head
.\apps\api\.venv\Scripts\python.exe -m uvicorn memtrace_api.main:app `
  --app-dir .\apps\api\src `
  --reload `
  --host 127.0.0.1 `
  --port 8000
```

另开终端检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
Invoke-RestMethod http://127.0.0.1:8000/api/v1/ready
```

Mock 模式下 `/ready` 应为 200，并明确返回 `provider_mode=mock`、数据库连接通过、
`migration_revision=pass`。空库、旧 Alembic revision、生产环境缺少
`SESSION_SECRET`，或真实模式缺少模型 Key 时必须返回 503。

## 4. 启动前端

另开 PowerShell：

```powershell
Set-Location .\apps\web
npm ci
npm run dev -- --host 127.0.0.1 --port 5173
```

浏览器打开 <http://127.0.0.1:5173>。开发服务器把 `/api` 代理到 8000，浏览器中
不保存也不读取模型 Key。

## 5. 本地测试

后端：

```powershell
.\apps\api\.venv\Scripts\python.exe -m ruff check .\apps\api\src .\apps\api\tests .\apps\api\scripts
.\apps\api\.venv\Scripts\python.exe -m ruff format --check .\apps\api\src .\apps\api\tests .\apps\api\scripts
.\apps\api\.venv\Scripts\python.exe -m pytest -W error .\apps\api\tests -q
```

前端：

```powershell
Set-Location .\apps\web
npm ci
npm run typecheck
npm run lint
npm run test
npm run build
Set-Location ..\..
```

Fixture/Schema：

```powershell
.\apps\api\.venv\Scripts\python.exe .\scripts\day1\validate_fixtures.py
```

该脚本依赖的 `jsonschema` 已写入后端 hash lock；不要临时安装未锁版本后声称
环境可复现。

## 6. Day 2 G1 全链路 smoke

先以 Mock 模式启动 API，并保持 `MOCK_CHUNK_DELAY_MS=250`，让断线恢复测试有足够
时间实际触发。然后在仓库根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\day1\smoke.ps1
```

Smoke 先建立 `blank_demo` Cookie 会话，再检查 health、ready、旧 `scenario` 422、
自动分类、任务幂等创建、SSE headers/顺序/正文、终态 TaskSnapshot、Provider partial
failure、未知任务 404，以及 `after_event_seq + after_offset` 双游标恢复。任何缺项都
必须非零退出。Day 1 的原始规则仍见 `docs/day1/SMOKE_SPEC.md`，Day 2 增量证据见
`docs/day2/VERIFICATION_REPORT.md`。

### 真实 Provider 门禁（Day 6 G5 必需）

真实测试不能复用 Mock fixture 的通过结果。用户在被 Git 忽略的 `.env` 中手工配置：

```dotenv
MOCK_MODE=false
LLM_API_KEY=<用户本人填写>
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=<先经官方模型列表和最小调用确认的模型 ID>
```

随后先运行真实预检和五阶段组件检查：

```powershell
.\apps\api\.venv\Scripts\python.exe .\scripts\day6\provider_preflight.py
.\apps\api\.venv\Scripts\python.exe .\scripts\day6\component_probe.py
```

API 以真实模式启动后，再通过公开 REST API 运行 16×2 语义评测与 8 组 A/B：

```powershell
.\apps\api\.venv\Scripts\python.exe .\scripts\day6\eval_runner.py `
  --base-url http://127.0.0.1:8000 --mode all `
  --output .\output\day6\real-g5-report.json
```

旧 G1 Provider 兼容 smoke 仍可单独运行：

```powershell
.\apps\api\.venv\Scripts\python.exe .\scripts\day1\real_provider_smoke.py `
  --base-url http://127.0.0.1:8000 `
  --expected-mode real `
  --timeout-seconds 180
```

上述 runner 只保存资源 ID、受控枚举、token、延迟、判定和失败码；不保存对话、记忆、
回答或 Key。旧脚本同样不读取 Key，也不打印任务正文、回答正文、请求头或上游错误体；成功时只输出
task/run ID、Provider 模式、模型、token 来源与数量、首字和总耗时。它会实际验证
AST 工具事件、连续 UTF-8 chunk、metrics、`run.completed`、`stream.done` 和终态
快照。完成后撤销聊天中暴露过的临时 Key，并重新生成正式开发 Key。

## 7. 单容器构建与启动

### 静态文件边界

后端支持环境变量 `MEMTRACE_WEB_DIST`，容器中固定为 `/app/static`。FastAPI 在
API 路由之后挂载构建产物，并只对非 `/api` 路径回退到 `index.html`；开发环境目录
不存在时跳过挂载，不影响 API。本机已分别验证根路径、`/memories` SPA 路由和未知
`/api` 路由的 404，不能只用镜像 build 成功替代这些检查。

### 静态检查

```powershell
docker compose config --quiet
```

不要把 `docker compose config` 的完整输出保存到日志：它可能展开本地 `.env`。

### 构建

```powershell
docker compose build --pull
```

Dockerfile 使用：

1. 固定 digest 的 Node 22 builder 执行 `npm ci` 和 `npm run build`；
2. 固定 digest 的 Python 3.11 runtime 按带 hash 的 `requirements.lock` 安装；
3. React dist 复制到 `/app/static`；
4. 非 root 用户先执行 `alembic upgrade head`，成功后才启动一个 Uvicorn worker；
5. `/api/v1/ready` 作为容器 healthcheck，迁移未到唯一 head 时不得 healthy。

本机开发解释器是 Python 3.11.4；固定的容器镜像当前提供 Python 3.11.16，二者
属于同一 3.11 兼容系列。容器采用更新的安全补丁版本，不为追求字面一致而降级，
最终报告必须分别记录两者，不能只写笼统的“Python 3.11”。

### 启动和验收

```powershell
docker compose up -d
docker compose ps
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
Invoke-RestMethod http://127.0.0.1:8000/api/v1/ready
Invoke-WebRequest http://127.0.0.1:8000/ -UseBasicParsing
powershell -ExecutionPolicy Bypass -File .\scripts\day1\smoke.ps1
```

根路径必须返回 React HTML，而不是 FastAPI 404。`docker compose ps` 必须显示
healthy。创建 task 和 feedback 后记录非敏感 ID，再验证重启及同一任务恢复：

```powershell
docker compose restart
docker compose ps
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
powershell -ExecutionPolicy Bypass -File .\scripts\day1\smoke.ps1
```

只在同一 Demo 会话 Cookie 下恢复任务；换到另一个演示用户时，同一 task 的 REST 与
SSE 都必须是 404。持久性验收还必须执行一次保留卷的 `docker compose down` / `up -d`。

查看非敏感尾部日志：

```powershell
docker compose logs --no-color --tail 100 app
```

结束容器但保留数据卷：

```powershell
docker compose down
```

只有明确要删除所有 MemTrace 容器数据时才运行下列命令；它不可恢复：

```powershell
docker compose down --volumes
```

Compose 使用三个命名卷：`memtrace-data`、`memtrace-exports` 和
`memtrace-eval-results`。Day 2 的 task、run、event、feedback、MemoryJob 和
idempotency 记录写入 `memtrace-data` 内的 SQLite；保留同一卷时，容器 restart 和
compose down/up 后必须可恢复。进程中途终止的运行任务恢复为 `RUN_INTERRUPTED`，
而不是伪装继续运行。

当前为减少两名初学者维护两套 Python lock 的风险，运行镜像暂时安装同一份
hash lock，其中也包含 pytest、Ruff 等开发依赖，因此镜像不是最小生产镜像。另一个
已知边界是 Uvicorn 直连尚未设置整个 HTTP 请求体的全局字节上限；字段级契约已有
上限，但公开部署前仍需在可信反向代理设置请求体限制。两项均不得被误报为已解决。

修复后的运行镜像已移除不需要的 `setuptools`，Docker Scout 的“存在修复版本的
高危/严重漏洞”结果为零。但 Debian 基础层仍有 5 项被 Scout 标记为
`not fixed` 的高危/严重 CVE；这属于明确保留的发布风险，不等于镜像总漏洞为零。
完整编号与扫描证据见 `docs/day1/VERIFICATION_REPORT.md` 和
`output/docker-scout-day1.sarif`。

## 8. 常见故障

| 现象 | 检查 | 处理 |
|---|---|---|
| `python` 不是 3.11 | `python --version`、`Get-Command python` | 修 PATH 后重建 `apps/api/.venv` |
| `npm ci` 拒绝安装 | Node 版本、`package-lock.json` | 使用 Node 22.12+，不要删除 lock |
| `/ready` 返回 503 | DB 连接、Alembic head、`SESSION_SECRET`、Provider | 先修迁移或环境；不要在代码中填密钥 |
| SSE 一直等待 | API 日志、Mock delay、事件终态 | 不得改成一次性假流；修复 `stream.done` |
| 双游标 smoke 说任务过早结束 | `MOCK_CHUNK_DELAY_MS` | 设为 250 或更高后重启 API |
| 容器根路径 404 | `MEMTRACE_WEB_DIST`、静态挂载 | 后端实现 SPA fallback 后重建镜像 |
| 容器 unhealthy | `docker compose logs app` | 先修 `/ready` 所报告的迁移/配置问题，不要提高 retries 掩盖错误 |
| 真实 Provider 失败 | 余额、模型名、网络、限流 | 保留真实失败；Mock 必须显式标识 |

## 9. 验证报告必须记录

- 当前 commit；
- `python/node/npm/docker/docker compose` 版本；
- 测试、build、smoke 命令和退出码；
- Docker image ID；
- Mock/Real task 和 run ID，但不记录请求头或 Key；
- SSE 断线恢复是否真正收到 cursor 之后的 continuation chunk；
- Docker cold start 和 restart 的 health 结果；
- 第二台电脑尚未执行时明确写“未验证”。

“我电脑上运行过一次”或“Dockerfile 已存在”都不等于 Day 2 完成。
