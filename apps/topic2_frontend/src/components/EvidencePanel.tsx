/** Evidence panel: displays the real compile result / run evidence state.
 *  The frontend never computes applicability — everything is backend output. */

import type { EvidenceCompileResult } from '../api/types'
import { transferClass, transferLabel } from '../lib/format'

function MatchIcon({ value }: { value: boolean | null }) {
  if (value === true) return <span className="badge ok">✓</span>
  if (value === false) return <span className="badge err">✕</span>
  return <span className="badge neutral">○</span>
}

export function EvidencePanel({ evidence }: { evidence: EvidenceCompileResult }) {
  return (
    <div>
      <div className="row" style={{ marginBottom: 12 }}>
        <div className="stat-card" style={{ flex: 1 }}>
          <div className="stat-value">{evidence.candidates.length}</div>
          <div className="stat-label">候选证据</div>
        </div>
        <div className="stat-card" style={{ flex: 1 }}>
          <div className="stat-value">{evidence.applicability_results.length}</div>
          <div className="stat-label">已完成适用性评估</div>
        </div>
        <div className="stat-card" style={{ flex: 1 }}>
          <div className="stat-value">{evidence.accepted.length}</div>
          <div className="stat-label">已接受（Prior 可用）</div>
        </div>
        <div className="stat-card" style={{ flex: 1 }}>
          <div className="stat-value">{evidence.rejected.length}</div>
          <div className="stat-label">已拒绝</div>
        </div>
      </div>

      {evidence.applicability_results.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Evidence ID</th>
              <th>材料</th>
              <th>激光</th>
              <th>几何</th>
              <th>设备</th>
              <th>目标</th>
              <th>适用性</th>
            </tr>
          </thead>
          <tbody>
            {evidence.applicability_results.map((item) => (
              <tr key={item.evidence_id}>
                <td className="mono">{item.evidence_id}</td>
                <td><MatchIcon value={item.material_match} /></td>
                <td><MatchIcon value={item.laser_type_match} /></td>
                <td><MatchIcon value={item.geometry_match} /></td>
                <td><MatchIcon value={item.equipment_match} /></td>
                <td><MatchIcon value={item.target_match} /></td>
                <td>
                  <span className={`badge ${transferClass(item.transfer_level)}`}>
                    {transferLabel(item.transfer_level)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {evidence.rejected.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <h3>拒绝原因（Backend 判定）</h3>
          <ul className="detail-list">
            {evidence.rejected.map((item) => (
              <li key={item.evidence_id}>
                <span className="dl-key mono">{item.evidence_id}</span>
                <span className="dl-value">{item.reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {evidence.candidates.length === 0 && (
        <div className="empty-state">
          当前任务暂无证据候选。证据由 RAG / Agent 检索提供，前端不虚构任何 Evidence。
        </div>
      )}
    </div>
  )
}
