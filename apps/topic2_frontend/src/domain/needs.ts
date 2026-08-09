/** ScientificNeedSet view model (M6) — four-way need classification. */

export type ScientificNeedType =
  | 'RESOURCE_INPUT'
  | 'SCIENTIFIC_KNOWLEDGE'
  | 'CALIBRATION_OBSERVATION'
  | 'TARGET_DATA'

export interface ScientificNeedView {
  needId: string
  needType: ScientificNeedType
  target: string
  question: string
  requiredFor: string
  priority: string
  triggerReasons: string[]
  resolutionTarget: string
  satisfactionCriteria: string[]
}

export interface NeedsView {
  needs: ScientificNeedView[]
  byType: Record<ScientificNeedType, ScientificNeedView[]>
  counts: Record<ScientificNeedType, number>
}

export interface NeedsContent {
  schema_version?: string
  needs?: Array<{
    need_id?: string
    need_type?: string
    target?: string
    question?: string
    required_for?: string
    priority?: string
    trigger_reasons?: string[]
    resolution_target?: string
    satisfaction_criteria?: string[]
  }>
}

export const NEED_TYPE_LABEL: Record<ScientificNeedType, string> = {
  RESOURCE_INPUT: '资源输入',
  SCIENTIFIC_KNOWLEDGE: '科学知识（文献）',
  CALIBRATION_OBSERVATION: '标定观测（实验）',
  TARGET_DATA: '目标数据（数据集）',
}

export const NEED_TONE: Record<ScientificNeedType, 'ok' | 'warn' | 'err' | 'neutral' | 'info'> = {
  RESOURCE_INPUT: 'info',
  SCIENTIFIC_KNOWLEDGE: 'warn',
  CALIBRATION_OBSERVATION: 'neutral',
  TARGET_DATA: 'err',
}

export const RESOLUTION_TARGET_LABEL: Record<string, string> = {
  EQUIPMENT_MANAGER: '设备管理',
  LITERATURE_RETRIEVAL: '文献检索',
  EXPERIMENT_OBSERVATION: '实验观测',
  DATASET: '数据集',
}

export function normalizeNeedType(raw: string): ScientificNeedType {
  const value = raw.toUpperCase().replace(/-/g, '_')
  if (
    value === 'RESOURCE_INPUT' ||
    value === 'SCIENTIFIC_KNOWLEDGE' ||
    value === 'CALIBRATION_OBSERVATION' ||
    value === 'TARGET_DATA'
  ) {
    return value
  }
  return 'TARGET_DATA'
}

export function buildNeedsView(content: NeedsContent | null | undefined): NeedsView {
  const raw = content ?? {}
  const needs: ScientificNeedView[] = (raw.needs ?? []).map((need) => ({
    needId: String(need.need_id ?? ''),
    needType: normalizeNeedType(String(need.need_type ?? '')),
    target: String(need.target ?? ''),
    question: String(need.question ?? ''),
    requiredFor: String(need.required_for ?? ''),
    priority: String(need.priority ?? 'medium'),
    triggerReasons: Array.isArray(need.trigger_reasons) ? need.trigger_reasons.map(String) : [],
    resolutionTarget: String(need.resolution_target ?? ''),
    satisfactionCriteria: Array.isArray(need.satisfaction_criteria)
      ? need.satisfaction_criteria.map(String)
      : [],
  }))
  const byType: Record<ScientificNeedType, ScientificNeedView[]> = {
    RESOURCE_INPUT: [],
    SCIENTIFIC_KNOWLEDGE: [],
    CALIBRATION_OBSERVATION: [],
    TARGET_DATA: [],
  }
  for (const need of needs) {
    byType[need.needType].push(need)
  }
  const counts = {
    RESOURCE_INPUT: byType.RESOURCE_INPUT.length,
    SCIENTIFIC_KNOWLEDGE: byType.SCIENTIFIC_KNOWLEDGE.length,
    CALIBRATION_OBSERVATION: byType.CALIBRATION_OBSERVATION.length,
    TARGET_DATA: byType.TARGET_DATA.length,
  }
  return { needs, byType, counts }
}
