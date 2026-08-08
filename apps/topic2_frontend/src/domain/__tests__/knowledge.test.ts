import {
  buildEvidenceItems,
  buildPriors,
  buildQueryPlans,
  buildRequirements,
} from '../knowledge'

describe('knowledge lineage mappers (spec §十-§十一 / FE-5)', () => {
  const requirementSet = {
    requirements: [
      {
        requirement_id: 'KR-001',
        type: 'PARAMETER_PRIOR',
        scientific_question: 'need SiC F_th',
        required_for: 'LogAblationModel.F_th',
        priority: 'high',
        trigger_reasons: ['computation_gap'],
        required_evidence_roles: ['THRESHOLD'],
        satisfaction_criteria: ['range'],
        status: 'PARTIALLY_SATISFIED',
      },
    ],
    diagnostics: {},
  }

  it('maps requirement set 1:1 with typed view', () => {
    const views = buildRequirements(requirementSet)
    expect(views).toHaveLength(1)
    expect(views[0]).toMatchObject({
      requirementId: 'KR-001',
      type: 'PARAMETER_PRIOR',
      requiredFor: 'LogAblationModel.F_th',
    })
  })

  it('returns empty array for missing artifact', () => {
    expect(buildRequirements(null)).toEqual([])
    expect(buildRequirements(undefined)).toEqual([])
    expect(buildRequirements({})).toEqual([])
  })

  it('query plan exposes geometry as soft-only policy (spec FE-4/B3)', () => {
    const plans = buildQueryPlans({
      geometry_policy: 'SOFT_RANKING_HINT_ONLY',
      plans: [
        {
          query_plan_id: 'qp-1',
          requirement_id: 'KR-001',
          requirement_type: 'PARAMETER_PRIOR',
          scientific_question: 'need SiC F_th',
          hard_facets: { material_or_family: ['SiC'], pulse_regime: ['fs'] },
          soft_facets: { target_geometry_hint: ['rectangular_groove'] },
          query_terms: ['ablation threshold'],
          geometry_is_hard_filter: false,
          reason_codes: ['exact_geometry_is_ranking_hint_only'],
        },
      ],
    })
    expect(plans[0].geometryIsHardFilter).toBe(false)
    expect(plans[0].hardFacets.material_or_family).toEqual(['SiC'])
    expect(plans[0].softFacets.target_geometry_hint).toEqual(['rectangular_groove'])
  })

  it('priors carry evidence refs and uncertainty (spec §7.3)', () => {
    const priors = buildPriors({
      priors: [
        {
          prior_id: 'pr-1',
          prior_type: 'ParameterPrior',
          parameter: 'F_th',
          lower: 0.6,
          upper: 1.1,
          unit: 'J/cm2',
          uncertainty: 'HIGH',
          status: 'EXTERNAL_PRIOR',
          conflict_status: 'NONE',
          evidence_refs: [{ type: 'EvidenceIR', id: 'e1' }],
        },
      ],
    })
    expect(priors[0].range).toEqual([0.6, 1.1])
    expect(priors[0].uncertainty).toBe('HIGH')
    expect(priors[0].evidenceRefs[0].id).toBe('e1')
  })

  it('evidence items are passed through untouched (no reinterpretation)', () => {
    const items = buildEvidenceItems({ items: [{ evidence_id: 'e1', role: 'THRESHOLD' }] })
    expect(items).toHaveLength(1)
    expect(items[0].evidence_id).toBe('e1')
  })
})
