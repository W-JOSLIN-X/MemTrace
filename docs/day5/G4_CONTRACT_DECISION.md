# MemTrace Day 5 G4 契约冻结决策

状态：`frozen-for-member-a-implementation`

冻结日期：2026-08-25（Asia/Shanghai）

事实核验起点：`origin/main = 47cfb07cb544267ab91acf18f30657c9500e6986`

适用范围：Day 5 成员 A 的 Memory Center/Conflict/Memory Pack 后端实现，以及成员 B 第二阶段的独立审查、前端、fixture、EvalRunner、完整 G4 门禁和最终发布。本文是 Day 5 共享契约 change note；任何字段、状态、事务、错误或安全边界变化都必须先更新本文和全部契约投影，不能在代码里静默漂移。

## 1. 事实优先级与当前已验证现状

优先级固定为：当前用户要求 > 根目录 `AGENTS.md` > `docs/OWNER_LED_COLLABORATION_WORKFLOW.md` > 当前可执行代码/契约/迁移/本轮测试 > 本文 > 两人总计划 > 旧 Prompt、旧 handoff、旧报告。

从上述精确 main 独立确认：

- 当前公开契约为 G3 `1.3.0`，TaskFingerprint 仍为 `1.1`；G4 使用向后兼容的协调版本 `1.4.0`。
- 当前唯一 Alembic head 是 `004_g3_retrieval_usage`；G4 必须新增唯一线性 head `005_g4_memory_center_pack`。
- 当前后端可收集 `403` 项测试；这里只记录 collection 事实，不把旧报告或尚未在本轮完整运行的 suite 写成通过。
- 当前真实 OpenAPI 已有 memory list/detail、active edit、pause/resume、versions/usages、task trace/usage 路由；没有 archive/restore/permanent delete、source-task delete、relation/conflict/merge 或 Memory Pack 路由。
- 当前 memory list 只接受 `candidate|active|rejected|paused`，没有 query/kind/domain/task_type/source_type/used_after/sort；当前 Memories 页只列 active/paused 并做最小 edit/pause/resume。
- `memory_cards.status` 已预留 `conflicted|superseded|merged|archived|deleted`，但这只是枚举/DB check，不是 Day 5 行为已经实现。
- `memory_relations` 已存在，但只有 `duplicate_of|conflicts_with|supersedes|related_to`，没有 relation status、resolution、`reinforces|merged_into`，也没有公开 API。
- `memory_versions.created_by_action` 只允许 `accept|edit_accept|edit`。
- 当前永久删除会遇到真实外键问题：version、usage、verification job、relation、evidence link、idempotency response snapshot 与 task 来源数据都可能残留正文或悬空引用。
- 当前依赖已有 `jsonschema`，没有 RFC 8785 canonical JSON 实现；若新增依赖，必须固定版本、更新 `requirements.in/lock`，并保持 Docker `--require-hashes --no-deps` 安装通过。
- `fixtures/day5/conflict_events.json` 是 8 条 `0.1-draft`，状态为 `member_b_draft_requires_joint_review`，不是 executable fixture 或 gold。

## 2. G4 产品边界与两阶段时序

Day 5 交付：

1. owner-scoped Memory Center 搜索、筛选、详情、版本、Diff、relation 和 usage；
2. immutable edit、pause/resume、archive/restore、单卡永久删除和来源 task 净化删除；
3. 显式人工冲突标记、四类固定裁决、一次人工 merge、supersede；
4. 单文件 `.mempack.json` 匿名导出、严格 preview、隔离 batch、合法新增项单事务 paused 导入；
5. 可恢复的 memory/import metadata audit event；
6. G4 fixture、REST-only EvalRunner、完整前端和只读结果页壳由成员 B 第二阶段最终完成。

旧两人计划写过“成员 A 集成成员 B 提供的 Pack Schema”，这与当前 owner-led 两阶段顺序冲突。Day 5 的实际顺序冻结为：本文先进入 main；成员 A 直接按本文实现 Pydantic、后端 validator、JSON Schema 草案和 API；成员 B 接管后独立核对并最终同步 JSON Schema、TS strict parser、fixture、UI 和真实 OpenAPI。A 不等待尚未开始的 B 代码，B 也不把 A 的 schema/tests 当成自己的验证结论。

