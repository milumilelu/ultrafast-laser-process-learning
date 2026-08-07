import { describe, expect, it, vi } from 'vitest'

import { buildUrl, request, resolveUrl } from '../client'
import { topic2Api } from '../topic2'

const base = '/api/v1'

describe('url building', () => {
  it('resolves relative paths against the base without duplicating prefixes', () => {
    expect(resolveUrl('/api/v1', '/experiments')).toBe('/api/v1/experiments')
    expect(resolveUrl('http://127.0.0.1:8010/api/v1', '/runs')).toBe(
      'http://127.0.0.1:8010/api/v1/runs',
    )
  })

  it('rejects absolute urls passed to request', () => {
    expect(() => resolveUrl('/api/v1', 'http://127.0.0.1:8010/api/v1/experiments')).toThrow(
      /绝对 URL/,
    )
  })

  it('buildUrl only joins path and query (relative)', () => {
    expect(buildUrl('/experiments', { material: 'SiC' })).toBe('/experiments?material=SiC')
    expect(buildUrl('/runs', { run_type: undefined })).toBe('/runs')
  })
})

describe('topic2 api adapter', () => {
  it('requests the exact single-prefix url', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ items: [] }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await topic2Api.experiments({ material: 'SiC', laser_type: 'fs' })

    const [url] = fetchMock.mock.calls[0]
    expect(url).toBe(`${base}/experiments?material=SiC&laser_type=fs`)

    vi.unstubAllGlobals()
  })

  it('omits empty filters from the query string', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ items: [] }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await topic2Api.experiments({ material: null, target: undefined })

    const [url] = fetchMock.mock.calls[0]
    expect(url).toBe(`${base}/experiments`)

    vi.unstubAllGlobals()
  })

  it('listRuns builds the exact filtered url', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ items: [] }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await topic2Api.listRuns('optimization')

    const [url] = fetchMock.mock.calls[0]
    expect(url).toBe(`${base}/runs?run_type=optimization`)

    vi.unstubAllGlobals()
  })

  it('never emits a doubled api prefix', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ items: [] }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await topic2Api.experiments()
    await topic2Api.listRuns()
    await topic2Api.statistics()

    for (const [url] of fetchMock.mock.calls) {
      expect(String(url).split(`${base}/`).length - 1).toBe(1)
    }

    vi.unstubAllGlobals()
  })

  it('surfaces backend errors with detail', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      text: async () => 'no comparable experiments found',
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      topic2Api.scopeCapability({
        material: 'SiC',
        laser_type: 'fs',
        equipment_id: 'EQ-TEST-FS',
        geometry_type: 'rectangular_groove',
      }),
    ).rejects.toThrow(/no comparable experiments found/)

    vi.unstubAllGlobals()
  })

  it('request posts to the exact url', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ run_id: 'pi-1' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await request(base, 'POST', '/parameter-identification/run', { scope: {} })

    const [url] = fetchMock.mock.calls[0]
    expect(url).toBe(`${base}/parameter-identification/run`)

    vi.unstubAllGlobals()
  })
})
