/** EvidenceLifecycle (8.4 调整版): EvidenceIR → 引用 SourceCondition → Applicability
 *  → GovernedPriorArtifact。对象间是引用关系而非严格单线链；第一版保留
 *  provenance / reference 即可（source_id / review_id / transfer_level）。 */

import type { Evidence } from '../../api/types'
import { parameterLabel } from '../../lib/canonical'
import { scientificTone, type StatusTone } from '../../lib/status'
import { StatusBadge } from '../StatusBadge'

export function EvidenceLifecycle({
  evidence,
  applicabilityLevel,
  governedPriorEvidenceIds,
}: {
  evidence: Evidence
  /** EvidenceCompileResult.applicability_results 中对应条的 transfer_level */
  applicabilityLevel?: string | null
  /** GovernedPriorArtifact.evidence_ids（被治理先验引用时展示） */
  governedPriorEvidenceIds?: string[]
}) {
  const governed = governedPriorEvidenceIds?.includes(evidence.evidence_id)

  return (
    <div className="evidence-lifecycle" data-testid="evidence-lifecycle">
      <div className="chain">
        <span className="chain-step">PDF</span>
        <span className="chain-arrow">→</span>
        <span className="chain-step">ScientificDocument</span>
        <span className="chain-arrow">→</span>
        <span className="chain-step">ScientificCandidate</span>
        <span className="chain-arrow">→</span>
        <span className="chain-step">EvidenceIR</span>
        <span className="chain-arrow">└ 引用</span>
        <span className="chain-step">SourceCondition</span>
        <span className="chain-arrow">→</span>
        <span className="chain-step">Applicability</span>
        <span className="chain-arrow">→</span>
        <span className="chain-step">GovernedPriorArtifact</span>
      </div>
      <div className="card-sub" style={{ marginTop: 6 }}>
        EvidenceIR 通过 provenance 引用 SourceCondition，再评估适用性——不是严格单线对象链。
      </div>
      <ul className="detail-list" style={{ marginTop: 8 }}>
        <li>
          <span className="dl-key">Evidence ID</span>
          <span className="dl-value mono">{evidence.evidence_id}</span>
        </li>
        <li>
          <span className="dl-key">Parameter</span>
          <span className="dl-value">{parameterLabel(evidence.parameter ?? '—')}</span>
        </li>
        <li>
          <span className="dl-key">Raw Value</span>
          <span className="dl-value mono">{JSON.stringify(evidence.claim)}</span>
        </li>
        <li>
          <span className="dl-key">SourceCondition（引用）</span>
          <span className="dl-value mono">
            {evidence.provenance.source_id}
            {evidence.scope.material ? ` · ${evidence.scope.material}` : ''}
            {evidence.scope.laser_type ? ` · ${evidence.scope.laser_type}` : ''}
            {evidence.scope.geometry_type ? ` · ${evidence.scope.geometry_type}` : ''}
          </span>
        </li>
        <li>
          <span className="dl-key">Condition Role</span>
          <span className="dl-value">{evidence.claim_type}</span>
        </li>
        <li>
          <span className="dl-key">Applicability</span>
          <span className="dl-value">
            {applicabilityLevel ? (
              <StatusBadge tone={scientificTone(applicabilityLevel) as StatusTone}>
                {applicabilityLevel}
              </StatusBadge>
            ) : (
              '—'
            )}
          </span>
        </li>
        <li>
          <span className="dl-key">Governed Prior</span>
          <span className="dl-value">
            {governed ? (
              <StatusBadge tone="ok">被引用（evidence_ids）</StatusBadge>
            ) : (
              <StatusBadge tone="neutral">未引用</StatusBadge>
            )}
          </span>
        </li>
        <li>
          <span className="dl-key">Verification</span>
          <span className="dl-value">
            <StatusBadge
              tone={
                evidence.review_status === 'approved'
                  ? 'ok'
                  : evidence.review_status === 'rejected'
                    ? 'err'
                    : 'warn'
              }
            >
              {evidence.review_status}
            </StatusBadge>
          </span>
        </li>
        <li>
          <span className="dl-key">review_id（provenance）</span>
          <span className="dl-value mono">{evidence.provenance.review_id ?? '—'}</span>
        </li>
      </ul>
    </div>
  )
}
