/** ScientificKnowledgePack 候选 → Topic2 Evidence[]（证据篮）。
 *  科学链（RAG→LLM→E2P）分析出的数值/范围候选编译为 compile/policy 可消费的证据。 */

import type { Evidence, EvidenceScope } from '../api/types'

interface KnowledgeCandidate {
  candidate_id: string
  type: string
  parameter?: string | null
  value?: number | null
  lower?: number | null
  upper?: number | null
  unit?: string | null
  target?: string | null
  conditions?: Record<string, unknown>
  semantic_role?: string | null
  supporting_sources?: { paper_id?: string | null; page?: number | null; chunk_ids?: string[] }[]
}

export function candidatesToEvidence(
  knowledge: Record<string, unknown>,
  scope: {
    material: string | null
    laser_type: string | null
    geometry_type: string | null
    equipment_id: string | null
    target: string | null
  },
): Evidence[] {
  const candidates = (knowledge.candidates ?? []) as KnowledgeCandidate[]
  const evidence: Evidence[] = []
  for (const candidate of candidates) {
    if (
      candidate.type !== 'parameter_value' &&
      candidate.type !== 'parameter_range' &&
      candidate.type !== 'reported_optimum'
    ) {
      continue
    }
    const parameter = candidate.parameter
    if (!parameter) continue
    const unit = candidate.unit ?? null
    let lower: number | null = candidate.lower ?? candidate.value ?? null
    let upper: number | null = candidate.upper ?? candidate.value ?? null
    if (lower == null || upper == null) continue
    if (lower > upper) {
      const swap = lower
      lower = upper
      upper = swap
    }
    const source = candidate.supporting_sources?.[0]
    const paperId = source?.paper_id ?? null
    evidence.push({
      evidence_id: candidate.candidate_id,
      source_type: 'literature',
      claim_type: 'range_preference',
      parameter,
      target: scope.target ?? candidate.target ?? null,
      claim: { lower, upper, unit },
      scope: {
        material: scope.material,
        laser_type: scope.laser_type,
        geometry_type: scope.geometry_type,
        equipment_id: scope.equipment_id,
        target: scope.target,
      } as EvidenceScope,
      provenance: { source_id: paperId ?? '', review_id: null },
      review_status: 'pending',
      version: '1',
    })
  }
  return evidence
}
