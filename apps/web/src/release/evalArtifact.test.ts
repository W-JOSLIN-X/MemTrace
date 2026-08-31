import { describe, expect, it } from 'vitest'

import rawArtifact from './day7-eval.json'
import { parseDay7EvalArtifact } from './evalArtifact'

describe('Day 7 release artifact parser', () => {
  it('accepts the frozen real release artifact and rejects unknown fields', () => {
    const parsed = parseDay7EvalArtifact(structuredClone(rawArtifact))
    expect(parsed.release_status).toBe('passed')
    expect(parsed.candidate_commit).toBe('5d02d3010b4e5560d9de697b471391e6ff742796')
    const unknown = { ...structuredClone(rawArtifact), unexpected: true }
    expect(() => parseDay7EvalArtifact(unknown)).toThrow(/unknown or missing/)
  })

  it('rejects a passed label when the measured release thresholds are not met', () => {
    const artifact = passedArtifact()
    artifact.metrics.activation_precision = 0.5
    expect(() => parseDay7EvalArtifact(artifact)).toThrow(/release thresholds/)
  })

  it('accepts a complete, threshold-compliant four-baseline artifact', () => {
    const parsed = parseDay7EvalArtifact(passedArtifact())
    expect(parsed.release_status).toBe('passed')
    expect(parsed.baselines.map((item) => item.baseline)).toEqual([
      'no_memory',
      'full_history',
      'retrieval_only',
      'memtrace',
    ])
  })
})

function passedArtifact() {
  return {
    ...structuredClone(rawArtifact),
    release_status: 'passed',
    generated_at: '2026-08-30T12:00:00Z',
    candidate_commit: 'a'.repeat(40),
    model: 'live-verified-model',
    selected_config: {
      auto_activate_threshold: 0.85,
      per_card_token_budget: 100,
      total_token_budget: 300,
    },
    gates: {
      provider_preflight: { status: 'passed', completed: 6, expected: 6, failure_code: null },
      validation_semantic: { status: 'passed', completed: 16, expected: 16, failure_code: null },
      semantic_test: { status: 'passed', completed: 16, expected: 16, failure_code: null },
      memory_ab: { status: 'passed', completed: 8, expected: 8, failure_code: null },
      four_baselines: { status: 'passed', completed: 64, expected: 64, failure_code: null },
    },
    metrics: {
      untouched_test_passes: 16,
      untouched_test_expected: 16,
      activation_precision: 0.97,
      safety_false_activations: 0,
      memory_ab_wins: 7,
      memory_ab_cases: 8,
      memtrace_not_worse_cases: 7,
      memtrace_comparison_cases: 8,
      memtrace_median_input_tokens: 500,
      full_history_median_input_tokens: 900,
      p95_first_token_ms: 8_000,
      p95_total_latency_ms: 50_000,
    },
    baselines: ['no_memory', 'full_history', 'retrieval_only', 'memtrace'].map(
      (baseline, index) => ({
        baseline,
        completed: 16,
        expected: 16,
        median_input_tokens: 400 + index * 100,
        median_first_token_ms: 1_500,
        p95_latency_ms: 12_000,
        quality_passes: 15,
      }),
    ),
  }
}
