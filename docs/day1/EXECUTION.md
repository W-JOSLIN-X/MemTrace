# Day 1 G0 execution specification

## Outcome

Day 1 ends with one verifiable vertical slice:

1. submit a programming task;
2. derive a deterministic task fingerprint;
3. publish a public plan without private chain-of-thought;
4. run an allow-listed static Python AST tool when applicable;
5. stream a Mock or DeepSeek response through SSE;
6. render stages, tool evidence, output, metrics, and failures in React.

Database persistence, feedback extraction, long-term memory, embeddings, and
the functional memory center are explicitly out of scope.

## Contract authority

- `contracts/schemas/g0-api.schema.json` is the normative REST body contract.
- `contracts/schemas/events.schema.json` is the normative SSE data contract.
- `contracts/day1-g0.json` is an audit manifest, not a third type source.
- FastAPI Pydantic models export `contracts/openapi.json`; contract tests compare
  the exported models and enums with the two normative schemas.

G0 is intentionally anonymous, single-user, and process-local. Tasks and replay
buffers disappear when the process restarts. Session ownership, idempotency,
SQLite, and restart recovery start at G1 on Day 2; no Day 1 acceptance statement
may imply those later guarantees.

## Stream recovery boundary

Persistent metadata uses a task-local monotonic `event_seq`. Answer chunks are
transient and use monotonic UTF-8 byte offsets. On a connection error, the web
client closes `EventSource`, loads the task snapshot, and reconnects with both
`after_event_seq` and `after_offset` query cursors. The server captures replay
high-water marks and registers the subscriber under the same per-task lock, so
events cannot fall into a replay/live-subscription gap. A terminal event always
causes one final snapshot fetch.

Persistent events contain safe metadata only. Task text, answer text, semantic
queries, raw tool input, AST source, upstream bodies, headers, and credentials
must never be written into a persistent event payload.

## Git checkpoints

| Step | Commit message | Gate |
|---|---|---|
| Contract | `docs(day1): freeze G0 scope and contracts` | JSON and naming audit |
| Contract repair | `fix(contract): make G0 interface executable and race-safe` | JSON Schema and reconnect audit |
| API skeleton | `chore(api): scaffold reproducible FastAPI runtime` | health/readiness tests |
| Agent API | `feat(api): implement G0 agent stream and safe tool` | API/SSE/tool tests |
| Web skeleton | `chore(web): scaffold React Vite Tailwind runtime` | install/type/lint/build |
| Chat UI | `feat(web): implement G0 chat event experience` | reducer/UI tests |
| Fixtures | `test(day1): add G0 fixtures contracts and smoke tests` | contract and smoke tests |
| Container | `build(day1): add verified single-container G0 delivery` | Docker health/restart |
| Browser UX repair | `fix(web): show accurate terminal timeline states` | Chrome/Edge terminal-state review |
| Evidence | `test(day1): record final G0 verification evidence` | all release gates |

No implementation commit may be amended after it has been reviewed. Fixes use
new commits so every rollback point remains available.

## Credential boundary

The application reads `LLM_API_KEY` from process environment or an ignored
local `.env`. A live key must never appear in tracked files, commands saved in
documentation, fixtures, logs, screenshots, or Git objects. Real-provider
smoke records only task/run identifiers, model, status, token counts, and
timings. The currently shared temporary key must be revoked after verification.

## Completion evidence

The final verification report records exact commands, exit codes, commit IDs,
OpenAPI hash, Mock and real-provider run IDs, Docker image ID, and remaining
external gates. The second-developer gate stays open until another environment
returns its smoke log.
