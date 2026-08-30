import rawArtifact from './day7-eval.json'

export type EvalGateStatus = 'not_run' | 'passed' | 'failed'

export interface EvalGate {
  status: EvalGateStatus
  completed: number
  expected: number
  failure_code: string | null
}

export interface SelectedEvalConfig {
  auto_activate_threshold: 0.8 | 0.85 | 0.9
  per_card_token_budget: 80 | 100 | 120
  total_token_budget: 240 | 300 | 360
}

export interface ReleaseMetrics {
  untouched_test_passes: number
  untouched_test_expected: 16
  activation_precision: number
  safety_false_activations: number
  memory_ab_wins: number
  memory_ab_cases: 8
  memtrace_not_worse_cases: number
  memtrace_comparison_cases: 8
  memtrace_median_input_tokens: number
  full_history_median_input_tokens: number
  p95_first_token_ms: number
  p95_total_latency_ms: number
}

export interface BaselineSummary {
  baseline: 'no_memory' | 'full_history' | 'retrieval_only' | 'memtrace'
  completed: number
  expected: 16
  median_input_tokens: number
  median_first_token_ms: number
  p95_latency_ms: number
  quality_passes: number
}

export interface Day7EvalArtifact {
  schema_version: '1.1.0'
  release_status: 'pending_external_gates' | 'semantic_gates_passed' | 'passed' | 'failed'
  generated_at: string | null
  candidate_commit: string | null
  model: string | null
  semantic_fixture_sha256: string
  ab_fixture_sha256: string
  baseline_fixture_sha256: string
  split: 'g5_day7_frozen_v1'
  config_selection: 'single_config_validation' | 'validation_grid_v1'
  selected_config: SelectedEvalConfig | null
  gates: {
    provider_preflight: EvalGate
    validation_semantic: EvalGate
    semantic_test: EvalGate
    memory_ab: EvalGate
    four_baselines: EvalGate
  }
  metrics: ReleaseMetrics | null
  baselines: BaselineSummary[]
}

export const day7EvalArtifact = parseDay7EvalArtifact(rawArtifact)

export function parseDay7EvalArtifact(value: unknown): Day7EvalArtifact {
  const row = exact(value, [
    'schema_version',
    'release_status',
    'generated_at',
    'candidate_commit',
    'model',
    'semantic_fixture_sha256',
    'ab_fixture_sha256',
    'baseline_fixture_sha256',
    'split',
    'config_selection',
    'selected_config',
    'gates',
    'metrics',
    'baselines',
  ])
  if (row.schema_version !== '1.1.0' || row.split !== 'g5_day7_frozen_v1') {
    throw new Error('invalid Day 7 eval artifact version')
  }
  if (!['pending_external_gates', 'semantic_gates_passed', 'passed', 'failed'].includes(String(row.release_status))) {
    throw new Error('invalid release status')
  }
  if (!['single_config_validation', 'validation_grid_v1'].includes(String(row.config_selection))) {
    throw new Error('invalid config selection')
  }
  const gates = exact(row.gates, [
    'provider_preflight',
    'validation_semantic',
    'semantic_test',
    'memory_ab',
    'four_baselines',
  ])
  const result: Day7EvalArtifact = {
    schema_version: '1.1.0',
    release_status: row.release_status as Day7EvalArtifact['release_status'],
    generated_at: nullablePattern(
      row.generated_at,
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/,
    ),
    candidate_commit: nullablePattern(row.candidate_commit, /^[0-9a-f]{40}$/),
    model: nullableString(row.model, 128),
    semantic_fixture_sha256: pattern(row.semantic_fixture_sha256, /^[0-9a-f]{64}$/),
    ab_fixture_sha256: pattern(row.ab_fixture_sha256, /^[0-9a-f]{64}$/),
    baseline_fixture_sha256: pattern(row.baseline_fixture_sha256, /^[0-9a-f]{64}$/),
    split: 'g5_day7_frozen_v1',
    config_selection: row.config_selection as Day7EvalArtifact['config_selection'],
    selected_config: row.selected_config === null ? null : parseConfig(row.selected_config),
    gates: {
      provider_preflight: parseGate(gates.provider_preflight),
      validation_semantic: parseGate(gates.validation_semantic),
      semantic_test: parseGate(gates.semantic_test),
      memory_ab: parseGate(gates.memory_ab),
      four_baselines: parseGate(gates.four_baselines),
    },
    metrics: row.metrics === null ? null : parseMetrics(row.metrics),
    baselines: array(row.baselines).map(parseBaseline),
  }
  const complete = Object.values(result.gates).every((gate) => gate.status === 'passed')
  const expectedGateCounts = {
    provider_preflight: 6,
    validation_semantic: 16,
    semantic_test: 16,
    memory_ab: 8,
    four_baselines: 64,
  } as const
  for (const [name, expected] of Object.entries(expectedGateCounts)) {
    if (result.gates[name as keyof typeof result.gates].expected !== expected) {
      throw new Error('invalid frozen gate cardinality')
    }
  }
  if (result.release_status === 'passed' || result.release_status === 'semantic_gates_passed') {
    if (
      !complete ||
      result.metrics === null ||
      result.baselines.length !== 4 ||
      result.selected_config === null ||
      result.generated_at === null ||
      result.model === null
    ) {
      throw new Error('passed artifact is incomplete')
    }
    if (result.release_status === 'passed' && result.candidate_commit === null) {
      throw new Error('passed artifact requires a candidate commit')
    }
    enforceReleaseThresholds(result.metrics, result.baselines)
  } else if (result.metrics !== null || result.baselines.length !== 0) {
    throw new Error('non-passed artifact cannot publish release metrics')
  }
  return result
}

