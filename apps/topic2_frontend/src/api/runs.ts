/** ApplicationRun API: create / continue / result / events / artifacts.
 *
 * The ApplicationRun is the single source of truth (spec §27).
 */

import { config } from '../config'
import type { ArtifactMeta, ArtifactSnapshot } from '../domain/artifact'
import { buildQuery, jsonBody, request } from './client'

export type RunStatus = 'running' | 'completed' | 'failed'

export interface RunStageStatus {
  status: string
}

export interface ApplicationRunRecord {
  application_run_id: string
  status: RunStatus
  task_context_ref: string
  mode: 'demo' | 'research'
  workflow_version: string
  stage_status: Record<string, RunStageStatus>
  task_spec?: Record<string, unknown> | null
  created_at: string
  completed_at: string | null
  result?: Record<string, unknown> | null
}

export interface ApplicationRunSummary {
  application_run_id: string
  status: RunStatus
  task_context_ref: string
  mode: 'demo' | 'research'
  workflow_version: string
  stage_status: Record<string, RunStageStatus>
  created_at: string
  completed_at: string | null
}

export type WorkflowEventType =
  | 'RUN_STARTED'
  | 'RUN_COMPLETED'
  | 'RUN_FAILED'
  | 'STAGE_STARTED'
  | 'STAGE_PROGRESS'
  | 'STAGE_COMPLETED'
  | 'TOOL_STARTED'
  | 'TOOL_COMPLETED'
  | 'ENTITY_CREATED'
  | 'ARTIFACT_CREATED'
  | 'VALIDATION'
  | 'WARNING'
  | 'ERROR'

export interface WorkflowEvent {
  event_id: string
  run_id: string
  sequence: number
  timestamp: string
  type: WorkflowEventType
  stage: string | null
  summary: string
  progress?: { current?: number; total?: number } | null
  entityRefs: ArtifactRefLite[]
  artifactRefs: ArtifactRefLite[]
  details: Record<string, unknown>
}

export interface ArtifactRefLite {
  type: string
  id: string
}

export interface CreateRunPayload {
  mode?: 'demo' | 'research'
  task_spec?: Record<string, unknown>
  stages?: string[]
  client_request_id?: string
}

export interface ContinueRunPayload {
  stages?: string[]
  client_request_id?: string
}

/** GET /artifacts/{id} returns { artifact_id, artifact_type, content: <stored snapshot> }. */
export interface ArtifactEnvelope<T = Record<string, unknown>> {
  artifact_id: string
  artifact_type: string
  content: ArtifactSnapshot<T>
}

export const runsApi = {
  createRun(payload: CreateRunPayload): Promise<ApplicationRunSummary> {
    return request(config.topic2ApiUrl, '/application-runs', {
      method: 'POST',
      ...jsonBody(payload),
    })
  },

  continueRun(runId: string, payload: ContinueRunPayload): Promise<ApplicationRunSummary> {
    return request(config.topic2ApiUrl, `/application-runs/${runId}/continue`, {
      method: 'POST',
      ...jsonBody(payload),
    })
  },

  getRun(runId: string): Promise<ApplicationRunRecord> {
    return request(config.topic2ApiUrl, `/application-runs/${runId}`)
  },

  listRuns(mode?: 'demo' | 'research'): Promise<{ items: ApplicationRunSummary[] }> {
    return request(config.topic2ApiUrl, `/application-runs${buildQuery({ mode })}`)
  },

  getResult(runId: string): Promise<Record<string, unknown>> {
    return request(config.topic2ApiUrl, `/application-runs/${runId}/result`)
  },

  getEvents(runId: string, afterSequence = 0): Promise<{ items: WorkflowEvent[] }> {
    return request(
      config.topic2ApiUrl,
      `/application-runs/${runId}/events${buildQuery({ after_sequence: afterSequence })}`,
    )
  },

  getArtifacts(runId: string): Promise<{ items: ArtifactMeta[] }> {
    return request(config.topic2ApiUrl, `/application-runs/${runId}/artifacts`)
  },

  getArtifact<T>(artifactId: string): Promise<ArtifactEnvelope<T>> {
    return request(config.topic2ApiUrl, `/artifacts/${artifactId}`)
  },

  replay(runId: string): Promise<Record<string, unknown>> {
    return request(config.topic2ApiUrl, `/application-runs/${runId}/replay`, { method: 'POST' })
  },
}
