# Day 5 Conflict Fixture Review

**Reviewer**: Member A (zlbk-wxy)
**Date**: 2026-08-25
**Status**: Initial review complete, member B joint review pending

## Fixture Overview

**Source**: `fixtures/day5/conflict_events.json`
**Version**: 0.1-draft
**Review Status**: `member_b_draft_requires_joint_review`
**Executable in Day 3**: false
**Entries**: 8 cases (d5-c01 through d5-c08)

## Individual Case Review

### d5-c01: 回答先给提示 vs 回答直接给完整修复

**Status**: ✅ **KEEP**

**Reasoning**:
- **Existing**: "回答先给提示" (Give hints before answers)
- **Incoming**: "回答直接给完整修复" (Give complete fix directly)
- **Scope Relation**: `same` - Identical scope (programming_learning)
- **Expected Relation**: `contradicts` - Correct
- **Expected Action**: `require_user_resolution` - Correct

**Mapping to Structured Memory**:
- Both cards would have scope: `{domain: programming_learning, task_type: debugging_guidance}`
- Current conflict type: `conflicts_with`
- Status: `unresolved`
- **G4 Action**: `prefer` or `separate_scopes` (user must choose)

**Notes**:
- Classic opposite-preference conflict
- Both active → both must be `conflicted`
- Winner becomes `active`, loser becomes `superseded`

---

### d5-c02: 回答使用中文 vs 回答保持简洁

**Status**: ⚠️ **REVISE**

**Reasoning**:
- **Issue**: `compatible` is NOT a conflict action
- **Scope Relation**: `same` (overlapping)
- **Expected Relation**: Should be `duplicate_of` or `related_to`, NOT `conflicts_with`
- **Expected Action**: `keep_both` is not a valid G4 action

**G4 Decision**:
- These are compatible preferences (language + conciseness)
- No conflict relation should be created
- If both are active, they should coexist
- If force relation needed: `related_to` not `conflicts_with`

**Required Fix**:
```json
{
  "expected_relation": "related_to",  // or "duplicate_of" if truly identical
  "expected_action": "keep_both"  // Remove this or replace with G4 action
}
```

---

### d5-c03: Python教学先给思路 vs 所有任务先给思路

**Status**: ✅ **KEEP** (with refinement)

**Reasoning**:
- **Existing**: "Python 教学先给思路" (Python teaching: give思路first)
- **Incoming**: "所有任务先给思路" (All tasks: give思路first)
- **Scope Relation**: `incoming_broader` - Incoming has broader scope
- **Expected Relation**: `scope_overlap` - Correct, overlapping but different scope
- **Expected Action**: `require_scope_narrowing` - Correct

**Mapping to Structured Memory**:
- **Existing scope**: `{domain: programming_learning, task_type: code_explanation}`
- **Incoming scope**: `{domain: any, task_type: any}` or `{domain: other, task_type: other}`
- This is a **scope refinement**, not a content conflict

**G4 Action**: `separate_scopes`
- User must narrow incoming card scope to not blanket-override existing
- Result: Both `active` with non-overlapping scopes
- New versions created for both with `created_by_action=scope_resolution`

**Notes**:
- NOT an automatic conflict requiring user resolution
- G4 `scope_overlap_v1` function must detect this as non-disjoint

---

### d5-c04: 所有开发任务先跑测试 vs 仅项目alpha先跑测试

**Status**: ✅ **KEEP** (with refinement)

**Reasoning**:
- **Existing**: "所有开发任务先跑测试" (All dev tasks: run tests first)
- **Incoming**: "仅项目alpha先跑测试" (Only project alpha: run tests first)
- **Scope Relation**: `incoming_narrower` - Incoming is narrower
- **Expected Relation**: `refines` - Correct
- **Expected Action**: `allow_versioned_refinement` - Correct

**Mapping to Structured Memory**:
- **Existing scope**: `{project_key: ANY, domain: software_development}`
- **Incoming scope**: `{project_key: "alpha", domain: software_development}`
- Narrower scope refines broader, does not contradict

**G4 Action**: `separate_scopes`
- Both remain active
- New versions created with distinct scopes
- No conflict relation created

**Notes**:
- This is a scope refinement, not a conflict
- Both preferences can coexist without contradiction

---

### d5-c05: 部署前检查migration (duplicate)

**Status**: ✅ **KEEP** (as reinforcement evidence)

**Reasoning**:
- **Existing**: "部署前检查 migration"
- **Incoming**: "部署前检查 migration"
- **Scope Relation**: `same`
- **Expected Relation**: `duplicate` - Correct
- **Expected Action**: `merge_evidence` - Correct

**Important Distinction**:
- **Merge evidence ≠ content merge**
- This means: reinforce existing card with new evidence
- Do NOT create a new merged card
- Update `evidence_count` and add relation `reinforces`

**Mapping**:
- Detect exact fingerprint match
- Add `reinforces` relation
- Increment `evidence_count` on existing card
- No new version created

---

### d5-c06: 使用pytest vs 使用unittest

**Status**: ✅ **KEEP**

