/**
 * Evidence → Prior V1 lineage visualization.
 * Renders the full chain Task → Requirements → Retrieval → LLM Extraction → E2P
 * from data already returned by the analyze endpoint.
 */

import { useMemo, useState } from 'react'
import type { EvidenceItem, EvidencePriorResult } from '../../api/evidencePrior'
import { Card, EmptyState } from '../../components/ui/Card'
import { Badge } from '../../components/ui/StatusBadge'
import {
  beliefsForRequirement,
  buildLineage,
  evidenceTouched,
  priorsForBeliefs,
  type LineageView,
  type RequirementLineageView,
} from '../../domain/evidencePriorLineage'

export function LineagePanel({ result }: { result?: EvidencePriorResult }) {
  const lineage = useMemo(() => (result ? buildLineage(result) : null), [result])
  const [selectedRequirementId, setSelectedRequirementId] = useState<string | null>(null)
  const [expandedEvidenceId, setExpandedEvidenceId] = useState<string | null>(null)

  const selected =
    lineage?.requirements.find((requirement) => requirement.requirementId === selectedRequirementId) ??
    lineage?.requirements[0] ??
    null

  if (!lineage) {
    return (
      <Card title="证据血缘流程（可视化）">
        <EmptyState
          message="尚未运行分析"
          hint="提交设备 revision 与任务后，这里展示 需求 → 检索候选 → LLM 抽取 → E2P 的完整血缘。"
        />
      </Card>
    )
  }

  const stats = lineage.stats

  return (
    <Card title="证据血缘流程（可视化）">
      <div className="result-stats">
        <span>{stats.requirementCount} 个需求</span>
        <span>{stats.candidateCount} 个检索候选</span>
        <span>{stats.validatedCount} 条验证通过</span>
        <span>{stats.rejectedCount} 条被拒</span>
        <span>{stats.missCount} 次未命中</span>
        <span>{stats.llmCallCount} 次 LLM</span>
        <span>{stats.knowledgeReusedCount} 条知识复用</span>
        <span>{stats.beliefCount} belief / {stats.priorCount} prior</span>
      </div>

      <div className="lineage-v1-flow">
        <FlowNode
          title="任务"
          lines={[
            `${lineage.task.material}${lineage.task.materialGrade ? ` / ${lineage.task.materialGrade}` : ''}`,
            lineage.task.targetMetric,
          ]}
        />
        <FlowArrow />
        <FlowNode
          title="精确需求"
          lines={[`${stats.requirementCount} 个`]}
        />
        <FlowArrow />
        <FlowNode
          title="双索引检索"
          lines={[`${stats.candidateCount} 篇候选`, 'paper + global block']}
        />
        <FlowArrow />
        <FlowNode
          title="LLM 逐论文抽取"
          lines={[`${stats.validatedCount} 验证通过`, `LLM ${stats.llmCallCount} 次`]}
        />
        <FlowArrow />
        <FlowNode
          title="E2P 先验"
          lines={[`${stats.beliefCount} belief`, `${stats.priorCount} prior`]}
        />
      </div>

      <div className="lineage-v1-grid">
        <ol className="lineage-v1-requirements">
          {lineage.requirements.map((requirement) => (
            <li key={requirement.requirementId}>
              <button
                className={
                  selected?.requirementId === requirement.requirementId
                    ? 'lineage-v1-req lineage-v1-req-active'
                    : 'lineage-v1-req'
                }
                onClick={() => {
                  setSelectedRequirementId(requirement.requirementId)
                  setExpandedEvidenceId(null)
                }}
              >
                <span className="lineage-v1-req-type">{requirement.requirementType}</span>
                <span className="lineage-v1-req-question">{requirement.scientificQuestion}</span>
                <span className="lineage-v1-req-meta">
                  {requirement.validatedCount} 验证通过 · {requirement.candidates.length} 候选
                  {requirement.rejectedCount > 0 ? ` · ${requirement.rejectedCount} 被拒` : ''}
                </span>
              </button>
            </li>
          ))}
        </ol>

        <div className="lineage-v1-chain">
          {selected && (
            <RequirementChain
              requirement={selected}
              lineage={lineage}
              expandedEvidenceId={expandedEvidenceId}
              onToggleEvidence={setExpandedEvidenceId}
            />
          )}
        </div>
      </div>
    </Card>
  )
}

