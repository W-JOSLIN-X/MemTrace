# Contract Change Note: 2.0.0 — Conversation-First Memory

> Status: member-a-implementation — frozen for implementation, pending member-b review.
> Effective: 2026-08-28 (Asia/Shanghai)
> Base SHA: `bb69aa90a9ddb3c0a84f02b5a58dd92b7094f922`

## 1. Why 2.0.0

This is a breaking change to the **memory semantics and user experience layer**, not to the persistence/infra layer. G1–G4 data safety, owner isolation, idempotency, and event contracts remain intact. The v1.x contract tokens (`schema_version="1.0"`, `MemoryCard.schema_version`, etc.) are preserved as legacy identifiers but no longer drive product behavior.

The old contract assumed: "classify the conversation → map to a fixed category → store as MemoryCard."
The new contract assumes: "extract real user preferences/rules/experiences from the conversation via LLM → store as MemoryCard with 3 visible kinds → LLM judges applicability and effect."

## 2. Breaking Changes

### 2.1 MemoryKind normalization (v1 → v2)

| v1 kind | v2 kind | Notes |
|---|---|---|
| `preference` | `preference` | No change |
| `constraint` | `rule` | Renamed; `rule_subtype = "constraint"` kept internally |
| `procedure` | `rule` | Renamed; `rule_subtype = "procedure"` kept internally |
| `experience` | `experience` | No change |
| `environment` | **migrated to `legacy_unverified`** | No longer auto-active |
| `learning_checkpoint` | **migrated to `legacy_unverified`** | No longer auto-active |

Users see only three kinds: `preference`, `rule`, `experience`.

### 2.2 Task classification removed from product semantic chain

- `TaskFingerprint.domain`, `task_type`, `artifact_type`, `framework`, `classification_source`, `classification_reasons`, `concepts`, `tool_context`, `semantic_query` are **read-only legacy fields**.
- They persist in `task_fingerprints` for migration compatibility only.
- They no longer drive MemoryManager, retrieval, or the v2 API.
- v2 retrieval uses `MemoryCard.scope` (natural-language `applies_when`) + LLM applicability judge.

### 2.3 MemoryCard schema_version bump

| Field | v1 | v2 |
|---|---|---|
| `MemoryCard.schema_version` | `"1.0"` | `"2.0"` |
| `MemoryMutationBatch.schema_version` | N/A | `"2.0"` |

### 2.4 New required fields on MemoryCard (v2)

```json
{
  "applies_when": "Natural language description of when this memory applies",
  "exceptions": ["Natural language exception conditions"],
  "confidence": 0.92,
  "review_status": "active | review | paused | archived | superseded",
  "valid_from": "RFC3339",
  "valid_to": null,
  "rule_subtype": "constraint | procedure | null"
}
```

### 2.5 MemoryCard v1 fields that become legacy-only

| v1 field | v2 status |
|---|---|
| `title` | **Deprecated.** Kept for v1 legacy compatibility; v2 uses `content` as primary field. |
| `rule` | **Deprecated.** Folded into `content`. |
| `avoid` | **Deprecated.** Folded into `content`. |
| `trigger_text` | **Deprecated.** Folded into `applies_when`. |
| `scope` (structured) | **Deprecated.** Replaced by `applies_when` (natural language) + optional tags. |
| `scope_level`, `scope_domain`, `scope_task_type` | **Legacy only.** Kept in DB for migration; not exposed in v2 list/detail. |
| `domain`, `task_type`, `artifact_type`, `audience`, `project_key`, `language`, `framework`, `concepts` | **Legacy scope fields.** Replaced by `applies_when` natural language. |
| `source_trust` | **Deprecated.** v2 uses `confidence` only. |
| `rule_confidence`, `scope_confidence` | **Deprecated.** v2 uses single `confidence`. |
| `save_preselected` | **Removed.** v2 uses `review_status` and auto-activation rules. |
| `evidence_missing` | **Legacy.** v2 uses `confidence` and source validation. |
| `retrieved_count`, `injected_count`, `verified_applied_count` | **Moved to usage/trace.** Not on card projection. |
| `helpful_count`, `harmful_count`, `stale_count` | **Moved to usage feedback.** Not on card projection. |
| `last_used_at` | **Legacy.** Use `valid_from`/retrieval trace instead. |

### 2.6 MemoryKind enum change (v1 → v2)

```python
# v1 (G2/G3)
class MemoryKind(StrEnum):
    PREFERENCE = "preference"
    CONSTRAINT = "constraint"
    PROCEDURE = "procedure"
    EXPERIENCE = "experience"
    ENVIRONMENT = "environment"
    LEARNING_CHECKPOINT = "learning_checkpoint"

# v2 (Day 6+)
class MemoryKindV2(StrEnum):
    PREFERENCE = "preference"
    RULE = "rule"
    EXPERIENCE = "experience"
```

## 3. New Types (v2.0.0)

### 3.1 MemoryMutationBatch

The structured output from the background Memory Manager LLM call.

