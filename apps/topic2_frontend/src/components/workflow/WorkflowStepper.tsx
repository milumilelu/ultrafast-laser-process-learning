/** WorkflowStepper (6.2): 项目概览页的阶段可视化。 */

import { Link } from 'react-router-dom'
import type { StatusTone } from '../../lib/status'

export interface StepperStage {
  key: string
  label: string
  state: 'done' | 'pending' | 'current' | 'warn'
  detail?: string | null
  to?: string
}

export function WorkflowStepper({ stages }: { stages: StepperStage[] }) {
  const toneOf = (state: StepperStage['state']): StatusTone => {
    if (state === 'done') return 'ok'
    if (state === 'warn') return 'warn'
    if (state === 'current') return 'info'
    return 'neutral'
  }

  return (
    <div className="workflow-stepper" data-testid="workflow-stepper">
      {stages.map((stage, index) => {
        const content = (
          <div className={`step ${stage.state}`}>
            <span className="step-index">
              {stage.state === 'done' ? '✓' : index + 1}
            </span>
            <span className="step-label">{stage.label}</span>
            {stage.detail && <span className="step-detail">{stage.detail}</span>}
            {stage.state === 'warn' && (
              <span className={`badge ${toneOf('warn')}`}>部分</span>
            )}
          </div>
        )
        return (
          <div key={stage.key} className="step-node">
            {stage.to ? <Link to={stage.to}>{content}</Link> : content}
            {index < stages.length - 1 && <span className="step-arrow">↓</span>}
          </div>
        )
      })}
    </div>
  )
}