Day 5 明确不做：自动生成 merge 文案、自动 scope refinement、逐卡选择/编辑导入、版本 rollback、批量删除、清空用户全部数据、ZIP/脚本/Skill 导入、签名或 Pack 市场、动态 eval run API、Day 6 阈值调参、真实 Provider 硬门禁。

## 3. 协调版本、ID 和严格解析

- `contract_version = 1.4.0`；现有 G1/G2/G3 字段不得回退。
- `RelationId`：`rel_` + 26 位 Crockford Base32 ULID。
- `ImportBatchId`：`batch_` + 26 位 Crockford Base32 ULID。
- Pack 内 `pack_id`：`pack_` + 26 位 Crockford Base32 ULID；它是外部声明，不作为本地 owner 资源 ID。
- Pack 内 `external_id`：`card_` + 1–64 个 ASCII 字母、数字、`_` 或 `-`，包内唯一。
- 所有 owner-scoped ID 的 missing 与 cross-owner 均返回同一 404，不泄露存在性。
- Pydantic、JSON Schema、OpenAPI、examples、TypeScript runtime parser 均 `additionalProperties=false`/`extra=forbid`；nullable 必须显式 `null`，不能用缺字段、空字符串或 `any` 代替 unknown。
- 所有公开时间为 UTC RFC 3339；所有 hash 为小写 64 位 SHA-256 hex。

## 4. Memory Center 查询与投影

### 4.1 路由

冻结路由：

```text
GET    /api/v1/memories
GET    /api/v1/memories/{memory_id}
PATCH  /api/v1/memories/{memory_id}
POST   /api/v1/memories/{memory_id}/pause
POST   /api/v1/memories/{memory_id}/resume
POST   /api/v1/memories/{memory_id}/archive
POST   /api/v1/memories/{memory_id}/restore
DELETE /api/v1/memories/{memory_id}
GET    /api/v1/memories/{memory_id}/versions
GET    /api/v1/memories/{memory_id}/version-diff
GET    /api/v1/memories/{memory_id}/usages
GET    /api/v1/memories/{memory_id}/relations
DELETE /api/v1/tasks/{task_id}
```

归档/恢复使用独立 POST，而不把 `status` 塞进现有 `PATCH`。这样 `PATCH` 继续只代表创建 immutable 内容版本，不会让同一 body 同时承担内容编辑和生命周期转换。

### 4.2 list/filter/sort/cursor

`GET /memories` 支持：

- `query`：1–100 Unicode scalar；对当前 owner、非 deleted card 的 title/rule/trigger_text 做 NFKC + casefold + whitespace-collapse 后的包含匹配。
- `kind`、`status`、`domain`、`task_type`、`source_type`：受控单值枚举；status 支持除 `deleted` 外的全部公开状态。
- `used_after`：UTC RFC 3339；`last_used_at >= used_after`。
- `sort`：`updated_desc`（默认）、`created_desc`、`last_used_desc`、`title_asc`。
- `cursor`：opaque base64url cursor，绑定 sort、最后排序值和 memory_id；不同 filter/sort 复用 cursor 返回 `422 INVALID_CURSOR`。
- 每页 50，最多读取 51 判断 `next_cursor`；稳定 tie-break 永远是 `memory_id ASC`。

搜索必须先在 SQL 绑定 owner；不得先取全库再在 Python 或前端过滤 owner。deleted tombstone 永远不出现在 list/detail/search。

### 4.3 G4 MemoryCard/Detail 增量

`MemoryCard` 同步增加：

- `evidence_missing: boolean`
- `import_batch_id: ImportBatchId | null`
- `import_source_version: integer >= 1 | null`

数据库 tombstone 例外必须显式建模：当且仅当 `status=deleted` 时，kind/source/title/rule/avoid/trigger、scope 列/JSON、confidence、validity、current version/import source 可全部为 null，version/counters 归零；其他状态继续满足既有非空和 admission check。deleted row 只保留 memory_id、owner_id、status、created_at、deleted_at 等不可反推正文的审计元数据。deleted 不进入公开 `MemoryCard` parser。

`MemoryDetailResponse` 增加分页外的最近 relation 摘要；完整关系从 `/relations` 读取。`MemoryRelation` 投影：

- `relation_id`
- `from_memory_id`
- `to_memory_id`
- `relation_type: duplicate_of | reinforces | conflicts_with | supersedes | merged_into | related_to`
- `status: unresolved | resolved`
- `resolution_action: prefer | separate_scopes | merge | pause_both | null`
- `resolution_memory_id: MemoryId | null`
- `created_at`
- `resolved_at: datetime | null`

