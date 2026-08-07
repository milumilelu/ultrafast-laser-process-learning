/** Build the structured context block the Agent receives for every message.
 *  Values come from the real TaskContext / PageContext stores — never invented. */

import {
  laserTypeLabel,
  materialLabel,
  objectiveLabel,
  objectiveToTarget,
  processParamLabel,
  processTaskLabel,
  targetLabel,
} from '../lib/canonical'
import type { PageName } from '../stores/pageContext'
import type { TaskContextState } from '../stores/taskContext'

export function formatTaskContextLine(context: TaskContextState | null): string {
  if (!context || !context.materialId || !context.laserType) return '未定义'
  const parts = [
    `材料=${materialLabel(context.materialId)}(${context.materialId})`,
    `激光=${laserTypeLabel(context.laserType)}`,
    `数据集设备=${context.datasetEquipmentId ?? '未设置'}`,
    `设备档案=${context.equipmentId ?? '未设置'}`,
    `加工任务=${context.processType ? processTaskLabel(context.processType) : '未设置'}`,
    `加工目标=${context.objective ? objectiveLabel(context.objective) : '未设置'}`,
  ]
  const params = Object.entries(context.processParams)
    .filter(([, value]) => value !== '' && value !== null && value !== undefined)
    .map(([key, value]) => `${processParamLabel(key) ?? key}=${String(value)}`)
  if (params.length > 0) parts.push(`任务参数=${params.join(',')}`)
  // 科学目标始终由加工目标派生，杜绝旧版本 targetMetrics 残留造成的语义矛盾。
  const derivedTarget = objectiveToTarget(context.objective)
  if (derivedTarget) parts.push(`科学目标=${targetLabel(derivedTarget)}`)
  return parts.join(' / ')
}

export function buildAgentSystemPrefix(
  task: TaskContextState | null,
  page: PageName,
  activeRunId: string | null | undefined,
  activeModelId: string | null | undefined,
): string {
  const lines = [
    `[TaskContext ${task?.taskContextId ?? 'none'} v${task?.version ?? '-'}] ${formatTaskContextLine(task)}`,
    `[PageContext] page=${page}${activeRunId ? ` active_run_id=${activeRunId}` : ''}${activeModelId ? ` active_model_id=${activeModelId}` : ''}`,
    `[Rule] 解释必须以实际后端运行结果与检索证据为依据，不得虚构科学指标。`,
  ]
  return lines.join('\n')
}
