# Day 7 owner release report

Status: local-machine release gates accepted; normal `main`/`v0.1.0`
publication remains to be executed

## 1. Authority, source and scope

- Owner, integrator and publisher: `W-JOSLIN-X`.
- Integration branch: `codex/day7-release-hardening`.
- Fetched Day 6 base: `4aadf45fdb9de84e4efd645162d6cb6c29568067`.
- Browser-validated product image revision:
  `53eebfc5c6528c9d9d7325e3563af6bc88977d1d`.
- The following commit, `20ed143a5b8aa5cb6001cf121c696554aaf5509a`,
  changes only Ruff formatting in a historical schema utility and does not
  change the release runtime.
- Original brief page 5 SHA-256:
  `7CD810AFCA0E535A8802E4C19F6F4D270B64EBA1668CA2CA4676DFBE146E14E3`.
- Public contract: `2.1.0`; unique database head:
  `007_day7_public_release`.

The owner explicitly changed the acceptance scope on 2026-08-31: the clean
second-device/VM gate is removed. Day 7 is accepted on this computer using a
real DeepSeek provider, release Docker, installed Google Chrome and installed
Microsoft Edge. This decision does not weaken the real-provider gate and does
not claim that server deployment has happened. Server deployment remains a
separate stage after `v0.1.0` is frozen.

## 2. Failure baseline retained before fixes

- Settings was a placeholder and Evals was a static Day 5 `N/A` shell.
- Production routing had no public login, invitation registration, recovery,
  account security, CSRF, rate-limit or quota experience.
- Shared `blank_demo` and `seeded_demo` owners were enabled by default and were
  unsuitable for a public multi-user release.
- Memory Center mixed G4/v1 and G5/v2 projections.
- The ordinary conversation path did not expose real provider deltas and did
  not ask the real model to choose the approved AST tool.
- DeepSeek streaming buffered the full answer before yielding, making TTFT
  untruthful.
- The database head was still `006_conversation_first_memory`; release account
  tables and Day 7 runtime metrics did not exist.
- Production dependencies, secret-file Compose, backup/restore and security
  artifacts were not separated from development tooling.
- Page tests covered Conversation but not Auth, Memories, Evals or Settings as
  a finished release product.
- There was no four-baseline artifact, exact-image Docker evidence, full
  two-browser public-account evidence, or final backup-restore drill.

The pre-Day-7 deterministic baseline was 466 backend tests and 63 frontend
tests. It was engineering evidence only; no Mock result below is presented as
semantic acceptance.

## 3. Delivered product

The release now provides:

- invitation-only username/password accounts with Argon2id, one-time recovery
  codes, hashed sessions, Origin-bound CSRF, uniform auth errors, rate limits,
  logout-all, password change and transactional account deletion;
- a 50-real-turn UTC daily quota and one concurrent active turn per owner;
- ordinary multi-turn chat with real DeepSeek SSE deltas, truthful actual
  usage, TTFT, total latency, current-turn memory override and memory-off mode;
- real-model applicability, extraction/classification, conflict/consolidation
  and effect judgment with no keyword, TF-IDF or substring semantic fallback;
- real model selection of the sole `python_ast_check` tool, whose argument is a
  server-created code-block ID and whose implementation only performs
  `ast.parse`;
- a live preference/rule/experience sidebar and a unified v2 Memory Center for
  lifecycle, immutable versions, Diff, restore-as-new-version, relations,
  conflict resolution, anonymous Pack and safe deletion;
- measured Evals and complete Settings pages, with no production placeholder or
  required `N/A` metric;
- a runtime-only, non-root, read-only release image, secret-file Compose,
  request-size/security-header controls, account CLI and SQLite backup/restore
  utilities.

The v1 API remains only as a G1-G4 compatibility surface. Production pages use
the v2 `kind/content/applies_when` projection.

## 4. Deterministic engineering evidence

### Initial and repaired gate

