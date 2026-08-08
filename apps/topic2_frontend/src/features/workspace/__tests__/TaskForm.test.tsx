import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TaskForm } from '../TaskForm'
import { saveTaskDraft } from '../../../stores/taskDrafts'
import { datasetsApi } from '../../../api/datasets'

function renderWithProviders(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>,
  )
}

const DRAFT = {
  taskId: 'TASK-FORM',
  name: 't',
  material: '',
  laserType: 'fs' as const,
  processType: 'fs_laser_processing',
  geometryType: 'rectangular_groove',
  objectiveMetric: 'depth_um' as const,
  equipmentProfileId: '',
  taskContextRef: null,
  runId: null,
  version: 1,
  updatedAt: new Date().toISOString(),
}

describe('TaskForm (材料下拉选择)', () => {
  beforeEach(() => {
    localStorage.clear()
    saveTaskDraft(DRAFT)
    vi.spyOn(datasetsApi, 'materials').mockResolvedValue([
      { material: 'SiC', is_synthetic: 0, data_origin: 'real_machining_data' },
      { material: 'ZrO2', is_synthetic: 0, data_origin: 'real_machining_data' },
    ])
    vi.spyOn(datasetsApi, 'equipment').mockResolvedValue([
      { equipment_id: 'EQ-TEST-FS', samples: 12 },
      { equipment_id: 'EQ-REAL', samples: 100 },
    ])
  })

  afterEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('material is a select fed by the backend /materials catalog, not free text', async () => {
    renderWithProviders(<TaskForm taskId="TASK-FORM" onSaved={() => undefined} />)
    const materialField = (await screen.findByText('材料')).closest('label')
    expect(materialField?.querySelector('select')).not.toBeNull()
    expect(materialField?.querySelector('input')).toBeNull()
    expect(await screen.findByRole('option', { name: 'SiC' })).toBeInTheDocument()
    expect(await screen.findByRole('option', { name: 'ZrO2' })).toBeInTheDocument()
  })

  it('saving without a material shows 请选择材料', async () => {
    const onSaved = vi.fn()
    renderWithProviders(<TaskForm taskId="TASK-FORM" onSaved={onSaved} />)
    await screen.findByRole('option', { name: 'SiC' })
    fireEvent.click(screen.getByRole('button', { name: '保存任务' }))
    expect(await screen.findByText('请选择材料')).toBeInTheDocument()
    expect(onSaved).not.toHaveBeenCalled()
  })

  it('empty-string draft fields must fall back to defaults (regression: ?? vs empty string)', async () => {
    saveTaskDraft({
      ...DRAFT,
      laserType: '',
      geometryType: '',
      objectiveMetric: '',
    })
    const onSaved = vi.fn()
    renderWithProviders(<TaskForm taskId="TASK-FORM" onSaved={onSaved} />)
    await screen.findByRole('option', { name: 'SiC' })
    expect(screen.getByRole('combobox', { name: /激光体制/ })).toHaveValue('fs')
    expect(screen.getByRole('combobox', { name: /目标几何/ })).toHaveValue('rectangular_groove')
    expect(screen.getByRole('combobox', { name: /目标指标/ })).toHaveValue('depth_um')
    fireEvent.change(screen.getByRole('combobox', { name: /材料/ }), { target: { value: 'SiC' } })
    fireEvent.change(screen.getByRole('combobox', { name: /设备/ }), { target: { value: 'EQ-TEST-FS' } })
    fireEvent.click(screen.getByRole('button', { name: '保存任务' }))
    expect(onSaved).toHaveBeenCalledTimes(1)
    const saved = JSON.parse(localStorage.getItem('task-drafts-v3') ?? '[]')[0] as typeof DRAFT
    expect(saved.laserType).toBe('fs')
    expect(saved.geometryType).toBe('rectangular_groove')
    expect(saved.objectiveMetric).toBe('depth_um')
    expect(saved.material).toBe('SiC')
  })

  it('saving with material + equipment completes the draft', async () => {
    const onSaved = vi.fn()
    renderWithProviders(<TaskForm taskId="TASK-FORM" onSaved={onSaved} />)
    await screen.findByRole('option', { name: 'SiC' })
    fireEvent.change(screen.getByRole('combobox', { name: /材料/ }), { target: { value: 'SiC' } })
    fireEvent.change(screen.getByRole('combobox', { name: /设备/ }), { target: { value: 'EQ-TEST-FS' } })
    fireEvent.click(screen.getByRole('button', { name: '保存任务' }))
    expect(onSaved).toHaveBeenCalledTimes(1)
    const saved = JSON.parse(localStorage.getItem('task-drafts-v3') ?? '[]')[0] as typeof DRAFT
    expect(saved.material).toBe('SiC')
    expect(saved.equipmentProfileId).toBe('EQ-TEST-FS')
  })
})
