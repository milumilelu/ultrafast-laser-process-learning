/** EvidenceTracePanel (14.5): Governed Prior Trace - content_hash / evidence_ids /
 *  approval_ids / verification。点击 evidence ID 跳转 /evidence。 */

import { Link } from 'react-router-dom'

import type { PriorAppliedEvidence } from '../../api/types'

export function EvidenceTracePanel({
  priorAppliedEvidence,
  governedPrior,
}: {
  priorAppliedEvidence: PriorAppliedEvidence | null
  governedPrior?: Record<string, unknown> | null
}) {
  const hash = governedPrior?.content_hash ?? priorAppliedEvidence?.governed_prior_hash
  const evidenceIds =
    (governedPrior?.evidence_ids as string[] | undefined) ??
    priorAppliedEvidence?.assisted_prior_evidence_ids ??
    []

  return (
    <div className="card" data-testid="evidence-trace-panel">
      <div className="card-title">Governed Prior Trace</div>
      {!hash ? (
        <div className="empty-state">
          无受治理先验（governed prior 不可用或未应用）。
        </div>
      ) : (
        <ul className="detail-list">
          <li>
            <span className="dl-key">GovernedPriorArtifact</span>
            <span className="dl-value mono">
              {governedPrior?.artifact_id != null ? String(governedPrior.artifact_id) : '—'}
            </span>
          </li>
          <li>
            <span className="dl-key">content_hash</span>
            <span className="dl-value mono">{hash ? String(hash) : '—'}</span>
          </li>
          <li>
            <span className="dl-key">evidence_ids</span>
            <span className="dl-value">
              {evidenceIds.map((id) => (
                <Link key={id} className="id-chip" to={`/evidence?evidence=${encodeURIComponent(id)}`}>
                  {id}
                </Link>
              ))}
            </span>
          </li>
          <li>
            <span className="dl-key">approval_ids</span>
            <span className="dl-value mono">
              {(governedPrior?.review_ids as string[] | undefined)?.join(', ') ?? '—'}
            </span>
          </li>
          <li>
            <span className="dl-key">verification</span>
            <span className="dl-value mono">
              {String(governedPrior?.verification ?? '—')}
            </span>
          </li>
        </ul>
      )}
    </div>
  )
}
