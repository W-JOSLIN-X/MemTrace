# Day 1 risk register

| Risk | Detection | Required response |
|---|---|---|
| Live credential reaches Git or logs | staged secret scan and log search | stop, remove, revoke key, add a new fix commit |
| Python launcher resolves a missing install | `python --version` and resolved executable | use the working Python 3.11 executable; document both-machine setup |
| Docker engine is installed but stopped | `docker version` cannot reach server | start Docker Desktop before container gate |
| SSE loses or duplicates output after reconnect | dual-cursor, high-water-mark, and browser reconnect tests | snapshot first; reconnect with event and byte-offset cursors; reject already applied data |
| Initial EventSource connects after the run starts | late-subscriber smoke test | replay process-local metadata and buffered chunks, then fetch the terminal snapshot |
| Provider fails after partial output | forced failure test | retain partial output; never silently retry after first chunk |
| Tool executes user code | static scan and adversarial tests | block merge; AST parsing only |
| Frontend and backend invent different events | contract comparison | update contract first, then both implementations |
| Mock is presented as a real call | UI and fixture review | permanent provider-mode badge and evidence label |
| Day 2 work leaks into Day 1 | scope review | remove database/memory-learning behavior from the branch |
| G0 is mistaken for durable or multi-user | restart and scope review | label it anonymous, single-user, process-local; keep G1 claims out of Day 1 |
| Persistent metadata contains user or model text | schema validation and event-log payload scan | store only controlled enums, IDs, counts, timings, offsets, and curated safe messages |
