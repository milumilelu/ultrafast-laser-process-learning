import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { CapabilitySection } from '../CapabilitySection'
import { OverviewSection } from '../../workspace/OverviewSection'
import { saveTaskDraft } from '../../../stores/taskDrafts'
import { runsApi } from '../../../api/runs'

function renderWithProviders(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

const capabilitySnapshot = {
  id: 'ScientificCapabilityReport-1',
  type: 'ScientificCapabilityReport',
  schema_version: 'physics-to-planning-v1',
  input_refs: [{ type: 'TaskState', id: 't1' }],
  created_at: '2026-01-01T00:00:00Z',
  content: {
    capability_id: 'cap-1',
    interaction_topology: 'SHALLOW_2_5D',
    simulation_supported: true,
    supported_fidelity: ['F2_DEFOCUS_RECURSION'],
    available: [{ name: 'frequency_kHz', value: 100, unit: 'kHz', status: 'AVAILABLE', source_refs: [{ type: 'MachineProfile', id: 'm1' }] }],
    missing: [
      { name: 'actual_power', value: null, unit: 'W', status: 'MISSING', source_refs: [] },
      { name: 'F_th', value: null, unit: 'J/cm2', status: 'MISSING', source_refs: [] },
    ],
    identifiability: [{ parameter: 'thermal_diffusivity', status: 'NOT_IDENTIFIABLE', reason_codes: ['terminal_depth_only'], required_observations: [] }],
    recommended_requirements: [
      { requirement_id: 'KR-001', type: 'PARAMETER_PRIOR', scientific_question: 'need SiC F_th', required_for: 'LogAblationModel.F_th', priority: 'high', trigger_reasons: ['computation_gap'], required_evidence_roles: ['THRESHOLD'], satisfaction_criteria: [], status: 'UNKNOWN' },
    ],
    status: 'PARTIAL',
    reason_codes: ['missing_inputs'],
  },
}

describe('CapabilitySection (spec §七-§九 / FE-4)', () => {
  it('renders the dependency chain with blockers', () => {
    renderWithProviders(<CapabilitySection artifact={capabilitySnapshot} />)
    expect(screen.getByText('执行能力依赖图')).toBeInTheDocument()
    expect(screen.getByText('激光功率')).toBeInTheDocument()
    expect(screen.getAllByText('受阻').length).toBeGreaterThan(0)
    expect(screen.getAllByText(/缺少: actual_power/).length).toBeGreaterThan(0)
  })

  it('renders input resolver with source classification', () => {
    renderWithProviders(<CapabilitySection artifact={capabilitySnapshot} />)
    expect(screen.getByText('输入解析器')).toBeInTheDocument()
    expect(screen.getByText('设备档案')).toBeInTheDocument()
    expect(screen.getAllByText('缺失').length).toBeGreaterThan(0)
  })

  it('renders empty state when no report exists', () => {
    renderWithProviders(<CapabilitySection />)
    expect(screen.getByText(/尚未生成 ScientificCapabilityReport/)).toBeInTheDocument()
  })
})

describe('OverviewSection (spec §六)', () => {
  beforeEach(() => {
    localStorage.clear()
    saveTaskDraft({
      taskId: 'TASK-OV',
      name: 'ov',
      material: 'SiC',
      laserType: 'fs',
      processType: 'fs_laser_processing',
      geometryType: 'rectangular_groove',
      objectiveMetric: 'depth_um',
      equipmentProfileId: 'EQ-1',
      taskContextRef: null,
      runId: null,
      version: 1,
      updatedAt: new Date().toISOString(),
    })
  })

  afterEach(() => localStorage.clear())

  it('shows four readiness cards and a single next action (FE-1: values from artifacts)', () => {
    const artifacts = new Map([['ScientificCapabilityReport', capabilitySnapshot]])
    renderWithProviders(
      <OverviewSection
        taskId="TASK-OV"
        runStatus={null}
        artifacts={artifacts}
        run={null}
        events={[]}
        busy={false}
        onContinue={() => undefined}
        nextCheckpoint="assess_capability"
      />,
    )
    expect(screen.getByText('Scientific Capability')).toBeInTheDocument()
    expect(screen.getByText('Knowledge')).toBeInTheDocument()
    expect(screen.getByText('Physical Model')).toBeInTheDocument()
    expect(screen.getByText('Planning')).toBeInTheDocument()
    expect(screen.getByText('Recommended Next Action')).toBeInTheDocument()
    expect(screen.getByText(/补充 actual_power、F_th/)).toBeInTheDocument()
  })

  it('"开始运行" creates the first run and never shows a second run', async () => {
    const createSpy = vi.spyOn(runsApi, 'createRun').mockResolvedValue({
      application_run_id: 'run-ov',
      status: 'running',
      task_context_ref: '',
      mode: 'research',
      workflow_version: 'v1',
      stage_status: {},
      created_at: '2026-01-01T00:00:00Z',
      completed_at: null,
    })
    const continueSpy = vi.spyOn(runsApi, 'continueRun')
    const onContinue = vi.fn()
    renderWithProviders(
      <OverviewSection
        taskId="TASK-OV"
        runStatus={null}
        artifacts={new Map()}
        run={null}
        events={[]}
        busy={false}
        onContinue={onContinue}
        nextCheckpoint={null}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: '开始运行' }))
    expect(onContinue).toHaveBeenCalledTimes(1)
    expect(createSpy).not.toHaveBeenCalled()
    expect(continueSpy).not.toHaveBeenCalled()
  })

  it('an incomplete draft cannot start a run: opens the task form instead (no empty spec to backend)', () => {
    const onContinue = vi.fn()
    saveTaskDraft({
      taskId: 'TASK-INCOMPLETE',
      name: 'incomplete',
      material: '',
      laserType: 'fs',
      processType: 'fs_laser_processing',
      geometryType: 'rectangular_groove',
      objectiveMetric: 'depth_um',
      equipmentProfileId: 'EQ-1',
      taskContextRef: null,
      runId: null,
      version: 1,
      updatedAt: new Date().toISOString(),
    })
    renderWithProviders(
      <OverviewSection
        taskId="TASK-INCOMPLETE"
        runStatus={null}
        artifacts={new Map()}
        run={null}
        events={[]}
        busy={false}
        onContinue={onContinue}
        nextCheckpoint={null}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: '开始运行' }))
    expect(onContinue).not.toHaveBeenCalled()
    expect(screen.getByText(/任务未完成/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '保存任务' })).toBeInTheDocument()
  })
})
