import { useCallback, useEffect, useReducer, useRef } from 'react'

import { browserG0Api, G0ApiError, type G0Api } from './api'
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
}

export function useG0Agent({
  api = browserG0Api,
  eventSourceFactory = browserEventSourceFactory,
  retryDelaysMs = DEFAULT_RETRY_DELAYS_MS,
}: UseG0AgentOptions = {}) {
  const [state, reducerDispatch] = useReducer(
    g0Reducer,
    undefined,
    createInitialG0State,
  )
  const stateRef = useRef(state)
  const generationRef = useRef(0)
  const connectionEpochRef = useRef(0)
  const connectionRef = useRef<EventStreamConnection | null>(null)
  const controllersRef = useRef(new Set<AbortController>())
  const timerResolversRef = useRef(
    new Map<ReturnType<typeof setTimeout>, () => void>(),
  )
  const recoveryInFlightRef = useRef<number | null>(null)
  const finalizingInFlightRef = useRef<number | null>(null)

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
    closeConnection()
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
      const controller = new AbortController()
      controllersRef.current.add(controller)
      try {
        const accepted = await api.createTask(request, controller.signal)
        if (generation !== generationRef.current) return
        commit({ type: 'task_accepted', accepted })
        connect(accepted.events_url, 0, 0, generation)
      } catch (error) {
        if (isAbortError(error) || generation !== generationRef.current) return
        commit({ type: 'submit_failed', error: toPublicError(error) })
      } finally {
        controllersRef.current.delete(controller)
      }
    },
    [api, commit, connect, stopSession],
  )

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

  return { state, submitTask, retryConnection }
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
