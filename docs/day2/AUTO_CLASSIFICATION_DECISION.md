# Day 2 自动任务分类决策

## 决策

用户不再选择或提交 `scenario`。`POST /api/v1/tasks` 只接收 `task_text`、`memory_mode` 和 `current_constraints`；继续发送 `scenario` 因 `extra=forbid` 返回 422。

服务端使用纯函数 `auto_rule_v1` 生成四选一 domain：

- `programming_learning`
- `software_development`
- `general_text`
- `other`

不增加 LLM 调用。数据库 `tasks.scenario` 在 D2 保留旧列名，但只保存服务端检测 domain；TaskSnapshot 的同名字段也明确为 server-derived。

## 规范化、信号和计分

输入先执行 Unicode NFKC 和 casefold。中英文词表产生受控信号；不保存命中的原文片段。

| reason code | programming_learning | software_development | general_text |
|---|---:|---:|---:|
| `code_present` | +1 | +1 | 0 |
| `technical_context` | +1 | +1 | 0 |
| `debugging_cue` | +3 | 0 | 0 |
| `learning_cue` | +3 | 0 | 0 |
| `explanation_intent`，仅技术语境 | +2 | 0 | 0 |
| `development_action` | 0 | +3 | 0 |
| `deployment_cue` | 0 | +3 | 0 |
| `text_task`，仅非技术语境 | 0 | 0 | +4 |

唯一最高分至少为 3 才选择对应 domain。无信号、低于阈值或最高分并列时选择 `other` 并加入 `ambiguous`。

非 `other` 的规则分数为：

```text
min(0.95, 0.50 + 0.06 * min(top_score, 5) + 0.05 * min(top_score - second_score, 3))
```

结果四舍五入到两位小数。无信号的 `other` 为 0.20；弱证据或冲突为 0.30。它不是统计概率。UI 小于 0.70 时显示“低置信”。理由按固定枚举顺序去重，最多 5 个；`other` 必须包含 `ambiguous`。

## 单一分析来源

生产请求固定顺序：

1. 对不含任何派生分类的规范请求体计算幂等 hash；
2. 已存在的相同请求直接重放；
3. 新请求先取得 TaskStore 容量 reservation；
4. 只调用一次 `analyze_task(request)` 得到 TaskAnalysis；
5. Repository 使用 `analysis.fingerprint.domain` 写 `tasks.scenario`；
6. TaskStore 使用同一 analysis 建立 snapshot 和 worker record；
7. Orchestrator 只持久化、发布这个 fingerprint，不重新分类；
8. 所有失败、并发输家和幂等冲突释放 reservation。

request hash 不含 domain、置信度、理由或 fingerprint ID。一个成功 task 的 DB scenario、snapshot scenario 和 fingerprint domain 必须一致。

## 契约与兼容策略

- Day 2 contract：`1.1.0`。
- TaskFingerprint schema：`1.1`。
- 新字段：`classification_source="auto_rule_v1"`、`classification_confidence`、`classification_reasons`。
- `task.fingerprinted` 事件只带安全枚举摘要、分数和 reason code；不带 task_text 或 semantic_query。
- 这是有意的请求破坏性变更：旧客户端发送 `scenario` 会收到 422，以免继续信任用户自报分类。
- DB 不做只改列名的 migration；后续 migration 才可将 `scenario` 重命名为 `detected_domain`。

## UI 行为

- 不存在“使用场景”下拉框。
- fingerprint 到达前显示“正在识别”；到达后只读显示系统识别 domain、规则分数和简短理由。
- `other` 显示“暂未明确识别”；低分显示“低置信”，不要求用户补选类别。
- D2 不增加“纠正分类”输入；未来纠正只能作为普通反馈进入准入流程。

## Day 3 连接点

Feedback Compiler 接收自动 TaskFingerprint、轨迹、原输出、编辑 Diff 和显式反馈，自动判断 preference、rule、experience、one-shot。自动分类不能绕过 MemoryCard candidate、evidence gate 或用户确认；低置信 `other` 不得自动生成宽作用域 active 规则。

## 必测案例

- 中文/英文编程学习、Python 教学调试；
- React 重构/代码审查、部署/环境配置；
- 非代码改写/总结；
- 无证据与冲突输入；
- NFKC/casefold 后确定性；
- 旧 `scenario` 422；
- DB/snapshot/fingerprint 一致；
- 同一 task 只分析一次；
- 事件和日志不包含用户正文。

