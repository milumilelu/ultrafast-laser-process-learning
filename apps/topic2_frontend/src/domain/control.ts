/** RunControlState view model (M6).
 *
 * The backend is the single source of truth for run status: the frontend
 * renders RunControlState and never derives workflow state from stages.
 */

export interface GateView {
  gate: string
  status: 'READY' | 'PARTIAL' | 'BLOCKED' | 'NOT_RUN'
  reasons: string[]
  nextActions: { type: string; missing?: string[]; parameters?: string[]; source_quality?: string }[]
}

export interface NextActionView {
  type: string
  missing?: string[]
  parameters?: string[]
  sourceQuality?: string
  resumeStage?: string
  targetPhase?: string
  requirementIds?: string[]
  observationTypes?: string[]
}

export interface PhaseView {
  status: 'READY' | 'PARTIAL' | 'BLOCKED' | 'COMPLETED' | 'NOT_RUN'
  blockingReasons: string[]
}

export interface RunControlView {
  schemaVersion: string
  executionMode: string
  currentPhase: string
  phaseStatus: 'READY' | 'PARTIAL' | 'BLOCKED' | 'COMPLETED' | 'NOT_RUN'
  /** Backend-computed per-phase status (阶段三 T1): the frontend renders
   * these verbatim and performs zero gate-to-phase interpretation. */
  phases: Record<string, PhaseView>
  gates: Record<string, GateView>
  blockingReasons: string[]
  nextActions: NextActionView[]
  completedStages: string[]
  provisional: boolean
}

export interface RunControlContent {
  schema_version?: string
  execution_mode?: string
  current_phase?: string
  phase_status?: string
  phases?: Record<string, { status?: string; blocking_reasons?: string[] }>
  gates?: Record<string, unknown>
  blocking_reasons?: string[]
  next_actions?: Array<Record<string, unknown>>
  completed_stages?: string[]
  provisional?: boolean
}

export type PhaseStatus = RunControlView['phaseStatus']

export function buildRunControl(content: RunControlContent | null | undefined): RunControlView {
  const raw = content ?? {}
  const gatesRaw = (raw.gates ?? {}) as Record<string, Record<string, unknown>>
  const gates: Record<string, GateView> = {}
  for (const [name, gate] of Object.entries(gatesRaw)) {
    const gateStatus = String(gate.status ?? 'NOT_RUN').toUpperCase().replace(/-/g, '_')
    gates[name] = {
      gate: String(gate.gate ?? name),
      status:
        gateStatus === 'READY' || gateStatus === 'PARTIAL' || gateStatus === 'BLOCKED'
          ? gateStatus
          : 'NOT_RUN',
      reasons: Array.isArray(gate.reasons) ? gate.reasons.map(String) : [],
      nextActions: Array.isArray(gate.next_actions)
        ? gate.next_actions.map((action: Record<string, unknown>) => ({
            type: String(action.type ?? ''),
            missing: Array.isArray(action.missing) ? action.missing.map(String) : undefined,
            parameters: Array.isArray(action.parameters) ? action.parameters.map(String) : undefined,
            sourceQuality: action.source_quality ? String(action.source_quality) : undefined,
            resumeStage: action.resume_stage ? String(action.resume_stage) : undefined,
            targetPhase: action.target_phase ? String(action.target_phase) : undefined,
            requirementIds: Array.isArray(action.requirement_ids)
              ? action.requirement_ids.map(String)
              : undefined,
            observationTypes: Array.isArray(action.observation_types)
              ? action.observation_types.map(String)
              : undefined,
          }))
        : [],
    }
  }
  const phasesRaw = (raw.phases ?? {}) as Record<string, Record<string, unknown>>
  const phases: Record<string, PhaseView> = {}
  for (const [name, phase] of Object.entries(phasesRaw)) {
    const phaseStatus = normalizePhase(String(phase.status ?? 'NOT_RUN'))
    phases[name] = {
      status: phaseStatus,
      blockingReasons: Array.isArray(phase.blocking_reasons)
        ? phase.blocking_reasons.map(String)
        : [],
    }
  }
  const phase = normalizePhase(String(raw.phase_status ?? 'NOT_RUN'))
  return {
    schemaVersion: String(raw.schema_version ?? ''),
    executionMode: String(raw.execution_mode ?? ''),
    currentPhase: String(raw.current_phase ?? ''),
    phaseStatus: phase,
    phases,
    gates,
    blockingReasons: Array.isArray(raw.blocking_reasons)
      ? raw.blocking_reasons.map(String)
      : [],
    nextActions: Array.isArray(raw.next_actions)
      ? raw.next_actions.map((action: Record<string, unknown>) => ({
          type: String(action.type ?? ''),
          missing: Array.isArray(action.missing) ? action.missing.map(String) : undefined,
          parameters: Array.isArray(action.parameters) ? action.parameters.map(String) : undefined,
          sourceQuality: action.source_quality ? String(action.source_quality) : undefined,
          resumeStage: action.resume_stage ? String(action.resume_stage) : undefined,
          targetPhase: action.target_phase ? String(action.target_phase) : undefined,
          requirementIds: Array.isArray(action.requirement_ids)
            ? action.requirement_ids.map(String)
            : undefined,
          observationTypes: Array.isArray(action.observation_types)
            ? action.observation_types.map(String)
            : undefined,
        }))
      : [],
    completedStages: Array.isArray(raw.completed_stages)
      ? raw.completed_stages.map(String)
      : [],
    provisional: Boolean(raw.provisional),
  }
}

export function normalizePhase(raw: string): PhaseStatus {
  const value = raw.toUpperCase().replace(/-/g, '_')
  if (value === 'READY' || value === 'PARTIAL' || value === 'BLOCKED' || value === 'COMPLETED') {
    return value
  }
  return 'NOT_RUN'
}

export const PHASE_LABEL: Record<PhaseStatus, string> = {
  READY: '就绪',
  PARTIAL: '部分就绪',
  BLOCKED: '受阻',
  COMPLETED: '已完成',
  NOT_RUN: '未运行',
}

export const GATE_LABEL: Record<string, string> = {
  A: '资源就绪 (Gate A)',
  B: '知识就绪 (Gate B)',
  C: '物理模型 (Gate C)',
  D: '规划就绪 (Gate D)',
}

export const PHASE_LABEL_SHORT: Record<string, string> = {
  CAPABILITY: '能力预检',
  KNOWLEDGE: '知识解析',
  CALIBRATION: '物理标定',
  MODEL: '过程建模',
  SIMULATION: '形貌仿真',
  PLANNING: '路径规划',
  OBSERVATION: '观察闭环',
  COMPLETED: '完成',
  UNKNOWN: '未知',
}
