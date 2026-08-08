/** CFAFacetInspector (9.2/9.3): 点击矩阵单元格后的坐标对照明细。
 *  坐标比较来自后端 CFAReport，前端不自行判定。 */

import { scientificLabel, scientificTone, type StatusTone } from '../../lib/status'
import { StatusBadge } from '../StatusBadge'

export function CFAFacetInspector({
  facet,
  details,
}: {
  facet: string
  details: Record<string, unknown> | null | undefined
}) {
  if (!details) {
    return <div className="empty-state">该单元格无坐标级明细。</div>
  }
  const coordinates = details.coordinates as
    | Record<string, Record<string, unknown>>
    | undefined
  const matches = details.matches as Record<string, string> | undefined
  const reconstructible = details.reconstructible
  const total = details.total

  return (
    <div className="card" data-testid="cfa-facet-inspector">
      <div className="card-title">{facet} 明细</div>
      {coordinates && Object.keys(coordinates).length > 0 ? (
        <table className="table">
          <thead>
            <tr>
              <th>坐标</th>
              <th>Source</th>
              <th>Target</th>
              <th>Comparison</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(coordinates).map(([name, coordinate]) => (
              <tr key={name}>
                <td className="mono">{name}</td>
                <td className="mono">
                  {String(coordinate.source ?? '—')}
                </td>
                <td className="mono">
                  {String(coordinate.target ?? '—')}
                </td>
                <td>
                  <StatusBadge tone={scientificTone(String(coordinate.comparison)) as StatusTone}>
                    {scientificLabel(String(coordinate.comparison))}
                  </StatusBadge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {matches && (
        <ul className="detail-list">
          {Object.entries(matches).map(([dimension, value]) => (
            <li key={dimension}>
              <span className="dl-key">{dimension}</span>
              <span className="dl-value">
                <StatusBadge tone={scientificTone(value) as StatusTone}>
                  {scientificLabel(value)}
                </StatusBadge>
              </span>
            </li>
          ))}
        </ul>
      )}
      {typeof reconstructible === 'number' && (
        <div className="card-sub" style={{ marginTop: 8 }}>
          可重建 {reconstructible} / {typeof total === 'number' ? total : '—'}
        </div>
      )}
    </div>
  )
}
