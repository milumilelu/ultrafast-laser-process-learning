/** Knowledge section (spec §十-§十一): requirement-centric lineage with inspector. */

import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import type { ArtifactSnapshot } from '../../domain/artifact'
import {
  buildEvidenceItems,
  buildQueryPlans,
  buildRequirements,
  buildPriors,
  type EvidenceItemView,
  type PriorView,
  type RequirementView,
} from '../../domain/knowledge'
import { Card, EmptyState } from '../../components/ui/Card'
import { StatusBadge } from '../../components/ui/StatusBadge'
import { Tabs } from '../../components/ui/Tabs'
import { RefList, SnapshotMeta } from '../../components/scientific/Artifact'

interface KnowledgeSectionProps {
  taskId: string
  requirements?: ArtifactSnapshot
  queryPlans?: ArtifactSnapshot
  evidence?: ArtifactSnapshot
  priors?: ArtifactSnapshot
  knowledgeState?: ArtifactSnapshot
  developerMode: boolean
}

const REQ_TONE: Record<string, 'ok' | 'warn' | 'neutral'> = {
  SATISFIED: 'ok',
  PARTIALLY_SATISFIED: 'warn',
  SATISFIED_WITH_CONFLICT: 'warn',
  UNSATISFIED: 'neutral',
}

