/** Calibration view-models. The parameter registry is built from the union of
 * backend-provided parameters (spec §十二/§三十八 FE-6); the count is never fixed.
 */

import type { CapabilityReportView } from './capability'
import type { PriorView } from './knowledge'
import type { ParameterStatus, ParameterSemantics } from './status'

export type Identifiability = 'IDENTIFIABLE' | 'WEAKLY_IDENTIFIABLE' | 'NOT_IDENTIFIABLE'

export interface ParameterEstimateView {
  parameter: string
  estimate: number | null
  lower: number | null
  upper: number | null
  unit: string
  identifiability: Identifiability
  semantics: ParameterSemantics
  priorRefs: Array<{ type: string; id: string }>
  dataRefs: Array<{ type: string; id: string }>
  assumptions: string[]
}

export interface CalibrationResultView {
  calibrationId: string
  parameters: ParameterEstimateView[]
  fitMetrics: {
    rmse: number
    mae: number
    r2: number | null
    targetUnit: string
    nObservations: number
  }
  status: string
  validationDataRefs: Array<{ type: string; id: string }>
  assumptions: string[]
}

export interface CalibrationContent {
  calibration_id?: string
  parameters?: Array<{
    parameter?: string
    estimate?: number | null
    lower?: number | null
    upper?: number | null
    unit?: string
    identifiability?: string
    parameter_semantics?: string
    prior_refs?: Array<{ type: string; id: string }>
    data_refs?: Array<{ type: string; id: string }>
    assumptions?: string[]
  }>
  fit_metrics?: {
    rmse?: number
    mae?: number
    r2?: number | null
    target_unit?: string
    n_observations?: number
  }
  status?: string
  validation_data_refs?: Array<{ type: string; id: string }>
  assumptions?: string[]
}

export interface IdentifiabilityReportContent {
  report_id?: string
  observation_type?: string
  status?: string
  parameters?: Array<{
    parameter?: string
    status?: string
    reason_codes?: string[]
    required_observations?: string[]
  }>
}

export function buildCalibrationView(content: CalibrationContent | undefined | null): CalibrationResultView | null {
  if (!content) return null
  return {
    calibrationId: content.calibration_id ?? '',
    parameters: (content.parameters ?? []).map((p) => ({
      parameter: p.parameter ?? '',
      estimate: p.estimate ?? null,
      lower: p.lower ?? null,
      upper: p.upper ?? null,
      unit: p.unit ?? '',
      identifiability: (p.identifiability ?? 'NOT_IDENTIFIABLE') as Identifiability,
      semantics: (p.parameter_semantics ?? 'PROVISIONAL') as ParameterSemantics,
      priorRefs: p.prior_refs ?? [],
      dataRefs: p.data_refs ?? [],
      assumptions: p.assumptions ?? [],
    })),
    fitMetrics: {
      rmse: content.fit_metrics?.rmse ?? 0,
      mae: content.fit_metrics?.mae ?? 0,
      r2: content.fit_metrics?.r2 ?? null,
      targetUnit: content.fit_metrics?.target_unit ?? '',
      nObservations: content.fit_metrics?.n_observations ?? 0,
    },
    status: content.status ?? 'NOT_YET_CALIBRATED',
    validationDataRefs: content.validation_data_refs ?? [],
    assumptions: content.assumptions ?? [],
  }
}

/* --------------------------- Dynamic parameter registry --------------------------- */

export interface RegistryRow {
  parameter: string
  role: string
  requiredBy: string[]
  value: number | null
  lower: number | null
  upper: number | null
  unit: string
  source: ParameterStatus
  semantics: ParameterSemantics | null
  identifiability: Identifiability | null
  priorUncertainty: string | null
}

const PARAMETER_ROLES: Record<string, string> = {
  wavelength: 'Optical',
  beam_radius: 'Optical',
  spot_radius: 'Optical',
  actual_power: 'Source',
  average_power: 'Source',
  pulse_width: 'Source',
  frequency: 'Source',
  scan_speed: 'Kinematic',
  hatch_spacing: 'Kinematic',
  passes: 'Kinematic',
  F_th: 'Interaction',
  f_th_eff: 'Interaction',
  incubation_S: 'Interaction',
  delta_eff: 'Ablation',
  alpha_defocus: 'Optical',
  thermal_diffusivity: 'Material',
  thermal_memory_eff: 'Thermal',
}