**Reasoning**:
- **Existing**: "使用 pytest"
- **Incoming**: "使用 unittest"
- **Scope Relation**: `same_project`
- **Expected Relation**: `contradicts` - Correct (opposite tool preferences)
- **Expected Action**: `require_user_resolution` - Correct

**Mapping**:
- True conflict: user prefers different testing frameworks
- Both `active` → both must be `conflicted`
- Requires explicit user choice

**G4 Action**: `prefer` or `pause_both`
- Cannot be `separate_scopes` (contradictory, not complementary)
- Cannot be `merge` (cannot use both simultaneously)

---

### d5-c07: 初学者解释要分步 vs 高级用户解释要简洁

**Status**: ✅ **KEEP**

**Reasoning**:
- **Existing**: "初学者解释要分步" (Beginners: step-by-step)
- **Incoming**: "高级用户解释要简洁" (Advanced: concise)
- **Scope Relation**: `disjoint_audience` - Different audience
- **Expected Relation**: `compatible` - Correct
- **Expected Action**: `keep_both` - Correct

**Mapping**:
- Different `scope.audience` values (`beginner` vs `advanced`)
- No conflict relation needed
- Both can be `active` simultaneously
- Retrieval filter ensures correct card for correct audience

**G4 Decision**: No action needed
- Both cards active with different scope
- Retrieval hard-filter prevents cross-audience leakage

---

### d5-c08: 普通任务先解释 vs 紧急任务直接修复

**Status**: ✅ **KEEP** (as controlled exception)

**Reasoning**:
- **Existing**: "普通任务先解释" (Normal tasks: explain first)
- **Incoming**: "紧急任务直接修复" (Urgent: direct fix)
- **Scope Relation**: `exception` - Not a conflict, an exception
- **Expected Relation**: `exception` - Correct
- **Expected Action**: `attach_controlled_exception` - Correct

**Structured Input**:
- **Existing card rule**: "先解释再给代码"
- **Exception on existing**: `urgency:urgent`
- **New card**: NOT a separate conflicting card
- **Modification**: Add `exceptions: ["urgency:urgent"]` to existing card

**G4 Action**: Modify existing card
- Add `urgency:urgent` to existing card's `exceptions` list
- No conflict relation created
- No new card created
- `created_by_action=edit` on existing card

**Notes**:
- This is the **correct use of exceptions** (AllowedException enum)
- Controlled override, not a contradiction
- Both preferences can coexist via exception mechanism

---

## G4 Conflict Types Summary

| Case | Type | Action | G4 Implementation |
|------|------|--------|------------------|
| c01 | True conflict (opposite rules) | prefer/separate_scopes | Create `conflicts_with` relation, both → `conflicted` |
| c02 | Compatible preferences | N/A (no action) | Should be `related_to` or no relation |
| c03 | Scope overlap (broader vs narrower) | separate_scopes | Create new versions with non-overlapping scopes |
| c04 | Scope refinement (narrowing) | separate_scopes | Create new versions with refined scopes |
| c05 | Duplicate with reinforcement | reinforce | Add `reinforces` relation, increment evidence_count |
| c06 | True conflict (tool preference) | prefer/pause_both | Create `conflicts_with`, both → `conflicted` |
| c07 | Disjoint audience | N/A (no action) | Both active, retrieval filter prevents leakage |
| c08 | Controlled exception | edit existing | Add `urgency:urgent` to exceptions, no new card/relation |

## Critical Issues Found

1. **c02 "compatible" is not a G4 action**: Must revise to `related_to` or remove
2. **c03/c04 are scope refinements, not automatic conflicts**: Should use `separate_scopes`, not "require_user_resolution"
3. **c05 merge_evidence ≠ content merge**: Clear distinction between reinforcing and merging
4. **c08 controlled exception structure**: Must map to existing card exception list, not create new card

## Unresolved Questions

1. **c02**: Should we create a `related_to` relation or leave unlinked?
   - Recommendation: `related_to` with status `resolved`
2. **c03/c04**: Should scope overlap trigger automatic `separate_scopes` or require user confirmation?
   - G4 Decision says `separate_scopes` is a user action, not automatic
   - Recommendation: Mark as `potential_conflict` requiring user review

## Required Changes Before Approval

1. **Revise c02**: Change `expected_relation` to `related_to`, remove `expected_action`
2. **Revise c03/c04**: Update `expected_action` to reflect non-automatic scope separation
3. **Clarify c05**: Add explicit note that `merge_evidence` = reinforce only
4. **Add c08 structured input**: Show exact exception list modification

## Member B Review Status

**Pending**: Member B must independently verify this review before fixture can be marked as executable.

**Disagreements Expected**:
- c02 scope classification (compatible vs related)
- c03/c04 automatic vs manual scope separation
- c05 evidence reinforcement semantics

**Agreed Points**:
- c01, c06 are true conflicts requiring user resolution
- c07 has disjoint scopes, no conflict
- c08 is correctly modeled as controlled exception

---

**Review Completed By**: Member A (zlbk-wxy)
**Timestamp**: 2026-08-25
**Next Step**: Member B independent review and joint approval
