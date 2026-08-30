# Day 7 owner release report

Status: product candidate verified locally; external vulnerability-scan consent and
second-device release gates remain open

## Locked baseline

- Owner: `W-JOSLIN-X`.
- Integration branch: `codex/day7-release-hardening`.
- Verified base and fetched `origin/main`:
  `4aadf45fdb9de84e4efd645162d6cb6c29568067`.
- Original brief page 5 SHA-256:
  `7CD810AFCA0E535A8802E4C19F6F4D270B64EBA1668CA2CA4676DFBE146E14E3`.
- GitHub CLI was independently verified as `W-JOSLIN-X` in the system
  environment. Docker Desktop 4.81.0 / Engine 29.6.1 was available. The local
  ignored `.env` contained an `LLM_API_KEY`; its value was not printed.

## Failure baseline retained before fixes

- Settings was a placeholder and Evals was a static Day 5 N/A shell.
- Production routing had no login, registration, recovery, account, CSRF,
  invite, rate-limit, or quota experience.
- The memory center mixed G4/v1 and G5/v2 projections.
- The G5 turn endpoint returned only after generation and did not expose live
  provider deltas to the product UI.
- DeepSeek streaming buffered the complete response before yielding, so it did
  not provide truthful first-token UX.
- The G5 conversation path did not ask the real model to select the approved
  AST tool.
- Shared `blank_demo` and `seeded_demo` owners were enabled by default and were
  unsuitable for public deployment.
- The only migration head was `006_conversation_first_memory`; no public
  account schema existed.
- Production requirements and release Compose/backup/restore/SBOM workflow had
  not been separated.
- Page tests covered Conversation but not authentication, Memories, Evals, or
  Settings as a release product.
- No Day 7 four-baseline artifact, Docker release evidence, two-browser public
  account evidence, second-device evidence, release tag, or final backup
  restore evidence existed.

## Engineering baseline before Day 7 changes

| Gate | Result |
|---|---|
| `python -m pip check` | exit 0, no broken requirements |
| `python -m ruff check apps/api` | exit 0 |
| `python -m ruff format --check apps/api` | exit 0, 82 files |
| `python -m pytest apps/api/tests -q` with engineering Mock mode | exit 0, 466 passed in 376.16s |
| `alembic heads` | exit 0, `006_conversation_first_memory` |
| fixture validator | exit 0 |
| web typecheck/lint | exit 0 |
| web Vitest in system environment | exit 0, 12 files / 63 tests |
| web production build in system environment | exit 0 |

The sandbox-only Vitest/build attempts initially failed with `spawn EPERM`;
the same commands passed in the system environment, so this is retained as an
environment distinction rather than a product failure.

## Fix and release evidence

The first fully exercised product-code candidate is
`5d02d3010b4e5560d9de697b471391e6ff742796`. It contains all 23 owner commits
after the fetched Day 6 base. The final three browser-visible correctness fixes
before the candidate were:

- `cb50676`: restore the release page layouts;
- `e2a667f`: keep memory actions visible at normal desktop heights;
- `5d02d30`: make permanent-deletion events replayable without weakening the
  mutable lifecycle contract.

The last fix retains `pending | active | paused | archived | superseded` for
mutable memory state and permits `deleted` only as the terminal
`memory.deleted.new_status`. Before the fix, replaying the owner memory stream
from sequence zero after a permanent deletion returned HTTP 500. The fixed
backend and strict TypeScript parser now accept only that event exception, and
the OpenAPI/schema generator sorts `$defs` deterministically.

### Local deterministic engineering gates

All commands below ran against `5d02d3010b4e5560d9de697b471391e6ff742796`.

| Gate | Actual result |
|---|---|
| `apps/api/.venv/Scripts/python.exe -m pip check` | exit 0 |
| `python -m ruff check apps/api scripts` | exit 0 |
| `python -m ruff format --check apps/api` | exit 0, 93 files |
| `python -m pytest apps/api/tests -q` | exit 0, 501 passed in 521.36s |
| `python -m alembic -c apps/api/alembic.ini heads` | exit 0, only `007_day7_public_release` |
| `python scripts/day1/validate_fixtures.py` | exit 0, Day 1 through Day 7 fixtures valid |
| `npm run typecheck` | exit 0 |
| `npm run lint` | exit 0 |
| `npm test` | exit 0, 19 files / 83 tests |
| `npm run build` | exit 0 |
| OpenAPI and Day 7 schema generation twice | exit 0 and zero diff both times |
| `git diff --check` and tracked secret scan | exit 0 / no finding |

