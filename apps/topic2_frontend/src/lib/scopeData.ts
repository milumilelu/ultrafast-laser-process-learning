/** 按当前 Task Scope 加载实验数据并计算执行门槛。
 *  所有页面展示的 DataProfile 必须是当前 scope 的，而不是全库统计。 */

import { useCallback, useEffect } from 'react'

import { topic2Api } from '../api/topic2'
import { taskContextToScope, scopeDataGates } from './scope'
import type { DataGates } from './scope'
import { useScienceStore } from '../stores/science'
import { useTaskContextStore } from '../stores/taskContext'

export function useScopeExperiments(): {
  gates: DataGates | null
  loading: boolean
  experiments: ReturnType<typeof useScienceStore.getState>['experiments']
} {
  const context = useTaskContextStore((state) => state.context)
  const setExperiments = useScienceStore((state) => state.setExperiments)
  const experiments = useScienceStore((state) => state.experiments)
  const loading = useScienceStore((state) => state.experimentsLoading)

  useEffect(() => {
    let cancelled = false
    let scope
    try {
      scope = taskContextToScope(context)
    } catch {
      setExperiments([])
      return () => {
        cancelled = true
      }
    }
    setExperiments([], null, true)
    topic2Api
      .experiments({
        material: scope.material,
        laser_type: scope.laser_type,
        equipment_id: scope.equipment_id,
        geometry_type: scope.geometry_type,
      })
      .then((result) => {
        if (!cancelled) setExperiments(result.items)
      })
      .catch(() => {
        if (!cancelled) setExperiments([])
      })
    return () => {
      cancelled = true
    }
  }, [
    context.materialId,
    context.laserType,
    context.datasetEquipmentId,
    context.processType,
    setExperiments,
  ])

  const gates = useCallback((): DataGates | null => {
    const valid = experiments.filter((row) => row.valid_flag === 1)
    const designs = new Set(valid.map((row) => row.parameter_combination_id)).size
    const target = context.objective === 'quality_first' ? 'roughness_um' : 'depth_um'
    const optimizationSamples = valid.filter((row) => row[target] !== null).length
    return scopeDataGates(valid.length, designs, optimizationSamples)
  }, [experiments, context.objective])

  return { gates: gates(), loading, experiments }
}
