import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { CalibrationSection } from '../CalibrationSection'

function renderWithProviders(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

const calibrationSnapshot = {
  id: 'CalibrationResult-1',
  type: 'CalibrationResult',
  schema_version: 'physics-to-planning-v1',
  input_refs: [{ type: 'PriorObjectSet', id: 'p' }],
  created_at: '2026-01-01T00:00:00Z',
  content: {
    calibration_id: 'cal-1',
    parameters: [
      {
        parameter: 'F_th_eff',
        estimate: 0.83,
        lower: 0.7,
        upper: 0.95,
        unit: 'J/cm2',
        identifiability: 'IDENTIFIABLE',
        parameter_semantics: 'EFFECTIVE',
        prior_refs: [{ type: 'PriorObjectSet', id: 'p1' }],
        data_refs: [],
        assumptions: [],
      },
    ],
    fit_metrics: { rmse: 4.88, mae: 3.1, r2: null, target_unit: 'um', n_observations: 120 },
    status: 'CALIBRATED',
    validation_data_refs: [],
    assumptions: ['effective parameter; not a material constant'],
  },
}

describe('CalibrationSection (spec §十二 / FE-6)', () => {
  it('renders the dynamic registry from backend parameters', () => {
    renderWithProviders(
      <CalibrationSection calibration={calibrationSnapshot} developerMode={false} />,
    )
    expect(screen.getByText(/动态参数 Registry/)).toBeInTheDocument()
    expect(screen.getByText('F_th_eff')).toBeInTheDocument()
    expect(screen.getByText('0.83 J/cm2')).toBeInTheDocument()
    expect(screen.getAllByText('已标定').length).toBeGreaterThan(0)
  })

  it('renders Fit view with in-sample disclaimer when no validation refs', async () => {
    renderWithProviders(
      <CalibrationSection calibration={calibrationSnapshot} developerMode={false} />,
    )
    fireEvent.click(screen.getByRole('tab', { name: 'Fit' }))
    expect(await screen.findByText(/in-sample/)).toBeInTheDocument()
    expect(screen.getByText(/4\.88/)).toBeInTheDocument()
  })

  it('renders Identifiability view for NOT_IDENTIFIABLE without a fitted value', async () => {
    const withReport = {
      ...calibrationSnapshot,
      content: {
        ...calibrationSnapshot.content,
        parameters: [
          {
            parameter: 'thermal_diffusivity',
            estimate: null,
            lower: null,
            upper: null,
            unit: 'mm2/s',
            identifiability: 'NOT_IDENTIFIABLE',
            parameter_semantics: 'PROVISIONAL',
            prior_refs: [],
            data_refs: [],
            assumptions: [],
          },
        ],
      },
    }
    renderWithProviders(
      <CalibrationSection calibration={withReport} developerMode={false} />,
    )
    fireEvent.click(screen.getByRole('tab', { name: 'Identifiability' }))
    expect(await screen.findByText('当前数据不可辨识')).toBeInTheDocument()
  })

  it('empty state when no calibration artifacts exist', () => {
    renderWithProviders(<CalibrationSection developerMode={false} />)
    expect(screen.getByText(/尚未生成标定产物/)).toBeInTheDocument()
  })
})
