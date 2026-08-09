/** Capability view-models. Pure display mapping over backend artifacts; no science. */

export type Availability = 'AVAILABLE' | 'UNVERIFIED' | 'MISSING'

export interface CapabilityInputRow {
  name: string
  value: number | string | null
  unit: string
  status: Availability
  source: 'MEASURED' | 'MACHINE_PROFILE' | 'DERIVED' | 'LITERATURE_PRIOR' | 'CALIBRATED' | 'MISSING'
  sourceRefTypes: string[]
  requiredBy: string[]
}

export interface IdentifiabilityRow {
  parameter: string
  status: 'IDENTIFIABLE' | 'WEAKLY_IDENTIFIABLE' | 'NOT_IDENTIFIABLE'
  reasonCodes: string[]
  requiredObservations: string[]
}

export interface CapabilityRequirementView {
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

export interface CapabilityReportView {
  capabilityId: string
  interactionTopology: string
  simulationSupported: boolean
  supportedFidelity: string[]
  inputs: CapabilityInputRow[]
  identifiability: IdentifiabilityRow[]
  recommendedRequirements: CapabilityRequirementView[]
  status: string
  reasonCodes: string[]
}

export interface CapabilityContent {
  capability_id?: string
  interaction_topology?: string
  simulation_supported?: boolean
  supported_fidelity?: string[]
  available?: Array<{
    name: string
    value?: number | string | null
    unit?: string
    status?: string
    source_refs?: Array<{ type: string; id: string }>
  }>
  missing?: Array<{
    name: string
    value?: number | string | null
    unit?: string
    status?: string
    source_refs?: Array<{ type: string; id: string }>
  }>
  identifiability?: Array<{
    parameter: string
    status?: string
    reason_codes?: string[]
    required_observations?: string[]
  }>
  recommended_requirements?: Array<{
    requirement_id?: string
    type?: string
    scientific_question?: string
    required_for?: string
    priority?: string
    trigger_reasons?: string[]
    required_evidence_roles?: string[]
    satisfaction_criteria?: string[]
    status?: string
  }>
  status?: string
  reason_codes?: string[]
}

function classifySource(row: {
  status?: string
  source_refs?: Array<{ type: string; id: string }>
}): CapabilityInputRow['source'] {
  const status = (row.status ?? '').toUpperCase()
  if (status === 'MISSING') return 'MISSING'
  const refTypes = (row.source_refs ?? []).map((ref) => ref.type)
  if (refTypes.some((t) => t.toLowerCase().includes('evidence') || t.toLowerCase().includes('prior'))) {
    return 'LITERATURE_PRIOR'
  }
  if (refTypes.some((t) => t.toLowerCase().includes('machine') || t.toLowerCase().includes('equipment'))) {
    return 'MACHINE_PROFILE'
  }
  if (refTypes.some((t) => t.toLowerCase().includes('data') || t.toLowerCase().includes('observation'))) {
    return 'MEASURED'
  }
  if (refTypes.some((t) => t.toLowerCase().includes('calibration'))) return 'CALIBRATED'
  if (status === 'AVAILABLE') return 'DERIVED'
  return 'MISSING'
}

export function buildCapabilityView(content: CapabilityContent | undefined | null): CapabilityReportView | null {
  if (!content) return null
  const available = content.available ?? []
  const missing = content.missing ?? []
  const requirements = content.recommended_requirements ?? []
  const inputs: CapabilityInputRow[] = [...available, ...missing].map((row) => {
    const name = row.name ?? 'unknown'
    const requiredBy = requirements
      .filter((req) => {
        const haystack = `${req.required_for ?? ''} ${req.scientific_question ?? ''}`.toLowerCase()
        return haystack.includes(name.toLowerCase()) || haystack.includes((row.unit ?? '').toLowerCase())
      })
      .map((req) => req.requirement_id ?? req.type ?? '')
      .filter(Boolean)
    return {
      name,
      value: row.value ?? null,
      unit: row.unit ?? '',
      status: (row.status ?? 'MISSING').toUpperCase() as Availability,
      source: classifySource(row),
      sourceRefTypes: (row.source_refs ?? []).map((ref) => ref.type),
      requiredBy,
    }
  })
  return {
    capabilityId: content.capability_id ?? '',
    interactionTopology: content.interaction_topology ?? 'UNKNOWN',
    simulationSupported: content.simulation_supported ?? false,
    supportedFidelity: content.supported_fidelity ?? [],
    inputs,
    identifiability: (content.identifiability ?? []).map((row) => ({
      parameter: row.parameter,
      status: (row.status ?? 'NOT_IDENTIFIABLE') as IdentifiabilityRow['status'],
      reasonCodes: row.reason_codes ?? [],
      requiredObservations: row.required_observations ?? [],
    })),
    recommendedRequirements: requirements.map((req) => ({
      requirementId: req.requirement_id ?? '',
      type: req.type ?? '',
      scientificQuestion: req.scientific_question ?? '',
      requiredFor: req.required_for ?? '',
      priority: req.priority ?? '',
      triggerReasons: req.trigger_reasons ?? [],
      requiredEvidenceRoles: req.required_evidence_roles ?? [],
      satisfactionCriteria: req.satisfaction_criteria ?? [],
      status: req.status ?? 'UNKNOWN',
    })),
    status: content.status ?? 'UNKNOWN',
    reasonCodes: content.reason_codes ?? [],
  }
}
