/** Status namespaces (Physics-to-Planning V3 workbench).
 *
 * Three strictly separated namespaces (spec §二十四 / §二十五):
 * - ExecutionStatus: whether a workflow capability HAS RUN or CAN run.
 * - ScientificStatus: what we know about the science.
 * - ParameterStatus: where a parameter value comes from.
 *
 * An execution capability (e.g. Simulator) must never be labeled UNKNOWN.
 * The type system enforces this by construction.
 */

export type ExecutionStatus = 'NOT_RUN' | 'RUNNING' | 'READY' | 'BLOCKED' | 'FAILED'

export type ScientificStatus = 'KNOWN' | 'PARTIAL' | 'UNKNOWN' | 'MISMATCH'

export type ParameterStatus =
  | 'MEASURED'
  | 'DERIVED'
  | 'PRIOR_ONLY'
  | 'CALIBRATED'
  | 'PROVISIONAL'
  | 'NOT_IDENTIFIABLE'
  | 'MISSING'

export type Tone = 'ok' | 'warn' | 'err' | 'neutral' | 'info'

/** Backend enum values may arrive in PascalCase; normalize defensively. */
function normalize(value: string | null | undefined): string {
  return (value ?? '').toUpperCase().replace(/-/g, '_')
}

/* ---------------------------- ExecutionStatus ---------------------------- */

const EXECUTION_TONE: Record<ExecutionStatus, Tone> = {
  NOT_RUN: 'neutral',
  RUNNING: 'info',
  READY: 'ok',
  BLOCKED: 'warn',
  FAILED: 'err',
}

const EXECUTION_LABEL: Record<ExecutionStatus, string> = {
  NOT_RUN: '未运行',
  RUNNING: '运行中',
  READY: '就绪',
  BLOCKED: '受阻',
  FAILED: '失败',
}

export function executionTone(status: ExecutionStatus): Tone {
  return EXECUTION_TONE[status]
}

export function executionLabel(status: ExecutionStatus): string {
  return EXECUTION_LABEL[status]
}

/** Parse a backend stage/run status into the ExecutionStatus namespace. */
export function executionStatusFrom(raw: string | null | undefined): ExecutionStatus {
  const value = normalize(raw)
  switch (value) {
    case 'RUNNING':
    case 'IN_PROGRESS':
      return 'RUNNING'
    case 'COMPLETED':
    case 'DONE':
      return 'READY'
    case 'FAILED':
    case 'ERROR':
      return 'FAILED'
    case 'BLOCKED':
    case 'BLOCKING':
      return 'BLOCKED'
    default:
      return 'NOT_RUN'
  }
}

/* ---------------------------- ScientificStatus --------------------------- */

const SCIENTIFIC_TONE: Record<ScientificStatus, Tone> = {
  KNOWN: 'ok',
  PARTIAL: 'warn',
  UNKNOWN: 'neutral',
  MISMATCH: 'err',
}

const SCIENTIFIC_LABEL: Record<ScientificStatus, string> = {
  KNOWN: '已知',
  PARTIAL: '部分',
  UNKNOWN: '未知',
  MISMATCH: '不匹配',
}

export function scientificTone(status: ScientificStatus): Tone {
  return SCIENTIFIC_TONE[status]
}

export function scientificLabel(status: ScientificStatus): string {
  return SCIENTIFIC_LABEL[status]
}

export function scientificStatusFrom(raw: string | null | undefined): ScientificStatus {
  const value = normalize(raw)
  switch (value) {
    case 'KNOWN':
      return 'KNOWN'
    case 'PARTIAL':
    case 'PARTIALLY_SATISFIED':
      return 'PARTIAL'
    case 'MISMATCH':
    case 'CONTRADICTED':
      return 'MISMATCH'
    default:
      return 'UNKNOWN'
  }
}

/* ----------------------------- ParameterStatus --------------------------- */

const PARAMETER_TONE: Record<ParameterStatus, Tone> = {
  MEASURED: 'ok',
  DERIVED: 'info',
  PRIOR_ONLY: 'warn',
  CALIBRATED: 'ok',
  PROVISIONAL: 'warn',
  NOT_IDENTIFIABLE: 'neutral',
  MISSING: 'neutral',
}

const PARAMETER_LABEL: Record<ParameterStatus, string> = {
  MEASURED: '实测',
  DERIVED: '派生',
  PRIOR_ONLY: '仅文献先验',
  CALIBRATED: '已标定',
  PROVISIONAL: '临时有效值',
  NOT_IDENTIFIABLE: '当前数据不可辨识',
  MISSING: '缺失',
}

export function parameterTone(status: ParameterStatus): Tone {
  return PARAMETER_TONE[status]
}

export function parameterLabel(status: ParameterStatus): string {
  return PARAMETER_LABEL[status]
}

/** Semantic values from backend (PHYSICAL / EFFECTIVE / PROVISIONAL). */
export type ParameterSemantics = 'PHYSICAL' | 'EFFECTIVE' | 'PROVISIONAL'

export const SEMANTICS_LABEL: Record<ParameterSemantics, string> = {
  PHYSICAL: '物理常数',
  EFFECTIVE: '有效参数',
  PROVISIONAL: '临时推算值',
}

/* ----------------------------- shared helpers ---------------------------- */

export function isExecutionStatus(value: string): value is ExecutionStatus {
  return value in EXECUTION_LABEL
}

export function isScientificStatus(value: string): value is ScientificStatus {
  return value in SCIENTIFIC_LABEL
}

export function isParameterStatus(value: string): value is ParameterStatus {
  return value in PARAMETER_LABEL
}
