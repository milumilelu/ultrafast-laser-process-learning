/** ParameterImportanceChart (12.3): 可控参数重要性水平条图（纯 CSS，无重依赖）。 */

import type { ParameterImportance } from '../../api/types'
import { effectClass, effectLabel, formatNumber } from '../../lib/format'
import { parameterLabel } from '../../lib/canonical'

export function ParameterImportanceChart({
  items,
  title,
}: {
  items: ParameterImportance[]
  title: string
}) {
  if (!items || items.length === 0) return null
  const max = Math.max(...items.map((item) => item.importance), 1e-9)

  return (
    <div className="importance-chart" data-testid="importance-chart">
      <div className="card-sub">{title}</div>
      {items.map((item) => (
        <div key={item.feature} className="importance-row">
          <span className="importance-name">{parameterLabel(item.feature)}</span>
          <span className="importance-bar-track">
            <span
              className="importance-bar"
              style={{ width: `${(item.importance / max) * 100}%` }}
            />
          </span>
          <span className="importance-value mono">
            {formatNumber(item.importance, 4)}
          </span>
          <span className={effectClass(item.effect_direction)}>
            {effectLabel(item.effect_direction)}
          </span>
          <span className="importance-rank mono">#{item.rank}</span>
        </div>
      ))}
    </div>
  )
}
