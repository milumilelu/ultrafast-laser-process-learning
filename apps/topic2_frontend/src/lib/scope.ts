/** Map the global TaskContext to the backend TaskScope. The scope is the only
 *  official scientific request shape; free-text fields never leak into it. */

import { objectiveToTarget, PROCESS_TASK_CANONICAL } from './canonical'
import type { TaskScope } from '../api/types'
import type { TaskContextState } from '../stores/taskContext'

export class IncompleteTaskContextError extends Error {
  constructor(missing: string[]) {
    super(`Task Context 不完整，缺少：${missing.join('、')}`)
    this.name = 'IncompleteTaskContextError'
  }
}

export function taskContextToScope(context: TaskContextState): TaskScope {
  const missing: string[] = []
  if (!context.materialId) missing.push('材料')
  if (!context.laserType) missing.push('激光类型')
  if (!context.datasetEquipmentId) missing.push('数据集设备')
  if (!context.processType) missing.push('加工任务')
  if (!context.objective) missing.push('加工目标')
  if (missing.length > 0) throw new IncompleteTaskContextError(missing)

  const material = context.materialId as string
  const laserType = context.laserType as TaskScope['laser_type']
  const equipmentId = context.datasetEquipmentId as string
  const processType = context.processType as NonNullable<TaskContextState['processType']>
  const target = objectiveToTarget(context.objective)
  if (!target) throw new IncompleteTaskContextError(['加工目标'])
  return {
    task_context_id: context.taskContextId,
    task_context_version: context.version,
    material,
    material_grade: context.materialGrade,
    laser_type: laserType,
    equipment_id: equipmentId,
    geometry_type: PROCESS_TASK_CANONICAL[processType],
    target,
    process_parameters: { ...context.processParams },
    device_properties: {
      ...context.deviceProperties,
      equipment_profile_id: context.equipmentId,
    },
  }
}

export interface DataGates {
  identification: boolean
  modeling: boolean
  optimization: boolean
}

/** 当前 scope 数据的执行门槛（与后端一致：辨识 ≥4 样本/≥2 设计；
 *  建模 ≥2 独立设计；优化 ≥5 完整样本）。纯计数，不做科学判定。 */
export function scopeDataGates(
  nSamples: number,
  nUniqueDesigns: number,
  nOptimizationSamples: number,
): DataGates {
  return {
    identification: nSamples >= 4 && nUniqueDesigns >= 2,
    modeling: nUniqueDesigns >= 2,
    optimization: nOptimizationSamples >= 5,
  }
}
