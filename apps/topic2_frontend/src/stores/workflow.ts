/** workflowStore (UI-7): execution state only - no scientific payload copies.
 *  Events arrive via NDJSON streaming or resumed polling; the workflow is
 *  never re-executed after a broken stream (resume from lastSequence). */

import { create } from 'zustand'

import type { WorkflowEvent } from '../api/types'
import { workflowReducer, lastSequence } from '../lib/workflow'

export type WorkflowStatus = 'idle' | 'running' | 'completed' | 'failed'

interface WorkflowStore {
  activeRunId: string | null
  status: WorkflowStatus
  currentStage: string | null
  events: WorkflowEvent[]
  lastSequence: number
  error: string | null
  start: (runId: string) => void
  resume: () => void
  append: (incoming: WorkflowEvent[]) => void
  stageChanged: (stage: string | null) => void
  complete: () => void
  fail: (error: string) => void
  clear: () => void
}

export const useWorkflowStore = create<WorkflowStore>()((set, get) => ({
  activeRunId: null,
  status: 'idle',
  currentStage: null,
  events: [],
  lastSequence: 0,
  error: null,
  start: (runId) =>
    set({
      activeRunId: runId,
      status: 'running',
      currentStage: null,
      events: [],
      lastSequence: 0,
      error: null,
    }),
  resume: () => set({ status: 'running', error: null }),
  append: (incoming) => {
    if (incoming.length === 0) return
    const merged = workflowReducer(get().events, incoming)
    set({
      events: merged,
      lastSequence: lastSequence(merged),
      error: null,
    })
    const latest = merged[merged.length - 1]
    if (latest?.stage && latest.type !== 'STAGE_COMPLETED') {
      set({ currentStage: latest.stage })
    }
  },
  stageChanged: (stage) => set({ currentStage: stage }),
  complete: () => set({ status: 'completed' }),
  fail: (error) => set({ status: 'failed', error }),
  clear: () =>
    set({ activeRunId: null, status: 'idle', currentStage: null, events: [], lastSequence: 0, error: null }),
}))

export function selectWorkflowStatus(events: WorkflowEvent[]): WorkflowStatus {
  const types = events.map((event) => event.type)
  if (types.includes('RUN_FAILED')) return 'failed'
  if (types.includes('RUN_COMPLETED')) return 'completed'
  if (types.includes('RUN_STARTED')) return 'running'
  return 'idle'
}