非 `conflicts_with` relation 创建时直接为 `resolved`；`conflicts_with` 创建时必须为 `unresolved`。

`GET /version-diff` 要求 `from_version_id` 和 `to_version_id`；两者必须同 owner、同 memory。响应返回完整 `from_version`、`to_version` 和稳定排序的 `changed_fields`，字段枚举仅为 `title|rule|avoid|trigger_text|scope|exceptions`。服务端不生成自由文本总结，不提供 rollback。

## 5. 生命周期、版本和删除

### 5.1 编辑与状态转换

- `PATCH` 请求继续携带 `expected_current_version_id` 和非空 patch；允许当前状态 `active|paused|archived|conflicted`。
- 每次编辑创建 `version+1`，`created_by_action=edit`，原子切换 current version；历史行不可修改。
- `pause`：`active -> paused`。
- `resume`：`paused -> active`，必须重跑 active Admission Guard，并拒绝 unresolved active conflict。
- `archive`：`active|paused -> archived`；不创建版本。
- `restore`：`archived -> paused`；必须再显式 resume 才参与检索，避免恢复动作突然影响生成。
- stale version 为 `409 MEMORY_VERSION_CONFLICT`；非法状态为 `409 MEMORY_STATE_CONFLICT`；同 key 异请求为 `409 IDEMPOTENCY_CONFLICT`。

### 5.2 单卡永久删除

`DELETE /memories/{memory_id}` body：

```json
{
  "expected_current_version_id": null,
  "confirm_title": "必须与当前 title 精确一致"
}
```

任意本人非 deleted card 都可删除；candidate 的 expected version 为 null，有 current version 的 card 必须传其精确 `memver_...`。确认失败为 `409 CONFIRMATION_MISMATCH`。成功返回只含 `request_id`、`memory_id`、`status=deleted`、`deleted_at` 的 tombstone 响应，不返回 title/rule/version/evidence。

同一 `BEGIN IMMEDIATE` 事务中必须：

1. owner 与 expected version 二次校验；
2. `current_version_id=NULL`；
3. 删除所有 versions、embedding（若未来存在）、relations、retrieval decisions/usages、verification jobs、evidence links；
4. 删除已无任何 link 的 evidence；
5. 清空 card 的 title/rule/avoid/trigger/scope/exceptions、来源引用、计数和任何可反推正文的字段；
6. 清除引用该 memory/task/version 的 idempotency response snapshot 和未完成 import preview 正文引用；
7. 保留无正文 card tombstone，并追加 metadata-only `memory.lifecycle.changed`。

清理顺序必须删除该资源先前所有可能含正文的 idempotency snapshot，最后再保存当前 DELETE 的安全 tombstone replay record。成功后 list/detail/versions/usages/relations/retrieval 均视为不存在；重复新 key 删除返回同一 404/409 契约，不伪装成再次成功。幂等 replay 同 key 返回原 tombstone 响应。

### 5.3 来源 Task 净化删除

`DELETE /tasks/{task_id}` body：

```json
{
  "confirm_task_id": "task_...",
  "memory_policy": "preserve_and_mark_evidence_missing"
}
```

URL 与 body ID 必须一致。成功后 task row 保留无正文 tombstone（`status=deleted`、`task_text=''`、`deleted_at`），普通 task snapshot/SSE/feedback/retry 均返回 404。

单事务矩阵：

- 删除 task fingerprint、messages、tool calls、feedback events、相关 extraction jobs/evidence、retrieval traces/usages/verification jobs；
- agent run 只保留 provider mode/model、状态、耗时、token 和安全错误码，不保留消息或正文引用；
- task metadata event 可保留，但不能含正文；
- 受影响且仍保留的 card 不删除，重算 evidence_count 并设 `evidence_missing=true`；
- 清除受影响 idempotency response snapshot；
- 任务删除不自动永久删除 MemoryCard，UI 必须分别解释两类操作。

## 6. Conflict、supersede 和人工 merge

### 6.1 路由

```text
GET  /api/v1/memory-conflicts?status=unresolved|resolved&cursor=
GET  /api/v1/memory-conflicts/{relation_id}
POST /api/v1/memory-conflicts
POST /api/v1/memory-conflicts/{relation_id}/resolve
POST /api/v1/memories/merge
```

