/** workflowStore / WorkflowEvent reducer 测试（UI-7 §38.1）。 */

import { describe, expect, it } from 'vitest'

import {
  lastSequence,
  normalizeEvent,
  parseEventLines,
  workflowReducer,
} from '../workflow'
import { useWorkflowStore } from '../../stores/workflow'

describe('WorkflowEvent normalization', () => {
  it('filters transport-only events (delta/heartbeat/thinking_status)', () => {
    expect(normalizeEvent({ type: 'delta', content: 'x' })).toBeNull()
    expect(normalizeEvent({ type: 'heartbeat' })).toBeNull()
    expect(normalizeEvent({ type: 'thinking_status' })).toBeNull()
    expect(normalizeEvent({ type: 'done' })).toBeNull()
  })

  it('normalizes a formal event', () => {
    const event = normalizeEvent({
      event_id: 'e1',
      run_id: 'app-1',
      sequence: 3,
      timestamp: '2026-08-08T00:00:00Z',
      type: 'STAGE_COMPLETED',
      stage: 'process_learning',
      summary: '完成',
      artifactRefs: [{ type: 'ModelTrainingResult', id: 'M-1' }],
    })
    expect(event).not.toBeNull()
    expect(event?.event_id).toBe('e1')
    expect(event?.sequence).toBe(3)
    expect(event?.artifactRefs?.[0].id).toBe('M-1')
  })

  it('drops malformed lines in NDJSON parsing', () => {
    const events = parseEventLines(
      'not-json\n' +
        JSON.stringify({
          event_id: 'e2',
          run_id: 'app-1',
          sequence: 1,
          type: 'RUN_STARTED',
          summary: 'start',
        }),
    )
    expect(events).toHaveLength(1)
    expect(events[0].event_id).toBe('e2')
  })
})

describe('workflowReducer', () => {
  const make = (id: string, sequence: number) => ({
    event_id: id,
    run_id: 'app-1',
    sequence,
    timestamp: '2026-08-08T00:00:00Z',
    type: 'STAGE_STARTED' as const,
    stage: 'x',
    summary: id,
    entityRefs: [],
    artifactRefs: [],
    details: {},
  })

  it('merges and orders by sequence', () => {
    const merged = workflowReducer([make('a', 1), make('b', 3)], [make('c', 2)])
    expect(merged.map((event) => event.sequence)).toEqual([1, 2, 3])
  })

  it('deduplicates by event_id', () => {
    const merged = workflowReducer([make('a', 1)], [make('a', 1), make('b', 2)])
    expect(merged).toHaveLength(2)
  })

  it('lastSequence resumes streaming from the last event', () => {
    const events = [make('a', 1), make('b', 4)]
    expect(lastSequence(events)).toBe(4)
    expect(lastSequence([])).toBe(0)
  })
})

describe('workflowStore', () => {
  it('start resets state and sets running', () => {
    const store = useWorkflowStore.getState()
    store.append([
      {
        event_id: 'e1',
        run_id: 'app-1',
        sequence: 1,
        timestamp: '2026-08-08T00:00:00Z',
        type: 'RUN_STARTED',
        stage: 'application',
        summary: 'start',
        entityRefs: [],
        artifactRefs: [],
        details: {},
      },
    ])
    expect(useWorkflowStore.getState().lastSequence).toBe(1)
    store.start('app-2')
    const state = useWorkflowStore.getState()
    expect(state.activeRunId).toBe('app-2')
    expect(state.status).toBe('running')
    expect(state.events).toHaveLength(0)
    expect(state.lastSequence).toBe(0)
  })

  it('complete and fail update status', () => {
    useWorkflowStore.getState().start('app-3')
    useWorkflowStore.getState().complete()
    expect(useWorkflowStore.getState().status).toBe('completed')
    useWorkflowStore.getState().start('app-4')
    useWorkflowStore.getState().fail('boom')
    expect(useWorkflowStore.getState().status).toBe('failed')
    expect(useWorkflowStore.getState().error).toBe('boom')
  })

  it('resume keeps the same run and its persisted event cursor', () => {
    useWorkflowStore.getState().start('app-resume')
    useWorkflowStore.getState().append([
      {
        event_id: 'resume-1',
        run_id: 'app-resume',
        sequence: 7,
        timestamp: '2026-08-08T00:00:00Z',
        type: 'STAGE_COMPLETED',
        stage: 'assess_capability',
        summary: 'capability complete',
      },
    ])
    useWorkflowStore.getState().complete()
    useWorkflowStore.getState().resume()
    const state = useWorkflowStore.getState()
    expect(state.activeRunId).toBe('app-resume')
    expect(state.status).toBe('running')
    expect(state.lastSequence).toBe(7)
    expect(state.events).toHaveLength(1)
  })
})
