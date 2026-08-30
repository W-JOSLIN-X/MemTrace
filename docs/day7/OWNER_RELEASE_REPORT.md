# Day 7 owner release report

Status: implementation in progress

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

Append-only. No Day 7 completion claim is valid until local engineering, real
DeepSeek, Docker, Chrome, Edge, second-device, backup/restore, remote `main`,
and annotated `v0.1.0` evidence are recorded here.