`POST /memory-conflicts` 是显式人工标记，不声称系统已经可靠理解自然语言矛盾。请求带两端 memory/version ID；两端必须不同、同 owner、均有 immutable current version，状态为 active 或 paused，且按下述保守规则 scope 重叠。创建 canonical pair（较小 memory_id 为 from）和唯一 unresolved `conflicts_with` relation；active/paused 两端都转为 `conflicted`，因此 G3 检索立即排除。

请求字段冻结为：

```json
{
  "left_memory_id": "mem_...",
  "left_expected_current_version_id": "memver_...",
  "right_memory_id": "mem_...",
  "right_expected_current_version_id": "memver_..."
}
```

Day 5 不实现未经评测的自动语义裁决。Pack preview 可用第 7 节的保守规则标 `potential_conflict`，但不会创建本地 card/relation。

`scope_overlap_v1` 固定为保守判断：对 domain/task_type/artifact/audience/project/language/framework，只有两端都为显式非-null、非-any 且值不同，才判该维度 disjoint；任一维度 disjoint 则两个 scope 不重叠，否则视为可能重叠。concepts/unknown 不得被用来证明 disjoint。separate_scopes action 也用同一函数，结果必须为不重叠。

### 6.2 四种固定裁决

`POST /memory-conflicts/{relation_id}/resolve` 的 action 只有：

1. `prefer`：请求明确 `preferred_memory_id`；winner 经 Admission Guard 后 active，loser superseded，并写 `supersedes`。
2. `separate_scopes`：请求为两端提供完整新 scope；各自创建 `created_by_action=scope_resolution` 的新版本。服务端验证新 scope 不再重叠后两端 active。
3. `merge`：请求提供完整、人工编辑的 merged card 内容；创建一个新 active card v1（`created_by_action=merge`），两端为 merged，并各写 `merged_into`。
4. `pause_both`：两端均 paused，保留 current version。

每次请求都携带 relation 当前状态和两端 expected current version；同事务更新 card、version、relation、附属 relation 和 metadata event。已 resolved、stale version、非法 winner、scope 仍重叠或 Admission Guard 失败均为受控 409/422，不能部分提交。

resolve body 共有字段为 `expected_relation_status="unresolved"`、两端 expected version 和 `action`。条件字段严格互斥：prefer 只带 `preferred_memory_id`；separate_scopes 只带 `left_scope/right_scope`；merge 只带 `merged_card`；pause_both 不带额外 payload。`merged_card` 只允许 `kind,title,rule,avoid,trigger_text,scope,exceptions`，不接受 owner/status/source/trust/version/ID。

### 6.3 独立人工 merge

`POST /memories/merge` 用于两张重复/可合并 card，不要求先有 conflict relation。请求固定包含 left/right memory ID、各自 expected version 和完整 merged card 内容。成功创建新 active card v1，两张来源 card 置 merged，建立两条 `merged_into`；全过程单事务。不得用模型自动生成 merged rule，也不得原地覆盖任一旧 card。

若两端已有 unresolved conflict，独立 merge 路由必须返回 409 并要求走 conflict resolve 的 merge action，不能留下 unresolved relation 指向 merged card。

`MemoryVersion.created_by_action` 在 G4 扩展为：`accept|edit_accept|edit|import|merge|scope_resolution`。

## 7. Memory Pack V1

### 7.1 固定格式与 Schema

- 文件名后缀：`.mempack.json`；单个 UTF-8 JSON 文件，不接受 ZIP、目录、脚本或 URL。
- `schema_ref = memtrace-memory-pack@1.0.0`
- `format = memtrace-memory-pack`
- `format_version = 1.0.0`
- JSON Schema 路径：`contracts/schemas/memory-pack.schema.json`
- 顶层必含 `schema_ref,format,format_version,pack_id,name,description,created_at,producer,source,privacy,cards,relations,integrity`，所有对象拒绝 unknown field。
- Pack card 使用 G3 冻结的单值 `scope.language`；旧总计划示例中的 `languages` 与当前可执行 MemoryScope 不同，G4 明确拒绝 `languages`，不能双轨兼容。
- card 只含 current canonical fields、claimed origin 摘要、source version 和 updated_at；不含 owner_id、本地 memory/version/task/run/evidence ID、历史正文、usage/counters、embedding、原聊天、路径、Provider 配置或 system prompt。
- relation 只能引用同包 external_id，类型仅 `duplicate_of|reinforces|conflicts_with|supersedes|merged_into`；悬空、自引用、重复关系或跨包引用整包拒绝。
- `privacy.contains_raw_evidence` 必须 false，`privacy.anonymized` 必须 true。V1 没有数字签名；checksum 只证明传输一致，所有外部 Pack 都显示 unverified。

