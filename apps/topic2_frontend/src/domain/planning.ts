/** ToolpathPlan view model (M6) — path candidate comparison + selection. */

export interface PlanCandidateView {
  pathFamily: string
  morphologyRmseUm: number | null
  machiningTimeS: number | null
  objectiveValue: number | null
  planId: string
  simulationRefId: string | null
}

export interface PlanView {
  planId: string
  pathFamily: string
  status: string
  objectiveValue: number | null
  predictedRmseUm: number | null
  predictedMaxDepthUm: number | null
  predictedTimeS: number | null
  candidates: PlanCandidateView[]
  machineConstraints: { name: string; lower: number | null; upper: number | null; unit: string }[]
  simulationRef: { type: string; id: string } | null
  inputRefs: { type: string; id: string }[]
  planningPriorRefs: { type: string; id: string }[]
  pathParameters: Record<string, unknown>
}

export interface PlanContent {
  plan_id?: string
  path_family?: string
  status?: string
  objective_value?: number
  predicted_metrics?: {
    mean_depth_um?: number
    max_depth_um?: number
    morphology_rmse_um?: number | null
    machining_time_s?: number
  }
  candidate_summary?: Array<{
    path_family?: string
    morphology_rmse_um?: number | null
    machining_time_s?: number
    objective_value?: number
    plan_id?: string
    simulation_ref?: string
  }>
  machine_constraints?: Array<{
    name?: string
    lower?: number | null
    upper?: number | null
    unit?: string
  }>
  simulation_ref?: { type?: string; id?: string }
  planning_prior_refs?: Array<{ type?: string; id?: string }>
  path_parameters?: Record<string, unknown>
}

export const PATH_FAMILY_LABEL: Record<string, string> = {
  RASTER: 'Raster（单向）',
  CROSS_HATCH: 'Cross Hatch（交叉）',
  SPIRAL: 'Spiral',
}

export function buildPlanView(content: PlanContent | null | undefined): PlanView {
  const raw = content ?? {}
  const predicted = raw.predicted_metrics ?? {}
  const candidates: PlanCandidateView[] = (raw.candidate_summary ?? []).map((item) => ({
    pathFamily: String(item.path_family ?? ''),
    morphologyRmseUm: item.morphology_rmse_um ?? null,
    machiningTimeS: item.machining_time_s ?? null,
    objectiveValue: item.objective_value ?? null,
    planId: String(item.plan_id ?? ''),
    simulationRefId: item.simulation_ref ?? null,
  }))
  return {
    planId: String(raw.plan_id ?? ''),
    pathFamily: String(raw.path_family ?? ''),
    status: String(raw.status ?? ''),
    objectiveValue: raw.objective_value ?? null,
    predictedRmseUm: predicted.morphology_rmse_um ?? null,
    predictedMaxDepthUm: predicted.max_depth_um ?? null,
    predictedTimeS: predicted.machining_time_s ?? null,
    candidates,
    machineConstraints: (raw.machine_constraints ?? []).map((item) => ({
      name: String(item.name ?? ''),
      lower: item.lower ?? null,
      upper: item.upper ?? null,
      unit: String(item.unit ?? ''),
    })),
    simulationRef: raw.simulation_ref?.id
      ? { type: String(raw.simulation_ref.type ?? ''), id: String(raw.simulation_ref.id) }
      : null,
    inputRefs: [],
    planningPriorRefs: (raw.planning_prior_refs ?? []).map((ref) => ({
      type: String(ref.type ?? ''),
      id: String(ref.id ?? ''),
    })),
    pathParameters: raw.path_parameters ?? {},
  }
}
