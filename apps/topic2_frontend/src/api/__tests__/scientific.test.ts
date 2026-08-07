import { describe, expect, it, vi } from 'vitest'

import { agentApi } from '../agent'

const agentBase = '/agent-api'

describe('scientific pipeline api adapter', () => {
  it('buildCorpus posts to the scientific-retrieval endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ corpus_pack_id: 'CP-1' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await agentApi.buildCorpus({
      task_scope: {
        material: 'SiC',
        laser_type: 'fs',
        geometry_type: 'rectangular_groove',
        target: 'depth_um',
      },
      task_context_id: 'TASK-1',
      retrieval_intents: ['parameter_effect', 'formula'],
    })

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`${agentBase}/api/v1/scientific-retrieval/build-corpus`)
    const payload = JSON.parse(init.body as string)
    expect(payload.task_scope.material).toBe('SiC')
    expect(payload.retrieval_intents).toContain('formula')

    vi.unstubAllGlobals()
  })

  it('analyzeCorpus posts the corpus pack to the analysis endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ knowledge_pack_id: 'KP-1', degraded: true }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await agentApi.analyzeCorpus({
      corpus_pack: { corpus_pack_id: 'CP-1' },
    })

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`${agentBase}/api/v1/scientific-analysis/analyze`)
    expect(JSON.parse(init.body as string).corpus_pack.corpus_pack_id).toBe('CP-1')
    expect(result.knowledge_pack_id).toBe('KP-1')

    vi.unstubAllGlobals()
  })

  it('validateKnowledge posts to the validate endpoint and returns verdict', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        validated_candidates: ['KC-1'],
        rejected_candidates: ['KC-2'],
        issues: [{ candidate_id: 'KC-2', code: 'missing_source', message: 'x', severity: 'error' }],
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await agentApi.validateKnowledge({
      knowledge_pack: { knowledge_pack_id: 'KP-1' },
    })

    const [url] = fetchMock.mock.calls[0]
    expect(url).toBe(`${agentBase}/api/v1/scientific-analysis/validate`)
    expect(result.rejected_candidates).toEqual(['KC-2'])

    vi.unstubAllGlobals()
  })

  it('creates an analysis job and lists run traces', async () => {
    const fetchMock = vi.fn().mockImplementation(async (url: string) => ({
      ok: true,
      status: 200,
      json: async () =>
        url.endsWith('/jobs')
          ? { analysis_run_id: 'sa-1', status: 'queued', stage: 'queued' }
          : { items: [{ run_id: 'rt-1', task_id: 'TASK-1', pipeline_stats: { completed: 6 } }] },
    }))
    vi.stubGlobal('fetch', fetchMock)

    const job = await agentApi.createAnalysisJob({
      task_scope: { material: 'SiC' },
      retrieval_intents: ['formula'],
    })
    expect(job.analysis_run_id).toBe('sa-1')

    const runs = await agentApi.listAnalysisRuns()
    expect(runs.items[0].pipeline_stats.completed).toBe(6)

    vi.unstubAllGlobals()
  })
})