function RequirementChain({
  requirement,
  lineage,
  expandedEvidenceId,
  onToggleEvidence,
}: {
  requirement: RequirementLineageView
  lineage: LineageView
  expandedEvidenceId: string | null
  onToggleEvidence: (evidenceId: string | null) => void
}) {
  const beliefs = beliefsForRequirement(requirement, lineage.beliefsByEvidence)
  const beliefIds = new Set(beliefs.map((belief) => belief.beliefId))
  const evidenceIds = new Set(
    requirement.evidence
      .filter((item) => item.validation_state === 'VALIDATED')
      .map((item) => item.evidence_id),
  )
  const priors = priorsForBeliefs(lineage.priors, beliefIds, evidenceIds)

  return (
    <>
      <ChainNode label="Requirement">
        <div className="lineage-v1-node-title">{requirement.scientificQuestion}</div>
        <div className="lineage-meta">
          {requirement.requirementType} · priority {requirement.priority}
        </div>
      </ChainNode>

      <ChainNode label="检索候选（paper + global block 双索引）">
        {requirement.candidates.length === 0 ? (
          <div className="lineage-meta">无候选论文</div>
        ) : (
          <ol className="lineage-v1-candidates">
            {requirement.candidates.map((candidate) => (
              <li key={`${candidate.paperId}::${candidate.documentVersionId}`}>
                <div className="lineage-v1-candidate-head">
                  <span className="lineage-v1-candidate-title">{candidate.paperId}</span>
                  {evidenceTouched(candidate) ? (
                    <Badge label="已抽取" tone="ok" />
                  ) : (
                    <Badge label="未产出证据" tone="neutral" />
                  )}
                </div>
                <div className="lineage-meta">
                  routes: {candidate.routes.join(' + ')}
                  {candidate.paperIndexScore !== undefined && (
                    <> · paper index {candidate.paperIndexScore.toFixed(3)}</>
                  )}
                  {candidate.globalBlockScore !== undefined && (
                    <> · block index {candidate.globalBlockScore.toFixed(3)}</>
                  )}
                </div>
              </li>
            ))}
          </ol>
        )}
      </ChainNode>

      <ChainNode label="LLM 逐论文抽取（EvidenceIR）">
        {requirement.evidence.length === 0 ? (
          <div className="lineage-meta">该需求未抽取到证据</div>
        ) : (
          <ol className="lineage-v1-evidence">
            {requirement.evidence.map((item) => (
              <li key={item.evidence_id}>
                <button
                  className={
                    expandedEvidenceId === item.evidence_id
                      ? 'lineage-v1-evidence lineage-v1-evidence-active'
                      : 'lineage-v1-evidence'
                  }
                  onClick={() =>
                    onToggleEvidence(
                      expandedEvidenceId === item.evidence_id ? null : item.evidence_id,
                    )
                  }
                >
                  <span className="lineage-v1-evidence-head">
                    <strong>{item.content.evidence_type}</strong>
                    {item.validation_state === 'VALIDATED' ? (
                      <Badge label="VALIDATED" tone="ok" />
                    ) : (
                      <Badge label="REJECTED" tone="err" />
                    )}
                  </span>
                  <span className="lineage-meta">
                    {item.paper_title || item.paper_id} · p.{item.source_pages.join(', ') || '—'} ·
                    conf {item.extraction_confidence.toFixed(2)}
                  </span>
                  {expandedEvidenceId === item.evidence_id && (
                    <EvidenceInline item={item} />
                  )}
                </button>
              </li>
            ))}
          </ol>
        )}
        {requirement.misses.length > 0 && (
          <div className="lineage-v1-misses">
            <span className="lineage-label-inline">未命中</span>
            <ul>
              {requirement.misses.map((miss, index) => (
                <li key={index}>
                  {miss.paperId} · {miss.status}
                  {miss.reason ? ` — ${miss.reason}` : ''}
                </li>
              ))}
            </ul>
          </div>
        )}
      </ChainNode>

      <ChainNode label="E2P（EvidenceBelief → PriorObject）">
        {beliefs.length === 0 ? (
          <div className="lineage-meta">无已验证证据，未形成 belief/prior</div>
        ) : (
          <>
            <ol className="lineage-v1-beliefs">
              {beliefs.map((belief) => (
                <li key={belief.beliefId}>
                  <div className="lineage-v1-belief-head">
                    <span>{belief.evidenceType}</span>
                    <span>app {belief.applicabilityScore.toFixed(3)} · {belief.transferLevel}</span>
                  </div>
                  <div className="lineage-meta">
                    {belief.facetCount} 个适用性维度 · prior weight {belief.priorWeight.toFixed(3)} ·
                    uncertainty {belief.uncertainty}
                  </div>
                </li>
              ))}
            </ol>
            <ol className="lineage-v1-priors">
              {priors.map((prior) => (
                <li key={prior.priorId}>
                  <div className="lineage-v1-prior-head">
                    <strong>{prior.priorType}</strong>
                    <span>
                      app {prior.applicabilityScore.toFixed(3)} · weight {prior.weight.toFixed(3)}
                    </span>
                  </div>
                  <div className="lineage-meta">
                    {prior.status}
                    {prior.conflictGroupId ? ` · 冲突组 ${prior.conflictGroupId}` : ''} · uncertainty{' '}
                    {prior.uncertainty}
                  </div>
                </li>
              ))}
            </ol>
          </>
        )}
      </ChainNode>
    </>
  )
}

function EvidenceInline({ item }: { item: EvidenceItem }) {
  return (
    <span className="lineage-v1-evidence-inline">
      <blockquote>{item.evidence_quote || '无有效原文引文'}</blockquote>
      <span className="lineage-meta">
        blocks: {item.source_block_refs.join(', ') || '—'} ·{' '}
        {item.extractor_model} · {item.extraction_route} · {item.governance_status}
      </span>
      {item.validation_errors.length > 0 && (
        <span className="lineage-v1-errors">{item.validation_errors.join('; ')}</span>
      )}
    </span>
  )
}

function FlowNode({ title, lines }: { title: string; lines: string[] }) {
  return (
    <div className="flow-node">
      <strong>{title}</strong>
      {lines.map((line) => (
        <span key={line}>{line}</span>
      ))}
    </div>
  )
}

function FlowArrow() {
  return <div className="flow-arrow">→</div>
}

function ChainNode({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="lineage-node">
      <span className="lineage-label">{label}</span>
      {children}
    </div>
  )
}
