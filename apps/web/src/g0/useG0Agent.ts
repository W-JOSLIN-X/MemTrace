import { useCallback, useEffect, useReducer, useRef, useState } from 'react'

import {
  browserG0Api,
  G0ApiError,
  newIdempotencyKey,
  type G0Api,
} from './api'
import {
  browserEventSourceFactory,
  buildEventStreamUrl,
  type EventSourceFactory,
  type EventStreamConnection,
} from './eventStream'
import {
  createInitialG0State,
  g0Reducer,
  type G0Action,
  type PublicUiError,
  type RecoveryReason,
} from './reducer'
import { parseSseEvent } from './runtime'
import type {
  G0EventType,
  FeedbackCreateAccepted,
  FeedbackCreateRequest,
  MemoryDetailResponse,
  MemoryId,
  MemoryJobId,
  MemoryJobResponse,
  ResolveRequest,
  ResolveResponse,
  ResponsePolicy,
  TaskCreateRequest,
  TaskId,
  TaskSnapshot,
} from './types'

const DEFAULT_RETRY_DELAYS_MS = [250, 500, 1000, 2000] as const

export interface SubmitTaskOptions {
  memoryMode: 'on' | 'off'
  responsePolicy: ResponsePolicy
}

export interface UseG0AgentOptions {
  api?: G0Api
  eventSourceFactory?: EventSourceFactory
  retryDelaysMs?: readonly number[]
  idempotencyKeyFactory?: () => string
  feedbackCatchupTimeoutMs?: number
  memoryMonitorTimeoutMs?: number
}

export interface FeedbackSubmissionState {
  phase: 'idle' | 'submitting' | 'recorded' | 'failed'
  accepted: FeedbackCreateAccepted | null
  job: MemoryJobResponse | null
  catchup: 'event' | 'snapshot' | 'unconfirmed' | null
  monitor:
    | 'idle'
    | 'monitoring'
    | 'still_processing'
    | 'completed'
    | 'failed'
  error: PublicUiError | null
}

const INITIAL_FEEDBACK_STATE: FeedbackSubmissionState = {
  phase: 'idle',
  accepted: null,
  job: null,
  catchup: null,
  monitor: 'idle',
  error: null,
}

