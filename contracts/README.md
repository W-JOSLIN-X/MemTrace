# MemTrace contracts

`day1-g0.json` is the single source of truth for the Day 1 public REST, error,
and server-sent event vocabulary. Backend tests must compare their enums and
OpenAPI document with this file. Frontend types and mock fixtures must use the
same names; neither side may introduce a second spelling in application code.

Contract changes require a dedicated `docs` or `chore` commit before backend
and frontend implementation changes.

