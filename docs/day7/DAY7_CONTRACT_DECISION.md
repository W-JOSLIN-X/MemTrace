# Day 7 G5 public release contract decision

Status: frozen for implementation on 2026-08-30

## Source and product boundary

The controlling source is page 5 of `大工黑客松S2-赛题发布.pdf`, whose
SHA-256 is
`7CD810AFCA0E535A8802E4C19F6F4D270B64EBA1668CA2CA4676DFBE146E14E3`.
MemTrace remains a normal conversational Agent: planning, the single approved
`python_ast_check` tool, answer generation, background feedback-memory
extraction, and later memory application are all part of the product. Legacy
keyword classification, TF-IDF selection, and substring verification remain
compatibility-only G1-G4 paths and never decide G5 semantics.

## Public wire contract

- Public G5 REST/Event contract version: `2.1.0`.
- Database head: `007_day7_public_release`, linearly following
  `006_conversation_first_memory`.
- Authentication: local username/password accounts created by a one-time
  invitation, Argon2id passwords, hashed session/invite/recovery secrets,
  Origin-bound CSRF, uniform authentication failures, and database-backed rate
  limits.
- Quota: 50 real-model user turns per owner per UTC day and one active turn per
  owner. A reserved provider attempt consumes quota even when it fails.
- Production disables shared demo sessions. G1-G4 demo routes remain available
  only when `ALLOW_DEMO_SESSIONS=true`.
- Public pages and API use only the v2 memory projection
  `kind/content/applies_when`; v1 stays a compatibility test surface.

## Streaming and tool safety

`assistant.delta` is transient SSE content and is never written to the event
log. `turn.started`, `turn.completed`, and `turn.failed` are persistent,
metadata-only events. Provider retry is allowed only before the first visible
delta. Python candidates are assigned server-generated IDs; the model can
choose only a candidate ID, and the server performs `ast.parse` without code
execution, imports, shell, file, or network access.

## Evidence policy

Fake/Mock Provider results are engineering evidence only. Semantic release
evidence requires `MOCK_MODE=false`, the frozen real DeepSeek model, actual
provider usage, no fallback, REST-only evaluations, Docker, Chrome, Edge, and a
clean second-device clone. Missing external evidence blocks release and cannot
be represented as success.
