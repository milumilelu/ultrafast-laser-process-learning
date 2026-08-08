/** PriorInfluencePanel (14.4): Base UCB / Evidence Prior Term / Final Acquisition。 */

import type { BOResult } from '../../api/types'
import { formatNumber } from '../../lib/format'

export function PriorInfluencePanel({
  result,
}: {
  result: BOResult
}) {
  const acquisition = (result.acquisition ?? {}) as Record<string, unknown>
  const normalizedUcb = acquisition.normalized_ucb as number | undefined
  const logPrior = acquisition.log_prior as number | undefined
  const score = acquisition.score as number | undefined

  return (
    <div className="card" data-testid="prior-influence-panel">
      <div className="card-title">先验影响（Backend 输出）</div>
      <ul className="detail-list">
        <li>
          <span className="dl-key">Base UCB（normalized）</span>
          <span className="dl-value mono">{formatNumber(normalizedUcb, 6)}</span>
        </li>
        <li>
          <span className="dl-key">Evidence Prior Term（log prior）</span>
          <span className="dl-value mono">{formatNumber(logPrior, 6)}</span>
        </li>
        <li>
          <span className="dl-key">Final Acquisition Score</span>
          <span className="dl-value mono">{formatNumber(score, 6)}</span>
        </li>
      </ul>
      <div className="card-sub" style={{ marginTop: 8 }}>
        {typeof acquisition.lambda_t === 'number' && (
          <span>证据权重 λ(t) = {formatNumber(acquisition.lambda_t, 3)}（随独立设计数衰减）</span>
        )}
        {result.search_prior_applied === false && (
          <div className="warn-banner" style={{ marginTop: 8 }}>
            当前推荐未应用搜索先验（无 GovernedPriorArtifact 或与 Vanilla 一致）。
          </div>
        )}
      </div>
    </div>
  )
}
