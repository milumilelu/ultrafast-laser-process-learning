/** CFAMatrix (9.1): 论文/证据 × 五 facet 的适用性矩阵。
 *  状态只可能是 KNOWN/PARTIAL/UNKNOWN/MISMATCH，从不出现概率。 */

import { CFA_FACETS, scientificLabel, scientificTone, type StatusTone } from '../../lib/status'
import { StatusBadge } from '../StatusBadge'

export interface CFAFacetCell {
  facet: string
  status: string
  details?: Record<string, unknown>
}

export interface CFARow {
  rowId: string
  label: string
  cells: Record<string, CFAFacetCell>
}

export function CFAMatrix({
  rows,
  onCellClick,
}: {
  rows: CFARow[]
  onCellClick?: (rowId: string, facet: string) => void
}) {
  if (rows.length === 0) {
    return <div className="empty-state">无 CFA 审计行（需文献侧 canonical state 输入）。</div>
  }
  return (
    <table className="table" data-testid="cfa-matrix">
      <thead>
        <tr>
          <th>证据</th>
          {CFA_FACETS.map((facet) => (
            <th key={facet}>{facet}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.rowId}>
            <td className="mono">{row.label}</td>
            {CFA_FACETS.map((facet) => {
              const cell = row.cells[facet]
              const status = cell?.status ?? 'UNKNOWN'
              return (
                <td key={facet}>
                  <button
                    className="cfa-cell"
                    disabled={!onCellClick}
                    onClick={() => onCellClick?.(row.rowId, facet)}
                  >
                    <StatusBadge tone={scientificTone(status) as StatusTone}>
                      {scientificLabel(status)}
                    </StatusBadge>
                  </button>
                </td>
              )
            })}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
