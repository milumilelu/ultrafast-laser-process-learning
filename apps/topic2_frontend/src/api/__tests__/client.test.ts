import { ApiError, buildQuery, request } from '../client'
import { runsApi } from '../runs'
import { datasetsApi } from '../datasets'

describe('buildQuery', () => {
  it('omits null / undefined / empty values', () => {
    expect(buildQuery({ a: 1, b: null, c: undefined, d: '' })).toBe('?a=1')
  })

  it('returns empty string for no params', () => {
    expect(buildQuery({})).toBe('')
  })

  it('encodes values', () => {
    expect(buildQuery({ after_sequence: 5, mode: 'research' })).toBe('?after_sequence=5&mode=research')
  })
})

describe('request', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('normalizes backend error detail (FE-1: values come from backend)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false,
      status: 422,
      text: async () => JSON.stringify({ detail: 'task spec incomplete, missing: material' }),
    }) as Response))
    await expect(request('http://x/api/v1', '/application-runs', { method: 'POST', body: '{}' }))
      .rejects.toMatchObject({ status: 422, message: 'task spec incomplete, missing: material' })
  })

  it('wraps network failure in ApiError', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('boom') }))
    await expect(request('http://x/api/v1', '/x')).rejects.toMatchObject({ status: 0, message: expect.stringContaining('boom') })
  })

  it('ApiError carries status and detail', () => {
    const err = new ApiError(404, 'not found', { detail: 'x' })
    expect(err.status).toBe(404)
    expect(err.name).toBe('ApiError')
  })
})

describe('runsApi paths (ApplicationRun gateway)', () => {
  afterEach(() => vi.unstubAllGlobals())

  function stubOk(body: unknown) {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      status: 200,
      text: async () => JSON.stringify(body),
    }) as Response))
  }

  it('createRun posts /application-runs with client_request_id', async () => {
    stubOk({ application_run_id: 'run-1', status: 'running' })
    const fetchMock = vi.mocked(fetch)
    await runsApi.createRun({ mode: 'research', task_spec: { material: 'SiC' }, client_request_id: 'task-TASK-001' })
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/api/v1/application-runs')
    expect(JSON.parse(String(init?.body)).client_request_id).toBe('task-TASK-001')
  })

  it('continueRun targets the SAME run id (FE-10: no second run)', async () => {
    stubOk({ application_run_id: 'run-1', status: 'completed' })
    const fetchMock = vi.mocked(fetch)
    await runsApi.continueRun('run-1', { stages: ['calibrate_physics'] })
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/api/v1/application-runs/run-1/continue')
    expect(String(init?.method)).toBe('POST')
  })

  it('events endpoint carries after_sequence cursor', async () => {
    stubOk({ items: [] })
    const fetchMock = vi.mocked(fetch)
    await runsApi.getEvents('run-1', 42)
    expect(String(fetchMock.mock.calls[0][0])).toContain('after_sequence=42')
  })

  it('getArtifact unwraps the backend envelope (content: <stored snapshot>)', async () => {
    const envelope = {
      artifact_id: 'ScientificCapabilityReport-abc',
      artifact_type: 'ScientificCapabilityReport',
      content: {
        id: 'ScientificCapabilityReport-abc',
        type: 'ScientificCapabilityReport',
        schema_version: 'physics-to-planning-v1',
        input_refs: [{ type: 'TaskState', id: 't1' }],
        content: { status: 'PARTIAL', available: [] },
        created_at: '2026-01-01T00:00:00Z',
      },
    }
    stubOk(envelope)
    const response = await runsApi.getArtifact<Record<string, unknown>>('ScientificCapabilityReport-abc')
    expect(response.content.schema_version).toBe('physics-to-planning-v1')
    expect((response.content.content as { status: string }).status).toBe('PARTIAL')
  })

  it('datasets API unwraps {items} wrappers', async () => {
    stubOk({ items: [{ material: 'SiC', samples: 12 }] })
    const materials = await datasetsApi.materials()
    expect(materials).toEqual([{ material: 'SiC', samples: 12 }])
  })
})