function enforceReleaseThresholds(
  metrics: ReleaseMetrics,
  baselines: BaselineSummary[],
): void {
  if (
    metrics.untouched_test_passes !== 16 ||
    metrics.activation_precision < 0.95 ||
    metrics.safety_false_activations !== 0 ||
    metrics.memory_ab_wins < 6 ||
    metrics.memtrace_not_worse_cases < 7 ||
    metrics.memtrace_median_input_tokens >= metrics.full_history_median_input_tokens ||
    metrics.p95_first_token_ms > 10_000 ||
    metrics.p95_total_latency_ms >= 60_000
  ) {
    throw new Error('passed artifact does not meet release thresholds')
  }
  const expected = new Set(['no_memory', 'full_history', 'retrieval_only', 'memtrace'])
  for (const baseline of baselines) {
    if (!expected.delete(baseline.baseline) || baseline.completed !== 16) {
      throw new Error('passed artifact baseline evidence is incomplete')
    }
  }
  if (expected.size !== 0) throw new Error('passed artifact baseline evidence is incomplete')
}

function parseGate(value: unknown): EvalGate {
  const row = exact(value, ['status', 'completed', 'expected', 'failure_code'])
  if (!['not_run', 'passed', 'failed'].includes(String(row.status))) throw new Error('invalid gate')
  const gate = {
    status: row.status as EvalGateStatus,
    completed: integer(row.completed),
    expected: integer(row.expected, 1),
    failure_code: nullablePattern(row.failure_code, /^[A-Z0-9_]{2,64}$/),
  }
  if (gate.completed > gate.expected) throw new Error('invalid gate count')
  if (gate.status === 'passed' && (gate.completed !== gate.expected || gate.failure_code !== null)) {
    throw new Error('passed gate is inconsistent')
  }
  return gate
}

function parseConfig(value: unknown): SelectedEvalConfig {
  const row = exact(value, [
    'auto_activate_threshold',
    'per_card_token_budget',
    'total_token_budget',
  ])
  if (![0.8, 0.85, 0.9].includes(Number(row.auto_activate_threshold))) throw new Error('bad threshold')
  if (![80, 100, 120].includes(Number(row.per_card_token_budget))) throw new Error('bad card budget')
  if (![240, 300, 360].includes(Number(row.total_token_budget))) throw new Error('bad total budget')
  return row as unknown as SelectedEvalConfig
}

function parseMetrics(value: unknown): ReleaseMetrics {
  const row = exact(value, [
    'untouched_test_passes',
    'untouched_test_expected',
    'activation_precision',
    'safety_false_activations',
    'memory_ab_wins',
    'memory_ab_cases',
    'memtrace_not_worse_cases',
    'memtrace_comparison_cases',
    'memtrace_median_input_tokens',
    'full_history_median_input_tokens',
    'p95_first_token_ms',
    'p95_total_latency_ms',
  ])
  if (row.untouched_test_expected !== 16 || row.memory_ab_cases !== 8 || row.memtrace_comparison_cases !== 8) {
    throw new Error('invalid fixed metric cardinality')
  }
  const precision = number(row.activation_precision, 0, 1)
  return {
    untouched_test_passes: integer(row.untouched_test_passes),
    untouched_test_expected: 16,
    activation_precision: precision,
    safety_false_activations: integer(row.safety_false_activations),
    memory_ab_wins: integer(row.memory_ab_wins),
    memory_ab_cases: 8,
    memtrace_not_worse_cases: integer(row.memtrace_not_worse_cases),
    memtrace_comparison_cases: 8,
    memtrace_median_input_tokens: integer(row.memtrace_median_input_tokens),
    full_history_median_input_tokens: integer(row.full_history_median_input_tokens),
    p95_first_token_ms: number(row.p95_first_token_ms, 0),
    p95_total_latency_ms: number(row.p95_total_latency_ms, 0),
  }
}

function parseBaseline(value: unknown): BaselineSummary {
  const row = exact(value, [
    'baseline',
    'completed',
    'expected',
    'median_input_tokens',
    'median_first_token_ms',
    'p95_latency_ms',
    'quality_passes',
  ])
  if (!['no_memory', 'full_history', 'retrieval_only', 'memtrace'].includes(String(row.baseline))) {
    throw new Error('invalid baseline')
  }
  if (row.expected !== 16) throw new Error('invalid baseline cardinality')
  return {
    baseline: row.baseline as BaselineSummary['baseline'],
    completed: integer(row.completed),
    expected: 16,
    median_input_tokens: integer(row.median_input_tokens),
    median_first_token_ms: number(row.median_first_token_ms, 0),
    p95_latency_ms: number(row.p95_latency_ms, 0),
    quality_passes: integer(row.quality_passes),
  }
}

function exact(value: unknown, keys: readonly string[]): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new Error('expected object')
  const row = value as Record<string, unknown>
  const actual = Object.keys(row).sort()
  const expected = [...keys].sort()
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    throw new Error('unknown or missing eval artifact field')
  }
  return row
}

function array(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw new Error('expected array')
  return value
}

function integer(value: unknown, minimum = 0): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < minimum) throw new Error('invalid integer')
  return value
}

function number(value: unknown, minimum: number, maximum = Number.POSITIVE_INFINITY): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < minimum || value > maximum) {
    throw new Error('invalid number')
  }
  return value
}

function pattern(value: unknown, expression: RegExp): string {
  if (typeof value !== 'string' || !expression.test(value)) throw new Error('invalid string')
  return value
}

function nullableString(value: unknown, maximum: number): string | null {
  if (value === null) return null
  if (typeof value !== 'string' || value.length < 1 || value.length > maximum) throw new Error('invalid string')
  return value
}

function nullablePattern(value: unknown, expression: RegExp): string | null {
  return value === null ? null : pattern(value, expression)
}
