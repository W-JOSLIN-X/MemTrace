# MemTrace Day 1 G0 verification report

## Verdict

Updated at `2026-08-21T21:04:06+08:00` on branch `feat/day1-g0`.

The G0 implementation is buildable, testable, browser-verified,
container-verified, and verified against the real DeepSeek Provider. It is
**not yet a fully closed Day 1 release** because one team gate remains open:

1. one smoke run by the second developer in another environment.

For that reason this report does not authorize the planned merge into `main` or
creation of the `day1-g0-verified` tag. Local verification cannot replace the
second developer's independent run.

## Release identity

| Item | Recorded value |
|---|---|
| Source HEAD before this report | `f727158520c87f198ded0c089de9ad636dd2f496` |
| OpenAPI SHA-256 | `763B8159610106C9E80DD6287594D2F510017125D4A334FB1B9CC6837A065A02` |
| Container image | `sha256:6cd18548ca5bbcd410fee60d674c428d4792983ca940fae86316bea6a1fd23e8` |
| Image size | `71,797,880` bytes |
| Chrome evidence SHA-256 | `1D237E68B641F7304BABDDC00727D0C25B3A6628DB1BEC3CF82497EE46C9F4D4` |
| Edge evidence SHA-256 | `78AEFE2EDCD8B9571BFF4685A3C14AE66B378FD2D1EEFA394545D369470D8BD1` |

Evidence images:

- `output/playwright/chrome-g0-success.png`
- `output/playwright/edge-g0-success.png`

## Runtime versions

| Component | Version |
|---|---|
| Local Python | `3.11.4` |
| API virtual environment Python | `3.11.4` |
| Container Python | `3.11.16` |
| Node.js | `22.15.0` |
| npm | `10.9.2` |
| Docker Engine CLI | `29.6.1`, build `8900f1d` |
| Docker Compose | `v5.2.0` |
| Docker Scout | `v1.22.0` |
| Trivy | `v0.73.0` |

The container deliberately uses a newer Python 3.11 security patch than the
local interpreter. Both Node and Python base images are pinned by digest in the
Dockerfile, so a future tag update cannot silently change this verified image.

## Git checkpoints

| Commit | Purpose |
|---|---|
| `dff2256` | initialize the MemTrace project baseline |
| `0d46656` | freeze G0 scope and initial contracts |
| `4db16d7` | make REST/SSE contracts executable and reconnect-safe |
| `855ab0e` | scaffold reproducible FastAPI runtime |
| `1610b56` | scaffold React/Vite/Tailwind runtime |
| `518ad32` | reject final messages on failed snapshots |
| `4694b43` | implement the G0 chat event experience |
| `c658331` | implement G0 API, stream, provider, store, and AST tool |
| `5ed2e48` | add fixtures, contract validator, and live smoke |
| `b58d8b6` | add and verify the single-container delivery |
| `f727158` | correct current/completed/skipped/failed timeline UI states |
| `6bcfb2b` | record local verification evidence and real-provider smoke gate |
| `2de013f` | remove vulnerable runtime packaging tools |

No checkpoint was amended or history-rewritten.

## Automated verification

### Backend

Command shape:

```powershell
.\apps\api\.venv\Scripts\python.exe -m pytest -W error -q .\apps\api\tests
```

Result: three consecutive final-source runs returned exit code `0`, each with
`83 passed`. Ruff check, Ruff format check, `pip check`, fixture validation, and
deterministic OpenAPI export also returned exit code `0`.

The OpenAPI exporter was run with malformed environment overrides and produced
the same SHA-256. This proves the committed document is not altered by a
developer's local `APP_NAME`, `APP_VERSION`, or model setting.

Provider failure gate:

```powershell
.\apps\api\.venv\Scripts\python.exe -m pytest -W error -q `
  .\apps\api\tests\test_providers.py `
  .\apps\api\tests\test_orchestrator.py `
  -k 'timeout or status_errors or empty_provider_stream or empty_first_attempt or failure_after_first_chunk or invalid_provider'
