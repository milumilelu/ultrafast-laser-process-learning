/** OptimizationComparison (14.3): Vanilla vs Evidence-assisted 并列对照。
 *  数据来自后端 compare 结果，前端不自行拼接。 */

import type { BOResult, OptimizationComparison } from '../../api/types'
import { parameterLabel } from '../../lib/canonical'
import { formatNumber } from '../../lib/format'
import { RecommendationCard } from './RecommendationCard'

export function OptimizationComparison({
  comparison,
}: {
  comparison: OptimizationComparison
}) {
  const vanilla: BOResult = comparison.vanilla
  const assisted: BOResult = comparison.evidence_assisted
  const prior = comparison.prior_applied_evidence
  const parameters = Object.keys(vanilla.recommended_parameters ?? {})

  return (
    <div className="optimization-comparison" data-testid="optimization-comparison">
      <div className="grid grid-2">
        <RecommendationCard result={vanilla} title="Vanilla BO" />
        <RecommendationCard result={assisted} title="Evidence-assisted BO" isAssisted />
      </div>

      <div className="card">
        <div className="card-title">推荐对照</div>
        <table className="table">
          <thead>
            <tr>
              <th>工艺参数</th>
              <th>Vanilla</th>
              <th>Assisted</th>
              <th>是否相同</th>
            </tr>
          </thead>
          <tbody>
            {parameters.map((name) => {
              const v = vanilla.recommended_parameters?.[name]
              const a = assisted.recommended_parameters?.[name]
              const same = v === a
              return (
                <tr key={name}>
                  <td>{parameterLabel(name)}</td>
                  <td className="mono">{formatNumber(v)}</td>
                  <td className="mono">{formatNumber(a)}</td>
                  <td>{same ? <span className="badge ok">相同</span> : <span className="badge warn">不同</span>}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
        <div className="row" style={{ marginTop: 12 }}>
          <span className="badge neutral">
            vanilla_search_prior_applied = {String(prior.vanilla_search_prior_applied)}
          </span>
          <span className="badge neutral">
            assisted_search_prior_applied = {String(prior.assisted_search_prior_applied)}
          </span>
          {prior.assisted_prior_guidance && (
            <span className="badge info">prior_guidance: {prior.assisted_prior_guidance}</span>
          )}
        </div>
      </div>
    </div>
  )
}
