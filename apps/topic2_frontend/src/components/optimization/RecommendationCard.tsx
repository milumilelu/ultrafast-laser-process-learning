/** RecommendationCard (14.2): 推荐下一实验点。文案固定为「推荐下一实验点」，
 *  禁止「最优工艺参数」。 */

import type { BOResult } from '../../api/types'
import { parameterLabel } from '../../lib/canonical'
import { formatNumber } from '../../lib/format'

export function RecommendationCard({
  result,
  title = '推荐下一实验点',
  isAssisted = false,
}: {
  result: BOResult
  title?: string
  isAssisted?: boolean
}) {
  const parameters = Object.keys(result.recommended_parameters ?? {})
  const prediction = result.prediction as { mean?: number; std?: number }
  return (
    <div
      className={`card ${isAssisted ? 'assisted-card' : ''}`}
      data-testid="recommendation-card"
    >
      <div className="card-title">
        {title}
        {isAssisted && <span className="badge info">Evidence-assisted</span>}
        <span className="id-chip muted">{result.run_id ?? result.bo_run_id ?? ''}</span>
      </div>
      <table className="table">
        <thead>
          <tr>
            <th>工艺参数</th>
            <th>推荐值</th>
          </tr>
        </thead>
        <tbody>
          {parameters.map((name) => (
            <tr key={name}>
              <td>{parameterLabel(name)}</td>
              <td className="mono">{formatNumber(result.recommended_parameters[name])}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row" style={{ marginTop: 12 }}>
        <div className="stat-card" style={{ flex: 1 }}>
          <div className="stat-value">{formatNumber(prediction?.mean)}</div>
          <div className="stat-label">预测质量</div>
        </div>
        <div className="stat-card" style={{ flex: 1 }}>
          <div className="stat-value">±{formatNumber(prediction?.std)}</div>
          <div className="stat-label">预测区间（std）</div>
        </div>
        <div className="stat-card" style={{ flex: 1 }}>
          <div className="stat-value">
            {typeof result.acquisition?.score === 'number'
              ? formatNumber(result.acquisition.score, 4)
              : '—'}
          </div>
          <div className="stat-label">Acquisition Score</div>
        </div>
        <div className="stat-card" style={{ flex: 1 }}>
          <div className="stat-value">
            {result.search_prior_applied ? '已应用' : '未应用'}
          </div>
          <div className="stat-label">搜索先验</div>
        </div>
      </div>
    </div>
  )
}
