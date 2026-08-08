/** Task context API (backend snapshot persistence; local drafts are the UI state). */

import { config } from '../config'
import { jsonBody, request } from './client'

export interface TaskContextRecord {
  task_context_id: string
  version: number
  payload: Record<string, unknown>
  updated_at?: string
}

export const tasksApi = {
  saveTaskContext(
    taskContextId: string,
    version: number,
    snapshot: Record<string, unknown>,
  ): Promise<TaskContextRecord> {
    return request(config.topic2ApiUrl, `/task-contexts/${taskContextId}/versions/${version}`, {
      method: 'PUT',
      ...jsonBody(snapshot),
    })
  },

  getTaskContext(taskContextId: string, version?: number): Promise<TaskContextRecord> {
    const suffix = version !== undefined ? `?version=${version}` : ''
    return request(config.topic2ApiUrl, `/task-contexts/${taskContextId}${suffix}`)
  },
}
