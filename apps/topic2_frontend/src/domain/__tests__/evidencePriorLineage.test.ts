import type { EvidencePriorResult } from '../../api/evidencePrior'
import {
  beliefsForRequirement,
  buildLineage,
  evidenceTouched,
  priorsForBeliefs,
} from '../evidencePriorLineage'

const RESULT: EvidencePriorResult = {
  analysis_run_id: 'evidence-prior-test-run',
  task: {
    material: 'CFRP',
    material_grade: null,
    target_metric: 'depth_um',
    equipment: {
      equipment_profile_id: 'eq_test',
      equipment_revision_id: 'eqrev_test',
      profile_name: 'Test fs system',
      effective_max_power_W: 16,
      effective_max_power_source: 'DERIVED_FROM_ATTENUATION',
      missing_fields: [],
    },
  },
  requirements: [
    {
      requirement_id: 'kreq-a',
      requirement_type: 'MATERIAL_IDENTITY',
      scientific_question: 'Is the processed material CFRP?',
      priority: 'high',
    },
    {
      requirement_id: 'kreq-b',
      requirement_type: 'PARAMETER_RANGE',
      scientific_question: 'What fluence range is reported for CFRP?',
      priority: 'high',
    },
  ],
  evidence: {
    evidence_set_id: 'evidence-set-test',
    items: [
      {
        evidence_id: 'ev-1',
        requirement_id: 'kreq-a',
        paper_id: 'paper-cfrp-a.pdf',
        document_version_id: 'doc-a',
        paper_title: 'CFRP ablation study',
        content: { evidence_type: 'MATERIAL_IDENTITY', statement: 'CFRP samples used' },
        conditions: { material: 'CFRP' },
        evidence_quote: 'CFRP laminates were processed',
        source_block_refs: ['b1'],
        source_pages: [3],
        extraction_confidence: 0.95,
        validation_state: 'VALIDATED',
        validation_errors: [],
        governance_status: 'unreviewed',
        extraction_route: 'llm_extraction',
        extractor_model: 'deepseek-v4-flash',
      },
      {
        evidence_id: 'ev-2',
        requirement_id: 'kreq-a',
        paper_id: 'paper-cfrp-b.pdf',
        document_version_id: 'doc-b',
        paper_title: 'CFRP texturing study',
        content: { evidence_type: 'MATERIAL_IDENTITY', statement: 'CFRP surface' },
        conditions: {},
        evidence_quote: 'CFRP coupons',
        source_block_refs: ['b2'],
        source_pages: [5],
        extraction_confidence: 0.9,
        validation_state: 'REJECTED',
        validation_errors: ['quote not verbatim'],
        governance_status: 'unreviewed',
        extraction_route: 'llm_extraction',
        extractor_model: 'deepseek-v4-flash',
      },
    ],
    misses: [
      {
        requirement_id: 'kreq-b',
        paper_id: 'paper-cfrp-a.pdf',
        document_version_id: 'doc-a',
        status: 'NOT_FOUND',
        reason: 'no numeric range reported',
      },
    ],
    paper_candidates: {
      'kreq-a': [
        {
          paper_id: 'paper-cfrp-a.pdf',
          document_version_id: 'doc-a',
          score: 0.032,
          matched_terms: ['cfrp'],
          paper_index_score: 0.91,
          global_block_score: 0.87,
          retrieval_routes: ['paper_index', 'global_block_index'],
        },
      ],
    },
    knowledge_reused_count: 1,
    llm_call_count: 2,
  },
  beliefs: {
    belief_set_id: 'belief-set-test',
    beliefs: [
      {
        belief_id: 'bl-1',
        evidence_id: 'ev-1',
        evidence_type: 'MATERIAL_IDENTITY',
        applicability_score: 0.9,
        transfer_level: 'SAME_MATERIAL',
        prior_weight: 0.9,
        uncertainty: 'LOW',
        facets: [
          { facet: 'material', status: 'MATCH', score: 1.0, task_value: 'CFRP', evidence_value: 'CFRP', reason: 'same material' },
        ],
        governance_status: 'unreviewed',
      },
    ],
  },
  priors: {
    prior_set_id: 'prior-set-test',
    priors: [
      {
        prior_id: 'pr-1',
        prior_type: 'PreferencePrior',
        evidence_refs: ['ev-1'],
        belief_refs: ['bl-1'],
        applicability_score: 0.85,
        weight: 0.85,
        uncertainty: 'MEDIUM',
        status: 'ACTIVE',
        conflict_group_id: null,
        direction: 'prefer_low_fluence',
      },
    ],
    conflicts: [],
    warnings: [],
  },
  warnings: [],
}

describe('buildLineage', () => {
  const lineage = buildLineage(RESULT)

  it('maps task and equipment context', () => {
    expect(lineage.task.material).toBe('CFRP')
    expect(lineage.task.targetMetric).toBe('depth_um')
    expect(lineage.task.equipmentProfileName).toBe('Test fs system')
    expect(lineage.task.effectiveMaxPowerW).toBe(16)
  })

  it('computes stats from the response', () => {
    expect(lineage.stats).toEqual({
      requirementCount: 2,
      candidateCount: 1,
      validatedCount: 1,
      rejectedCount: 1,
      missCount: 1,
      beliefCount: 1,
      priorCount: 1,
      llmCallCount: 2,
      knowledgeReusedCount: 1,
    })
  })

  it('links candidates to extracted evidence per requirement', () => {
    const requirement = lineage.requirements.find((item) => item.requirementId === 'kreq-a')
    expect(requirement?.candidates).toHaveLength(1)
    expect(requirement?.candidates[0].paperId).toBe('paper-cfrp-a.pdf')
    expect(requirement?.candidates[0].routes).toEqual(['paper_index', 'global_block_index'])
    expect(requirement?.candidates[0].evidenceIds).toEqual(['ev-1'])
    expect(evidenceTouched(requirement!.candidates[0])).toBe(true)
  })

  it('keeps misses scoped to their requirement', () => {
    const requirement = lineage.requirements.find((item) => item.requirementId === 'kreq-b')
    expect(requirement?.misses).toHaveLength(1)
    expect(requirement?.misses[0].status).toBe('NOT_FOUND')
    expect(requirement?.misses[0].paperId).toBe('paper-cfrp-a.pdf')
  })

  it('exposes beliefs only for validated evidence', () => {
    const requirement = lineage.requirements.find((item) => item.requirementId === 'kreq-a')!
    const beliefs = beliefsForRequirement(requirement, lineage.beliefsByEvidence)
    expect(beliefs).toHaveLength(1)
    expect(beliefs[0].beliefId).toBe('bl-1')
    expect(beliefs[0].evidenceType).toBe('MATERIAL_IDENTITY')
  })

  it('links priors through belief or evidence refs', () => {
    const requirement = lineage.requirements.find((item) => item.requirementId === 'kreq-a')!
    const beliefs = beliefsForRequirement(requirement, lineage.beliefsByEvidence)
    const priors = priorsForBeliefs(
      lineage.priors,
      new Set(beliefs.map((belief) => belief.beliefId)),
      new Set(requirement.evidence.filter((item) => item.validation_state === 'VALIDATED').map((item) => item.evidence_id)),
    )
    expect(priors).toHaveLength(1)
    expect(priors[0].priorId).toBe('pr-1')
    expect(priors[0].applicabilityScore).toBe(0.85)
  })
})
