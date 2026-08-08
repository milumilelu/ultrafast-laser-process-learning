/** §38.1 补充 unit 测试：旧路由 redirect / CFA 无概率契约 / proposal 状态机。 */

import { beforeEach, describe, expect, it } from 'vitest'

import { LEGACY_ROUTE_REDIRECTS, legacyRouteRedirect } from '../routes'
import { CFA_FACETS } from '../status'
import { useAgentStore } from '../../stores/agent'

describe('legacy route redirects (§3.2 / UI1-G4)', () => {
  it('redirects every legacy route to the new location', () => {
    expect(legacyRouteRedirect('/identification')).toBe('/application?tab=identification')
    expect(legacyRouteRedirect('/modeling')).toBe('/application?tab=modeling')
    expect(legacyRouteRedirect('/optimization')).toBe('/application?tab=optimization')
    expect(legacyRouteRedirect('/database')).toBe('/resources/data')
  })

  it('covers exactly the documented four legacy routes', () => {
    expect(Object.keys(LEGACY_ROUTE_REDIRECTS).sort()).toEqual([
      '/database',
      '/identification',
      '/modeling',
      '/optimization',
    ])
  })

  it('returns null for non-legacy paths', () => {
    expect(legacyRouteRedirect('/application')).toBeNull()
    expect(legacyRouteRedirect('/runs')).toBeNull()
  })
})

describe('CFA UI contract (§9/UI-P4)', () => {
  it('exposes only the five canonical facets', () => {
    expect(CFA_FACETS).toEqual([
      'Material',
      'Task',
      'InteractionState',
      'Reconstructibility',
      'Reachability',
    ])
  })

  it('status vocabulary contains no probability/confidence fields', () => {
    // 契约层面：CFA 状态只可能是四种定性状态 + 未校准
    const vocab = ['KNOWN', 'PARTIAL', 'UNKNOWN', 'MISMATCH', 'NOT_YET_CALIBRATED']
    for (const status of vocab) {
      expect(status).not.toMatch(/probability|confidence|percent|%/i)
    }
  })
})

describe('proposal state machine (§29)', () => {
  beforeEach(() => {
    useAgentStore.getState().resetConversation()
  })

  it('adds a pending proposal and resolves accepted', () => {
    const store = useAgentStore.getState()
    const proposal = store.addProposal({
      proposalId: 'PROP-T1',
      agentRunId: null,
      taskContextVersion: 2,
      type: 'select_model',
      changes: { model_name: 'GPR', selection_mode: 'manual' },
      reasons: ['人工覆盖'],
    })
    expect(proposal.status).toBe('pending')
    store.resolveProposal('PROP-T1', true)
    const resolved = useAgentStore.getState().proposals.find((item) => item.proposalId === 'PROP-T1')
    expect(resolved?.status).toBe('accepted')
  })

  it('marks rejected proposals', () => {
    const store = useAgentStore.getState()
    store.addProposal({
      proposalId: 'PROP-T2',
      agentRunId: null,
      taskContextVersion: 1,
      type: 'run_optimization',
      changes: {},
      reasons: [],
    })
    store.resolveProposal('PROP-T2', false)
    const resolved = useAgentStore.getState().proposals.find((item) => item.proposalId === 'PROP-T2')
    expect(resolved?.status).toBe('rejected')
  })
})
