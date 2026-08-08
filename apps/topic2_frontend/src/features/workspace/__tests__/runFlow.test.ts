import { createOrContinueRun } from '../runFlow'
import { getTaskDraft, saveTaskDraft } from '../../../stores/taskDrafts'
import { runsApi } from '../../../api/runs'

const COMPLETE_DRAFT = {
  taskId: 'TASK-TEST',
  name: 't',
  material: 'SiC',
  laserType: 'fs' as const,
  processType: 'fs_laser_processing',
  geometryType: 'rectangular_groove',
  objectiveMetric: 'depth_um' as const,
  equipmentProfileId: 'EQ-1',
  taskContextRef: null,
  runId: null,
  version: 1,
  updatedAt: new Date().toISOString(),
}

describe('createOrContinueRun (spec FE-10)', () => {
  beforeEach(() => {
    localStorage.clear()
    saveTaskDraft(COMPLETE_DRAFT)
  })

  afterEach(() => {
    localStorage.clear()
    vi.unstubAllGlobals()
  })

  it('first launch creates one run and persists runId', async () => {
    const createSpy = vi.spyOn(runsApi, 'createRun').mockResolvedValue({
      application_run_id: 'run-1',
      status: 'running',
      task_context_ref: '',
      mode: 'research',
      workflow_version: 'v1',
      stage_status: {},
      created_at: '2026-01-01T00:00:00Z',
      completed_at: null,
    })
    const continueSpy = vi.spyOn(runsApi, 'continueRun')

    const result = await createOrContinueRun('TASK-TEST')

    expect(result).toMatchObject({ runId: 'run-1', created: true })
    expect(createSpy).toHaveBeenCalledTimes(1)
    expect(continueSpy).not.toHaveBeenCalled()
    expect(getTaskDraft('TASK-TEST')?.runId).toBe('run-1')
  })

  it('second launch continues the SAME run, never creates a second one', async () => {
    const createSpy = vi.spyOn(runsApi, 'createRun')
    const continueSpy = vi.spyOn(runsApi, 'continueRun').mockResolvedValue({
      application_run_id: 'run-1',
      status: 'running',
      task_context_ref: '',
      mode: 'research',
      workflow_version: 'v1',
      stage_status: { assess_capability: { status: 'completed' } },
      created_at: '2026-01-01T00:00:00Z',
      completed_at: null,
    })
    saveTaskDraft({ ...COMPLETE_DRAFT, runId: 'run-1' })

    const result = await createOrContinueRun('TASK-TEST', ['satisfy_requirements'])

    expect(result).toMatchObject({ runId: 'run-1', created: false })
    expect(continueSpy).toHaveBeenCalledTimes(1)
    expect(createSpy).not.toHaveBeenCalled()
    expect(continueSpy.mock.calls[0][0]).toBe('run-1')
  })

  it('client_request_id is stable per task (idempotent create)', async () => {
    const createSpy = vi.spyOn(runsApi, 'createRun').mockResolvedValue({
      application_run_id: 'run-1',
      status: 'running',
      task_context_ref: '',
      mode: 'research',
      workflow_version: 'v1',
      stage_status: {},
      created_at: '2026-01-01T00:00:00Z',
      completed_at: null,
    })
    await createOrContinueRun('TASK-TEST')
    const payload = createSpy.mock.calls[0][0] as { client_request_id?: string; task_spec?: Record<string, unknown> }
    expect(payload.client_request_id).toBe('task-TASK-TEST')
    expect(payload.task_spec?.material).toBe('SiC')
    expect(payload.task_spec?.objective_metric).toBe('depth_um')
  })
})
