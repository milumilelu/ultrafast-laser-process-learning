/** §38.2 组件测试：ParameterImportanceChart / PhysicsReadinessMatrix /
 *  ModelDecisionCard / CFAMatrix / OptimizationComparison / ActivityTimeline。 */

import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import { ParameterImportanceChart } from '../learning/ParameterImportanceChart'
import { PhysicsReadinessMatrix } from '../learning/PhysicsReadinessMatrix'
import { ModelDecisionCard } from '../learning/ModelDecisionCard'
import { CFAMatrix } from '../evidence/CFAMatrix'
import { OptimizationComparison } from '../optimization/OptimizationComparison'
import { ActivityTimeline } from '../assistant/ActivityTimeline'
import { useWorkflowStore } from '../../stores/workflow'

describe('ParameterImportanceChart (§12.3)', () => {
  const items = [
    { feature: 'scan_speed_mm_s', importance: 0.6, effect_direction: 'positive', rank: 1 },
    { feature: 'frequency_kHz', importance: 0.3, effect_direction: 'negative', rank: 2 },
  ]

  it('renders ranked bars with labels', () => {
    render(<ParameterImportanceChart items={items} title="可控参数" />)
    expect(screen.getByText('扫描速度 (mm/s)')).toBeInTheDocument()
    expect(screen.getByText('频率 (kHz)')).toBeInTheDocument()
    expect(screen.getByText('#1')).toBeInTheDocument()
    expect(screen.getByText('正向')).toBeInTheDocument()
    expect(screen.getByText('负向')).toBeInTheDocument()
  })

  it('renders nothing for empty ranking', () => {
    const { container } = render(<ParameterImportanceChart items={[]} title="空" />)
    expect(container.firstChild).toBeNull()
  })
})

describe('PhysicsReadinessMatrix (§7.3/§12.5)', () => {
  it('maps AVAILABLE green, BLOCKED/UNKNOWN gray, MISMATCH red', () => {
    render(
      <PhysicsReadinessMatrix
        coordinates={[
          { coordinate: 'pulse_interval', status: 'AVAILABLE', dependencies: [], reason: null },
          { coordinate: 'peak_fluence', status: 'BLOCKED', dependencies: ['laser_power_W'], reason: 'power missing' },
          { coordinate: 'pulse_overlap', status: 'UNKNOWN', dependencies: [], reason: null },
          { coordinate: 'pulse_spacing', status: 'MISMATCH', dependencies: [], reason: null },
        ]}
      />,
    )
    expect(screen.getByText('可用')).toBeInTheDocument()
    expect(screen.getByText('不可判断')).toBeInTheDocument()
    expect(screen.getByText('未知')).toBeInTheDocument()
    expect(screen.getByText('不匹配')).toBeInTheDocument()
    // Unknown 不得渲染为红色（UI-P3）：BLOCKED/UNKNOWN 均为 neutral 徽标
    const unknown = screen.getByText('未知').closest('span')
    expect(unknown?.className).not.toContain('badge err')
  })
})

describe('ModelDecisionCard (§13.2)', () => {
  it('shows recommended model and metrics', () => {
    render(
      <ModelDecisionCard
        selectedModel="GPR"
        metrics={{ RMSE: 0.36, MAE: 0.21, R2: 0.9, n_samples: 12, n_unique_designs: 6, cv_folds: 5, uncertainty_available: true }}
        cvStrategy="GroupKFold(parameter_combination_id)"
      />,
    )
    expect(screen.getByText('GPR')).toBeInTheDocument()
    expect(screen.getByText('0.36')).toBeInTheDocument()
    expect(screen.getByText('✓ 最低 Group-CV RMSE')).toBeInTheDocument()
  })
})

