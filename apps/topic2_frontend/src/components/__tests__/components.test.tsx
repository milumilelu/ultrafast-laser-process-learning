import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'

import { GlobalContextBar } from '../shell/GlobalContextBar'
import { AgentProposalCard } from '../AgentProposalCard'
import { useTaskContextStore } from '../../stores/taskContext'
import { useScienceStore } from '../../stores/science'
import { ModelComparisonTable } from '../ModelComparisonTable'
import type { ModelTrainingResult } from '../../api/types'

describe('GlobalContextBar', () => {
  beforeEach(() => {
    useTaskContextStore.setState({ context: useTaskContextStore.getState().reset() })
  })

  it('shows id and version', () => {
    render(
      <MemoryRouter>
        <GlobalContextBar />
      </MemoryRouter>,
    )
    expect(screen.getByText(/TASK-\d{4}/)).toBeInTheDocument()
    expect(screen.getByText(/v1/)).toBeInTheDocument()
  })

  it('shows defined material after update', () => {
    useTaskContextStore.getState().update({ materialId: 'SiC' })
    render(
      <MemoryRouter>
        <GlobalContextBar />
      </MemoryRouter>,
    )
    expect(screen.getByText('SiC')).toBeInTheDocument()
  })
})

describe('AgentProposalCard', () => {
  const baseProposal = {
    proposalId: 'PROP-0001',
    agentRunId: null,
    taskContextVersion: 2,
    type: 'select_model' as const,
    changes: { model_name: 'RandomForest', selection_mode: 'manual' },
    reasons: ['人工覆盖系统推荐模型。'],
    status: 'pending' as const,
  }

  it('renders pending proposal with apply/cancel actions', () => {
    render(<AgentProposalCard proposal={baseProposal} onApply={() => undefined} />)
    expect(screen.getByText(/Agent 建议/)).toBeInTheDocument()
    expect(screen.getByText(/应用修改/)).toBeInTheDocument()
    expect(screen.getByText(/取消/)).toBeInTheDocument()
  })

  it('calls onApply when accepted', async () => {
    const onApply = vi.fn()
    render(<AgentProposalCard proposal={baseProposal} onApply={onApply} />)
    await userEvent.click(screen.getByText(/应用修改/))
    expect(onApply).toHaveBeenCalledWith(baseProposal)
  })
})

describe('ModelComparisonTable', () => {
  const training = {
    run_id: 'train-001',
    model_id: 'model-001',
    model_version: 'v1',
    dataset_version: 'ds-v1',
    selected_model: 'GPR',
    validation_metrics: {
      GPR: { RMSE: 1.1, MAE: 0.9, R2: 0.9, n_samples: 12, n_unique_designs: 6, cv_folds: 5, uncertainty_available: true },
      RandomForest: { RMSE: 2.2, MAE: 1.8, R2: 0.7, n_samples: 12, n_unique_designs: 6, cv_folds: 5, uncertainty_available: false },
    },
    comparison: {
      baseline: { model: 'GPR', RMSE: 1.1, MAE: 0.9, R2: 0.9, n_samples: 12, n_unique_designs: 6, cv_folds: 5, uncertainty_available: true },
      optimized: { model: 'GPR', RMSE: 1.1, MAE: 0.9, R2: 0.9, n_samples: 12, n_unique_designs: 6, cv_folds: 5, uncertainty_available: true },
      comparison_basis: 'same dataset',
      improved: true,
    },
    cv_strategy: 'GroupKFold(parameter_combination_id)',
  } as ModelTrainingResult

  beforeEach(() => {
    useScienceStore.setState({
      selectedModelId: null,
      selectionMode: null,
    })
  })

  it('renders all candidate models with metrics and system star', () => {
    render(<ModelComparisonTable training={training} onSelect={() => undefined} />)
    expect(screen.getAllByTestId('model-row')).toHaveLength(2)
    expect(screen.getByText('★')).toBeInTheDocument()
  })

  it('reports manual override state', () => {
    useScienceStore.setState({ selectedModelId: 'RandomForest', selectionMode: 'manual' })
    render(<ModelComparisonTable training={training} onSelect={() => undefined} />)
    expect(screen.getAllByText(/人工覆盖/).length).toBeGreaterThan(0)
    expect(screen.getByText(/该操作将被记录/)).toBeInTheDocument()
  })
})
