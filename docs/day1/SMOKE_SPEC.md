# Day 1 G0 smoke specification

## Status

This document and `scripts/day1/smoke.ps1` define the executable gate. The
current source-tree implementation has now passed this script against a live
local API process. A script file or this status sentence alone is still not
evidence: the verification report must record the exact command, exit code,
timestamp, API commit, provider mode, and emitted Mock task IDs.

The verification report may mark this gate passed only after recording the
command, exit code, timestamp, API commit, and provider mode from a real run.

## Inputs

- `contracts/schemas/g0-api.schema.json`
- `contracts/schemas/events.schema.json`
- `fixtures/day1/demo_core.json`
- `fixtures/day1/feedback_drafts.json` (Day 2 design input only)
- the three `fixtures/day1/mock_sse_*.json` traces

Before any network request, the smoke script runs:

```powershell
python .\scripts\day1\validate_fixtures.py
```

This checks both Draft 2020-12 schemas, all REST fixture bodies, every event
envelope, event sequence, UTF-8 byte offsets, terminal snapshots, and a basic
credential/private-reasoning scan.

## Required API mode

Start the API in visible Mock mode. The response must say
`provider_mode=mock`; the script never treats fixture output as a real model
call. To make the disconnect test deterministic, the Mock Provider must stream
slowly enough that the process remains non-terminal after its first chunk. The
implementation should expose a test-only process setting such as:

```dotenv
MOCK_MODE=true
MOCK_CHUNK_DELAY_MS=250
```

The smoke script does not set or read `LLM_API_KEY`, and no fixture contains a
credential. Do not use this script as the real-provider smoke; that is a
separate gate whose environment supplies the key outside Git.

Run from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\day1\smoke.ps1
```

Optional parameters:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\day1\smoke.ps1 `
  -BaseUrl http://127.0.0.1:8000 `
  -PythonExe .\apps\api\.venv\Scripts\python.exe `
  -TimeoutSeconds 60 `
  -ReconnectProbeSeconds 8
```

When `-PythonExe` is omitted, the script first uses
`apps/api/.venv/Scripts/python.exe` if it exists, then falls back to the
`python` command on `PATH`. The selected interpreter must have the locked
`jsonschema` dependency; otherwise the smoke fails rather than silently
skipping fixture validation.

Success is exit code `0`. Any assertion, missing executable, network error,
unexpected status, malformed SSE frame, missing continuation chunk, or early
terminal run exits non-zero.

## Network checks

The script performs these checks in order:

1. `GET /api/v1/health` returns `200` and `status=ok`.
2. `GET /api/v1/ready` returns `200`, `status=ready`, and visible Mock mode.
3. Empty, whitespace-only, and generated 20,001-character inputs each return a
   unified `422 VALIDATION_ERROR` and a valid request ID.
4. The exact Python fixture returns `202`, a complete Python success trace,
   AST tool events, contiguous UTF-8 byte chunks, and a matching terminal
   TaskSnapshot.
5. The exact forced-failure fixture returns `202`, retains its partial output,
   emits `run.metrics -> task.stage:failed -> run.failed -> error ->
   stream.done`, and exposes `PROVIDER_ERROR` in its terminal snapshot.
6. A valid but unknown task ID returns unified `404 TASK_NOT_FOUND`.
7. The no-tool fixture is disconnected after its first chunk. The script gets a
   TaskSnapshot, reads `last_persistent_event_seq` and `end_offset`, reconnects
   with both `after_event_seq` and `after_offset`, rejects replay at or below
   either cursor, receives at least one continuation chunk, and reconstructs
   exactly the final snapshot.
8. The terminal snapshot is fetched after `stream.done`; it is the final truth
   for both success and failure.

The SSE response must include:

- `Content-Type: text/event-stream; charset=utf-8`
- `Cache-Control: no-cache, no-transform`
- `X-Accel-Buffering: no`

Heartbeat is a comment every 15 seconds. The ordinary fixture stream is shorter
than 15 seconds, so this script does not wait solely to observe a heartbeat;
heartbeat cadence belongs in the backend streaming test with a fake clock.

## Trace cardinality

Python success requires exactly one tool pair and one or more chunks. No-tool
success forbids tool events and requires one or more chunks. Forced failure
allows partial chunks but requires exactly one metrics, failed stage,
`run.failed`, `error`, and `stream.done`, with no `run.completed`.

Persistent events carry contiguous task-local integer IDs. Transient retrieval
and chunk events omit the SSE `id:` line and have `event_seq=null`. For every
chunk:

```text
end_offset = start_offset + len(delta encoded as UTF-8)
```

## Fixtures deliberately outside Day 1

`feedback_drafts.json` contains exactly eight inputs for Day 2 design. Its
top-level `day1_consumed=false` is a hard boundary: the Day 1 API must not
accept, extract, persist, or replay those drafts.

## Integration evidence status

The local live run has verified the deterministic Mock mapping, forced failure,
stream delay, SSE headers and wire format, TaskSnapshot validation, and both
reconnect cursors. The script prints three Mock task IDs only after all eight
stages pass, so the verification report can tie a run to its evidence.

The second-developer run in another environment remains open and cannot be
self-certified on this machine. Do not copy the fixture validator's PASS output
into the final report as proof of network checks: Schema-valid fixtures and a
live passing API are two different gates.
