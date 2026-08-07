import { describe, expect, it } from 'vitest'

import { formatNumber, formatPercent, runTypeLabel, agentStatusLabel } from '../format'
import { computeDataProfile } from '../dataProfile'
import { defaultBoundsFromRows } from '../params'
import { inferAgentStatus } from '../../stores/agent'

describe('formatters', () => {
  it('formats numbers and missing values', () => {
    expect(formatNumber(3.14159, 2)).toBe('3.14')
    expect(formatNumber(null)).toBe('—')
    expect(formatNumber(Number.NaN)).toBe('—')
  })

  it('formats percents', () => {
    expect(formatPercent(0.1234, 1)).toBe('12.3%')
    expect(formatPercent(null)).toBe('—')
  })

  it('labels run types and agent statuses', () => {
    expect(runTypeLabel('parameter_identification')).toBe('参数辨识')
    expect(runTypeLabel('unknown_type')).toBe('unknown_type')
    expect(agentStatusLabel('thinking')).toBe('思考中')
    expect(agentStatusLabel('degraded')).toBe('降级模式')
  })
})

describe('data profile', () => {
  const rows = [
    { valid_flag: 1, parameter_combination_id: 'D01', experiment_batch_id: 'B1', equipment_id: 'E1' },
    { valid_flag: 1, parameter_combination_id: 'D01', experiment_batch_id: 'B1', equipment_id: 'E1' },
    { valid_flag: 0, parameter_combination_id: 'D02', experiment_batch_id: 'B2', equipment_id: 'E2' },
  ] as unknown as import('../../api/types').ExperimentRow[]

  it('counts only valid rows', () => {
    const profile = computeDataProfile(rows)
    expect(profile.n_samples).toBe(2)
    expect(profile.n_unique_designs).toBe(1)
    expect(profile.batch_count).toBe(1)
  })
})

describe('parameter bounds defaults', () => {
  it('derives bounds from real rows without hardcoding', () => {
    const bounds = defaultBoundsFromRows([
      { pulse_width_ps: 1, frequency_kHz: 10, hatch_spacing_um: 4, passes: 2, scan_speed_mm_s: 40 },
      { pulse_width_ps: 5, frequency_kHz: 20, hatch_spacing_um: 8, passes: 4, scan_speed_mm_s: 80 },
    ])
    expect(bounds.pulse_width_ps).toEqual({ lower: 1, upper: 5 })
    expect(bounds.passes).toEqual({ lower: 2, upper: 4 })
  })
})

describe('agent status inference', () => {
  it('maps blocked stages to needs confirmation', () => {
    const status = inferAgentStatus({
      session_id: 's1',
      assistant_message: '',
      blocked_stages: ['expert_review'],
    } as never)
    expect(status).toBe('needs_confirmation')
  })

  it('maps normal completion to completed', () => {
    const status = inferAgentStatus({
      session_id: 's1',
      assistant_message: 'ok',
      blocked_stages: [],
    } as never)
    expect(status).toBe('completed')
  })
})