精确字段约束沿用 MemoryCard：title 4–40、rule 20–300、avoid 0–400、trigger 0–240、exceptions 最多 8、concepts 最多 12；cards 1–200、relations 0–400、name 1–80、description 0–500。

字段形状冻结为：

```json
{
  "schema_ref": "memtrace-memory-pack@1.0.0",
  "format": "memtrace-memory-pack",
  "format_version": "1.0.0",
  "pack_id": "pack_...",
  "name": "...",
  "description": "...",
  "created_at": "2026-08-25T00:00:00Z",
  "producer": {"name": "MemTrace", "version": "0.1.0"},
  "source": {"kind": "user_export", "trust": "self_asserted"},
  "privacy": {"contains_raw_evidence": false, "anonymized": true},
  "cards": [
    {
      "external_id": "card_001",
      "schema_version": "1.0",
      "kind": "preference",
      "title": "...",
      "rule": "...",
      "avoid": "",
      "trigger_text": "",
      "scope": {
        "level": "global",
        "domain": "programming_learning",
        "task_type": "any",
        "artifact_type": null,
        "audience": null,
        "project_key": null,
        "language": "any",
        "framework": null,
        "concepts": []
      },
      "exceptions": [],
      "claimed_origin": {
        "source_type": "explicit_feedback",
        "trust_level": "user_confirmed",
        "created_at": "2026-08-25T00:00:00Z",
        "source_task_exported": false,
        "source_version": 1
      },
      "version": 1,
      "updated_at": "2026-08-25T00:00:00Z"
    }
  ],
  "relations": [],
  "integrity": {"algorithm": "sha256", "canonical_payload_sha256": "..."}
}
```

`source.kind` 只允许 `user_export|external_import`，`source.trust` 只允许 `self_asserted|unverified`；`claimed_origin.source_type` 复用现有 SourceType，trust_level 只允许 `user_confirmed|self_asserted|imported_unverified`。`scope` 必须是完整 G3 MemoryScope。

### 7.2 canonical JSON 与 integrity

`integrity.canonical_payload_sha256` 覆盖**除整个 integrity 字段自身外的全部顶层 payload**，包括 name/description/producer/source/privacy/cards/relations；不是只 hash cards。

步骤固定：

1. 删除顶层 `integrity`；
2. 按 RFC 8785 JCS 生成 canonical UTF-8 bytes；
3. SHA-256，写小写 hex；
4. 导出最终文件本身也按 RFC 8785 canonical JSON 序列化。

导入器必须拒绝重复 JSON key、NaN/Infinity、非 UTF-8、未知字段和 hash mismatch。若使用新 RFC 8785 依赖，必须 pin/lock 并通过本机与 Docker hash 安装；不得用普通 `sort_keys=True` 冒充完整 RFC 8785。

### 7.3 路由和导出

```text
POST /api/v1/memory-packs/export
POST /api/v1/memory-packs/import/preview
POST /api/v1/memory-packs/import/commit
GET  /api/v1/memory-packs/import/{batch_id}
```

export 是只读 POST，可选择最多 200 个同 owner、非 candidate/rejected/deleted 且有 current version 的 memory；省略 IDs 时只导出 active/paused。输出 `application/json` 和安全的 `Content-Disposition` 文件名。默认匿名不可关闭；不得把 Pack、card 正文或下载内容写入日志/event/idempotency snapshot。

export body 只允许 `memory_ids: list[MemoryId] | null`、`name` 和 `description`；服务端生成 pack_id/created_at/producer/source/privacy/integrity，客户端不能覆盖。

### 7.4 preview 文件级门禁

preview 读取原始 request bytes 后再解析，顺序固定：

1. 原始文件最大 `1,048,576` bytes，超限 `413 MEMORY_PACK_TOO_LARGE`；
2. UTF-8、重复 key、最大深度 12、最大 scalar node 10,000；
3. format/schema_ref/major version；
4. JSON Schema；
5. RFC 8785 integrity；
6. forbidden capability field/text 安全扫描；
7. owner-scoped duplicate/potential-conflict 分析。