```json
{
  "schema_version": "2.0",
  "decision": "mutate | noop | needs_review",
  "operations": [
    {
      "operation": "add | update | supersede",
      "target_memory_id": null,
      "kind": "preference | rule | experience",
      "content": "...",
      "applies_when": "...",
      "exceptions": [],
      "confidence": 0.92,
      "reason_code": "explicit_durable_preference",
      "evidence": [
        {"message_id": "msg_...", "quote": "User's original text"}
      ]
    }
  ]
}
```

**Model must NOT output**: owner_id, memory_id (for add), status, version, timestamps, event_seq, permissions.

### 3.2 MemoryDurability (LLM output)

```json
{
  "durability": "explicit_durable | one_shot | ambiguous | reinforce_usage_only",
  "reason_code": "explicit_keyword | inferred | ambiguous_mixed | no_reusable_content",
  "confidence": 0.88
}
```

### 3.3 ApplicabilityJudgeResult (LLM output)

```json
{
  "applicability": "applicable | current_instruction_override | conflict | irrelevant",
  "confidence": 0.91,
  "reason_code": "semantic_match | current_override | scope_conflict | no_semantic_link",
  "overridden_by": "Current user instruction text if override",
  "conflict_with": "memory_id if conflict"
}
```

### 3.4 EffectJudgeResult (LLM output)

```json
{
  "judgment": "applied | violated | not_observable | unknown",
  "confidence": 0.85,
  "evidence_excerpt": "Exact substring from assistant response",
  "reason_code": "memory_directly_influenced | memory_contradicted | no_observable_effect | judge_failed"
}
```

### 3.5 ConflictConsolidationResult (LLM output)

```json
{
  "decision": "duplicate | update | supersede | coexist | review",
  "primary_memory_id": "mem_...",
  "superseded_memory_id": "mem_...",
  "reason": "Natural language explanation",
  "confidence": 0.90
}
```

### 3.6 MemoryReflectionJob (DB model)

```json
{
  "job_id": "job_...",
  "task_id": "task_...",
  "run_id": "run_...",
  "turn_index": 1,
  "status": "pending | running | completed | failed",
  "attempt": 0,
  "mutation_decision": "mutate | noop | needs_review | null",
  "provider_model": "deepseek-v4-flash",
  "prompt_hash": "sha256:...",
  "schema_version": "2.0",
  "error_code": "MEMORY_... | null",
  "created_at": "...",
  "updated_at": "..."
}
```

### 3.7 MemoryEvent types (v2 additions)

New persistent event types added to `EventType`:
- `memory.analysis.started`
- `memory.analysis.completed`
- `memory.effect.judged`

Existing types retained: `memory.extraction.stage`, `memory.candidate.created`, `memory.admission.resolved`, `memory.job.failed`, `memory.injected`, `memory.usage.verified`, `memory.usage.feedback.recorded`, `memory.lifecycle.changed`, `memory.conflict.detected`, `memory.conflict.resolved`, `memory.pack.previewed`, `memory.pack.committed`.

### 3.8 ReviewStatus (MemoryCard v2)

```python
class ReviewStatus(StrEnum):
    ACTIVE = "active"
    REVIEW = "review"
    PAUSED = "paused"
    ARCHIVED = "archived"
    SUPERSEDED = "superseded"
```

Replaces the old `MemoryCardStatus` for the user-visible memory lifecycle in v2. The v1 status enum is kept as legacy.

## 4. v2 API Endpoints

### 4.1 Memory CRUD (v2)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v2/memories` | List with kind/status/review_status filter |
| GET | `/api/v2/memories/{id}` | Detail with versions/evidence |
| PATCH | `/api/v2/memories/{id}` | Edit kind/content/applies_when (creates new version) |
| POST | `/api/v2/memories/{id}/confirm` | Confirm review → active |
| POST | `/api/v2/memories/{id}/dismiss` | Dismiss review → archived |
| GET | `/api/v2/memories/{id}/events` | Memory-specific event history |

### 4.2 Memory Events (v2)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v2/memory-events?after_seq=` | Owner/session-level catch-up |

### 4.3 Task Memory (v2)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v2/tasks/{id}/memory-usage` | Memory usage for this task (diagnostic only) |
| POST | `/api/v2/tasks/{id}/memory-effect/{mem_id}/feedback` | Helpful/harmful/stale feedback |

### 4.4 Reflection Jobs (v2)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v2/reflection-jobs/{id}` | Job status and result |

## 5. Migration: 006_conversation_first_memory

### 5.1 New/modified tables

| Table | Action | Key changes |
|---|---|---|
| `memory_cards` | **Add columns** | `content`, `applies_when`, `review_status`, `confidence`, `valid_from`, `valid_to`, `rule_subtype`; `title`/`rule`/`avoid`/`trigger_text` become legacy |
| `memory_cards` | **Add index** | `owner_id, review_status, updated_at DESC` |
| `memory_versions` | **Add columns** | `content`, `applies_when`, `confidence`, `review_status` |
| `memory_evidence` | **Add columns** | `message_id` FK for v2 evidence |
| **`memory_reflection_jobs`** | **New table** | Background worker job for LLM memory extraction |
| **`memory_llm_judgments`** | **New table** | Applicability and effect judge results |
| `memory_relations` | **Add columns** | `llm_consolidation_decision`, `consolidation_confidence` |

