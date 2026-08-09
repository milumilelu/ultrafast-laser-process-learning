/** M6 component tests: Simulation / Planning / Needs / ControlState render
 * the REAL golden scenario payloads. */

import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import goldenRun from '../../__fixtures__/goldenRun.json'
import { SimulationSection } from '../simulation/SimulationSection'
import { PlanningSection } from '../planning/PlanningSection'
import { NeedsPanel, ReadingPanel } from '../knowledge/NeedsPanel'
import { ConditionTracePanel } from '../knowledge/ConditionTracePanel'
import { ControlStateCard } from '../../components/scientific/ControlStateCard'
import { EquipmentCard } from '../../components/scientific/EquipmentCard'

function snapshotOf(type: string) {
  const artifact = (goldenRun.artifacts as Record<string, { id: string; type: string; schema_version: string; content: Record<string, unknown> }>)[type]
  return {
    id: artifact.id,
    type: artifact.type,
    schema_version: artifact.schema_version,
    input_refs: [] as { type: string; id: string }[],
    created_at: '2026-01-01T00:00:00Z',
    content: artifact.content,
  }
}

function renderWithProviders(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('SimulationSection (M6)', () => {
  it('renders metrics, heatmap and cross-section from the golden simulation', () => {
    renderWithProviders(
      <SimulationSection
        simulation={snapshotOf('MorphologySimulationResult')}
        model={snapshotOf('LocalRemovalModel')}
      />,
    )
    expect(screen.getByText('Simulation 仿真')).toBeInTheDocument()
    expect(screen.getByText('预测指标')).toBeInTheDocument()
    expect(screen.getAllByText(/平均深度/).length).toBeGreaterThan(0)
    expect(screen.getByText(/形貌 RMSE/)).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'predicted morphology heatmap' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'cross-section profile' })).toBeInTheDocument()
    expect(screen.getByText(/RECONSTRUCTED/)).toBeInTheDocument()
  })

  it('renders empty state without simulation artifact', () => {
    renderWithProviders(<SimulationSection />)
    expect(screen.getByText(/尚无仿真产物/)).toBeInTheDocument()
  })
})

describe('PlanningSection (M6)', () => {
  it('renders recommended plan + candidate comparison from the golden plan', () => {
    renderWithProviders(
      <PlanningSection
        plan={snapshotOf('ToolpathPlan')}
        simulation={snapshotOf('MorphologySimulationResult')}
      />,
    )
    expect(screen.getByText('Planning 规划')).toBeInTheDocument()
    expect(screen.getByText('演示候选')).toBeInTheDocument()
    expect(screen.getAllByText(/Cross Hatch（交叉）/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/Raster（单向）/).length).toBeGreaterThan(0)
    expect(screen.getByText('推荐依据（可追溯）')).toBeInTheDocument()
    expect(screen.getAllByText(/最优/).length).toBeGreaterThan(0)
  })

  it('renders empty state without plan artifact', () => {
    renderWithProviders(<PlanningSection />)
    expect(screen.getByText(/尚无路径规划产物/)).toBeInTheDocument()
  })
})

describe('NeedsPanel + ReadingPanel (M6)', () => {
  it('renders the four-way need classification from the golden run', () => {
    renderWithProviders(<NeedsPanel artifact={snapshotOf('ScientificNeedSet')} />)
    expect(screen.getByText(/科学知识（文献）/)).toBeInTheDocument()
    expect(screen.getByText(/标定观测（实验）/)).toBeInTheDocument()
    expect(screen.getByText('F_th_eff')).toBeInTheDocument()
    expect(screen.getByText('incubation_law')).toBeInTheDocument()
    expect(screen.getAllByText('文献检索').length).toBeGreaterThan(0)
  })

  it('renders the reading chain: papers + cache mapping', () => {
    renderWithProviders(<ReadingPanel artifact={snapshotOf('ScientificCorpusPack')} />)
    expect(screen.getByText(/文献精读/)).toBeInTheDocument()
    expect(screen.getByText(/预录 LLM 精读缓存/)).toBeInTheDocument()
    expect(screen.getAllByText(/sic-/).length).toBeGreaterThan(0)
  })

  it('renders the mid-chain traceability: ledger -> conditions -> reconstructibility', () => {
    renderWithProviders(
      <ConditionTracePanel
        ledger={snapshotOf('CandidateLedger')}
        conditions={snapshotOf('SourceConditionSet')}
        reconstructibility={snapshotOf('ReconstructibilityReportSet')}
      />,
    )
    expect(screen.getByText(/CandidateLedger/)).toBeInTheDocument()
    expect(screen.getByText(/SourceConditions/)).toBeInTheDocument()
    expect(screen.getByText(/Reconstructibility/)).toBeInTheDocument()
    expect(screen.getAllByText(/frequency/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/PARTIAL|BLOCKED/).length).toBeGreaterThan(0)
  })
})

describe('ControlStateCard + EquipmentCard (M6)', () => {
  it('renders the authoritative run control state with gates', () => {
    const runControl = (
      goldenRun.run.result as { runControlState?: Record<string, unknown> }
    ).runControlState
    renderWithProviders(<ControlStateCard control={runControl} />)
    expect(screen.getByText(/Run Control（后端权威状态）/)).toBeInTheDocument()
    expect(screen.getByText('资源就绪 (Gate A)')).toBeInTheDocument()
    expect(screen.getByText('知识就绪 (Gate B)')).toBeInTheDocument()
    expect(screen.getByText('物理模型 (Gate C)')).toBeInTheDocument()
    expect(screen.getByText('规划就绪 (Gate D)')).toBeInTheDocument()
    expect(screen.getByText('执行模式 DEMO_FIXTURE')).toBeInTheDocument()
    expect(screen.queryByText('阻塞原因')).not.toBeInTheDocument()
  })

  it('renders the canonical equipment snapshot', () => {
    renderWithProviders(<EquipmentCard artifact={snapshotOf('MachineProfileSnapshot')} />)
    expect(screen.getByText(/Equipment DEMO-FS-LASER-01/)).toBeInTheDocument()
    expect(screen.getByText('资源就绪')).toBeInTheDocument()
    expect(screen.getByText('演示夹具（DEMO_FIXTURE）')).toBeInTheDocument()
    expect(screen.getByText(/10 W/)).toBeInTheDocument()
    expect(screen.getByText('派生')).toBeInTheDocument()
  })
})