文件级任一失败时不创建 batch、不写 card。禁止能力字段包括任何层级的 `script|tool|tools|allowed_tools|system_prompt|role|url_fetch|secret|api_key|command|executable`；由于 additionalProperties=false，它们通常在 schema 阶段被拒绝。合法文本中出现“忽略此前指令”、读取 key、执行脚本、`<script>` 等受控模式时标 `suspicious`，不执行、不渲染 HTML、不进入 commit 子集。

schema/integrity 合法后，每卡分类：

- `legal_new`：可导入；
- `duplicate`：与同 owner 非 deleted current card 的 canonical kind/rule/avoid/trigger/scope/exceptions 指纹完全一致，skip；
- `potential_conflict`：非 exact duplicate，但与同 owner current card 按 `scope_overlap_v1` 重叠且 `char_tfidf_v1 >= 0.68`，或包内明确 `conflicts_with`，manual/skip；
- `suspicious`：安全扫描命中，manual/skip。

这里的 `potential_conflict` 只是保守人工检查标记，不宣称语义矛盾。P0 不在 preview 中自动 merge、激活或逐卡编辑。

Pack 相似比较的 query 是 incoming card 的 G3 memory document；corpus 是该 query 加同 owner、非 deleted、具有 current version且 scope_overlap 的全部 existing memory documents。TF-IDF 规范、公开 rounding 和稳定 memory_id tie-break 完全复用 `char_tfidf_v1`，不能逐对改变 corpus 或为 fixture 偷调阈值。

通过文件级门禁后才创建 owner-scoped `quarantined` batch，保存 raw file hash、canonical payload、冻结的 legal-new external IDs、分析结果和 30 分钟 expiry。响应显示 Pack 元数据、完整 card/rule/scope/avoid 和每项受控分类；event/log 只含 batch ID 与计数。

### 7.5 preview token 和 commit

`preview_token` 是 43 字符 base64url HMAC-SHA256，绑定 session secret、owner、batch ID、file hash 和 expiry；只在响应与 commit body 中传输，不进 URL/log/event/Git。数据库只存 token hash。相同 Idempotency-Key 的 preview replay 必须从 batch 元数据确定性重建同一 token；SESSION_SECRET 轮换后旧 token 失效并要求重新 preview。

commit body：

```json
{
  "batch_id": "batch_...",
  "preview_token": "opaque",
  "mode": "import_all_paused"
}
```

commit 必须：

1. owner、状态、expiry、token、raw file hash 二次校验；
2. 对暂存 payload 重新 RFC 8785 canonicalize/hash；
3. 重新执行 schema/safety，并在同一写事务内重新检查 duplicate/potential conflict；
4. 只插入仍为 legal-new 的冻结子集；任一 DB 写失败整批回滚；
5. 为每张卡生成本地 ULID、status paused、local version 1、`created_by_action=import`、`source_type=import`、`source_trust=0.50`、confirmed rule/scope confidence；claimed origin 只作不可信摘要；
6. 只保存两端都成功导入的合法包内 relation；
7. 标记 committed，记录 metadata counts，立即清空 canonical payload、preview 正文和 token material。

合法外部卡绝不能直接 active；用户之后逐张 resume，且来源仍是 imported/unverified。expired/committed batch 的 GET 只返回 metadata/count，不返回已清除正文。

## 8. 事件、事务、幂等与错误

G4 新 persistent metadata events：

- `task.deleted`
- `memory.lifecycle.changed`
- `memory.conflict.detected`
- `memory.conflict.resolved`
- `memory.pack.previewed`
- `memory.pack.committed`

内容编辑/状态/删除/merge 使用 `stream_type=memory`、`stream_id=memory_id`；冲突事务为两张 card 各写一条安全 metadata event；Pack 使用 `stream_type=import`、`stream_id=batch_id`。每个 stream 在 `BEGIN IMMEDIATE` 事务内按 `MAX(seq)+1` 分配连续 seq。G4 操作由 REST 响应和 GET snapshot 恢复，不把 memory/import seq 混入 task SSE 的 Last-Event-ID，也不新增未冻结的 WebSocket。

event payload 只允许 object ID、old/new status、action、count、hash、expiry、受控 reason/error；不能含 task、rule、avoid、scope、Pack card、evidence、preview token 或 answer 正文。