### 5.2 Data migration rules

1. `preference → preference` (kind unchanged)
2. `constraint → rule` with `rule_subtype = "constraint"`
3. `procedure → rule` with `rule_subtype = "procedure"`
4. `experience → experience` (kind unchanged)
5. `environment → legacy_unverified` (review_status, no longer auto-active)
6. `learning_checkpoint → legacy_unverified` (review_status)
7. Cards created from Mock/fixed template → `review_status = "review"` (quarantine)
8. v1 `title` + `rule` + `avoid` concatenated into v2 `content`
9. v1 `trigger_text` → v2 `applies_when`
10. v1 structured `scope` → v2 `applies_when` (natural language projection)
11. Old `scenario`/`domain`/`task_type`/`classification_source` → **read-only legacy columns**, no longer drive product
12. `schema_version` updated from `"1.0"` to `"2.0"`

### 5.3 Downgrade safety

- 006→005 restores v1 schema but **does not** automatically reverse data transformations.
- Downgrade is for emergency rollback only; it must not be used on production data without manual review.
- 005→006→005→006 round-trip verified in tests.

## 6. Removed from Semantic Main Chain

| Component | Old behavior | New behavior |
|---|---|---|
| `logic.py auto_rule_v1` | Classifies conversation into domain/task_type/framework | **Legacy only.** No longer drives memory or retrieval. |
| `durability.py keyword detector` | "以后"→durable, "这次"→one_shot | **Legacy only.** Replaced by LLM durability judgment. |
| `compiler.py Mock templates` | Fixed title/rule/avoid/kind from keyword matching | **Test fixture only.** Never appears in real run. |
| `worker.py canonical scope` | Rule-based scope override | **Legacy only.** Replaced by LLM applies_when + server safety check. |
| `retrieval char_tfidf_v1 final decision` | TF-IDF score as semantic verdict | **Candidate recall only.** LLM applicability judge makes final decision. |
| `verifier longest-common-substring` | Text overlap → applied/violated | **Legacy only.** Replaced by LLM effect judge. |
| Mock REST Eval "semantic success" | Proves interface/state machine | **Engineering evidence only.** Not counted as semantic accuracy. |
| Chat candidate approval flow | User must approve each card | **Background auto-deposit + sidebar observation.** High-confidence auto-active; low-confidence → review. |

## 7. LLM Provider Contract

### 7.1 Responses API (replaces Chat Completions)

- Primary path: `POST /v1/responses` with streaming (`stream=True`)
- Structured output: `text.format = json_schema` with `strict=True`
- **Frozen model**: `deepseek-v4-flash` (confirmed 2026-08-28)
- `reasoning` items are **never read, stored, or emitted** to application objects
- Chat Completions retained as fallback path only; Responses API is primary

### 7.2 Provider modes

| Mode | Purpose | Semantics |
|---|---|---|
| `real` | DeepSeek Responses API | All semantic tests must run in this mode |
| `mock` | Deterministic fixture | Engineering tests only; never counted as semantic evidence |

`MOCK_MODE=true` with no Key → provider_mode=mock (default safe state)
`MOCK_MODE=false` + Key → provider_mode=real (required for semantic gate)

### 7.3 Fail-fast semantic runner

```
provider_mode != real → FAIL
has_llm_api_key != True → FAIL
model != frozen_manifest_model → FAIL
no actual token usage in response → FAIL
prompt/schema/config hash mismatch → FAIL
```

No automatic fallback to Mock.

## 8. Test Evidence Split

### 8.1 Engineering evidence (Mock allowed)

- Schema/parser/OpenAPI isomorphism
- Migration/transaction/concurrency/idempotency
- Owner isolation, Pack safety, SSE catch-up
- UI reducer, refresh recovery, drafts
- Provider timeout/illegal JSON/retry exhaustion
- OpenAPI zero-diff, secret scan

### 8.2 Semantic evidence (real required)

- Should this form long-term memory?
- Is extracted content faithful to the user?
- preference/rule/experience classification correct?
- add/update/supersede/noop/review decision correct?
- Does current task apply this memory?
- Does current explicit constraint override old memory?
- Did memory truly improve/constrain the answer?
- Chinese/English paraphrase, implicit expression, negation

## 9. Open Issues (for member B review)

1. **Embedding model selection**: v2 hybrid recall needs an embedding model. Day 6 MVP uses larger LLM-judged candidate set; embedding deferred to Day 7 or later.
2. **Confidence thresholds**: "high confidence auto-active" threshold must be set on validation set and frozen. Not set in this change note.
3. **Memory token budget**: Exact budget size (currently 100 per card / 300 total estimated) needs A/B validation.
4. **Reason code taxonomy**: `MemoryMutationBatch.reason_code` and `EffectJudgeResult.reason_code` enums need to be enumerated after first LLM run produces actual outputs.
5. **`applies_when` natural language format**: No enforced template; may benefit from a few-shot canonical form after real runs.
