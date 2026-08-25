# Day 4 Retrieval Fixture Owner Review

Review date: 2026-08-25. Reviewer: member B / repository owner. This is not a claim of joint approval. The original `fixtures/day4/retrieval_events.json` remains a Day 3-era draft; executable owner-verified cases live in `fixtures/day4/g3_retrieval_cases.json`.

| Original | Decision | Reason | Executable case |
|---|---|---|---|
| d4-r01 | keep | Chinese positive family match | d4-g3-01 |
| d4-r02 | revise | Bind to reproducible active v2 semantic query | d4-g3-02 |
| d4-r03 | revise | Use stable repeated retrieval before English negative | d4-g3-03 |
| d4-r04 | revise | Public API cannot set arbitrary environment scope | d4-g3-04 |
| d4-r05 | revise | Recast as hard domain negative | d4-g3-08 |
| d4-r06 | insufficient | `other` classification is not a stable positive oracle | d4-g3-09 |
| d4-r07 | keep | Domain hard-filter negative | d4-g3-07 |
| d4-r08 | keep | Unrelated-domain negative | d4-g3-08 |
| d4-r09 | keep | Task-family negative | d4-g3-09 |
| d4-r10 | keep | Artifact/domain negative | d4-g3-10 |
| d4-r11 | revise | Public runner uses observable non-active lifecycle filter | d4-g3-11 |
| d4-r12 | revise | Status hard-filter is exercised without internal DB seeding | d4-g3-12 |
| d4-r13 | keep | Pause removes card from new retrieval | d4-g3-13 |
| d4-r14 | revise | Archive is outside Day 4 lifecycle API | d4-g3-14 |
| d4-r15 | insufficient | Permanent delete is explicitly out of scope | d4-g3-15 |
| d4-r16 | keep | Direct-fix current constraint override | d4-g3-16 |
| d4-r17 | revise | Urgency and direct-fix use controlled exceptions | d4-g3-17 |
| d4-r18 | revise | Language is a scope field, not free-text preference alone | d4-g3-18 |
| d4-r19 | revise | Add deterministic English negative coverage | d4-g3-19 |
| d4-r20 | keep | Audience contributes to scope score | d4-g3-20 |
| d4-r21 | keep | Advanced/audience negative | d4-g3-21 |
| d4-r22 | revise | Arbitrary project keys cannot be set by the public Day 4 UI | d4-g3-22 |
| d4-r23 | keep | Project/task negative | d4-g3-23 |
| d4-r24 | revise | Resume lifecycle replaces generic artifact positive | d4-g3-24 |
| d4-r25 | revise | Single-card 100-token hard budget | d4-g3-25 |
| d4-r26 | revise | Total 300-token hard budget | d4-g3-26 |
| d4-r27 | revise | Exact final-section SHA-256 evidence | d4-g3-27 |
| d4-r28 | revise | Restart/recovery evidence, not only concept overlap | d4-g3-28 |
| d4-r29 | revise | Verifier four-state coverage | d4-g3-29 |
| d4-r30 | revise | Owner isolation plus separate memory-off cases | d4-g3-30 |

The executable set stays at 30 cases. It does not pre-claim the Day 5 60-case frozen dataset.
