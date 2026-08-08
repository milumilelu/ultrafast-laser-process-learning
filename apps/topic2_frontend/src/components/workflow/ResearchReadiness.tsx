/** ResearchReadinessMatrix (6.3): 各层就绪状态。状态来自正式结果，前端不判定依赖。 */

import { scientificLabel, scientificTone, type StatusTone } from '../../lib/status'
import { StatusBadge } from '../StatusBadge'

export interface ReadinessRow {
  layer: string
  status: string
  summary: string
}

export function ResearchReadiness({ rows }: { rows: ReadinessRow[] }) {
  return (
    <table className="table" data-testid="readiness-matrix">
      <thead>
        <tr>
          <th>层</th>
          <th>状态</th>
          <th>摘要</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.layer}>
            <td>{row.layer}</td>
            <td>
              <StatusBadge tone={scientificTone(row.status) as StatusTone}>
                {scientificLabel(row.status)}
              </StatusBadge>
            </td>
            <td className="muted">{row.summary}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
