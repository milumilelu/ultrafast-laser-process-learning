/** Knowledge view-models: Requirement → QueryPlan → Evidence → Prior lineage. */

export interface RequirementView {
  requirementId: string
  type: string
  scientificQuestion: string
  requiredFor: string
  priority: string
  triggerReasons: string[]
  requiredEvidenceRoles: string[]
  satisfactionCriteria: string[]
  status: string
}

export interface RequirementSetContent {
  requirements?: Array<{
    requirement_id?: string
    type?: string
    scientific_question?: string
    question?: string
    required_for?: string
    priority?: string
    trigger_reasons?: string[]
    required_evidence_roles?: string[]
    satisfaction_criteria?: string[]
    status?: string
  }>
  diagnostics?: Record<string, unknown>
}

export interface QueryPlanView {
  queryPlanId: string
  requirementId: string
  requirementType: string
  scientificQuestion: string
  hardFacets: Record<string, string[]>
  softFacets: Record<string, string[]>
  queryTerms: string[]
  geometryIsHardFilter: boolean
  reasonCodes: string[]
}

export interface QueryPlanContent {
  schema_version?: string
  geometry_policy?: string
  plans?: Array<{
    query_plan_id?: string
    requirement_id?: string
    requirement_type?: string
    scientific_question?: string
    hard_facets?: Record<string, string[]>
    soft_facets?: Record<string, string[]>
    query_terms?: string[]
    geometry_is_hard_filter?: boolean
    reason_codes?: string[]
  }>
}

export interface PriorView {
  priorId: string
  priorType: string
  parameter?: string
  range?: [number | null, number | null]
  unit?: string
  semantics?: string
  modelFamily?: string
  pathFamilies?: string[]
  preference?: string
  hardConstraint?: boolean
  uncertainty: string
  status: string
  conflictStatus: string
  evidenceRefs: Array<{ type: string; id: string }>
  applicabilityRefs: Array<{ type: string; id: string }>
}

export interface PriorSetContent {
  prior_set_id?: string
  priors?: Array<{
    prior_id?: string
    prior_type?: string
    parameter?: string
    lower?: number | null
    upper?: number | null
    unit?: string
    parameter_semantics?: string
    model_family?: string
    path_families?: string[]
    preference?: string
    hard_constraint?: boolean
    uncertainty?: string
    status?: string
    conflict_status?: string
    evidence_refs?: Array<{ type: string; id: string }>
    applicability_refs?: Array<{ type: string; id: string }>
  }>
  conflicts?: Record<string, unknown>[]
  warnings?: string[]
}

export interface EvidenceItemView {
  [key: string]: unknown
}

export function buildRequirements(content: RequirementSetContent | undefined | null): RequirementView[] {
  if (!content?.requirements) return []
  return content.requirements.map((req) => ({
    requirementId: req.requirement_id ?? '',
    type: req.type ?? 'OTHER',
    scientificQuestion: req.scientific_question ?? req.question ?? '',
    requiredFor: req.required_for ?? '',
    priority: req.priority ?? 'low',
    triggerReasons: req.trigger_reasons ?? [],
    requiredEvidenceRoles: req.required_evidence_roles ?? [],
    satisfactionCriteria: req.satisfaction_criteria ?? [],
    status: req.status ?? 'UNKNOWN',
  }))
}

export function buildQueryPlans(content: QueryPlanContent | undefined | null): QueryPlanView[] {
  if (!content?.plans) return []
  return content.plans.map((plan) => ({
    queryPlanId: plan.query_plan_id ?? '',
    requirementId: plan.requirement_id ?? '',
    requirementType: plan.requirement_type ?? '',
    scientificQuestion: plan.scientific_question ?? '',
    hardFacets: plan.hard_facets ?? {},
    softFacets: plan.soft_facets ?? {},
    queryTerms: plan.query_terms ?? [],
    geometryIsHardFilter: plan.geometry_is_hard_filter ?? false,
    reasonCodes: plan.reason_codes ?? [],
  }))
}

export function buildPriors(content: PriorSetContent | undefined | null): PriorView[] {
  if (!content?.priors) return []
  return content.priors.map((prior) => ({
    priorId: prior.prior_id ?? '',
    priorType: prior.prior_type ?? 'ParameterPrior',
    parameter: prior.parameter,
    range:
      prior.lower !== undefined && prior.upper !== undefined
        ? [prior.lower ?? null, prior.upper ?? null]
        : undefined,
    unit: prior.unit,
    semantics: prior.parameter_semantics,
    modelFamily: prior.model_family,
    pathFamilies: prior.path_families,
    preference: prior.preference,
    hardConstraint: prior.hard_constraint,
    uncertainty: prior.uncertainty ?? 'UNKNOWN',
    status: prior.status ?? 'UNKNOWN',
    conflictStatus: prior.conflict_status ?? 'NONE',
    evidenceRefs: prior.evidence_refs ?? [],
    applicabilityRefs: prior.applicability_refs ?? [],
  }))
}

/** EvidenceIR items are backend-shaped dicts; expose them without reinterpretation. */
export function buildEvidenceItems(content: Record<string, unknown> | undefined | null): EvidenceItemView[] {
  if (!content) return []
  const items = content.items
  if (!Array.isArray(items)) return []
  return items as EvidenceItemView[]
}