export function KnowledgeSection({
  requirements,
  queryPlans,
  evidence,
  priors,
  knowledgeState,
  developerMode,
}: KnowledgeSectionProps) {
  const [searchParams] = useSearchParams()
  const requirementsView = useMemo(
    () => buildRequirements((knowledgeState ?? requirements)?.content as Record<string, unknown>),
    [knowledgeState, requirements],
  )
  const plansView = useMemo(
    () => buildQueryPlans(queryPlans?.content as Record<string, unknown>),
    [queryPlans],
  )
  const priorsView = useMemo(
    () => buildPriors(priors?.content as Record<string, unknown>),
    [priors],
  )
  const evidenceItems = useMemo(
    () => buildEvidenceItems(evidence?.content as Record<string, unknown>),
    [evidence],
  )
  const [selectedRequirement, setSelectedRequirement] = useState<RequirementView | null>(null)
  const [selectedEvidence, setSelectedEvidence] = useState<EvidenceItemView | null>(null)

  const planForRequirement = (requirementId: string) =>
    plansView.find((plan) => plan.requirementId === requirementId)

  const evidenceForRequirement = (requirementId: string) => {
    const plan = planForRequirement(requirementId)
    return evidenceItems.filter((item) => {
      const requirementIds = Array.isArray(item.requirement_ids)
        ? item.requirement_ids.map(String)
        : []
      if (requirementIds.length > 0) return requirementIds.includes(requirementId)
      if (!plan?.queryPlanId) return false
      const queryRefs = Array.isArray(item.query_plan_refs)
        ? item.query_plan_refs
        : item.query_plan_ref
          ? [item.query_plan_ref]
          : []
      return queryRefs.some((ref) =>
        String(typeof ref === 'object' && ref !== null ? (ref as Record<string, unknown>).id : ref) ===
        plan.queryPlanId,
      )
    })
  }

  const priorsForRequirement = (requirementId: string): PriorView[] => {
    const evidenceIds = new Set(
      evidenceForRequirement(requirementId)
        .map((item) => String(item.evidence_id ?? item.id ?? ''))
        .filter(Boolean),
    )
    return priorsView.filter((prior) =>
      prior.evidenceRefs.some((ref) => evidenceIds.has(ref.id)),
    )
  }

  useEffect(() => {
    const requestedEvidenceId = searchParams.get('evidence')
    if (!requestedEvidenceId) return
    const requestedEvidence = evidenceItems.find(
      (item) => String(item.evidence_id ?? item.id ?? '') === requestedEvidenceId,
    )
    if (!requestedEvidence) return
    setSelectedEvidence(requestedEvidence)
    const requirement = requirementsView.find((candidate) =>
      evidenceForRequirement(candidate.requirementId).includes(requestedEvidence),
    )
    if (requirement) setSelectedRequirement(requirement)
  }, [evidenceItems, requirementsView, searchParams])

  if (requirementsView.length === 0 && priorsView.length === 0) {
    return (
      <div className="section">
        <h1>Knowledge 知识</h1>
        <EmptyState
          message="尚无知识需求产物"
          hint="返回总览点击「继续」，运行 analyze_knowledge_requirements / satisfy_requirements 后生成。"
        />
      </div>
    )
  }

  return (
    <div className="section section-knowledge">
      <div className="section-head">
        <h1>Knowledge 知识</h1>
      </div>

      <div className="three-col">
        <div className="col">
          <Card title={`Requirements（${requirementsView.length}）`}>
            {requirementsView.length === 0 ? (
              <EmptyState message="暂无需求" />
            ) : (
              <ol className="requirement-list">
                {requirementsView.map((req) => (
                  <li
                    key={req.requirementId}
                    className={`requirement-card ${selectedRequirement?.requirementId === req.requirementId ? 'requirement-card-active' : ''}`}
                    onClick={() => {
                      setSelectedRequirement(req)
                      setSelectedEvidence(null)
                    }}
                  >
                    <div className="requirement-head">
                      <span className="requirement-id">{req.requirementId}</span>
                      <StatusBadge
                        tone={REQ_TONE[req.status] ?? 'neutral'}
                        label={requirementStatusLabel(req.status)}
                      />
                    </div>
                    <div className="requirement-question">{req.scientificQuestion || req.type}</div>
                    <div className="requirement-meta">
                      Required for: {req.requiredFor || '—'}
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </Card>
        </div>

        <div className="col">
          <Card title={selectedRequirement ? `Lineage: ${selectedRequirement.requirementId}` : 'Lineage'}>
            {!selectedRequirement ? (
              <EmptyState message="选择左侧需求查看完整链路" />
            ) : (
              <div className="lineage">
                <div className="lineage-node">
                  <span className="lineage-label">Requirement</span>
                  <div>{selectedRequirement.scientificQuestion}</div>
                  <div className="lineage-meta">type: {selectedRequirement.type} · priority: {selectedRequirement.priority}</div>
                  {selectedRequirement.requiredEvidenceRoles.length > 0 && (
                    <div className="lineage-meta">roles: {selectedRequirement.requiredEvidenceRoles.join(', ')}</div>
                  )}
                </div>
                {(() => {
                  const plan = planForRequirement(selectedRequirement.requirementId)
                  return plan ? (
                    <div className="lineage-node">
                      <span className="lineage-label">Retrieval QueryPlan</span>
                      <div className="lineage-meta">
                        {plan.queryTerms.join(' · ')}
                      </div>
                      <div className="lineage-meta">
                        geometry hard filter: <strong>{plan.geometryIsHardFilter ? 'YES' : 'NO'}</strong>
                      </div>
                      {plan.reasonCodes.length > 0 && (
                        <div className="lineage-meta">{plan.reasonCodes.join('; ')}</div>
                      )}
                    </div>
                  ) : null
                })()}
                <div className="lineage-node">
                  <span className="lineage-label">Evidence</span>
                  {evidenceForRequirement(selectedRequirement.requirementId).length === 0 ? (
                    <div className="lineage-meta">暂无匹配 evidence</div>
                  ) : (
                    <ol className="evidence-list">
                      {evidenceForRequirement(selectedRequirement.requirementId).map((item, index) => (
                        <li key={index}>
                          <button
                            className={`evidence-item ${selectedEvidence === item ? 'evidence-item-active' : ''}`}
                            onClick={() => setSelectedEvidence(item)}
                          >
                            {evidenceTitle(item)}
                          </button>
                        </li>
                      ))}
                    </ol>
                  )}
                </div>
                <div className="lineage-node">
                  <span className="lineage-label">PriorObjects</span>
                  {priorsForRequirement(selectedRequirement.requirementId).length === 0 ? (
                    <div className="lineage-meta">暂无 prior</div>
                  ) : (
                    priorsForRequirement(selectedRequirement.requirementId).map((prior) => (
                      <div key={prior.priorId} className="prior-mini">
                        <div className="prior-mini-head">
                          <span className="prior-type">{prior.priorType}</span>
                          {prior.parameter && <strong>{prior.parameter}</strong>}
                        </div>
                        {prior.range && (
                          <div className="prior-mini-range">
                            [{formatRange(prior.range[0])}, {formatRange(prior.range[1])}]
                            {prior.unit ? ` ${prior.unit}` : ''}
                          </div>
                        )}
                        {prior.modelFamily && <div className="prior-mini-meta">model: {prior.modelFamily}</div>}
                        <div className="prior-mini-meta">
                          uncertainty: {prior.uncertainty} · status: {prior.status}
                        </div>
                        <RefList refs={prior.evidenceRefs} label="evidence refs" />
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}
            <SnapshotMeta snapshot={requirements} />
          </Card>
        </div>

        <div className="col">
          <Card title="Evidence Inspector">
            {!selectedEvidence ? (
              <EmptyState message="点击中间列的 Evidence 展开详情" hint="Inspector 展示 Source / Applicability / Reconstructibility / Provenance。" />
            ) : (
              <EvidenceInspector item={selectedEvidence} developerMode={developerMode} />
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}

function evidenceTitle(item: EvidenceItemView): string {
  return (
    String(
      item.paper_id ??
        item.paper_title ??
        item.document_id ??
        item.evidence_id ??
        item.id ??
        'Evidence',
    ) + (item.role ? ` · ${String(item.role)}` : '')
  )
}

function formatRange(value: number | null): string {
  return value === null ? '—' : String(value)
}

const INSPECTOR_TABS = [
  { id: 'evidence', label: 'Evidence' },
  { id: 'trace', label: '溯源链' },
  { id: 'source', label: 'Source' },
  { id: 'applicability', label: 'Applicability' },
  { id: 'provenance', label: 'Provenance' },
]

function EvidenceInspector({ item, developerMode }: { item: EvidenceItemView; developerMode: boolean }) {
  const [tab, setTab] = useState('evidence')

  const sections: Record<string, Array<[string, unknown]>> = {
    evidence: pickKeys(item, ['role', 'claim', 'statement', 'confidence', 'evidence_level', 'status']),
    source: pickKeys(item, ['paper_id', 'paper_title', 'source', 'block_id', 'page', 'quote', 'candidate_id']),
    applicability: pickKeys(item, ['material', 'laser_type', 'pulse_width', 'frequency', 'scan_speed', 'hatch', 'geometry', 'applicability', 'match']),
    provenance: pickKeys(item, ['provenance', 'ledger_version_id', 'revision', 'source_ref', 'review_status']),
  }

  const traceRefs = (key: string) => {
    const value = item[key]
    return Array.isArray(value) ? value : value ? [value] : []
  }

  return (
    <div>
      <Tabs tabs={INSPECTOR_TABS} active={tab} onChange={setTab} />
      <div className="inspector-body">
        {tab === 'trace' ? (
          <dl className="kv-list">
            {item.ledger_ref ? (
              <div className="kv-row">
                <dt>ledger</dt>
                <dd>
                  <code>{String((item.ledger_ref as Record<string, unknown>).id ?? item.ledger_ref)}</code>
                </dd>
              </div>
            ) : null}
            {traceRefs('condition_refs').map((ref, index) => (
              <div key={`c-${index}`} className="kv-row">
                <dt>condition {index + 1}</dt>
                <dd>
                  <code>{String((ref as Record<string, unknown>).id ?? ref)}</code>
                  {item.conditions ? (
                    <span className="card-hint"> {JSON.stringify(item.conditions)}</span>
                  ) : null}
                </dd>
              </div>
            ))}
            {traceRefs('reconstructibility_refs').map((ref, index) => (
              <div key={`r-${index}`} className="kv-row">
                <dt>reconstructibility {index + 1}</dt>
                <dd>
                  <code>{String((ref as Record<string, unknown>).id ?? ref)}</code>
                </dd>
              </div>
            ))}
            {traceRefs('source_refs').map((ref, index) => (
              <div key={`s-${index}`} className="kv-row">
                <dt>source {index + 1}</dt>
                <dd>
                  {sourceRefId(ref) ? (
                    <Link to={`/resources/literature?paper=${encodeURIComponent(sourceRefId(ref))}`}>
                      <code>{sourceRefId(ref)}</code>
                    </Link>
                  ) : (
                    <code>{String(ref)}</code>
                  )}
                </dd>
              </div>
            ))}
            {!item.ledger_ref && traceRefs('condition_refs').length === 0 && (
              <EmptyState
                message="无结构化溯源引用"
                hint="该 Evidence 来自持久化证据表（无 ledger/condition 链）。"
              />
            )}
          </dl>
        ) : sections[tab].length === 0 ? (
          <EmptyState message="该 Evidence 无此维度信息" hint="展示后端 EvidenceIR item 的原始字段，不做推断。" />
        ) : (
          <dl className="kv-list">
            {sections[tab].map(([key, value]) => (
              <div key={key} className="kv-row">
                <dt>{key}</dt>
                <dd>{typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value ?? '—')}</dd>
              </div>
            ))}
          </dl>
        )}
        {developerMode && (
          <details className="dev-payload">
            <summary>raw item</summary>
            <pre>{JSON.stringify(item, null, 2)}</pre>
          </details>
        )}
      </div>
    </div>
  )
}

function requirementStatusLabel(status: string): string {
  if (status === 'SATISFIED') return '已满足'
  if (status === 'PARTIALLY_SATISFIED') return '部分满足'
  if (status === 'SATISFIED_WITH_CONFLICT') return '冲突待决'
  return '未满足'
}

function sourceRefId(ref: unknown): string {
  if (typeof ref === 'string') return ref
  if (typeof ref !== 'object' || ref === null) return ''
  return String((ref as Record<string, unknown>).id ?? '')
}

function pickKeys(item: EvidenceItemView, keys: string[]): Array<[string, unknown]> {
  return keys
    .filter((key) => item[key] !== undefined && item[key] !== null && item[key] !== '')
    .map((key) => [key, item[key]] as [string, unknown])
}