The first expanded final command deliberately checked `apps/api scripts`, not
only the narrower planned `apps/api` format scope. Results were:

- pip check: exit 0;
- Ruff check: exit 0;
- backend pytest: exit 0, 501 passed in 528.09 seconds;
- Alembic heads: exit 0, only `007_day7_public_release`;
- Day 1-Day 7 fixture validator: exit 0;
- expanded Ruff format: exit 1 only because
  `scripts/day5/sync_g4_schema.py` had historical formatting drift.

The drift was mechanically repaired and committed as `20ed143`; targeted Ruff
check and format-check then both exited 0. The failure is retained here instead
of being rewritten as an initial pass.

### Frontend and contract evidence after the product fix

| Gate | Actual result |
|---|---|
| `npm run typecheck` | exit 0 |
| `npm run lint` | exit 0 |
| `npm test` | exit 0, 19 files / 84 tests |
| `npm run build` | exit 0, Vite production bundle |
| OpenAPI plus Day 7 schema generation, run twice | exit 0; identical hashes and zero Git diff |

The deterministic contract hashes are:

- OpenAPI:
  `7457ce4bd01ee1e4950ec105716392063592248aa275e79763dc7171c635851b`;
- G0 API schema:
  `143354f2089bf8b6b84eb5fc7658d32868ff5495b2fef6e07b68d77f9c074a9f`;
- Memory Pack v2 schema:
  `843d6342a7fa030201de526050661076e902180b0d11dbe5955b51eaa5ac6c79`;
- conversation-event schema:
  `45dab8808673df327949e099d72bcd46f68654655f1cfc21e7a3b0163573ac8`.

The 501-test backend suite includes fresh `007`, `006 -> 007 -> 006 -> 007`,
stale-revision readiness, auth/session/CSRF/rate/quota, transaction rollback,
worker recovery, SSE recovery, owner isolation, Pack safety, backup/restore and
G1-G4 regression coverage.

After the first report commit `f14ecd3`, the complete deterministic gates were
run again against the unchanged product tree:

- pip check, Ruff check over `apps/api scripts`, and Ruff format-check over all
  112 files: exit 0;
- backend pytest: exit 0, 501 passed in 562.03 seconds;
- Alembic heads and fixture validation: exit 0, unique `007`, all Day 1-Day 7
  fixtures valid;
- frontend typecheck, lint and build: exit 0;
- frontend Vitest: exit 0, 19 files / 84 tests.

This evidence-only wording update does not change runtime code. Contract
generation, Git whitespace, secret and artifact checks are repeated again on
the final publication candidate.

## 5. Real DeepSeek semantic evidence

Every accepted semantic result used `MOCK_MODE=false`, provider mode `real`,
model `deepseek-v4-flash`, provider-returned non-synthetic usage, and no
Mock/keyword fallback.

Failure evidence is retained:

- a runner without the ignored local configuration stopped before cases with
  `REAL_PROVIDER_NOT_CONFIGURED`;
- two nearly exhausted gate accounts stopped at 9/16 and 8/16 with controlled
  quota 429 responses;
- a sandbox-network blind-judge run recorded 8/8
  `BLIND_JUDGE_PROVIDER_ERROR`; the same official preflight and judge in the
  system network then passed.

Accepted results:

| Real gate | Result |
|---|---|
| model list, minimal response, streaming, strict JSON schema, function calling, actual usage | 6/6 |
| 16-case validation workflow, two independent executions | 16/16 each; precision 1.0; safety false activations 0 |
| untouched semantic test | 16/16 |
| blinded memory A/B | 8/8 memory-on wins; critical regressions 0 |
| four baselines, two repetitions | 64/64 real workflows |
| Day 3 public REST compatibility | 21/21 fixtures and 2/2 smoke; 9 engineering-only cases explicitly skipped |
| Day 4 public REST compatibility | first 29/30 timed out; complete retry 30/30 |
| Day 5 public REST compatibility | 20/20 with bounded two-second preview TTL |

