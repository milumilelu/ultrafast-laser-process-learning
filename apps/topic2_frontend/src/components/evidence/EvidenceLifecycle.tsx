/** EvidenceLifecycle (8.4): 单条 Evidence 的完整生命周期链。 */

import type { Evidence } from '../../api/types'
import { parameterLabel } from '../../lib/canonical'
import { StatusBadge } from '../StatusBadge'

export function EvidenceLifecycle({ evidence }: { evidence: Evidence }) {
  return (
    <div className="evidence-lifecycle" data-testid="evidence-lifecycle">
      <div className="chain">
        {['PDF', 'ScientificDocument', 'ScientificCandidate', 'ExperimentalCondition', 'EvidenceIR', 'GovernedPriorArtifact'].map(
          (step, index, steps) => (
            <span key={step} className="chain-step">
              {step}
              {index < steps.length - 1 && <span className="chain-arrow">→</span>}
            </span>
          ),
        )}
      </div>
      <ul className="detail-list" style={{ marginTop: 12 }}>
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
          <span className="dl-key">Source Paper</span>
          <span className="dl-value mono">{evidence.provenance.source_id}</span>
        </li>
        <li>
          <span className="dl-key">Condition Role</span>
          <span className="dl-value">{evidence.claim_type}</span>
        </li>
        <li>
          <span className="dl-key">Verification</span>
          <span className="dl-value">
            <StatusBadge tone={evidence.review_status === 'approved' ? 'ok' : evidence.review_status === 'rejected' ? 'err' : 'warn'}>
              {evidence.review_status}
            </StatusBadge>
          </span>
        </li>
        <li>
          <span className="dl-key">Mapping / Governance</span>
          <span className="dl-value mono">{evidence.provenance.review_id ?? '—'}</span>
        </li>
      </ul>
    </div>
  )
}
