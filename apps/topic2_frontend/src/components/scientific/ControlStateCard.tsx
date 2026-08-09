/** RunControlState card: the backend's authoritative run status (M6).
 *
 * The frontend renders this and never derives workflow state from stages.
 */

import { useMemo } from 'react'
import {
  buildRunControl,
  GATE_LABEL,
  PHASE_LABEL,
  PHASE_LABEL_SHORT,
} from '../../domain/control'
import { Card, EmptyState } from '../ui/Card'
import { StatusBadge } from '../ui/StatusBadge'

export function ControlStateCard({
  control,
}: {
  /** RunControlState lives in the run result (手册 §15), not an artifact. */
  control?: Record<string, unknown> | null
}) {
  const view = useMemo(() => buildRunControl(control), [control])
  if (!control) return null

  const phaseTone =
    view.phaseStatus === 'BLOCKED'
      ? 'warn'
      : view.phaseStatus === 'PARTIAL'
        ? 'warn'
        : view.phaseStatus === 'COMPLETED'
          ? 'ok'
          : 'neutral'

  return (
    <Card
      title="Run Control（后端权威状态）"
      actions={
        <StatusBadge
          tone={phaseTone}
          label={`${PHASE_LABEL[view.phaseStatus]} · ${PHASE_LABEL_SHORT[view.currentPhase] ?? view.currentPhase}`}
        />
      }
    >
      <div className="control-state">
        <div className="control-meta">
          <span className="control-chip">执行模式 {view.executionMode}</span>
          {view.provisional && <span className="control-chip control-chip-warn">PROVISIONAL</span>}
        </div>
        <div className="gates-grid">
          {Object.values(view.gates).map((gate) => (
            <div key={gate.gate} className="gate-cell">
              <div className="gate-head">
                <span className="gate-name">{GATE_LABEL[gate.gate] ?? `Gate ${gate.gate}`}</span>
                <StatusBadge
                  tone={
                    gate.status === 'READY'
                      ? 'ok'
                      : gate.status === 'PARTIAL'
                        ? 'warn'
                        : gate.status === 'BLOCKED'
                          ? 'err'
                          : 'neutral'
                  }
                  label={
                    gate.status === 'READY'
                      ? '就绪'
                      : gate.status === 'PARTIAL'
                        ? '部分'
                        : gate.status === 'BLOCKED'
                          ? '受阻'
                          : '未运行'
                  }
                />
              </div>
              {gate.reasons.length > 0 && (
                <ul className="gate-reasons">
                  {gate.reasons.map((reason, index) => (
                    <li key={index}>{reason}</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
        {view.blockingReasons.length > 0 && (
          <div className="blocking-reasons">
            <div className="blocking-title">阻塞原因</div>
            <ul>
              {view.blockingReasons.map((reason, index) => (
                <li key={index}>{reason}</li>
              ))}
            </ul>
          </div>
        )}
        {view.nextActions.length > 0 && (
          <div className="next-actions">
            <div className="next-actions-title">下一步可执行动作</div>
            <ul>
              {view.nextActions.map((action, index) => (
                <li key={index}>
                  <code>{action.type}</code>
                  {action.missing && action.missing.length > 0 && (
                    <span className="next-actions-missing"> 缺失: {action.missing.join(', ')}</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
        {Object.keys(view.gates).length === 0 && !view.blockingReasons.length && (
          <EmptyState message="运行尚未产生控制状态" hint="运行 prepare_task 后生成 RunControlState。" />
        )}
      </div>
    </Card>
  )
}
