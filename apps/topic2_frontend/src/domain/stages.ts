/** Canonical Physics-to-Planning workflow stages (backend ALL_STAGES). */

export const CANONICAL_STAGES = [
  'prepare_task',
  'assess_capability',
  'assess_data',
  'baseline_learning',
  'analyze_knowledge_requirements',
  'prepare_knowledge',
  'satisfy_requirements',
  'calibrate_physics',
  'establish_process_model',
  'plan_process',
] as const

export type CanonicalStage = (typeof CANONICAL_STAGES)[number]

export const STAGE_LABEL: Record<CanonicalStage, string> = {
  prepare_task: '任务准备',
  assess_capability: '能力预检',
  assess_data: '数据评估',
  baseline_learning: '基线学习',
  analyze_knowledge_requirements: '知识需求分析',
  prepare_knowledge: '知识准备',
  satisfy_requirements: '需求满足',
  calibrate_physics: '物理标定',
  establish_process_model: '过程建模',
  plan_process: '路径规划',
}

/** Workspace sections map to the checkpoint they unlock (spec §三). */
export interface WorkspaceSection {
  id: 'overview' | 'capability' | 'knowledge' | 'calibration' | 'simulation' | 'planning'
  label: string
  /** Backend stage whose completion makes this section meaningful. */
  unlockStage?: CanonicalStage
  /** Next-iteration sections that are not yet implemented in the frontend. */
  pending?: boolean
}

export const WORKSPACE_SECTIONS: WorkspaceSection[] = [
  { id: 'overview', label: '总览' },
  { id: 'capability', label: '能力', unlockStage: 'assess_capability' },
  { id: 'knowledge', label: '知识', unlockStage: 'satisfy_requirements' },
  { id: 'calibration', label: '标定', unlockStage: 'calibrate_physics' },
  { id: 'simulation', label: '仿真', unlockStage: 'establish_process_model', pending: true },
  { id: 'planning', label: '规划', unlockStage: 'plan_process', pending: true },
]

/** Continue-to checkpoints for the "继续" control (spec §三十二). */
export const CHECKPOINT_STAGES: CanonicalStage[] = [
  'assess_capability',
  'satisfy_requirements',
  'calibrate_physics',
  'plan_process',
]

export function stageIndex(stage: CanonicalStage): number {
  return CANONICAL_STAGES.indexOf(stage)
}

export function stagesThrough(stage: CanonicalStage): CanonicalStage[] {
  return CANONICAL_STAGES.slice(0, stageIndex(stage) + 1)
}
