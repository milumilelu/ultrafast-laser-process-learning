/** Task draft (Draft State, spec §26.3). Local, editable, submitted to the
 * backend as a task_spec when an ApplicationRun is created. The backend run
 * is the source of truth once created.
 */

export interface TaskDraft {
  taskId: string
  name: string
  material: string
  laserType: 'fs' | 'ps' | ''
  processType: string
  geometryType: string
  objectiveMetric: 'depth_um' | 'roughness_um' | ''
  equipmentProfileId: string
  taskContextRef: string | null
  runId: string | null
  version: number
  updatedAt: string
}

const STORAGE_KEY = 'task-drafts-v3'

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
    equipmentProfileId: '',
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
    return Array.isArray(parsed) ? parsed : []
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
  return updated
}

/** Map a draft to the backend task_spec contract (service._scope keys). */
export function draftToTaskSpec(draft: TaskDraft): Record<string, unknown> {
  return {
    material: draft.material,
    laser_type: draft.laserType,
    process_type: draft.processType,
    geometry_type: draft.geometryType,
    objective_metric: draft.objectiveMetric,
    equipment_profile_id: draft.equipmentProfileId,
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
      draft.equipmentProfileId,
  )
}