For the exact frozen baseline artifact, MemTrace was not worse than
retrieval-only/full-history in 7/8 cases, median provider input was 318 tokens
versus full-history 525, p95 TTFT was 1063 ms and p95 total latency was 8395 ms.
Observed quality passes were 0/16 no-memory, 15/16 full-history, 16/16
retrieval-only and 15/16 MemTrace. Raw synthetic conversations and blind-judge
material remain only in ignored output; the tracked artifact contains controlled
metrics and hashes.

## 6. Exact release Docker, persistence and recovery

- Docker Desktop Engine 29.6.1 ran image `memtrace:0.1.0` with OCI revision
  `53eebfc5c6528c9d9d7325e3563af6bc88977d1d`.
- Compose project `memtrace-d7-release-gate` used loopback port 18070,
  `MOCK_MODE=false`, `ALLOW_DEMO_SESSIONS=false`, real
  `deepseek-v4-flash`, read-only secret files, non-root runtime, read-only root
  filesystem and the unique `007` head.
- Cold start, `docker compose restart app`, and `down`/`up` without `-v` all
  preserved account, task, memory, event, quota and the two labeled volumes.
- After the down/up recovery, Chrome completed a new real memory-off turn with
  88 tokens, TTFT 1887 ms and total provider time 2378 ms; Edge completed one
  with 88 tokens, TTFT 789 ms and total time 1211 ms.
- The exact SQLite backup `/app/backups/memtrace-53eebfc.sqlite3` is 12,382,208
  bytes, SHA-256
  `7a1450f3dc14a42b57e39e8d3a34befa7a201ee2a4c81e66e7fbef6c0ece022f`,
  quick-check `ok`, migration `007_day7_public_release`.
- That backup was restored by the non-root runtime to a new independently
  labeled volume. The isolated instance on port 18072 read a pre-backup task
  with HTTP 200 and then completed a new real DeepSeek turn: 85 actual tokens,
  TTFT 1733 ms, total provider time 2329 ms, quota 29 -> 28, exact revision
  `53eebfc...`.
- The isolated restore container and only its temporary restore volume were
  removed after evidence capture. The main data and backup volumes were not
  touched.

Main-container logs contained 8,483 lines after the complete browser and
recovery exercise. Exact log matches were zero for the synthetic body canary,
the XSS body, known prompt phrases, DeepSeek API key, session secret and every
ignored browser credential file. Restore-instance logs likewise had zero known
body, API-key and session-secret matches.

## 7. Exact Chrome and Edge acceptance

Both installed browsers used separate persistent profiles and independent
invitation-created accounts; shared demo sessions were disabled.

- Google Chrome user agent: `Chrome/151.0.0.0` on Windows 10/11 x64.
- Microsoft Edge user agent: `Edg/152.0.0.0` on Windows 10/11 x64.
- Chrome account `d7_final_chrome` covered `prefer`, `separate_scopes`, recovery
  rotation, password change, logout-all/relogin and permanent single-memory
  deletion.
- Edge account `d7_final_edge` covered manual `merge`, `pause_both`, source-task
  deletion and Pack import from Chrome. The imported unique card was explicitly
  `source=import` and `status=paused`.
- Both completed invitation registration, recovery-code handling, logout/login,
  ordinary real streaming chat, positive and negative real tool planning,
  extraction of preference/rule/experience, sidebar edit/confirm/lifecycle,
  paraphrase/cross-language reuse, current override, unrelated negative,
  memory off, helpful/harmful feedback, search, immutable versions, Diff,
  restore-as-new-version, lifecycle, conflicts, Pack, Evals, Settings, desktop
  and mobile viewports, XSS plain-text rendering, refresh and Docker recovery.
- Edge requests for the Chrome task, stream, memory, memory events, usages,
  relations and Pack export all returned the uniform cross-owner 404.
