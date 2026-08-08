/** ActivityTimeline (UI-7): formal WorkflowEvent 执行流，仅展示正式科学事件。
 *  delta / heartbeat / thinking_status 等 transport 事件永不进入时间线。 */

import type { WorkflowEvent } from '../../api/types'
import { activityEntry } from '../../lib/workflow'
import { formatTimestamp } from '../../lib/format'
import { useWorkflowStore } from '../../stores/workflow'

const EVENT_TONE_CLASS: Record<string, string> = {
  ok: 'act-ok',
  warn: 'act-warn',
  err: 'act-err',
  info: 'act-info',
  neutral: 'act-neutral',
}

export function ActivityTimeline() {
  const events = useWorkflowStore((state) => state.events)
  const status = useWorkflowStore((state) => state.status)
  const currentStage = useWorkflowStore((state) => state.currentStage)

  if (events.length === 0) {
    return (
      <div className="empty-state">
        {status === 'running'
          ? '正在等待工作流事件…'
          : '暂无执行流。运行完整分析后将在此展示阶段事件。'}
      </div>
    )
  }

  return (
    <div className="activity-timeline" data-testid="activity-timeline">
      {currentStage && status === 'running' && (
        <div className="act-current">
          <span className="spinner" /> 当前阶段：{currentStage}
        </div>
      )}
      {events.map((event: WorkflowEvent) => {
        const entry = activityEntry(event)
        return (
          <div
            key={event.event_id}
            className={`act-item ${EVENT_TONE_CLASS[entry.tone] ?? 'act-neutral'}`}
          >
            <span className="act-time mono">{formatTimestamp(event.timestamp).slice(11)}</span>
            <span className="act-stage mono">{event.stage ?? ''}</span>
            <span className="act-summary">{entry.label}</span>
            {event.artifactRefs && event.artifactRefs.length > 0 && (
              <span className="act-refs">
                {event.artifactRefs.map((ref) => (
                  <span className="id-chip muted" key={ref.id}>
                    {ref.type}
                  </span>
                ))}
              </span>
            )}
          </div>
        )
      })}
    </div>
  )
}
