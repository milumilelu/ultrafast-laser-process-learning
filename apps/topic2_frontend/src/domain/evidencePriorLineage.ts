/**
 * Evidence → Prior V1 lineage view-models.
 * Pure display mapping over the analyze response; no science, no derivation.
 */

import type {
  EvidenceBelief,
  EvidenceItem,
  EvidencePriorResult,
  PaperCandidate,
  PriorObject,
} from '../api/evidencePrior'

export interface LineageStats {
  requirementCount: number
  candidateCount: number
  validatedCount: number
  rejectedCount: number
  missCount: number
  beliefCount: number
  priorCount: number
  llmCallCount: number
  knowledgeReusedCount: number
}

export interface LineageTaskView {
  material: string
  materialGrade: string | null
  targetMetric: string
  equipmentProfileName: string
  effectiveMaxPowerW: number | null
  effectiveMaxPowerSource: string
}

export interface LineageCandidateView {
  paperId: string
  documentVersionId: string
  score: number
  paperIndexScore: number
  globalBlockScore: number
  routes: string[]
  evidenceIds: string[]
}

export interface LineageMissView {
  paperId: string
  status: string
  reason: string
}

export interface LineageBeliefView {
  beliefId: string
  evidenceId: string
  evidenceType: string
  applicabilityScore: number
  transferLevel: string
  priorWeight: number
  uncertainty: string
  facetCount: number
}

export interface LineagePriorView {
  priorId: string
  priorType: string
  applicabilityScore: number
  weight: number
  uncertainty: string
  status: string
  conflictGroupId: string | null
  beliefRefs: string[]
  evidenceRefs: string[]
}

export interface RequirementLineageView {
  requirementId: string
  requirementType: string
  scientificQuestion: string
  priority: string
  candidates: LineageCandidateView[]
  evidence: EvidenceItem[]
  misses: LineageMissView[]
  validatedCount: number
  rejectedCount: number
}

export interface LineageView {
  task: LineageTaskView
  stats: LineageStats
  requirements: RequirementLineageView[]
  beliefsByEvidence: Map<string, LineageBeliefView>
  priors: LineagePriorView[]
}

export function buildLineage(result: EvidencePriorResult): LineageView {
  const evidenceByRequirement = groupBy(result.evidence.items, (item) => item.requirement_id)
  const beliefsByEvidence = new Map(
    result.beliefs.beliefs.map((belief) => [belief.evidence_id, toBeliefView(belief)]),
  )

  const requirements: RequirementLineageView[] = result.requirements.map((requirement) => {
    const items = evidenceByRequirement.get(requirement.requirement_id) ?? []
    const candidates = (result.evidence.paper_candidates[requirement.requirement_id] ?? []).map(
      (candidate) => toCandidateView(candidate, items),
    )
    const misses = result.evidence.misses
      .filter((miss) => miss.requirement_id === requirement.requirement_id)
      .map((miss) => ({
        paperId: miss.paper_id,
        status: miss.status,
        reason: miss.reason,
      }))
    return {
      requirementId: requirement.requirement_id,
      requirementType: requirement.requirement_type,
      scientificQuestion: requirement.scientific_question,
      priority: requirement.priority,
      candidates,
      evidence: items,
      misses,
      validatedCount: countBy(items, (item) => item.validation_state === 'VALIDATED'),
      rejectedCount: countBy(items, (item) => item.validation_state === 'REJECTED'),
    }
  })

  return {
    task: {
      material: result.task.material,
      materialGrade: result.task.material_grade ?? null,
      targetMetric: result.task.target_metric,
      equipmentProfileName: result.task.equipment.profile_name,
      effectiveMaxPowerW: result.task.equipment.effective_max_power_W ?? null,
      effectiveMaxPowerSource: result.task.equipment.effective_max_power_source,
    },
    stats: {
      requirementCount: requirements.length,
      candidateCount: requirements.reduce(
        (total, requirement) => total + requirement.candidates.length,
        0,
      ),
      validatedCount: countBy(
        result.evidence.items,
        (item) => item.validation_state === 'VALIDATED',
      ),
      rejectedCount: countBy(
        result.evidence.items,
        (item) => item.validation_state === 'REJECTED',
      ),
      missCount: result.evidence.misses.length,
      beliefCount: result.beliefs.beliefs.length,
      priorCount: result.priors.priors.length,
      llmCallCount: result.evidence.llm_call_count,
      knowledgeReusedCount: result.evidence.knowledge_reused_count,
    },
    requirements,
    beliefsByEvidence,
    priors: result.priors.priors.map(toPriorView),
  }
}

export function evidenceTouched(candidate: LineageCandidateView): boolean {
  return candidate.evidenceIds.length > 0
}

export function beliefsForRequirement(
  requirement: RequirementLineageView,
  beliefsByEvidence: Map<string, LineageBeliefView>,
): LineageBeliefView[] {
  return requirement.evidence
    .filter((item) => item.validation_state === 'VALIDATED')
    .map((item) => beliefsByEvidence.get(item.evidence_id))
    .filter((belief): belief is LineageBeliefView => belief !== undefined)
}

export function priorsForBeliefs(
  priors: LineagePriorView[],
  beliefIds: Set<string>,
  evidenceIds: Set<string>,
): LineagePriorView[] {
  return priors.filter(
    (prior) =>
      prior.beliefRefs.some((ref) => beliefIds.has(ref)) ||
      prior.evidenceRefs.some((ref) => evidenceIds.has(ref)),
  )
}

function toCandidateView(
  candidate: PaperCandidate,
  items: EvidenceItem[],
): LineageCandidateView {
  const matching = new Set(
    items
      .filter(
        (item) =>
          item.paper_id === candidate.paper_id &&
          item.document_version_id === candidate.document_version_id,
      )
      .map((item) => item.evidence_id),
  )
  return {
    paperId: candidate.paper_id,
    documentVersionId: candidate.document_version_id,
    score: candidate.score,
    paperIndexScore: candidate.paper_index_score,
    globalBlockScore: candidate.global_block_score,
    routes: candidate.retrieval_routes,
    evidenceIds: [...matching],
  }
}

function toBeliefView(belief: EvidenceBelief): LineageBeliefView {
  return {
    beliefId: belief.belief_id,
    evidenceId: belief.evidence_id,
    evidenceType: belief.evidence_type,
    applicabilityScore: belief.applicability_score,
    transferLevel: belief.transfer_level,
    priorWeight: belief.prior_weight,
    uncertainty: belief.uncertainty,
    facetCount: belief.facets.length,
  }
}

function toPriorView(prior: PriorObject): LineagePriorView {
  return {
    priorId: prior.prior_id,
    priorType: prior.prior_type,
    applicabilityScore: prior.applicability_score,
    weight: prior.weight,
    uncertainty: prior.uncertainty,
    status: prior.status,
    conflictGroupId: prior.conflict_group_id ?? null,
    beliefRefs: prior.belief_refs,
    evidenceRefs: prior.evidence_refs,
  }
}

function groupBy<T>(items: T[], key: (item: T) => string): Map<string, T[]> {
  const groups = new Map<string, T[]>()
  for (const item of items) {
    const groupKey = key(item)
    const bucket = groups.get(groupKey)
    if (bucket) bucket.push(item)
    else groups.set(groupKey, [item])
  }
  return groups
}

function countBy<T>(items: T[], predicate: (item: T) => boolean): number {
  return items.filter(predicate).length
}