- Edge account deletion returned to login, invalidated the session (401), and
  the old credentials produced only the generic authentication error.
- A browser-discovered defect allowed superseded cards to appear editable.
  Commit `53eebfc` made superseded content/type/scope and version restore
  read-only while retaining permanent deletion. The exact image and a new
  Vitest regression test passed.

The final clean recovery traces for both browsers had zero console errors and
zero unexpected network failures. Expected owner-isolation 404s and deliberate
Docker restart/down-up SSE interruptions are recorded separately. After the
restore instance was intentionally removed, a later Chrome user-agent read saw
expected reconnect errors to port 18072; that post-cleanup diagnostic is not
misrepresented as part of the clean product trace.

Screenshots and traces are ignored under:

- `output/playwright/day7/chrome/final-53eebfc`;
- `output/playwright/day7/edge/final-53eebfc`.

They include chat, Memory Center, Evals, Settings, desktop/mobile layouts and
clean post-recovery traces. No browser profile, raw prompt, screenshot, trace or
credential is tracked by Git.

## 8. Dependency, SBOM and CVE evidence

- `npm audit --omit=dev --audit-level=high`: exit 0; 8 production dependencies;
  zero vulnerabilities at every npm severity.
- isolated `pip-audit 2.10.1` against the hash-locked runtime: exit 0; 40
  dependencies; zero known vulnerabilities. Artifact SHA-256:
  `a1045ef7c35517cb204740674a5c3f0348a4a50720e50ba2b1842b26c0059854`.
- exact-image SPDX 2.3 SBOM: 197 packages, 809,444 bytes, SHA-256
  `b9a331756841021c68348d0b0a751294c121bd0ddd9f7857c8c1280b87d313e8`.
- Docker Scout full SARIF: 72 findings in 17 packages: 2 critical, 5 high,
  14 medium, 40 low and 11 unspecified. All 72 reported `not fixed`; none had a
  fixed version. SARIF SHA-256:
  `d8c20d1471ae20f9d5cc8ca00335624c191d93c0855f176d6aab96ad17027ca6`.
- Docker Scout `--only-fixed --only-severity critical,high`: zero findings.
  SARIF SHA-256:
  `cd93fa72c47ff0b04b5150bfb780a66bae711a2cab50112ac167ffd39bdb887d`.

The owner explicitly authorized Docker Scout's PURL/layer-digest transmission.
The release criterion is no fixable critical/high finding, which passed. The 72
currently unfixed upstream findings are retained as residual risk, not hidden
behind a generic “scan passed” statement.

## 9. Privacy incident retained

During an earlier browser-driver password-change diagnostic, a newly generated
password candidate was accidentally included in an ignored automation snapshot.
The server rejected it, it was never an active credential, and the snapshot was
deleted. No accepted password, recovery code, invite, API key or session secret
entered Git or final screenshots. This remains recorded as test-driver handling
error.

## 10. Remaining publication procedure and limitations

The post-report backend and frontend reruns are complete. At the time this
evidence update is committed, no remote claim is made yet. Publication still
requires:

1. repeat deterministic contract generation, `git diff --check`, secret and
   ignored-artifact checks on the final candidate;
2. rebuild the release image with the final Git revision in its OCI label and
   recheck health/ready and runtime-only dependencies;
3. verify GitHub identity with `gh auth status`, `gh api user` and an official
   remote read, retrying before treating one failed check as logout;
4. fetch `origin`, reject an unreviewed main race, and use only
   `git push origin HEAD:main`;
5. verify remote main, create and normally push annotated `v0.1.0`, then verify
   the peeled tag and remote main resolve to the same full SHA.

No force push, PR, collaborator approval or `integration/day2` promotion is
part of this release. Real server SSH, DNS, TLS, reverse proxy and production
data migration remain outside Day 7. The owner has expressly accepted that no
second-device evidence is required for this release.
