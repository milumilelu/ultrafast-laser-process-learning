/** Task draft (Draft State, spec §26.3). Local, editable, submitted to the
 * backend as a task_spec when an ApplicationRun is created. The backend run
 * is the source of truth once created.
 */

import { useEffect, useState } from 'react'

export interface TaskDraft {
  taskId: string
  name: string
  material: string
  laserType: 'fs' | 'ps' | ''
  processType: string
  geometryType: string
  objectiveMetric: 'depth_um' | 'roughness_um' | ''
  datasetRef: string
  equipmentProfileId: string
  equipmentRevisionId: string
  /** Actual average-power setpoint at the material surface for this task. */
  workpieceIncidentPowerW: number
  /** TargetGeometry is mandatory in RESEARCH (Gate A, 阶段二 T1). */
  targetGeometry: {
    geometry_type: string
    width_um: number
    height_um: number
    target_depth_um: number
    grid_spacing_um: number
  } | null
  /** The user workbench only creates fail-closed RESEARCH runs. */
  executionMode: 'RESEARCH'
  taskContextRef: string | null
  runId: string | null
  version: number
  updatedAt: string
}

const STORAGE_KEY = 'task-drafts-v4'
const taskDraftListeners = new Set<() => void>()

function notifyTaskDraftListeners(): void {
  taskDraftListeners.forEach((listener) => listener())
}

function subscribeTaskDrafts(listener: () => void): () => void {
  taskDraftListeners.add(listener)
  return () => taskDraftListeners.delete(listener)
}

export function newTaskId(): string {
  const count = listTaskDrafts().length + 1
  return `TASK-${String(count).padStart(3, '0')}`
}

export function emptyTaskDraft(): TaskDraft {
  return {
    taskId: newTaskId(),
    name: '',
    material: '',
    laserType: '',
    processType: 'fs_laser_processing',
    geometryType: '',
    objectiveMetric: '',
    datasetRef: '',
    equipmentProfileId: '',
    equipmentRevisionId: '',
    workpieceIncidentPowerW: 0,
    targetGeometry: null,
    executionMode: 'RESEARCH',
    taskContextRef: null,
    runId: null,
    version: 1,
    updatedAt: new Date().toISOString(),
  }
}

export function listTaskDrafts(): TaskDraft[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as TaskDraft[]
    return Array.isArray(parsed)
      ? parsed.map((draft) => ({
          ...draft,
          datasetRef: draft.datasetRef ?? '',
          equipmentRevisionId: draft.equipmentRevisionId ?? '',
          workpieceIncidentPowerW: Number(draft.workpieceIncidentPowerW) || 0,
          executionMode: 'RESEARCH',
        }))
      : []
  } catch {
    return []
  }
}

export function getTaskDraft(taskId: string): TaskDraft | null {
  return listTaskDrafts().find((draft) => draft.taskId === taskId) ?? null
}

export function saveTaskDraft(draft: TaskDraft): TaskDraft {
  const updated = { ...draft, updatedAt: new Date().toISOString() }
  const drafts = listTaskDrafts().filter((d) => d.taskId !== draft.taskId)
  drafts.push(updated)
  localStorage.setItem(STORAGE_KEY, JSON.stringify(drafts))
  notifyTaskDraftListeners()
  return updated
}

/** Reactive view of a local task draft.
 *
 * localStorage itself does not notify the tab that performed the write. This
 * hook bridges saveTaskDraft updates into React and also observes writes made
 * by another tab. Without it, a newly assigned runId and edited task context
 * remain stale until a full page reload.
 */
export function useTaskDraft(taskId: string): TaskDraft | null {
  const [draft, setDraft] = useState<TaskDraft | null>(() => getTaskDraft(taskId))

  useEffect(() => {
    const sync = () => setDraft(getTaskDraft(taskId))
    const unsubscribe = subscribeTaskDrafts(sync)
    const handleStorage = (event: StorageEvent) => {
      if (event.key === null || event.key === STORAGE_KEY) sync()
    }

    window.addEventListener('storage', handleStorage)
    sync()
    return () => {
      unsubscribe()
      window.removeEventListener('storage', handleStorage)
    }
  }, [taskId])

  return draft
}

/** Map a draft to the backend task_spec contract (service._scope keys). */
export function draftToTaskSpec(draft: TaskDraft): Record<string, unknown> {
  return {
    material: draft.material,
    laser_type: draft.laserType,
    process_type: draft.processType,
    geometry_type: draft.geometryType,
    objective_metric: draft.objectiveMetric,
    dataset_ref: draft.datasetRef,
    equipment_profile_id: draft.equipmentProfileId,
    execution_equipment_ref: {
      equipment_profile_id: draft.equipmentProfileId,
      revision_id: draft.equipmentRevisionId,
    },
    execution_mode: 'RESEARCH',
    process_parameters: {
      laser_power_W: draft.workpieceIncidentPowerW,
      laser_power_location: 'WORKPIECE_SURFACE_INCIDENT',
    },
    target_geometry: draft.targetGeometry ?? undefined,
    task_context_id: draft.taskContextRef ?? undefined,
    task_context_version: draft.taskContextRef ? draft.version : undefined,
  }
}

export function isTaskDraftComplete(draft: TaskDraft): boolean {
  return Boolean(
    draft.material &&
      draft.laserType &&
      draft.geometryType &&
      draft.objectiveMetric &&
      draft.datasetRef &&
      draft.equipmentProfileId &&
      draft.equipmentRevisionId &&
      draft.workpieceIncidentPowerW > 0 &&
      draft.targetGeometry &&
      draft.targetGeometry.target_depth_um > 0,
  )
}