function roleFor(parameter: string): string {
  return PARAMETER_ROLES[parameter.toLowerCase()] ?? 'Other'
}

export interface RegistryInput {
  capability: CapabilityReportView | null
  calibration: CalibrationResultView | null
  identifiabilityReport: IdentifiabilityReportContent | null
  priors: PriorView[]
}

export function buildParameterRegistry(input: RegistryInput): RegistryRow[] {
  const { capability, calibration, priors } = input
  const rows = new Map<string, RegistryRow>()

  const touch = (parameter: string): RegistryRow => {
    const existing = rows.get(parameter)
    if (existing) return existing
    const row: RegistryRow = {
      parameter,
      role: roleFor(parameter),
      requiredBy: [],
      value: null,
      lower: null,
      upper: null,
      unit: '',
      source: 'MISSING',
      semantics: null,
      identifiability: null,
      priorUncertainty: null,
    }
    rows.set(parameter, row)
    return row
  }

  for (const input of capability?.inputs ?? []) {
    const row = touch(input.name)
    if (input.value !== null && input.value !== undefined) {
      row.value = typeof input.value === 'number' ? input.value : Number(input.value)
      if (Number.isNaN(row.value)) row.value = null
    }
    row.unit = row.unit || input.unit
    row.requiredBy.push(...input.requiredBy)
    if (input.status === 'AVAILABLE' || input.status === 'UNVERIFIED') {
      if (row.source === 'MISSING') row.source = input.status === 'UNVERIFIED' ? 'PRIOR_ONLY' : 'MEASURED'
    }
  }

  for (const ident of capability?.identifiability ?? []) {
    const row = touch(ident.parameter)
    row.identifiability = ident.status
    if (ident.status === 'NOT_IDENTIFIABLE' && row.source === 'MISSING') {
      row.source = 'NOT_IDENTIFIABLE'
    }
  }

  for (const prior of priors) {
    if (prior.priorType !== 'ParameterPrior' || !prior.parameter) continue
    const row = touch(prior.parameter)
    row.lower = prior.range ? prior.range[0] : null
    row.upper = prior.range ? prior.range[1] : null
    row.unit = row.unit || prior.unit || ''
    row.priorUncertainty = prior.uncertainty
    row.semantics = (prior.semantics as ParameterSemantics) ?? null
    if (row.source === 'MISSING') row.source = 'PRIOR_ONLY'
  }

  for (const estimate of calibration?.parameters ?? []) {
    const row = touch(estimate.parameter)
    row.value = estimate.estimate
    row.lower = estimate.lower
    row.upper = estimate.upper
    row.unit = row.unit || estimate.unit
    row.semantics = estimate.semantics
    row.identifiability = estimate.identifiability
    if (estimate.identifiability === 'NOT_IDENTIFIABLE') {
      row.source = 'NOT_IDENTIFIABLE'
    } else if (estimate.semantics === 'PROVISIONAL') {
      row.source = 'PROVISIONAL'
    } else if (estimate.estimate !== null) {
      row.source = 'CALIBRATED'
    }
  }

  for (const ident of input.identifiabilityReport?.parameters ?? []) {
    const row = touch(ident.parameter ?? '')
    row.identifiability = (ident.status ?? 'NOT_IDENTIFIABLE') as Identifiability
    if (row.identifiability === 'NOT_IDENTIFIABLE' && row.source === 'MISSING') {
      row.source = 'NOT_IDENTIFIABLE'
    }
  }

  const uniqueRequiredBy = (names: string[]): string[] => [...new Set(names)]
  const sorted = [...rows.values()].sort((a, b) => a.parameter.localeCompare(b.parameter))
  for (const row of sorted) row.requiredBy = uniqueRequiredBy(row.requiredBy)
  return sorted
}