```

Result: exit code `0`, `17 passed, 4 deselected`. This covers explicit timeout,
safe upstream status mapping, retry only before the first visible chunk, no
silent retry after a visible chunk, malformed Unicode, and terminal failure
fallbacks.

### Frontend

Each final-source iteration ran, in order:

```powershell
npm run typecheck
npm run lint
npm run test
npm run build
```

Result: three consecutive iterations returned exit code `0`. Each Vitest run
reported `4` files and `23` tests passed; each production build transformed
`53` modules. A clean `npm ci --no-audit --no-fund` and `npm ls --depth=0`
also returned exit code `0`.

The only install warning is the deprecated `whatwg-encoding` package beneath
the jsdom test-only dependency. It is not present in the browser production
bundle and is not a vulnerability finding.

### Mock live smoke and SSE reconnect

Command shape:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\day1\smoke.ps1 `
  -BaseUrl http://127.0.0.1:8000 `
  -PythonExe .\apps\api\.venv\Scripts\python.exe
```

Result: five consecutive final-image runs returned exit code `0`. Every run
checked health, ready, three invalid inputs, Python AST success, a forced
post-chunk Provider failure, 404, terminal snapshot, SSE headers, event order,
UTF-8 offsets, `stream.done`, and a forced disconnect followed by dual-cursor
continuation. Therefore the reconnect branch was exercised five times, not
inferred from a unit test.

Safe IDs from the fifth run:

| Trace | Task ID |
|---|---|
| Python success | `task_01M0J4BC92V2MHRH6Q8DD6FEVN` |
| Forced Provider failure | `task_01M0J4BDCR0RZQ0M7VJVVPK907` |
| Forced disconnect/reconnect | `task_01M0J4BE6XRM8YYEADQESMNZXY` |

Mock metrics and fixture token counts are explicitly labelled Mock. They are
not evidence of real-provider latency or token usage.

## Container verification

The first build used `docker compose build --pull`, downloaded both base
images, ran `npm ci`, built the React application, installed the hash-locked
Python environment, and returned exit code `0`. The final frontend repair was
then rebuilt into the recorded image ID.

Verified behavior:

- container health became `healthy`;
- root and `/memories` returned the React SPA;
- unknown `/api` paths remained JSON 404 rather than SPA fallback;
- API `/ready` returned `provider_mode=mock`;
- runtime UID was `10001`, not root;
- container `pip check` passed;
- Mock container had an empty `LLM_API_KEY`;
- final container logs contained no credential-like literal, private reasoning,
  traceback, critical, or unhandled marker;
- `docker compose down` removed the container and network while preserving the
  named data volumes.

Three independent lifecycle iterations each performed:

1. `docker compose down`;
2. `docker compose up -d` and wait for healthy;
3. React root request;
4. `docker compose restart` and wait for healthy;
5. `/ready` verification.

All three cold-start and all three restart iterations returned exit code `0`.

## Browser verification

Playwright CLI drove installed Chrome and Microsoft Edge in headed mode against
the final container image.

Chrome verified:

- empty form disabled;
- task submission and Mock badge;
- Python AST call, public plan, streamed output, UTF-8 count, token and latency;
- accurate terminal timeline copy after the browser-discovered UX repair;
- a JavaScript task skipped the Python tool and displayed its reason;
- `/memories` navigation and direct refresh;
- console result: `0` errors and `0` warnings.

Edge independently ran a Python task through the same terminal UI and reported
`0` console errors and `0` warnings.

## Security and dependency gates

| Gate | Result |
|---|---|
| Tracked credential-pattern scan | pass |
| Git-history credential-pattern scan | pass |
| `.env` ignored by Git | pass |
| Static source scan for `exec`, `eval`, subprocess, shell execution | pass; AST tool calls only `ast.parse` |
| npm full dependency audit | `0 vulnerabilities` |
| npm production dependency audit | `0 vulnerabilities` |
| isolated `pip-audit` of `requirements.lock` | `No known vulnerabilities found` |
| Docker Scout authenticated full high/critical scan | 5 unfixed OS findings; SARIF preserved |
| Docker Scout fixable high/critical scan | pass; `0C / 0H` |
| Trivy full high/critical scan | 34 Debian findings and 2 Python packaging-tool findings before repair |
| Python packaging-tool findings after repair | pass; `setuptools` removed from runtime image |

The five remaining Docker Scout findings are `CVE-2026-12087`,
`CVE-2026-13221`, `CVE-2026-14456`, `CVE-2026-48959`, and
`CVE-2026-48962`. Scout marks every one as `fixed_version=not fixed`; they are
in the Debian Perl/OpenSSL base layer rather than a Python application package.
They remain an explicit release risk: the report does **not** claim zero total
high/critical CVEs. The fixable-only gate is zero after removing runtime
`setuptools`, whose vendored `jaraco.context` and `wheel` caused the two
actionable Trivy findings. The authenticated Scout evidence is stored in
`output/docker-scout-day1.sarif`.

## Provider contract and real-run gate

The real adapter targets `https://api.deepseek.com`, model
`deepseek-v4-flash`, with `thinking.type=disabled`, explicit timeout, SDK
retries disabled, and no use of `reasoning_content`. These choices follow the
official DeepSeek chat-completion, thinking-mode, pricing/model, and error-code
documentation:

