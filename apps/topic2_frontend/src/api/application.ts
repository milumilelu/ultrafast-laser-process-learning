/** Application Run API adapter (BE-1..BE-5 frontend mirror) + ApplicationGateway.
 *
 *  Phase-1 gateway delegates to the existing topic2Api / agentApi; the
 *  applicationApi is the second-phase unified endpoint. Page components never
 *  see the migration.
 */

import { config } from '../config'
import { request } from './client'
import type {
  ApplicationRunSummary,
  OptimizationComparison,
  Topic2ApplicationResult,
  WorkflowEvent,
} from './types'
import { normalizeEvent } from '../lib/workflow'

export interface ApplicationRunRequest {
  mode: 'demo' | 'research'
  task_spec?: Record<string, unknown>
  stages?: string[]
  optimization_modes?: string[]
  random_seed?: number
  client_request_id?: string
}

export const applicationApi = {
  /** POST /api/v1/application-runs (idempotent via client_request_id) */
  createRun(payload: ApplicationRunRequest): Promise<ApplicationRunSummary> {
    return request(config.topic2ApiUrl, 'POST', '/application-runs', payload, {
      timeoutMs: 600_000,
    })
  },

  /** POST /api/v1/application-runs/{run_id}/continue：同一 ApplicationRun 续跑剩余阶段
   *  （checkpoint resume，不重复已执行阶段）。 */
  continueRun(
    runId: string,
    payload: { stages?: string[]; random_seed?: number; client_request_id?: string },
  ): Promise<ApplicationRunSummary> {
    return request(
      config.topic2ApiUrl,
      'POST',
      `/application-runs/${encodeURIComponent(runId)}/continue`,
      payload,
      { timeoutMs: 600_000 },
    )
  },

  listRuns(mode?: string | null): Promise<{ items: ApplicationRunSummary[] }> {
    const query = mode ? `?mode=${encodeURIComponent(mode)}` : ''
    return request(config.topic2ApiUrl, 'GET', `/application-runs${query}`)
  },

  getRun(runId: string): Promise<ApplicationRunSummary & { result: Topic2ApplicationResult | null }> {
    return request(config.topic2ApiUrl, 'GET', `/application-runs/${encodeURIComponent(runId)}`)
  },

  getResult(runId: string): Promise<Topic2ApplicationResult> {
    return request(config.topic2ApiUrl, 'GET', `/application-runs/${encodeURIComponent(runId)}/result`)
  },

  getEvents(runId: string, afterSequence = 0): Promise<{ items: WorkflowEvent[] }> {
    return request(
      config.topic2ApiUrl,
      'GET',
      `/application-runs/${encodeURIComponent(runId)}/events?after_sequence=${afterSequence}`,
    )
  },

  getArtifacts(runId: string): Promise<{ items: { artifact_id: string; artifact_type: string; created_at: string }[] }> {
    return request(config.topic2ApiUrl, 'GET', `/application-runs/${encodeURIComponent(runId)}/artifacts`)
  },

  getArtifact(artifactId: string): Promise<{
    artifact_id: string
    application_run_id: string
    artifact_type: string
    content: Record<string, unknown>
  }> {
    return request(config.topic2ApiUrl, 'GET', `/artifacts/${encodeURIComponent(artifactId)}`)
  },

  replay(runId: string): Promise<{
    replay_run_id: string
    original_run_id: string
    scientific_payload_identical: boolean
    runtime_ids_changed: boolean
    note: string
  }> {
    return request(config.topic2ApiUrl, 'POST', `/application-runs/${encodeURIComponent(runId)}/replay`)
  },

  /** BE-5: Vanilla / Evidence-assisted comparison from the backend. */
  compareOptimization(payload: {
    scope: Record<string, unknown>
    machine_bounds: Record<string, { lower: number; upper: number }>
    governed_prior_artifact?: Record<string, unknown> | null
    model_id?: string | null
    random_seed?: number | null
  }): Promise<OptimizationComparison> {
    return request(config.topic2ApiUrl, 'POST', '/optimization/compare', payload, {
      timeoutMs: 300_000,
    })
  },

  /** NDJSON event streaming with resume-from-sequence semantics.
   *  A broken stream resumes from the last sequence - the workflow is never
   *  re-executed. */
  async streamEvents(
    runId: string,
    afterSequence: number,
    handlers: {
      onEvent: (event: WorkflowEvent) => void
      onDone: () => void
      onError: (error: string) => void
    },
    signal?: AbortSignal,
  ): Promise<void> {
    try {
      const response = await fetch(
        `${config.topic2ApiUrl.replace(/\/+$/, '')}/application-runs/${encodeURIComponent(runId)}/events?after_sequence=${afterSequence}`,
        {
          headers: { Accept: 'application/x-ndjson' },
          signal,
        },
      )
      if (!response.ok) {
        let detail = `HTTP ${response.status}`
        const text = await response.text().catch(() => '')
        if (text) detail = text.slice(0, 300)
        throw new Error(detail)
      }
      const reader = response.body?.getReader()
      if (!reader) throw new Error('stream body unavailable')
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed) continue
          try {
            const event = normalizeEvent(JSON.parse(trimmed) as Record<string, unknown>)
            if (event) handlers.onEvent(event)
          } catch {
            /* malformed line skipped */
          }
        }
      }
      if (buffer.trim()) {
        try {
          const event = normalizeEvent(JSON.parse(buffer.trim()) as Record<string, unknown>)
          if (event) handlers.onEvent(event)
        } catch {
          /* trailing fragment ignored */
        }
      }
      handlers.onDone()
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        handlers.onError('stream aborted')
        return
      }
      handlers.onError(error instanceof Error ? error.message : 'stream failed')
    }
  },
}

