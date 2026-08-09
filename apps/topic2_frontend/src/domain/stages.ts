/** Stage labels are presentation-only; ordering/status come from backend events. */
export const STAGE_LABEL: Record<string, string> = {
  prepare_task: '任务准备',
  assess_capability: '能力预检',
  assess_data: '数据评估',
  baseline_learning: '基线学习',
  analyze_knowledge_requirements: '知识需求分析',
  prepare_knowledge: '知识准备',
  satisfy_requirements: '需求满足',
  calibrate_physics: '物理标定',
  establish_process_model: '过程建模',
  simulate_morphology: '形貌仿真',
  plan_process: '路径规划',
  evaluate_observation: '观察闭环',
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
