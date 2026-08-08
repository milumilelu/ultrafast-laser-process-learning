/** WorkflowEvent helpers (UI-7): NDJSON parsing, reducer, resume-from-sequence.
 *  Transport-only events (delta / heartbeat / thinking_status) never become
 *  formal scientific activity and are filtered out here. */

import type { WorkflowEvent, WorkflowEventType } from '../api/types'

export const TRANSPORT_EVENT_TYPES = new Set(['delta', 'heartbeat', 'thinking_status', 'done'])

export function normalizeEvent(raw: Record<string, unknown>): WorkflowEvent | null {
  const type = String(raw.type ?? raw.event_type ?? '')
  if (TRANSPORT_EVENT_TYPES.has(type)) return null
  const id = String(raw.event_id ?? '')
  const runId = String(raw.run_id ?? '')
  const sequence = Number(raw.sequence ?? 0)
  if (!id || !type || !runId) return null
  return {
    event_id: id,
    eventId: id,
    run_id: runId,
    runId,
    sequence: Number.isFinite(sequence) ? sequence : 0,
    timestamp: String(raw.timestamp ?? new Date().toISOString()),
    type: type as WorkflowEventType,
    stage: raw.stage != null ? String(raw.stage) : null,
    summary: String(raw.summary ?? ''),
    progress:
      raw.progress && typeof raw.progress === 'object'
        ? (raw.progress as { current?: number; total?: number })
        : null,
    entityRefs: Array.isArray(raw.entityRefs) ? (raw.entityRefs as { type: string; id: string }[]) : [],
    artifactRefs: Array.isArray(raw.artifactRefs)
      ? (raw.artifactRefs as { type: string; id: string }[])
      : [],
    details: raw.details && typeof raw.details === 'object' ? (raw.details as Record<string, unknown>) : {},
  }
}

/** Parse an NDJSON body into formal workflow events (skips transport events). */
export function parseEventLines(body: string): WorkflowEvent[] {
  const events: WorkflowEvent[] = []
  for (const line of body.split('\n')) {
    const trimmed = line.trim()
    if (!trimmed) continue
    try {
      const event = normalizeEvent(JSON.parse(trimmed) as Record<string, unknown>)
      if (event) events.push(event)
    } catch {
      /* malformed line skipped */
    }
  }
  return events
}

/** Append events to the reducer state, preserving sequence order and
 *  deduplicating by event_id. */
export function workflowReducer(
  events: WorkflowEvent[],
  incoming: WorkflowEvent[],
): WorkflowEvent[] {
  if (incoming.length === 0) return events
  const seen = new Set(events.map((event) => event.event_id))
  const merged = [...events]
  for (const event of incoming) {
    if (seen.has(event.event_id)) continue
    seen.add(event.event_id)
    merged.push(event)
  }
  merged.sort((a, b) => a.sequence - b.sequence)
  return merged
}

export function lastSequence(events: WorkflowEvent[]): number {
  return events.reduce((max, event) => Math.max(max, event.sequence), 0)
}

export interface ActivityEntry {
  event: WorkflowEvent
  label: string
  tone: 'ok' | 'warn' | 'err' | 'neutral' | 'info'
}

export function activityEntry(event: WorkflowEvent): ActivityEntry {
  switch (event.type) {
    case 'ERROR':
    case 'RUN_FAILED':
      return { event, label: event.summary, tone: 'err' }
    case 'WARNING':
      return { event, label: event.summary, tone: 'warn' }
    case 'VALIDATION':
      return { event, label: event.summary, tone: 'info' }
    case 'RUN_STARTED':
    case 'RUN_COMPLETED':
      return { event, label: event.summary, tone: 'ok' }
    default:
      return { event, label: event.summary, tone: 'neutral' }
  }
}