所有真正改变状态的 POST/PATCH/DELETE 均要求 `Idempotency-Key`；export 是只读 POST，preview/commit 是写操作。幂等记录不得复制 Pack/card/task 正文；需要 replay 的 preview 使用 batch locator 重建安全响应。

新增受控错误至少包括：

- `INVALID_CURSOR` 422
- `MEMORY_RELATION_NOT_FOUND` 404
- `MEMORY_CONFLICT_ALREADY_RESOLVED` 409
- `MEMORY_MERGE_CONFLICT` 409
- `CONFIRMATION_MISMATCH` 409
- `MEMORY_PACK_TOO_LARGE` 413
- `MEMORY_PACK_INVALID` 422
- `MEMORY_PACK_UNSUPPORTED_VERSION` 422
- `MEMORY_PACK_INTEGRITY_MISMATCH` 422
- `IMPORT_BATCH_NOT_FOUND` 404
- `IMPORT_BATCH_EXPIRED` 409
- `IMPORT_PREVIEW_TOKEN_INVALID` 409
- `IMPORT_BATCH_STATE_CONFLICT` 409

现有 `MEMORY_NOT_FOUND|TASK_NOT_FOUND|MEMORY_STATE_CONFLICT|MEMORY_VERSION_CONFLICT|IDEMPOTENCY_CONFLICT` 语义不得回退。

## 9. 迁移与数据库不变量

`005_g4_memory_center_pack` 必须从 `004_g3_retrieval_usage` 线性升级，至少完成：

- task tombstone 字段/status 约束；
- card `evidence_missing/deleted_at/import_batch_id/import_source_version` 和 deleted tombstone invariants；
- version action check 扩展；
- relation type/status/resolution 字段、canonical conflict pair、same-owner 两端约束；
- `import_batches` 表及 owner/status/expiry/hash/token/index/check；
- list/search/filter 所需 owner-first indexes；
- 所有新增/重建 FK 的显式 `ON DELETE`；
- 保留 G1/G2/G3 的 idempotency/event/retrieval/usage unique/index/check，不得在 batch migration 中意外移除。

same-owner cross reference 必须由 DB composite FK/trigger与 repository 双层保证；不能只信请求。fresh DB、`004 -> 005`、`005 -> 004`、再升级、stale revision readiness 503、唯一 current head ready 都是硬门禁。downgrade 对 G4-only provenance/status 的处理必须在 migration doc/test 中明确，不能留下不满足 004 check 的行。

## 10. Fixture、数据集与 G4 验收

- 原 `fixtures/day5/conflict_events.json` 保持 draft；成员 A 逐条 review，成员 B 第二阶段再创建 executable G4 conflict fixture，不能静默改成“联合批准”。
- Day 5 安全集固定覆盖 12 类：unknown capability field、嵌套 script/tool、文本 prompt injection、超 1 MB、201 cards、重复 JSON key、错误 format/major、integrity mismatch、悬空 relation、HTML/XSS 纯文本、cross-owner batch、expired/tampered token 与事务回滚。
- “24/60/12/8” manifest 指：Day 2 的 24-case classification/feedback、Day 3+Day 4 的 60-case learning/retrieval、Day 5 的 12-case Pack/security、Day 1 的 8-case demo_core。manifest 必须列 case ID、source file SHA-256 和固定 train/validation/test assignment；已有 review status 原样保留，不伪造双人批准。
- split 使用 `g4_split_v1`：对 `suite + ":" + case_id` 加固定 salt `memtrace-g4-split-v1` 求 SHA-256 后升序；24 分为 14/5/5，60 分为 36/12/12，12 分为 6/3/3，8 分为 4/2/2（train/validation/test）。不能人工移动难例或根据 test 结果改 split。
- Day 5 conflict 8-case 是额外 G4 suite，不拿它冒充上述 demo_core 8-case。

G4 必须证明：G3 完整回归；搜索/筛选；编辑产生新版本与 Diff；pause/resume/archive/restore；四种 conflict action；manual merge；Pack export/preview/commit round-trip；非法 Pack 零 card 写入；导入卡全部 paused；永久删除正文/版本/usage/evidence/idempotency 残留清除；来源 task 删除矩阵；blank_demo/seeded_demo task/memory/relation/batch/event 全部隔离；刷新和进程/容器重启后恢复。

真实 Provider、自动 conflict 文案、BGE、版本 rollback、逐卡导入、动态 eval API 和 Day 6 指标不是 G4 完成门禁，也不得伪装为已完成。
