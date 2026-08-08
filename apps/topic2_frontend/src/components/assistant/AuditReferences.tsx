/** AuditReferences (UI-10/27.3): 引用与审计列表 - Paper / Candidate / Evidence /
 *  Model / CFA Report / Governed Prior / BO Run，点击跳转对应页面。 */

import { Link } from 'react-router-dom'

import { useAgentStore } from '../../stores/agent'
import { useApplicationStore } from '../../stores/application'
import { useWorkflowStore } from '../../stores/workflow'

export function AuditReferences() {
  const messages = useAgentStore((state) => state.messages)
  const proposals = useAgentStore((state) => state.proposals)
  const {
    processLearningArtifactId,
    evidenceArtifactId,
    cfaArtifactId,
    governedPriorArtifactId,
    vanillaBoRunId,
    assistedBoRunId,
    activeApplicationRunId,
  } = useApplicationStore()
  const workflowEvents = useWorkflowStore((state) => state.events)

  const agentRefs = new Set<string>()
  for (const message of messages) {
    for (const ref of message.references) agentRefs.add(ref)
  }

  const artifactTypes = new Set<string>()
  for (const event of workflowEvents) {
    for (const ref of event.artifactRefs ?? []) artifactTypes.add(ref.type)
  }

  return (
    <div className="audit-refs">
      <div className="card-sub">应用运行引用</div>
      <ul className="detail-list">
        <li>
          <span className="dl-key">Application Run</span>
          <span className="dl-value">
            {activeApplicationRunId ? (
              <Link className="id-chip" to={`/runs?run=${encodeURIComponent(activeApplicationRunId)}`}>
                {activeApplicationRunId}
              </Link>
            ) : (
              '—'
            )}
          </span>
        </li>
        <li>
          <span className="dl-key">Process Learning</span>
          <span className="dl-value mono">{processLearningArtifactId ?? '—'}</span>
        </li>
        <li>
          <span className="dl-key">Evidence</span>
          <span className="dl-value">
            {evidenceArtifactId ? (
              <Link className="id-chip" to={`/evidence?evidence=${encodeURIComponent(evidenceArtifactId)}`}>
                {evidenceArtifactId}
              </Link>
            ) : (
              '—'
            )}
          </span>
        </li>
        <li>
          <span className="dl-key">CFA Report</span>
          <span className="dl-value mono">{cfaArtifactId ?? '—'}</span>
        </li>
        <li>
          <span className="dl-key">Governed Prior</span>
          <span className="dl-value mono">{governedPriorArtifactId ?? '—'}</span>
        </li>
        <li>
          <span className="dl-key">Vanilla BO</span>
          <span className="dl-value mono">{vanillaBoRunId ?? '—'}</span>
        </li>
        <li>
          <span className="dl-key">Assisted BO</span>
          <span className="dl-value mono">{assistedBoRunId ?? '—'}</span>
        </li>
      </ul>

      {artifactTypes.size > 0 && (
        <>
          <div className="card-sub" style={{ marginTop: 12 }}>
            执行流产物
          </div>
          <div className="row" style={{ gap: 6 }}>
            {[...artifactTypes].map((type) => (
              <span className="badge neutral" key={type}>
                {type}
              </span>
            ))}
          </div>
        </>
      )}

      {agentRefs.size > 0 && (
        <>
          <div className="card-sub" style={{ marginTop: 12 }}>Agent 引用</div>
          <div className="row" style={{ gap: 6 }}>
            {[...agentRefs].map((ref) => (
              <span className="id-chip muted" key={ref}>
                {ref}
              </span>
            ))}
          </div>
        </>
      )}

      {proposals.length > 0 && (
        <>
          <div className="card-sub" style={{ marginTop: 12 }}>人工 Proposal</div>
          <ul className="detail-list">
            {proposals.map((proposal) => (
              <li key={proposal.proposalId}>
                <span className="dl-key">{proposal.proposalId}</span>
                <span className="dl-value">
                  {proposal.type} · {proposal.status}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
