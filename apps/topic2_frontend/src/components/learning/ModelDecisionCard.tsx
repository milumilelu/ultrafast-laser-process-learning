/** ModelDecisionCard (13.2): 推荐模型 + 理由。理由来自后端训练比较。 */

import type { ModelMetrics } from '../../api/types'
import { formatNumber } from '../../lib/format'
import { StatusBadge } from '../StatusBadge'

export function ModelDecisionCard({
  selectedModel,
  metrics,
  cvFolds,
  cvStrategy,
}: {
  selectedModel: string
  metrics?: ModelMetrics | null
  cvFolds?: number
  cvStrategy?: string | null
}) {
  return (
    <div className="card" data-testid="model-decision-card">
      <div className="card-title">推荐模型</div>
      <div className="row">
        <div className="stat-card" style={{ flex: 1 }}>
          <div className="stat-value">{selectedModel}</div>
          <div className="stat-label">系统推荐（Group-CV）</div>
        </div>
        <div className="stat-card" style={{ flex: 1 }}>
          <div className="stat-value">{formatNumber(metrics?.RMSE)}</div>
          <div className="stat-label">RMSE</div>
        </div>
        <div className="stat-card" style={{ flex: 1 }}>
          <div className="stat-value">{formatNumber(metrics?.MAE)}</div>
          <div className="stat-label">MAE</div>
        </div>
        <div className="stat-card" style={{ flex: 1 }}>
          <div className="stat-value">{metrics?.uncertainty_available ? '✓' : '—'}</div>
          <div className="stat-label">原生不确定性</div>
        </div>
      </div>
      <div className="row" style={{ marginTop: 8 }}>
        <StatusBadge tone="ok">✓ 最低 Group-CV RMSE</StatusBadge>
        <StatusBadge tone="neutral">
          CV 折数：{cvFolds ?? metrics?.cv_folds ?? '—'}
        </StatusBadge>
        {cvStrategy && <StatusBadge tone="neutral">{cvStrategy}</StatusBadge>}
        {metrics && !metrics.uncertainty_available && (
          <StatusBadge tone="warn">△ 无原生不确定性</StatusBadge>
        )}
      </div>
    </div>
  )
}
