# MemTrace contracts

Day 1 and Day 2 have normative, machine-validatable contracts:

- `schemas/g0-api.schema.json` defines REST request/response bodies, the task
  snapshot, controlled enums, and the unified error envelope.
- `schemas/events.schema.json` defines the JSON carried in each SSE `data:`
  field. The SSE wire `event:` value must equal `data.event_type`; persistent
  events also use `id:` equal to `data.event_seq`.
- `openapi.json` is deterministically exported from FastAPI OpenAPI definitions.

`day1-g0.json` and `day2-g1.json` are **audit manifests**, not schemas and not type-generation
sources. They record endpoint/status mappings, G0/G1 exceptions, trace cardinality,
reconnection rules, and links to the normative schemas.

The FastAPI Pydantic models must export OpenAPI compatible with
`g0-api.schema.json`. The backend event models must validate against
`events.schema.json`. Frontend types and Mock fixtures are generated from, or
checked against, those exported artifacts; neither side may invent a second
spelling in application code.

Contract changes require a dedicated `docs` or `chore` commit before backend
and frontend implementation changes.