- <https://api-docs.deepseek.com/api/create-chat-completion>
- <https://api-docs.deepseek.com/guides/thinking_mode>
- <https://api-docs.deepseek.com/quick_start/pricing-details-cny/>
- <https://api-docs.deepseek.com/quick_start/error_codes/>

The user configured the temporary credential only in ignored `.env`. Tools
checked only the presence boolean, and no command, report, source file, fixture,
or Git object contains its value. Two content-redacted real streams succeeded:

| Run | Task / run | Tokens | First token | Total |
|---|---|---|---:|---:|
| 1 | `task_01M0J6NSYQ9H3XXE85XMZJX82V` / `run_01M0J6NSYQ2XCB38TK85003JFB` | 78 prompt / 23 output | 3304.75 ms | 3755.31 ms |
| 2 | `task_01M0J6P5CXH3BA7YQEBQRSZWBQ` / `run_01M0J6P5CXF2K0G4EJP1B1YP35` | 78 prompt / 23 output | 1774.21 ms | 2138.74 ms |

Both reported `provider_mode=real`, model `deepseek-v4-flash`,
`token_source=actual`, terminal status `succeeded`, contiguous UTF-8 chunks,
`run.completed`, `stream.done`, and a matching final snapshot. A boolean-only
container-log scan found neither a credential pattern nor
`reasoning_content`.

`scripts/day1/real_provider_smoke.py` is the content-redacted executable gate.
Its parser and all success invariants passed the two real runs above. The
security-repaired final image also passed five additional Mock runs on an
isolated port.

Because the credential appeared in chat, it must be revoked after this gate and
must not become the team's formal development key.

## Known limitations and open gates

1. G0 is anonymous, single-user, and process-local. A restart intentionally
   discards every task; auth, SQLite, and durable event logs are Day 2 work.
2. Request fields are bounded, but Uvicorn direct exposure has no whole-request
   byte cap. A trusted reverse proxy must enforce one before public deployment.
3. The runtime image uses the single hash lock and therefore contains pytest,
   Ruff, and other test dependencies. It is verified but not a minimal image.
4. Second-developer smoke on another environment: open.
5. The base image has five currently unfixed Scout high/critical findings.
   Fixable application/runtime-package findings are zero, but total findings
   are not zero.

## Final release decision

Local implementation status: **pass with one team gate and one accepted-or-fix
risk decision still open**.

Do not merge `feat/day1-g0` into `main` and do not create the
`day1-g0-verified` tag until the second-developer gate passes. The five unfixed
OS-layer findings must be explicitly accepted by the team or eliminated by a
separately tested base-image change; they must not silently disappear from the
checklist.
