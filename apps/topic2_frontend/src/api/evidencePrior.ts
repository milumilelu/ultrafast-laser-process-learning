import { config } from '../config'
import { jsonBody, request } from './client'

export type TargetMetric = 'depth_um' | 'roughness_um'

export interface EvidencePriorRequest {
  material: string
  material_grade?: string
  equipment_profile_id: string
  equipment_revision_id: string
  target_metric: TargetMetric
}

export interface KnowledgeRequirement {
  requirement_id: string
  requirement_type: string
  scientific_question: string
  priority: string
}

export interface EvidenceContent {
  evidence_type: string
  statement?: string
  parameter?: string
  value?: number | null
  lower?: number | null
  upper?: number | null
  unit?: string | null
  direction?: string | null
  mechanism?: string
  method?: string
  material?: string
  material_grade?: string | null
  target_metric?: string | null
  measured_value?: number | null
  threshold_value?: number | null
  parameters?: Array<Record<string, unknown>>
}

export interface PaperCandidate {
  paper_id: string
  document_version_id: string
  score: number
  matched_terms: string[]
  paper_index_score: number
  global_block_score: number
  retrieval_routes: string[]
}

export interface EvidenceMiss {
  requirement_id: string
  paper_id: string
  document_version_id: string
  status: string
  reason: string
}

export interface EvidenceItem {
  evidence_id: string
  requirement_id: string
  paper_id: string
  document_version_id: string
  paper_title: string
  content: EvidenceContent
  conditions: Record<string, unknown>
  evidence_quote: string
  source_block_refs: string[]
  source_pages: number[]
  extraction_confidence: number
  validation_state: 'VALIDATED' | 'REJECTED'
  validation_errors: string[]
  governance_status: string
  extraction_route: 'llm_extraction' | 'structured_knowledge'
  extractor_model: string
}

export interface ApplicabilityFacet {
  facet: string
  status: string
  score: number
  task_value: unknown
  evidence_value: unknown
  reason: string
}

export interface EvidenceBelief {
  belief_id: string
  evidence_id: string
  evidence_type: string
  applicability_score: number
  evidence_quality: number
  transfer_level: string
  recommended_prior_strength: number
  uncertainty: string
  facets: ApplicabilityFacet[]
  governance_status: string
}

export interface PriorObject {
  prior_id: string
  prior_type: string
  evidence_refs: string[]
  belief_refs: string[]
  applicability_score: number
  evidence_quality: number
  recommended_strength: number
  uncertainty: string
  status: string
  conflict_group_id?: string | null
  parameter?: string
  value?: number | null
  lower?: number | null
  upper?: number | null
  unit?: string
  target_metric?: string
  parameters?: Array<Record<string, unknown>>
  direction?: string | null
  statement?: string
  mechanism?: string
}

export interface TransferObservation {
  observation_id: string
  evidence_refs: string[]
  belief_refs: string[]
  applicability_score: number
  evidence_quality: number
  recommended_strength: number
  uncertainty: string
  status: string
  target_metric?: string | null
  measured_value?: number | null
  unit?: string | null
  conditions: Record<string, unknown>
  statement: string
}

export interface EvidencePriorResult {
  analysis_run_id: string
  task: {
    material: string
    material_grade?: string | null
    target_metric: TargetMetric
    equipment: {
      equipment_profile_id: string
      equipment_revision_id: string
      profile_name: string
      effective_max_power_W?: number | null
      effective_max_power_source: string
      missing_fields: string[]
    }
  }
  requirements: KnowledgeRequirement[]
  evidence: {
    evidence_set_id: string
    items: EvidenceItem[]
    misses: EvidenceMiss[]
    paper_candidates: Record<string, PaperCandidate[]>
    knowledge_reused_count: number
    llm_call_count: number
  }
  beliefs: {
    belief_set_id: string
    beliefs: EvidenceBelief[]
  }
  priors: {
    prior_set_id: string
    priors: PriorObject[]
    observations: TransferObservation[]
    conflicts: Array<Record<string, unknown>>
    warnings: string[]
  }
  warnings: string[]
}

export const evidencePriorApi = {
  analyze(payload: EvidencePriorRequest): Promise<EvidencePriorResult> {
    return request(config.agentApiUrl, '/api/v1/evidence-prior/analyze', {
      method: 'POST',
      ...jsonBody(payload),
    })
  },
}
