/** PhysicsReadinessMatrix (7.3/12.5): 物理坐标就绪矩阵。
 *  状态与依赖全部来自后端 TargetPhysicsReadinessReport / CanonicalInteractionState，
 *  前端禁止自行判定 dependency。Unknown/Blocked 渲染为灰色，绝不渲染为红色。 */

import type { PhysicsCoordinateStatus } from '../../api/types'
import { scientificLabel, scientificTone, type StatusTone } from '../../lib/status'
import { StatusBadge } from '../StatusBadge'

export function PhysicsReadinessMatrix({
  coordinates,
}: {
  coordinates: PhysicsCoordinateStatus[]
}) {
  if (!coordinates || coordinates.length === 0) {
    return <div className="empty-state">无物理坐标就绪数据（状态来自后端报告）。</div>
  }
  return (
    <table className="table" data-testid="physics-readiness-matrix">
      <thead>
        <tr>
          <th>坐标</th>
          <th>状态</th>
          <th>依赖</th>
          <th>原因</th>
        </tr>
      </thead>
      <tbody>
        {coordinates.map((coord) => (
          <tr key={coord.coordinate}>
            <td className="mono">{coord.coordinate}</td>
            <td>
              <StatusBadge tone={scientificTone(coord.status) as StatusTone}>
                {scientificLabel(coord.status)}
              </StatusBadge>
            </td>
            <td className="mono">
              {(coord.dependencies ?? []).join(', ') || '—'}
            </td>
            <td className="muted">{coord.reason ?? '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
