/** Capability view-models. Pure display mapping over backend artifacts; no science. */

import type { ExecutionStatus } from './status'

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

/* --------------------- Execution capability graph (spec §七) --------------------- */

export interface ChainNode {
  id: string
  label: string
  /** Inputs that gate this node; status derived from the capability report. */
  gatingInputs: string[]
  downstream: string[]
}

/** Canonical dependency chain; node status comes from the backend report only. */
export const EXECUTION_CHAIN: ChainNode[] = [
  { id: 'power', label: '激光功率', gatingInputs: ['actual_power', 'average_power'], downstream: ['pulse_energy'] },
  { id: 'pulse_energy', label: '单脉冲能量', gatingInputs: ['pulse_energy'], downstream: ['peak_fluence'] },
  { id: 'beam', label: '光斑定义', gatingInputs: ['beam_radius', 'spot_radius'], downstream: ['peak_fluence', 'overlap'] },
  { id: 'peak_fluence', label: '峰值能量密度', gatingInputs: ['peak_fluence'], downstream: ['normalized_fluence'] },
  { id: 'threshold', label: '烧蚀阈值', gatingInputs: ['F_th', 'F_th_eff'], downstream: ['normalized_fluence'] },
  { id: 'normalized_fluence', label: '归一化能量密度', gatingInputs: ['normalized_fluence'], downstream: ['ablation'] },
  { id: 'ablation', label: '对数烧蚀模型', gatingInputs: ['delta_eff'], downstream: ['removal'] },
  { id: 'removal', label: 'LocalRemovalModel', gatingInputs: ['local_removal_model'], downstream: ['simulator'] },
  { id: 'simulator', label: '形貌仿真', gatingInputs: ['simulation_supported'], downstream: ['planning'] },
  { id: 'planning', label: '路径规划', gatingInputs: ['toolpath'], downstream: [] },
]

export type ChainNodeStatus = 'READY' | 'UNVERIFIED' | 'BLOCKED' | 'NOT_RUN'

export interface ChainNodeView {
  node: ChainNode
  status: ChainNodeStatus
  blockingInputs: string[]
}

export function buildChainStatus(view: CapabilityReportView | null): {
  nodes: ChainNodeView[]
  overall: ExecutionStatus
} {
  if (!view) {
    return { nodes: [], overall: 'NOT_RUN' }
  }
  const byName = new Map<string, Availability>()
  for (const input of view.inputs) byName.set(input.name.toLowerCase(), input.status)
  const alias: Record<string, string[]> = {
    actual_power: ['actual_power', 'average_power'],
    pulse_energy: ['pulse_energy'],
    beam_radius: ['beam_radius', 'spot_radius', 'spot_size'],
    peak_fluence: ['peak_fluence'],
    F_th: ['f_th', 'f_th_eff', 'threshold'],
    normalized_fluence: ['normalized_fluence'],
    delta_eff: ['delta_eff', 'delta'],
    local_removal_model: [],
    simulation_supported: [],
    toolpath: [],
  }
  const inputsStatus = (names: string[]): { status: Availability | null; name: string | null } => {
    for (const name of names) {
      const found = byName.get(name.toLowerCase())
      if (found) return { status: found, name }
    }
    return { status: null, name: null }
  }
  const nodes: ChainNodeView[] = EXECUTION_CHAIN.map((node) => {
    if (node.id === 'simulation_supported') {
      return {
        node,
        status: view.simulationSupported ? 'READY' : 'BLOCKED',
        blockingInputs: [],
      }
    }
    const resolved = node.gatingInputs
      .flatMap((gating) => inputsStatus(alias[gating] ?? [gating]))
      .filter((hit): hit is { status: Availability; name: string } => hit.status !== null)
    const missing = resolved.filter((hit) => hit.status === 'MISSING')
    const unverified = resolved.filter((hit) => hit.status === 'UNVERIFIED')
    if (missing.length > 0) {
      return { node, status: 'BLOCKED', blockingInputs: missing.map((hit) => hit.name) }
    }
    if (unverified.length > 0) {
      return { node, status: 'UNVERIFIED', blockingInputs: unverified.map((hit) => hit.name) }
    }
    return { node, status: 'READY', blockingInputs: [] }
  })
  const upstreamOf = (nodeId: string): ChainNodeView[] =>
    EXECUTION_CHAIN.filter((candidate) => candidate.downstream.includes(nodeId))
      .map((candidate) => nodes.find((n) => n.node.id === candidate.id))
      .filter((n): n is ChainNodeView => Boolean(n))

  const effective = (node: ChainNodeView): ChainNodeStatus => {
    const upstream = upstreamOf(node.node.id)
    const upstreamStatus = upstream.reduce<ChainNodeStatus>(
      (worst, n) => worse(worst, effective(n)),
      'READY',
    )
    return worse(upstreamStatus, node.status)
  }
  const overall: ExecutionStatus = nodes.some((n) => effective(n) === 'BLOCKED')
    ? 'BLOCKED'
    : nodes.some((n) => effective(n) === 'UNVERIFIED')
      ? 'BLOCKED'
      : 'READY'
  const withEffective = nodes.map((n) => ({ ...n, status: effective(n) }))
  return { nodes: withEffective, overall }
}

/** BLOCKED > UNVERIFIED > READY ordering for dependency propagation. */
function worse(a: ChainNodeStatus, b: ChainNodeStatus): ChainNodeStatus {
  const severity: Record<ChainNodeStatus, number> = { BLOCKED: 2, UNVERIFIED: 1, READY: 0, NOT_RUN: -1 }
  return severity[a] >= severity[b] ? a : b
}

/** Recommended next action (spec §六/§三十一): a single actionable step. */
export interface NextAction {
  kind: 'CONTINUE' | 'FILL_INPUTS' | 'PROVIDE_PRIOR' | 'COMPLETE'
  message: string
  detail: string
  missingInputs: string[]
}

export function recommendNextAction(view: CapabilityReportView | null, runStatus: string | null): NextAction {
  if (!view) {
    return {
      kind: 'CONTINUE',
      message: '运行能力预检',
      detail: '尚未生成 ScientificCapabilityReport，先运行 assess_capability。',
      missingInputs: [],
    }
  }
  const missing = view.inputs.filter((input) => input.status === 'MISSING')
  if (missing.length > 0) {
    return {
      kind: 'FILL_INPUTS',
      message: `补充 ${missing.map((m) => m.name).join('、')}`,
      detail: '这些输入缺失，将阻塞后续物理链（见左侧执行能力依赖图）。',
      missingInputs: missing.map((m) => m.name),
    }
  }
  const unverified = view.inputs.filter((input) => input.status === 'UNVERIFIED')
  if (unverified.length > 0) {
    return {
      kind: 'FILL_INPUTS',
      message: `确认 ${unverified.map((m) => m.name).join('、')}`,
      detail: '这些输入尚未验证，仿真将降级或阻塞。',
      missingInputs: unverified.map((m) => m.name),
    }
  }
  if (runStatus !== 'completed') {
    return {
      kind: 'CONTINUE',
      message: '继续推进主链',
      detail: '能力预检就绪，继续运行知识/标定/规划阶段。',
      missingInputs: [],
    }
  }
  return {
    kind: 'COMPLETE',
    message: '主链已运行完成',
    detail: '在左侧各 section 中查看产物；如有实验数据可记录 Observation 进入闭环。',
    missingInputs: [],
  }
}
