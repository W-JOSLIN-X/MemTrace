const ID = '01J00000000000000000000001'
const AT = '2026-08-30T12:00:00Z'

export function createG5Response() {
  return {
    schema_version: '2.0.0',
    request_id: 'req-test',
    task_id: `task_${ID}`,
    provider_mode: 'real',
    model: 'deepseek-v4-flash',
    memory_mode: 'on',
    created_at: AT,
  }
}

export function createG5TurnResponse() {
  return {
    schema_version: '2.0.0',
    request_id: 'req-turn',
    task_id: `task_${ID}`,
    run_id: `run_${ID}`,
    turn_index: 1,
    user_message: {
      message_id: `msg_${ID}`,
      run_id: `run_${ID}`,
      role: 'user',
      content: '以后请用中文回答。',
      turn_index: 1,
      created_at: AT,
    },
    assistant_message: {
      message_id: 'msg_01J00000000000000000000002',
      run_id: `run_${ID}`,
      role: 'assistant',
      content: '好的。',
      turn_index: 1,
      created_at: AT,
    },
    reflection_job_id: `job_${ID}`,
    memory_mode: 'on',
    memory_decisions: [],
    usage: [
      {
        stage: 'chat',
        provider_mode: 'real',
        model: 'deepseek-v4-flash',
        prompt_hash: `sha256:${'a'.repeat(64)}`,
        input_tokens: 20,
        output_tokens: 10,
        total_tokens: 30,
        reasoning_tokens: null,
        latency_ms: 100,
      },
    ],
  }
}

export function createG5SnapshotResponse() {
  const turn = createG5TurnResponse()
  return {
    schema_version: '2.0.0',
    request_id: 'req-snapshot',
    task_id: turn.task_id,
    memory_mode: 'on',
    provider_mode: 'real',
    model: 'deepseek-v4-flash',
    messages: [turn.user_message, turn.assistant_message],
    last_turn: {
      run_id: turn.run_id,
      turn_index: turn.turn_index,
      reflection_job_id: turn.reflection_job_id,
      memory_decisions: turn.memory_decisions,
      usage: turn.usage,
    },
    last_event_seq: 1,
    created_at: AT,
    updated_at: AT,
  }
}

export function createG5MemoryList() {
  return {
    request_id: 'req-memory',
    items: [
      {
        memory_id: `mem_${ID}`,
        kind: 'preference',
        content: '<img src=x onerror=alert(1)>偏好中文',
        applies_when: '回答一般问题时',
        review_status: 'active',
        confidence: 0.96,
        current_version_id: `memver_${ID}`,
        version: 1,
        source_type: 'conversation_turn',
        created_at: AT,
        updated_at: AT,
      },
    ],
    next_cursor: null,
  }
}

export function createG5EventList() {
  return {
    request_id: 'req-events',
    items: [
      {
        event_id: 'evt-test',
        event_seq: 1,
        event_type: 'memory.analysis.completed',
        memory_id: `mem_${ID}`,
        version_id: `memver_${ID}`,
        old_status: null,
        new_status: 'active',
        reason_code: 'llm_add',
        job_id: `job_${ID}`,
        created_at: AT,
      },
    ],
    next_seq: 1,
  }
}

export function createG5JobResponse() {
  return {
    request_id: 'req-job',
    job_id: `job_${ID}`,
    task_id: `task_${ID}`,
    run_id: `run_${ID}`,
    turn_index: 1,
    status: 'completed',
    attempt: 1,
    mutation_decision: 'mutate',
    provider_model: 'deepseek-v4-flash',
    schema_version: '2.0',
    error_code: null,
    created_at: AT,
    updated_at: AT,
  }
}
