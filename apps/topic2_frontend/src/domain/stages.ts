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

/** Workspace sections are pure display: each maps to a backend-computed
 * RunControlState.phases entry (阶段三 T1).  The frontend performs zero
 * workflow transition logic - it only renders the phase status verbatim. */
export interface WorkspaceSection {
  id: 'overview' | 'capability' | 'knowledge' | 'calibration' | 'simulation' | 'planning'
  label: string
  /** RunControlState.phases key whose status this section displays. */
  phase?: string
}

export const WORKSPACE_SECTIONS: WorkspaceSection[] = [
  { id: 'overview', label: '总览' },
  { id: 'capability', label: '能力', phase: 'CAPABILITY' },
  { id: 'knowledge', label: '知识', phase: 'KNOWLEDGE' },
  { id: 'calibration', label: '标定', phase: 'CALIBRATION' },
  { id: 'simulation', label: '仿真', phase: 'SIMULATION' },
  { id: 'planning', label: '规划', phase: 'PLANNING' },
]

export function stageIndex(stage: CanonicalStage): number {
  return CANONICAL_STAGES.indexOf(stage)
}

export function stagesThrough(stage: CanonicalStage): CanonicalStage[] {
  return CANONICAL_STAGES.slice(0, stageIndex(stage) + 1)
}