describe('CFAMatrix (§9.1)', () => {
  it('renders 5 facets per row with statuses', () => {
    render(
      <CFAMatrix
        rows={[
          {
            rowId: 'claim-1',
            label: 'Paper 04',
            cells: {
              Material: { facet: 'Material', status: 'KNOWN' },
              Task: { facet: 'Task', status: 'PARTIAL' },
              InteractionState: { facet: 'InteractionState', status: 'UNKNOWN' },
              Reconstructibility: { facet: 'Reconstructibility', status: 'PARTIAL' },
              Reachability: { facet: 'Reachability', status: 'PARTIAL' },
            },
          },
        ]}
      />,
    )
    expect(screen.getByText('Paper 04')).toBeInTheDocument()
    for (const facet of ['Material', 'Task', 'InteractionState', 'Reconstructibility', 'Reachability']) {
      expect(screen.getByText(facet)).toBeInTheDocument()
    }
    expect(screen.getByText('已知')).toBeInTheDocument()
    expect(screen.getByText('未知')).toBeInTheDocument()
  })
})

describe('OptimizationComparison (§14.3)', () => {
  const bo = {
    run_id: 'bo-1',
    model_id: null,
    model_source: 'fitted_for_optimization',
    optimization_method: 'GaussianProcess+UCB+E2PSoftPrior',
    recommended_parameters: { pulse_width_ps: 1.0, frequency_kHz: 100 },
    prediction: { mean: 5.0, std: 1.0 },
    acquisition: { normalized_ucb: 0.5, log_prior: 0.1, lambda_t: 0.2, score: 0.7 },
    machine_bounds: {},
  }
  const comparison = {
    vanilla: { ...bo, run_id: 'bo-v', recommended_parameters: { pulse_width_ps: 1.5, frequency_kHz: 200 } },
    evidence_assisted: bo,
    prior_applied_evidence: {
      vanilla_search_prior_applied: false,
      assisted_search_prior_applied: true,
      assisted_prior_guidance: 'e2p_soft_prior_v1',
      governed_prior_hash: 'hash-abc',
      assisted_prior_evidence_ids: ['E-1'],
    },
  }

  it('shows both columns and prior_applied flags', () => {
    render(<OptimizationComparison comparison={comparison} />)
    expect(screen.getByText('Vanilla BO')).toBeInTheDocument()
    expect(screen.getByText('Evidence-assisted BO')).toBeInTheDocument()
    expect(screen.getByText(/vanilla_search_prior_applied = false/)).toBeInTheDocument()
    expect(screen.getByText(/assisted_search_prior_applied = true/)).toBeInTheDocument()
    expect(screen.getByText(/prior_guidance: e2p_soft_prior_v1/)).toBeInTheDocument()
    // 推荐文案固定为「推荐下一实验点」而非「最优」
    expect(screen.queryByText(/最优工艺参数/)).not.toBeInTheDocument()
  })
})

describe('ActivityTimeline (§21)', () => {
  beforeEach(() => {
    useWorkflowStore.getState().start('app-1')
  })

  it('renders formal events only', () => {
    useWorkflowStore.getState().append([
      {
        event_id: 'e1',
        run_id: 'app-1',
        sequence: 1,
        timestamp: '2026-08-08T00:00:00Z',
        type: 'RUN_STARTED',
        stage: 'application',
        summary: '运行开始',
        entityRefs: [],
        artifactRefs: [],
        details: {},
      },
      {
        event_id: 'e2',
        run_id: 'app-1',
        sequence: 2,
        timestamp: '2026-08-08T00:00:00Z',
        type: 'WARNING',
        stage: 'prepare_knowledge',
        summary: '文献解析暂未执行',
        entityRefs: [],
        artifactRefs: [],
        details: {},
      },
    ])
    render(<ActivityTimeline />)
    expect(screen.getByText('运行开始')).toBeInTheDocument()
    expect(screen.getByText('文献解析暂未执行')).toBeInTheDocument()
  })

  it('shows empty state without events', () => {
    useWorkflowStore.getState().clear()
    render(<ActivityTimeline />)
    expect(screen.getByText(/暂无执行流/)).toBeInTheDocument()
  })
})