export function useG0Agent({
  api = browserG0Api,
  eventSourceFactory = browserEventSourceFactory,
  retryDelaysMs = DEFAULT_RETRY_DELAYS_MS,
  idempotencyKeyFactory = newIdempotencyKey,
  feedbackCatchupTimeoutMs = 1_500,
  memoryMonitorTimeoutMs = 30_000,
}: UseG0AgentOptions = {}) {
  const [state, reducerDispatch] = useReducer(
    g0Reducer,
    undefined,
    createInitialG0State,
  )
  const [feedbackState, setFeedbackState] = useState<FeedbackSubmissionState>(
    INITIAL_FEEDBACK_STATE,
  )
  const stateRef = useRef(state)
  const generationRef = useRef(0)
  const connectionEpochRef = useRef(0)
  const connectionRef = useRef<EventStreamConnection | null>(null)
  const feedbackConnectionRef = useRef<EventStreamConnection | null>(null)
  const feedbackCatchupCancelRef = useRef<(() => void) | null>(null)
  const memoryMonitorEpochRef = useRef(0)
  const controllersRef = useRef(new Set<AbortController>())
  const timerResolversRef = useRef(
    new Map<ReturnType<typeof setTimeout>, () => void>(),
  )
  const recoveryInFlightRef = useRef<number | null>(null)
  const finalizingInFlightRef = useRef<number | null>(null)
  const pendingTaskWriteRef = useRef<{ requestJson: string; key: string } | null>(
    null,
  )
  const pendingFeedbackWriteRef = useRef<{
    requestJson: string
    key: string
  } | null>(null)
  const pendingRetryWriteRef = useRef(
    new Map<MemoryJobId, { requestJson: string; key: string }>(),
  )
  const pendingResolveWriteRef = useRef(
    new Map<MemoryId, { requestJson: string; key: string }>(),
  )

  const commit = useCallback((action: G0Action) => {
    const next = g0Reducer(stateRef.current, action)
    stateRef.current = next
    reducerDispatch(action)
    return next
  }, [])

  const closeConnection = useCallback(() => {
    connectionEpochRef.current += 1
    connectionRef.current?.close()
    connectionRef.current = null
  }, [])

  const abortRequests = useCallback(() => {
    for (const controller of controllersRef.current) controller.abort()
    controllersRef.current.clear()
  }, [])

  const releaseTimers = useCallback(() => {
    for (const [timer, resolve] of timerResolversRef.current) {
      clearTimeout(timer)
      resolve()
    }
    timerResolversRef.current.clear()
  }, [])

  const stopSession = useCallback(() => {
    memoryMonitorEpochRef.current += 1
    closeConnection()
    feedbackCatchupCancelRef.current?.()
    feedbackCatchupCancelRef.current = null
    feedbackConnectionRef.current?.close()
    feedbackConnectionRef.current = null
    abortRequests()
    releaseTimers()
    recoveryInFlightRef.current = null
    finalizingInFlightRef.current = null
  }, [abortRequests, closeConnection, releaseTimers])

  const sleep = useCallback(async (delayMs: number) => {
    if (delayMs <= 0) return
    await new Promise<void>((resolve) => {
      const timer = setTimeout(() => {
        timerResolversRef.current.delete(timer)
        resolve()
      }, delayMs)
      timerResolversRef.current.set(timer, resolve)
    })
  }, [])

  const getSnapshot = useCallback(
    async (taskId: TaskId, generation: number): Promise<TaskSnapshot | null> => {
      const controller = new AbortController()
      controllersRef.current.add(controller)
      try {
        const snapshot = await api.getTask(taskId, controller.signal)
        if (generation !== generationRef.current) return null
        return snapshot
      } finally {
        controllersRef.current.delete(controller)
      }
    },
    [api],
  )

  const refreshSnapshot = useCallback(
    async (generation: number) => {
      const current = stateRef.current
      if (!current.taskId || generation !== generationRef.current) return
      try {
        const snapshot = await getSnapshot(current.taskId, generation)
        if (!snapshot || generation !== generationRef.current) return
        commit({ type: 'snapshot_received', snapshot, mode: 'enrichment' })
      } catch (error) {
        if (!isAbortError(error)) {
          // A metadata refresh is opportunistic. Stream recovery owns retries.
        }
      }
    },
    [commit, getSnapshot],
  )

  const connectRef = useRef<
    (
      eventsUrl: string,
      eventSeq: number,
      offset: number,
      generation: number,
    ) => void
  >(() => undefined)
  const recoverRef = useRef<
    (
      generation: number,
      reason: RecoveryReason,
      restartAttempts?: boolean,
    ) => Promise<void>
  >(async () => undefined)
  const finalizeRef = useRef<(generation: number) => Promise<void>>(
    async () => undefined,
  )
  const monitorMemoryJobRef = useRef<
    (
      memoryJobId: MemoryJobId,
      generation: number,
      accepted: FeedbackCreateAccepted,
    ) => Promise<void>
  >(async () => undefined)

  const finalize = useCallback(
    async (generation: number) => {
      if (
        finalizingInFlightRef.current === generation ||
        generation !== generationRef.current
      ) {
        return
      }
      finalizingInFlightRef.current = generation
      closeConnection()
      const delays = [0, ...retryDelaysMs]
      try {
        for (let index = 0; index < delays.length; index += 1) {
          await sleep(delays[index] ?? 0)
          if (generation !== generationRef.current) return
          const current = stateRef.current
          if (!current.taskId) return
          try {
            const snapshot = await getSnapshot(current.taskId, generation)
            if (!snapshot) return
            const next = commit({
              type: 'snapshot_received',
              snapshot,
              mode: 'final',
            })
            if (next.terminal) return
          } catch (error) {
            if (isAbortError(error) || generation !== generationRef.current) return
          }
        }
        commit({
          type: 'connection_exhausted',
          error: {
            code: 'FINAL_SNAPSHOT_UNAVAILABLE',
            message: '运行已结束，但最终任务快照暂时不可用；已保留现有输出。',
            retryable: true,
          },
        })
      } finally {
        if (finalizingInFlightRef.current === generation) {
          finalizingInFlightRef.current = null
        }
      }
    },
    [closeConnection, commit, getSnapshot, retryDelaysMs, sleep],
  )

  const recover = useCallback(
    async (
      generation: number,
      reason: RecoveryReason,
      restartAttempts = false,
    ) => {
      if (
        recoveryInFlightRef.current === generation ||
        generation !== generationRef.current ||
        stateRef.current.terminal
      ) {
        return
      }
      recoveryInFlightRef.current = generation
      closeConnection()
      const firstAttempt = restartAttempts
        ? 1
        : Math.max(1, stateRef.current.reconnectAttempt + 1)
      try {
        for (
          let attempt = firstAttempt;
          attempt <= retryDelaysMs.length;
          attempt += 1
        ) {
          commit({ type: 'connection_recovering', attempt, reason })
          await sleep(retryDelaysMs[attempt - 1] ?? 0)
          if (generation !== generationRef.current) return
          const current = stateRef.current
          if (!current.taskId || !current.eventsUrl) return
          const replayFromEventSeq = current.lastPersistentEventSeq
          try {
            const snapshot = await getSnapshot(current.taskId, generation)
            if (!snapshot) return
            const next = commit({
              type: 'snapshot_received',
              snapshot,
              mode: 'recovery',
            })
            connectRef.current(
              current.eventsUrl,
              replayFromEventSeq,
              next.endOffset,
              generation,
            )
            return
          } catch (error) {
            if (isAbortError(error) || generation !== generationRef.current) return
          }
        }
        commit({
          type: 'connection_exhausted',
          error: {
            code: 'STREAM_RECONNECT_EXHAUSTED',
            message: '流式连接多次恢复失败，现有回答已保留。你可以手动重试连接。',
            retryable: true,
          },
        })
      } finally {
        if (recoveryInFlightRef.current === generation) {
          recoveryInFlightRef.current = null
        }
      }
    },
    [closeConnection, commit, getSnapshot, retryDelaysMs, sleep],
  )

  const connect = useCallback(
    (
      eventsUrl: string,
      eventSeq: number,
      offset: number,
      generation: number,
    ) => {
      if (generation !== generationRef.current) return
      closeConnection()
      const url = buildEventStreamUrl(eventsUrl, eventSeq, offset)
      const connectionEpoch = connectionEpochRef.current
      const connection = eventSourceFactory(url, {
        onOpen: () => {
          if (
            generation !== generationRef.current ||
            connectionEpoch !== connectionEpochRef.current
          ) {
            return
          }
          commit({ type: 'connection_opened' })
        },
        onEvent: (
          eventType: G0EventType,
          rawData: string,
          lastEventId: string,
        ) => {
          if (
            generation !== generationRef.current ||
            connectionEpoch !== connectionEpochRef.current
          ) {
            return
          }
          let event
          try {
            event = parseSseEvent(eventType, rawData, lastEventId)
          } catch {
            commit({ type: 'protocol_error' })
            void recoverRef.current(generation, 'protocol_error')
            return
          }
          const before = stateRef.current
          if (event.task_id !== before.taskId || event.run_id !== before.runId) {
            return
          }
          const next = commit({ type: 'sse_event', event })
          if (next.recoveryReason) {
            void recoverRef.current(generation, next.recoveryReason)
            return
          }
          if (
            event.event_type === 'agent.plan.published' ||
            event.event_type === 'tool.result'
          ) {
            void refreshSnapshot(generation)
          }
          if (event.event_type === 'stream.done') {
            closeConnection()
            void finalizeRef.current(generation)
          }
        },
        onError: () => {
          if (
            generation !== generationRef.current ||
            connectionEpoch !== connectionEpochRef.current ||
            stateRef.current.terminal
          ) {
            return
          }
          void recoverRef.current(generation, stateRef.current.recoveryReason)
        },
      })
      if (
        generation !== generationRef.current ||
        connectionEpoch !== connectionEpochRef.current
      ) {
        connection.close()
        return
      }
      connectionRef.current = connection
    },
    [closeConnection, commit, eventSourceFactory, refreshSnapshot],
  )

  useEffect(() => {
    finalizeRef.current = finalize
  }, [finalize])

  useEffect(() => {
    recoverRef.current = recover
  }, [recover])

  useEffect(() => {
    connectRef.current = connect
  }, [connect])

  const submitTask = useCallback(
    async (taskText: string, options: SubmitTaskOptions) => {
      const trimmed = taskText.trim()
      const scalarLength = [...trimmed].length
      if (scalarLength === 0 || scalarLength > 20000) {
        commit({
          type: 'submit_failed',
          error: {
            code: 'CLIENT_VALIDATION_ERROR',
            message:
              scalarLength === 0
                ? '请输入任务内容。'
                : '任务内容不能超过 20,000 个 Unicode 字符。',
            retryable: false,
          },
        })
        return
      }

      const generation = generationRef.current + 1
      generationRef.current = generation
      stopSession()
      pendingFeedbackWriteRef.current = null
      pendingRetryWriteRef.current.clear()
      pendingResolveWriteRef.current.clear()
      commit({ type: 'submit_started' })
      const request: TaskCreateRequest = {
        task_text: trimmed,
        memory_mode: options.memoryMode,
        current_constraints: {
          response_policy: options.responsePolicy,
          urgency: 'normal',
          memory_disabled: options.memoryMode === 'off',
          source: 'ui',
        },
      }
      const requestJson = JSON.stringify(request)
      if (pendingTaskWriteRef.current?.requestJson !== requestJson) {
        pendingTaskWriteRef.current = {
          requestJson,
          key: idempotencyKeyFactory(),
        }
      }
      const idempotencyKey = pendingTaskWriteRef.current.key
      const controller = new AbortController()
      controllersRef.current.add(controller)
      try {
        const accepted = await api.createTask(
          request,
          controller.signal,
          idempotencyKey,
        )
        if (generation !== generationRef.current) return
        pendingTaskWriteRef.current = null
        setFeedbackState(INITIAL_FEEDBACK_STATE)
        commit({ type: 'task_accepted', accepted, taskText: trimmed })
        connect(accepted.events_url, 0, 0, generation)
      } catch (error) {
        if (isAbortError(error) || generation !== generationRef.current) return
        commit({ type: 'submit_failed', error: toPublicError(error) })
      } finally {
        controllersRef.current.delete(controller)
      }
    },
    [api, commit, connect, idempotencyKeyFactory, stopSession],
  )

  const resetOwner = useCallback(() => {
    generationRef.current += 1
    stopSession()
    pendingTaskWriteRef.current = null
    pendingFeedbackWriteRef.current = null
    pendingRetryWriteRef.current.clear()
    pendingResolveWriteRef.current.clear()
    setFeedbackState(INITIAL_FEEDBACK_STATE)
    commit({ type: 'owner_reset' })
  }, [commit, stopSession])

  const restoreTask = useCallback(
    async (taskId: TaskId): Promise<TaskSnapshot | null> => {
      const generation = generationRef.current + 1
      generationRef.current = generation
      stopSession()
      pendingTaskWriteRef.current = null
      pendingFeedbackWriteRef.current = null
      pendingRetryWriteRef.current.clear()
      pendingResolveWriteRef.current.clear()
      setFeedbackState(INITIAL_FEEDBACK_STATE)
      commit({ type: 'owner_reset' })
      try {
        const snapshot = await getSnapshot(taskId, generation)
        if (!snapshot || generation !== generationRef.current) return null
        const next = commit({ type: 'task_restored', snapshot })
        if (!next.terminal && next.eventsUrl) {
          connect(
            next.eventsUrl,
            next.lastPersistentEventSeq,
            next.endOffset,
            generation,
          )
        }
        const latestFeedback = snapshot.feedback_events.at(-1)
        if (latestFeedback) {
          const accepted: FeedbackCreateAccepted = {
            request_id: snapshot.request_id,
            feedback_id: latestFeedback.feedback_id,
            memory_job_id: latestFeedback.memory_job_id,
            feedback_type: latestFeedback.feedback_type,
            job_status: 'pending',
          }
          setFeedbackState({
            ...INITIAL_FEEDBACK_STATE,
            phase: 'recorded',
            accepted,
            catchup: 'snapshot',
            monitor: 'monitoring',
          })
          void monitorMemoryJobRef.current(
            latestFeedback.memory_job_id,
            generation,
            accepted,
          )
        }
        return snapshot
      } catch (error) {
        if (isAbortError(error) || generation !== generationRef.current) return null
        commit({ type: 'submit_failed', error: toPublicError(error) })
        return null
      }
    },
    [commit, connect, getSnapshot, stopSession],
  )

  const catchUpFeedback = useCallback(
    (
      accepted: FeedbackCreateAccepted,
      generation: number,
    ): Promise<boolean> => {
      const current = stateRef.current
      if (!current.taskId || !current.runId || !current.eventsUrl) {
        return Promise.resolve(false)
      }
      const expectedTaskId = current.taskId
      const expectedRunId = current.runId
      const url = buildEventStreamUrl(
        current.eventsUrl,
        current.lastPersistentEventSeq,
        current.endOffset,
      )

      return new Promise<boolean>((resolve) => {
        let finished = false
        let connection: EventStreamConnection | null = null
        let timeout: ReturnType<typeof setTimeout> | null = null

        const finish = (found: boolean) => {
          if (finished) return
          finished = true
          if (timeout !== null) clearTimeout(timeout)
          connection?.close()
          if (feedbackConnectionRef.current === connection) {
            feedbackConnectionRef.current = null
          }
          feedbackCatchupCancelRef.current = null
          resolve(found)
        }

        feedbackCatchupCancelRef.current = () => finish(false)
        timeout = setTimeout(() => finish(false), feedbackCatchupTimeoutMs)
        connection = eventSourceFactory(url, {
          onOpen: () => undefined,
          onEvent: (eventType, rawData, lastEventId) => {
            if (generation !== generationRef.current) {
              finish(false)
              return
            }
            try {
              const event = parseSseEvent(eventType, rawData, lastEventId)
              if (event.task_id !== expectedTaskId || event.run_id !== expectedRunId) {
                return
              }
              commit({ type: 'sse_event', event })
              if (
                event.event_type === 'feedback.recorded' &&
                event.data.feedback_id === accepted.feedback_id &&
                event.data.memory_job_id === accepted.memory_job_id
              ) {
                finish(true)
              }
            } catch {
              finish(false)
            }
          },
          onError: () => finish(false),
        })
        feedbackConnectionRef.current = connection
        if (finished) connection.close()
      })
    },
    [commit, eventSourceFactory, feedbackCatchupTimeoutMs],
  )

  const catchUpMemoryEvents = useCallback(
    (generation: number, timeoutMs = 150): Promise<void> => {
      const current = stateRef.current
      if (!current.taskId || !current.runId || !current.eventsUrl) {
        return Promise.resolve()
      }
      const expectedTaskId = current.taskId
      const expectedRunId = current.runId
      const url = buildEventStreamUrl(
        current.eventsUrl,
        current.lastPersistentEventSeq,
        current.endOffset,
      )
      return new Promise<void>((resolve) => {
        let finished = false
        let connection: EventStreamConnection | null = null
        const finish = () => {
          if (finished) return
          finished = true
          clearTimeout(timeout)
          connection?.close()
          resolve()
        }
        const timeout = setTimeout(finish, timeoutMs)
        connection = eventSourceFactory(url, {
          onOpen: () => undefined,
          onEvent: (eventType, rawData, lastEventId) => {
            if (generation !== generationRef.current) {
              finish()
              return
            }
            try {
              const event = parseSseEvent(eventType, rawData, lastEventId)
              if (
                event.task_id === expectedTaskId &&
                event.run_id === expectedRunId
              ) {
                commit({ type: 'sse_event', event })
              }
            } catch {
              finish()
            }
          },
          onError: finish,
        })
        if (finished) connection.close()
      })
    },
    [commit, eventSourceFactory],
  )

  const loadCandidateDetails = useCallback(
    async (
      candidateIds: readonly MemoryId[],
      generation: number,
      controller: AbortController,
    ): Promise<void> => {
      if (!api.getMemory) return
      for (const memoryId of candidateIds) {
        const detail = await api.getMemory(memoryId, controller.signal)
        if (generation !== generationRef.current) return
        commit({ type: 'memory_detail_received', detail })
      }
    },
    [api, commit],
  )

  const monitorMemoryJob = useCallback(
    async (
      memoryJobId: MemoryJobId,
      generation: number,
      accepted: FeedbackCreateAccepted,
    ) => {
      if (!api.getMemoryJob) return
      const monitorEpoch = memoryMonitorEpochRef.current + 1
      memoryMonitorEpochRef.current = monitorEpoch
      const deadline = Date.now() + memoryMonitorTimeoutMs
      const delays = [250, 500, 1000] as const
      let delayIndex = 0
      let previousSignature = ''
      setFeedbackState((current) =>
        current.accepted?.memory_job_id === memoryJobId
          ? { ...current, monitor: 'monitoring', error: null }
          : {
              ...INITIAL_FEEDBACK_STATE,
              phase: 'recorded',
              accepted,
              monitor: 'monitoring',
            },
      )

      while (
        generation === generationRef.current &&
        monitorEpoch === memoryMonitorEpochRef.current
      ) {
        const controller = new AbortController()
        controllersRef.current.add(controller)
        try {
          const job = await api.getMemoryJob(memoryJobId, controller.signal)
          if (
            generation !== generationRef.current ||
            monitorEpoch !== memoryMonitorEpochRef.current
          ) {
            return
          }
          commit({ type: 'memory_job_received', job })
          setFeedbackState((current) => ({
            ...current,
            phase: 'recorded',
            accepted,
            job,
            monitor:
              job.status === 'completed'
                ? 'completed'
                : job.status === 'failed'
                  ? 'failed'
                  : 'monitoring',
            error:
              job.status === 'failed'
                ? {
                    code: job.error_code ?? 'MEMORY_JOB_FAILED',
                    message: '记忆候选处理失败。',
                    retryable: job.retryable,
                  }
                : null,
          }))

          const signature = `${job.status}:${job.stage}:${job.attempt}:${job.candidate_ids.join(',')}`
          if (signature !== previousSignature) {
            previousSignature = signature
            await catchUpMemoryEvents(generation)
          }
          if (job.status === 'completed') {
            await loadCandidateDetails(job.candidate_ids, generation, controller)
            return
          }
          if (job.status === 'failed') return
        } catch (error) {
          if (
            isAbortError(error) ||
            generation !== generationRef.current ||
            monitorEpoch !== memoryMonitorEpochRef.current
          ) {
            return
          }
          if (Date.now() >= deadline) {
            setFeedbackState((current) => ({
              ...current,
              monitor: 'still_processing',
              error: null,
            }))
            return
          }
        } finally {
          controllersRef.current.delete(controller)
        }

        if (Date.now() >= deadline) {
          setFeedbackState((current) => ({
            ...current,
            monitor: 'still_processing',
            error: null,
          }))
          return
        }
        await sleep(delays[Math.min(delayIndex, delays.length - 1)] ?? 1000)
        delayIndex += 1
      }
    },
    [
      api,
      catchUpMemoryEvents,
      commit,
      loadCandidateDetails,
      memoryMonitorTimeoutMs,
      sleep,
    ],
  )

  useEffect(() => {
    monitorMemoryJobRef.current = monitorMemoryJob
  }, [monitorMemoryJob])

  const submitFeedback = useCallback(
    async (
      feedback: FeedbackCreateRequest,
    ): Promise<FeedbackCreateAccepted | null> => {
      const generation = generationRef.current
      const current = stateRef.current
      if (!current.taskId || !current.terminal || current.runStatus !== 'succeeded') {
        setFeedbackState({
          ...INITIAL_FEEDBACK_STATE,
          phase: 'failed',
          error: {
            code: 'TASK_NOT_READY_FOR_FEEDBACK',
            message: '任务尚未成功完成，无法提交反馈。',
            retryable: false,
          },
        })
        return null
      }
      if (!api.createFeedback) {
        setFeedbackState({
          ...INITIAL_FEEDBACK_STATE,
          phase: 'failed',
          error: {
            code: 'CLIENT_API_UNAVAILABLE',
            message: '当前客户端未配置反馈接口。',
            retryable: false,
          },
        })
        return null
      }

      const requestJson = `${current.taskId}:${JSON.stringify(feedback)}`
      if (pendingFeedbackWriteRef.current?.requestJson !== requestJson) {
        pendingFeedbackWriteRef.current = {
          requestJson,
          key: idempotencyKeyFactory(),
        }
      }
      const idempotencyKey = pendingFeedbackWriteRef.current.key
      setFeedbackState({ ...INITIAL_FEEDBACK_STATE, phase: 'submitting' })
      const controller = new AbortController()
      controllersRef.current.add(controller)
      try {
        const accepted = await api.createFeedback(
          current.taskId,
          feedback,
          idempotencyKey,
          controller.signal,
        )
        if (generation !== generationRef.current) return null
        pendingFeedbackWriteRef.current = null

        const caughtByEvent = await catchUpFeedback(accepted, generation)
        if (generation !== generationRef.current) return null
        let catchup: FeedbackSubmissionState['catchup'] = caughtByEvent
          ? 'event'
          : 'unconfirmed'
        if (!caughtByEvent) {
          try {
            const snapshot = await getSnapshot(current.taskId, generation)
            if (snapshot && generation === generationRef.current) {
              commit({ type: 'snapshot_received', snapshot, mode: 'final' })
              if (
                snapshot.feedback_events.some(
                  (item) => item.feedback_id === accepted.feedback_id,
                )
              ) {
                catchup = 'snapshot'
              }
            }
          } catch (error) {
            if (isAbortError(error) || generation !== generationRef.current) return null
          }
        }

        setFeedbackState({
          phase: 'recorded',
          accepted,
          job: null,
          catchup,
          monitor: 'monitoring',
          error: null,
        })
        void monitorMemoryJobRef.current(
          accepted.memory_job_id,
          generation,
          accepted,
        )
        return accepted
      } catch (error) {
        if (isAbortError(error) || generation !== generationRef.current) return null
        setFeedbackState({
          ...INITIAL_FEEDBACK_STATE,
          phase: 'failed',
          error: toPublicError(error),
        })
        return null
      } finally {
        controllersRef.current.delete(controller)
      }
    },
    [api, catchUpFeedback, commit, getSnapshot, idempotencyKeyFactory],
  )

  const retryMemoryJob = useCallback(
    async (memoryJobId: MemoryJobId): Promise<MemoryJobResponse | null> => {
      if (!api.retryMemoryJob) return null
      const generation = generationRef.current
      const currentFeedback = feedbackState.accepted
      const requestJson = `retry:${memoryJobId}`
      let pending = pendingRetryWriteRef.current.get(memoryJobId)
      if (!pending || pending.requestJson !== requestJson) {
        pending = { requestJson, key: idempotencyKeyFactory() }
        pendingRetryWriteRef.current.set(memoryJobId, pending)
      }
      const controller = new AbortController()
      controllersRef.current.add(controller)
      setFeedbackState((current) => ({
        ...current,
        monitor: 'monitoring',
        error: null,
      }))
      try {
        const job = await api.retryMemoryJob(
          memoryJobId,
          pending.key,
          controller.signal,
        )
        if (generation !== generationRef.current) return null
        pendingRetryWriteRef.current.delete(memoryJobId)
        commit({ type: 'memory_job_received', job })
        const accepted: FeedbackCreateAccepted = currentFeedback ?? {
          request_id: job.request_id,
          feedback_id: job.feedback_id,
          memory_job_id: job.memory_job_id,
          feedback_type:
            stateRef.current.feedbackEvents.find(
              (item) => item.feedback_id === job.feedback_id,
            )?.feedback_type ?? 'explicit_text',
          job_status: 'pending',
        }
        setFeedbackState((current) => ({
          ...current,
          phase: 'recorded',
          accepted,
          job,
          monitor: 'monitoring',
          error: null,
        }))
        void monitorMemoryJobRef.current(memoryJobId, generation, accepted)
        return job
      } catch (error) {
        if (isAbortError(error) || generation !== generationRef.current) return null
        setFeedbackState((current) => ({
          ...current,
          monitor: 'failed',
          error: toPublicError(error),
        }))
        return null
      } finally {
        controllersRef.current.delete(controller)
      }
    },
    [api, commit, feedbackState.accepted, idempotencyKeyFactory],
  )

  const resolveCandidate = useCallback(
    async (
      memoryId: MemoryId,
      request: ResolveRequest,
    ): Promise<ResolveResponse | null> => {
      if (!api.resolveMemoryCandidate) return null
      const generation = generationRef.current
      const normalizedRequest: ResolveRequest = {
        action: request.action,
        patch: request.patch ?? null,
      }
      const requestJson = JSON.stringify(normalizedRequest)
      let pending = pendingResolveWriteRef.current.get(memoryId)
      if (!pending || pending.requestJson !== requestJson) {
        pending = { requestJson, key: idempotencyKeyFactory() }
        pendingResolveWriteRef.current.set(memoryId, pending)
      }
      commit({ type: 'memory_resolve_started', memoryId })
      const controller = new AbortController()
      controllersRef.current.add(controller)
      try {
        const resolved = await api.resolveMemoryCandidate(
          memoryId,
          normalizedRequest,
          pending.key,
          controller.signal,
        )
        if (generation !== generationRef.current) return null
        pendingResolveWriteRef.current.delete(memoryId)
        let detail: MemoryDetailResponse
        if (api.getMemory) {
          detail = await api.getMemory(memoryId, controller.signal)
        } else {
          const current = stateRef.current.memoryDetails[memoryId]
          detail = {
            request_id: resolved.request_id,
            card: resolved.card,
            evidence: current?.evidence ?? [],
            versions: current?.versions ?? [],
          }
        }
        if (generation !== generationRef.current) return null
        commit({ type: 'memory_resolved', detail, resolution: resolved })
        await catchUpMemoryEvents(generation)
        return resolved
      } catch (error) {
        if (isAbortError(error) || generation !== generationRef.current) return null
        commit({
          type: 'memory_resolve_failed',
          memoryId,
          error: toPublicError(error),
        })
        return null
      } finally {
        controllersRef.current.delete(controller)
      }
    },
    [api, catchUpMemoryEvents, commit, idempotencyKeyFactory],
  )

  const toggleEvidence = useCallback(
    (memoryId: MemoryId) => {
      commit({ type: 'memory_evidence_toggled', memoryId })
    },
    [commit],
  )

  const resumeMemoryJobMonitor = useCallback(() => {
    const accepted = feedbackState.accepted
    if (!accepted) return
    void monitorMemoryJobRef.current(
      accepted.memory_job_id,
      generationRef.current,
      accepted,
    )
  }, [feedbackState.accepted])

  const retryConnection = useCallback(() => {
    const current = stateRef.current
    if (!current.taskId || current.terminal) return
    if (current.runStatus === 'succeeded' || current.runStatus === 'failed') {
      void finalizeRef.current(generationRef.current)
      return
    }
    void recoverRef.current(generationRef.current, current.recoveryReason, true)
  }, [])

  useEffect(
    () => () => {
      generationRef.current += 1
      stopSession()
    },
    [stopSession],
  )

  return {
    state,
    feedbackState,
    submitTask,
    restoreTask,
    resetOwner,
    submitFeedback,
    retryMemoryJob,
    resolveCandidate,
    toggleEvidence,
    resumeMemoryJobMonitor,
    retryConnection,
  }
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

function toPublicError(error: unknown): PublicUiError {
  if (error instanceof G0ApiError) {
    return {
      code: error.code,
      message: error.message,
      retryable: error.retryable,
    }
  }
  return {
    code: 'UNKNOWN_CLIENT_ERROR',
    message: '提交任务时发生未知错误，请稍后重试。',
    retryable: true,
  }
}
