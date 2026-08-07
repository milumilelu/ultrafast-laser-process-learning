import { useEffect } from 'react'

import { topic2Api } from '../api/topic2'
import { useTaskContextStore } from '../stores/taskContext'

/** Persist the browser projection into Topic2's immutable TaskContext store. */
export function TaskContextSync() {
  const context = useTaskContextStore((state) => state.context)

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void topic2Api
        .saveTaskContext(context.taskContextId, context.version, {
          task_context_id: context.taskContextId,
          version: context.version,
          material: context.materialId,
          material_grade: context.materialGrade,
          laser_type: context.laserType,
          equipment_profile_id: context.equipmentId,
          dataset_equipment_id: context.datasetEquipmentId,
          process_type: context.processType,
          process_parameters: context.processParams,
          objective: context.objective,
          target_metrics: context.targetMetrics,
          device_properties: context.deviceProperties,
          dataset_id: context.datasetId,
          selected_model_id: context.selectedModelId,
          created_at: context.createdAt,
          updated_at: context.updatedAt,
        })
        .catch((error: unknown) => {
          console.warn('TaskContext server sync failed', error)
        })
    }, 150)
    return () => window.clearTimeout(timer)
  }, [context])

  return null
}
