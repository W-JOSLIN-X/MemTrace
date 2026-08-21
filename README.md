# MemTrace（忆迹）

MemTrace 是一个面向黑客松第四赛道的轻量 Agent 原型。Day 1 的目标是打通
G0：任务提交、确定性任务指纹、公开计划、只读 Python AST 工具、Mock/真实
Provider 流式回答，以及 React 对阶段和结果的实时展示。

当前 Day 1 明确不包含数据库持久化、用户登录、长期记忆、反馈提取和记忆中心
业务。任务只保存在后端进程内；重启后旧任务返回 404，这是 G0 的预期行为。

## 当前验收状态

当前源码已在本机实际执行 build、up、health、React、SSE、restart 和 smoke。
下表只描述本机证据；最终重复次数、镜像 ID、命令退出码和 task ID 仍以验证报告
为准，第二台电脑不能由本机自证。

| 项目 | 当前状态 |
|---|---|
| 前后端入口和 lock 文件 | 已存在 |
| Fixture、Schema 与 live Mock smoke | 本机通过；smoke 8/8 |
| Docker/Compose 静态配置 | 本机通过；这与实际镜像构建分别验证 |
| Docker image build | 本机已实际构建 |
| 单容器 API/SSE/React | 本机已验证；包含 SPA fallback 和 API 404 隔离 |
| Docker restart/health/smoke | 本机已完成一次；最终重复门禁见验证报告 |
| 第二台电脑启动 | 未验证 |

## 目录

```text
apps/api/        FastAPI 后端，入口 memtrace_api.main:app
apps/web/        React/Vite 前端，生产构建输出 apps/web/dist
contracts/       G0 REST 和 SSE 规范
fixtures/day1/   Day 1 确定性 QA 输入
scripts/day1/    Fixture 校验和全链路 smoke
Dockerfile       Node 构建阶段 + Python 单进程运行阶段
compose.yaml     单容器和持久卷
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

首次联调保持：

```dotenv
MOCK_MODE=true
LLM_API_KEY=
```

真实模式只能把新生成的 Key 写入本地 `.env`，不能写进 README、源代码、fixture、
命令参数、日志、截图或 Git。先前在聊天中出现过的 Key 已经暴露，应撤销后再生成，
不能当成正式开发凭据。

## 3. 启动后端

在仓库根目录执行，无需激活虚拟环境：

```powershell
python -m venv .\apps\api\.venv
.\apps\api\.venv\Scripts\python.exe -m pip install --require-hashes -r .\apps\api\requirements.lock
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

Mock 模式下 `/ready` 应为 200 并明确返回 `provider_mode=mock`。真实模式缺少 Key
时必须返回 503，不能伪装 ready。

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

## 6. Day 1 全链路 smoke

先以 Mock 模式启动 API，并保持 `MOCK_CHUNK_DELAY_MS=250`，让断线恢复测试有足够
时间实际触发。然后在仓库根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\day1\smoke.ps1
```

Smoke 检查 health、ready、三种 422、任务创建、SSE headers/顺序/正文、终态
TaskSnapshot、Provider partial failure、未知任务 404，以及 `after_event_seq +
after_offset` 双游标恢复。任何缺项都必须非零退出。详细规则见
`docs/day1/SMOKE_SPEC.md`。

### 真实 Provider 门禁

真实测试不能复用 Mock fixture 的通过结果。用户在被 Git 忽略的 `.env` 中手工设为
`MOCK_MODE=false` 并填入临时 `LLM_API_KEY`，重启 API 后连续执行两次：

```powershell
.\apps\api\.venv\Scripts\python.exe .\scripts\day1\real_provider_smoke.py `
  --base-url http://127.0.0.1:8000 `
  --expected-mode real `
  --timeout-seconds 180
```

该脚本不读取 Key，也不打印任务正文、回答正文、请求头或上游错误体；成功时只输出
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
4. 非 root 用户启动一个 Uvicorn worker；
5. `/api/v1/health` 作为容器 healthcheck。

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
healthy。随后验证重启：

```powershell
docker compose restart
docker compose ps
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
powershell -ExecutionPolicy Bypass -File .\scripts\day1\smoke.ps1
```

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
`memtrace-eval-results`。Day 1 任务本身仍只在内存中，容器重启后消失；卷是为
后续日期预留，不应把任务恢复误报为已实现。

Day 1 为减少两名初学者维护两套 Python lock 的风险，运行镜像暂时安装同一份
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
| `/ready` 返回 503 | Mock 模式、数据目录、真实 Key | 先用 Mock；不要在代码中填 Key |
| SSE 一直等待 | API 日志、Mock delay、事件终态 | 不得改成一次性假流；修复 `stream.done` |
| 双游标 smoke 说任务过早结束 | `MOCK_CHUNK_DELAY_MS` | 设为 250 或更高后重启 API |
| 容器根路径 404 | `MEMTRACE_WEB_DIST`、静态挂载 | 后端实现 SPA fallback 后重建镜像 |
| 容器 unhealthy | `docker compose logs app` | 先修 `/health`，不要提高 retries 掩盖错误 |
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

“我电脑上运行过一次”或“Dockerfile 已存在”都不等于 Day 1 完成。
