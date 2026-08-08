/** Run flow helper: create on first launch, continue-in-place afterwards.
 * Never creates a second run for the same task (spec FE-10).
 */

import { runsApi } from '../../api/runs'
import { getTaskDraft, saveTaskDraft, type TaskDraft } from '../../stores/taskDrafts'

export interface RunFlowResult {
  runId: string
  created: boolean
  status: string
}

export async function createOrContinueRun(
  taskId: string,
  stages?: string[],
): Promise<RunFlowResult> {
  const draft = getTaskDraft(taskId)
  if (!draft) throw new Error(`task draft not found: ${taskId}`)
  if (!draft.runId) {
    const summary = await runsApi.createRun({
      mode: 'research',
      task_spec: {
        material: draft.material,
        laser_type: draft.laserType,
        process_type: draft.processType,
        geometry_type: draft.geometryType,
        objective_metric: draft.objectiveMetric,
        equipment_profile_id: draft.equipmentProfileId,
        task_context_id: draft.taskContextRef ?? undefined,
        task_context_version: draft.taskContextRef ? draft.version : undefined,
      },
      stages,
      client_request_id: `task-${draft.taskId}`,
    })
    saveTaskDraft({ ...draft, runId: summary.application_run_id })
    return { runId: summary.application_run_id, created: true, status: summary.status }
  }
  const summary = await runsApi.continueRun(draft.runId, { stages })
  return { runId: summary.application_run_id, created: false, status: summary.status }
}

export function assertTaskDraftComplete(draft: TaskDraft): boolean {
  return Boolean(
    draft.material &&
      draft.laserType &&
      draft.geometryType &&
      draft.objectiveMetric &&
      draft.equipmentProfileId,
  )
}