/** Phase-1 gateway: page components depend only on this surface.
 *  Internals may migrate from topic2Api/agentApi to applicationApi later. */
export interface ApplicationGateway {
  runFullApplication(payload: ApplicationRunRequest): Promise<ApplicationRunSummary>
  getApplicationResult(runId: string): Promise<Topic2ApplicationResult>
  listRuns(mode?: string | null): Promise<{ items: ApplicationRunSummary[] }>
  getRun(runId: string): Promise<ApplicationRunSummary & { result: Topic2ApplicationResult | null }>
  getEvents(runId: string, afterSequence?: number): Promise<{ items: WorkflowEvent[] }>
  streamEvents(
    runId: string,
    afterSequence: number,
    handlers: { onEvent: (event: WorkflowEvent) => void; onDone: () => void; onError: (error: string) => void },
    signal?: AbortSignal,
  ): Promise<void>
  compareOptimization(payload: {
    scope: Record<string, unknown>
    machine_bounds: Record<string, { lower: number; upper: number }>
    governed_prior_artifact?: Record<string, unknown> | null
    model_id?: string | null
    random_seed?: number | null
  }): Promise<OptimizationComparison>
  getArtifact(artifactId: string): Promise<{
    artifact_id: string
    application_run_id: string
    artifact_type: string
    content: Record<string, unknown>
  }>
}

export const applicationGateway: ApplicationGateway = {
  runFullApplication: (payload) => applicationApi.createRun(payload),
  getApplicationResult: (runId) => applicationApi.getResult(runId),
  listRuns: (mode) => applicationApi.listRuns(mode),
  getRun: (runId) => applicationApi.getRun(runId),
  getEvents: (runId, afterSequence = 0) => applicationApi.getEvents(runId, afterSequence),
  streamEvents: (runId, afterSequence, handlers, signal) =>
    applicationApi.streamEvents(runId, afterSequence, handlers, signal),
  compareOptimization: (payload) => applicationApi.compareOptimization(payload),
  getArtifact: (artifactId) => applicationApi.getArtifact(artifactId),
}