The two identical contract-generation runs produced these SHA-256 values:

- OpenAPI: `7457ce4bd01ee1e4950ec105716392063592248aa275e79763dc7171c635851b`;
- G0 schema: `143354f2089bf8b6b84eb5fc7658d32868ff5495b2fef6e07b68d77f9c074a9f`;
- Memory Pack schema: `843d6342a7fa030201de526050661076e902180b0d11dbe5955b51eaa5ac6c79`;
- conversation event schema:
  `45dab8808673df327949e099d72bcd46f68654655f1cfc21e7a3b0163573ac8`.

An intentionally broader, non-frozen `ruff format --check apps/api scripts`
also inspected historical utility scripts and reported only the pre-existing,
unmodified `scripts/day5/sync_g4_schema.py`. The frozen release gate is
`apps/api`, as documented above; this broader diagnostic is retained and is
not represented as a passing gate.

### Real DeepSeek semantic and product-effect gates

Every accepted semantic result below used `MOCK_MODE=false`, provider mode
`real`, and model `deepseek-v4-flash`. Provider usage was returned by the
provider; no zero usage was synthesized and no Mock/keyword fallback was
accepted.

The failure evidence was retained:

- the first runner invocation omitted the local `.env` and stopped with
  `REAL_PROVIDER_NOT_CONFIGURED` before executing a case;
- the first two 16-case accounts had nearly exhausted their daily product
  quota, so they stopped at 9/16 and 8/16 respectively with controlled 429
  failures;
- the first A/B run completed its product workflows, but the sandbox could not
  reach the independent blind-judge provider and recorded
  `BLIND_JUDGE_PROVIDER_ERROR` for 8/8;
- the same official provider preflight in the system network then passed 6/6,
  proving this was a sandbox-network distinction before the A/B rerun.

Fresh-account and system-network results:

| Real gate | Result |
|---|---|
| official provider preflight: model list, minimal response, streaming, strict JSON schema, function calling, actual usage | 6/6 passed |
| 16-case semantic workflow, fresh account A | 16/16 passed, precision 1.0, security false activations 0 |
| 16-case semantic workflow, fresh account B | 16/16 passed, precision 1.0, security false activations 0 |
| blinded memory A/B | 8/8 memory-on wins, critical regressions 0 |
| four baselines, two repetitions | 64/64 real workflows completed |
| Day 3 public REST compatibility | 21/21 fixtures and 2/2 smoke; 9 engineering-only cases explicitly skipped |
| Day 4 public REST compatibility | first 29/30 (`TASK_TIMEOUT`), complete retry 30/30 |
| Day 5 public REST compatibility with bounded two-second preview TTL | 20/20 |

For the exact four-baseline run, MemTrace was not worse in 7/8 comparison
cases, used median 318 provider input tokens versus full-history 525, and had
p95 first-token latency 1063 ms. All 64 workflows completed. The recorded
quality passes were 0/16 no-memory, 15/16 full-history, 16/16 retrieval-only,
and 15/16 MemTrace. These are observed values, not retrofitted thresholds.

Raw synthetic conversations and judge material are confined to ignored
`output/day7/docker-release/reports`; the repository artifact contains only
controlled aggregate metrics and hashes.

### Release Docker, persistence and recovery

- Docker Desktop Engine 29.6.1 built `memtrace:0.1.0` with OCI revision
  `5d02d3010b4e5560d9de697b471391e6ff742796`.
- Compose project `memtrace-d7-release-gate` ran on loopback port 18070 with
  `MOCK_MODE=false`, `ALLOW_DEMO_SESSIONS=false`, provider mode `real`, model
  `deepseek-v4-flash`, and only read-only secret-file mounts.
- Cold start reached the unique `007_day7_public_release` head and reported
  healthy/ready.
- `docker compose restart app` preserved account, task, memory, event and quota
  state. A post-restart real turn persisted with 91 chat tokens.
- `docker compose down` without `-v`, followed by `up -d`, preserved the exact
  labeled data and backup volumes. The pre-down task remained readable and a
  new post-up real turn persisted with 95 chat tokens, TTFT 1520 ms and provider
  latency 2043 ms.
- SQLite backup API created `/app/backups/memtrace-5d02d301.sqlite3`, 11796480
  bytes, SHA-256
  `5902e0a2570401120f74c143656c5ee3305e0223d740eb3bfc9ef8e41744b4e8`,
  quick-check `ok`, migration `007_day7_public_release`.
