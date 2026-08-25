# G4 Conflict Fixture Review

**日期**: 2026-08-25  
**审查者**: zlbk-wxy (成员 A)  
**fixture**: `fixtures/day5/conflict_events.json` (draft)

## 审查结果

### d5-c01: "User preference conflict"
**判定**: **revise**  
**理由**: 基本的 preference 冲突检测可行，但需要更明确的 scope/domain 区分标准  
**映射**: `scope_level` 从 global → project-specific, 触发 `separate_scopes` action

### d5-c02: "Compatible contradictory"
**判定**: **keep** (但需修正分类)  
**理由**: c02 文档明确说明 "compatible" - 这不是真正的 conflict  
**映射**: 应分类为 `related_to` 而非 `conflicts_with`, relation_type = "reinforces"

### d5-c03: "Scope refinement"
**判定**: **revise**  
**理由**: c03/c04 是 scope/refinement 而非自动矛盾  
**映射**: 使用 `scope_resolution` action, 创建新 version 调整 scope_level/domain

### d5-c04: "Conditional exception"
**判定**: **revise** (类似 c03)  
**理由**: 需要明确的 exception schema  
**映射**: 添加 exceptions 条目, 不创建 conflict relation

### d5-c05: "Reinforce vs Merge evidence"
**判定**: **insufficient**  
**理由**: reinforce/merge evidence 与内容 merge 的区别需要明确  
**问题**: 
- reinforce = 相同 rule, 不同 evidence
- merge = 两个不同 rule 需要合并  
**需要**: 明确的决策流程图和结构化字段

### d5-c06: "Temporal conflict"
**判定**: **keep** (需实现时间窗口检测)  
**映射**: `valid_from`/`valid_to` 重叠检测 → `prefer` newer 或 `pause_both`

### d5-c07: "Domain boundary"
**判定**: **keep**  
**映射**: `domain` 不匹配 → `separate_scopes` with domain change

### d5-c08: "Controlled exception"
**判定**: **revise** (需要 schema)  
**理由**: controlled exception 需要结构化输入 schema  
**映射**: exceptions_json 需要 "condition", "scope", "duration" 字段

## 关键问题

### 1. c02 "Compatible" 不是 Conflict Action
文档明确说明 c02 是 "compatible" - 不应触发 `conflicts_with` relation  
**建议**: 分类为 `reinforces` 或 `related_to`

### 2. c03/c04 是 Scope/Refinement 而非自动矛盾
当前实现会创建 `conflicts_with`, 但应该只是 scope 调整  
**建议**: 实现 `scope_resolution` action 而非 conflict

### 3. c05 Reinforce/Merge Evidence 与内容 Merge 的区别
- **Reinforce**: 相同 rule, 补充 evidence → `supersedes` with evidence_count++
- **Merge**: 不同 rule 需要合并 → `merged_into` + 新 card  
**需要**: 成员 B 提供明确决策逻辑

### 4. c08 Controlled Exception 结构化输入
当前 exceptions_json 是简单 string list  
**需要 schema**:
```json
{
  "type": "exception",
  "condition": "string",
  "scope": "scope_object",
  "duration": "temporal_constraint"
}
```

## 安全性审查 (12 类)

见 `fixtures/day5/g4_pack_security_cases.json`

| ID | 类别 | 预期 | 实现状态 |
|----|------|------|----------|
| g4-sec-01 | oversized_file | rejected | ✅ size check |
| g4-sec-02 | card_count_overflow | rejected | ✅ count check |
| g4-sec-03 | duplicate_json_keys | rejected | ⚠️ JSON parse 会失败 |
| g4-sec-04 | unknown_format_version | rejected | ✅ version check |
| g4-sec-05 | integrity_mismatch | rejected | ✅ hash verify |
| g4-sec-06 | dangling_relation | rejected | ⚠️ 未实现 |
| g4-sec-07 | self_referential_relation | rejected | ⚠️ 未实现 |
| g4-sec-08 | forbidden_capability_field | rejected | ⚠️ 未实现 |
| g4-sec-09 | xss_payload_in_card | suspicious | ⚠️ 未实现 |
| g4-sec-10 | cross_owner_batch_access | rejected | ✅ owner check |
| g4-sec-11 | expired_batch_commit | rejected | ✅ expiry check |
| g4-sec-12 | tampered_preview_token | rejected | ✅ HMAC verify |

## 未决异议

1. **自动冲突检测**: 当前实现只做显式人工标记 (`POST /memory-conflicts`), 不自动检测  
   → 符合 G4 决策 §F, 但需要 UI/前端明确

2. ** Conservative TF-IDF**: potential_conflict 检测规则冻结但未完全实现  
   → 需要成员 B 在第二阶段实现

3. **Forbidden Fields 列表**: g4-sec-08 中 "script/tool/system_prompt" 等是否完整  
   → 需要与 Pack Schema 同步更新

## 建议后续工作

1. 成员 B 批准 c02/c03/c04/c08 的分类方案
2. 实现 dangling/self-ref/forbidden fields 检测
3. 实现 conservative TF-IDF conflict detection
4. 将 fixture 状态从 "member_a_frozen" 更新为 "approved"
