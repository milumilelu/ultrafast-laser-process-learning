/** applicationApi / applicationStore 测试（§38.1）：幂等键、路由 redirects、store refs。 */

import { beforeEach, describe, expect, it, vi } from 'vitest'

import { applicationApi, applicationGateway } from '../application'
import { useApplicationStore } from '../../stores/application'

describe('applicationApi request paths', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ items: [] }), { status: 200 })),
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('createRun posts to /application-runs with client_request_id', async () => {
    await applicationApi.createRun({
      mode: 'demo',
      random_seed: 42,
      client_request_id: 'req-1',
    })
    const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/application-runs')
    expect(JSON.parse(String(init.body))).toMatchObject({
      mode: 'demo',
      client_request_id: 'req-1',
    })
  })

  it('compareOptimization posts to /optimization/compare', async () => {
    await applicationApi.compareOptimization({
      scope: { material: 'SiC' },
      machine_bounds: {},
    })
    const [url] = vi.mocked(fetch).mock.calls[0] as [string]
    expect(url).toContain('/optimization/compare')
  })

  it('gateway delegates runFullApplication and getApplicationResult', async () => {
    await applicationGateway.runFullApplication({ mode: 'demo' })
    await applicationGateway.getApplicationResult('app-1').catch(() => undefined)
    const urls = vi.mocked(fetch).mock.calls.map((call) => String(call[0]))
    expect(urls.some((url) => url.includes('/application-runs'))).toBe(true)
    expect(urls.some((url) => url.includes('/application-runs/app-1/result'))).toBe(true)
  })
})

describe('applicationStore (UI-P6: refs only)', () => {
  beforeEach(() => {
    useApplicationStore.getState().clear()
  })

  it('keeps only references, not payload copies', () => {
    useApplicationStore.getState().setRunRefs({
      runId: 'app-1',
      processLearningArtifactId: 'ProcessLearningResult-abc',
      vanillaBoRunId: 'bo-1',
      mode: 'demo',
    })
    const state = useApplicationStore.getState()
    expect(state.activeApplicationRunId).toBe('app-1')
    expect(state.processLearningArtifactId).toBe('ProcessLearningResult-abc')
    expect(state.vanillaBoRunId).toBe('bo-1')
    expect(state.assistedBoRunId).toBeNull()
    expect(state.runMode).toBe('demo')
  })

  it('tracks the selected tab', () => {
    useApplicationStore.getState().setSelectedTab('optimization')
    expect(useApplicationStore.getState().selectedTab).toBe('optimization')
  })
})