- The first restore attempt correctly failed because a fresh Docker volume was
  root-owned while the image runs as UID/GID 10001. Only the new independent
  restore volume was assigned to UID/GID 10001; the second restore then passed
  hash, quick-check and migration verification.
- Port 18071 was already occupied by an older owner-created restore-gate
  container, so no unrelated container was stopped. The exact candidate restore
  instance used port 18072 instead.
- The independent restore instance read a pre-backup task and completed a new
  real turn: 78 chat tokens, 2695 ms provider latency, provider mode `real`,
  model `deepseek-v4-flash`.
- The exact main-container log set contained 244 lines. Exact secret hits,
  synthetic body-canary hits, sensitive JSON body-field hits, Traceback hits,
  and HTTP 500 hits were all zero.

### Chrome and Edge

Both browsers used installed stable browser binaries, separate persistent
profiles and different real public accounts. Shared demo sessions were
disabled. The broad registration, conversation, tool, memory lifecycle,
conflict, Pack, account-security, recovery, owner-isolation and restart flows
were completed on ancestor `45bc9cb`. The exact `5d02d30` rerun was a bounded
changed-path retest after layout, action-visibility and deletion-replay fixes;
it is not substituted for the final full exact-SHA browser gate.

- Chrome evidence is under ignored `output/playwright/day7/chrome`, including
  `chat-5d02d30.png`, `memory-center-5d02d30.png`, `evals-5d02d30.png`,
  `settings-5d02d30.png`, `settings-mobile-5d02d30.png` and
  `final-trace-5d02d30`.
- Edge evidence is under ignored `output/playwright/day7/edge` with the same
  exact-candidate filenames and its own `final-trace-5d02d30`.
- Both final sessions showed the exact runtime revision, provider mode `real`,
  model `deepseek-v4-flash`, actual usage, conversation recovery, memory center,
  eval metrics and settings. User/model HTML canaries created zero executable
  image/script nodes.
- The exact Chrome and Edge changed-path sessions each had zero console errors,
  zero console warnings and zero unexpected network failures. Existing owner
  resources remained isolated and deletion-event replay returned HTTP 200 after
  the fix.

Earlier broad-flow profiles and screenshots remain ignored diagnostic history.
They prove feature exercise on the candidate ancestry, while a final exact-SHA
full-flow rerun remains mandatory before release.

### Dependency and image artifacts

- `npm audit --omit=dev --audit-level=high --json`: exit 0; 8 production
  dependencies; info/low/moderate/high/critical all zero.
- isolated `pip-audit 2.10.1` against the hash-locked runtime file: exit 0; 40
  dependencies; zero known vulnerabilities. Report SHA-256:
  `a1045ef7c35517cb204740674a5c3f0348a4a50720e50ba2b1842b26c0059854`.
- local-image Docker Scout SBOM: SPDX 2.3, 199 packages, 811255 bytes. Artifact
  SHA-256:
  `50e31e8a14255f430c67bc53e8d0f83c96ac22e5aae81c341a457f2d3cb35b9c`.

Docker's official data-handling documentation states that local Scout CVE
analysis transmits package URLs and layer digests to the Scout service. The
actual CVE image scan is therefore deliberately not run until the owner gives
explicit consent for that metadata transmission and completes any Docker
account login the official CLI requests.

### Privacy incident retained

During an earlier browser-driver password-change check, a newly generated
password candidate was accidentally included in an ignored automation snapshot.
The server rejected that candidate, it was never an active credential, and the
snapshot was deleted. No accepted password, recovery code, invite, API key or
session secret entered Git or the final screenshots. This remains recorded as a
test-driver handling error rather than being silently omitted.

## Open release gates

Day 7 is not complete and must not yet be pushed or tagged:

1. the owner must explicitly authorize Docker Scout to transmit PURLs and layer
   digests, after which a fixable critical/high CVE result blocks release;
2. Chrome and Edge must each repeat the entire frozen browser checklist on the
   final SHA, not only the bounded `5d02d30` changed-path checks;
3. an unused Windows computer or clean Windows VM must clone the exact candidate,
   build from the documented secret-file flow, register a new account, complete
   five golden paths, and restore a backup;
4. after those gates, the frozen eval artifact and report must be finalized,
   the post-report local gates rerun, and the release image rebuilt with the
   final annotated-tag revision;
5. `origin/main` must be fetched and race-checked, then updated only by a normal
   `git push origin HEAD:main`; annotated `v0.1.0` may be pushed only when its SHA
   equals the verified remote main.

No claim of “Day 7 complete” is valid until these entries are replaced with
actual evidence and both remote refs are verified.
