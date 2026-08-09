/** M6: full WorkspacePage flow over the REAL golden scenario payloads.
 *
 * Draft -> run (mock backend serving the exported golden artifacts) ->
 * all six sections render their real content.  This is the component-level
 * end-to-end walk; the HTTP-level e2e lives in tests/frontend_backend.e2e.test.ts.
 */

import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import goldenRun from '../../../__fixtures__/goldenRun.json'
import { WorkspacePage } from '../WorkspacePage'
import { saveTaskDraft } from '../../../stores/taskDrafts'

type FixtureArtifact = {
  id: string
  type: string
  schema_version: string
  content: Record<string, unknown>
}

const artifacts = goldenRun.artifacts as Record<string, FixtureArtifact>
const runRecord = {
  application_run_id: 'RUN-GOLDEN-FIXTURE',
  status: goldenRun.run.status,
  task_context_ref: 'DEMO-P2P-001:v1',
  mode: goldenRun.run.mode,
  workflow_version: 'physics-to-planning-application-v1',
  stage_status: goldenRun.run.stage_status,
  result: goldenRun.run.result,
  created_at: '2026-01-01T00:00:00Z',
  completed_at: '2026-01-01T00:00:01Z',
}

const TASK_ID = 'TASK-GOLDEN'

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
}

function stubGoldenFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost')
      const path = url.pathname.replace(/^\/api\/v1/, '')
      if (path.endsWith('/events')) return jsonResponse({ items: [] })
      if (path.endsWith('/artifacts')) {
        const items = Object.entries(artifacts).map(([type, artifact]) => ({
          artifact_id: artifact.id,
          artifact_type: type,
          created_at: '2026-01-01T00:00:00Z',
        }))
        return jsonResponse({ items })
      }
      if (path.startsWith('/artifacts/')) {
        const artifactId = path.split('/').pop()
        const entry = Object.values(artifacts).find((artifact) => artifact.id === artifactId)
        if (!entry) throw new Error(`fixture artifact not found: ${artifactId}`)
        return jsonResponse({
          artifact_id: entry.id,
          artifact_type: entry.type,
          content: {
            id: entry.id,
            type: entry.type,
            schema_version: entry.schema_version,
            input_refs: [],
            created_at: '2026-01-01T00:00:00Z',
            content: entry.content,
          },
        })
      }
      if (path.startsWith('/application-runs/')) return jsonResponse(runRecord)
      throw new Error(`unhandled fetch: ${path}`)
    }),
  )
}

function renderWorkspace(section: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/workspace/${TASK_ID}/${section}`]}>
        <Routes>
          <Route path="/workspace/:taskId/:section" element={<WorkspacePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('WorkspacePage golden flow (M6)', () => {
  beforeEach(() => {
    localStorage.clear()
    stubGoldenFetch()
    saveTaskDraft({
      taskId: TASK_ID,
      name: 'golden',
      material: 'SiC',
      laserType: 'fs',
      processType: 'fs_laser_processing',
      geometryType: 'rectangular_groove',
      objectiveMetric: 'depth_um',
      equipmentProfileId: 'DEMO-FS-LASER-01',
      executionMode: 'DEMO_FIXTURE' as const,
  taskContextRef: null,
      runId: 'RUN-GOLDEN-FIXTURE',
      version: 1,
      updatedAt: new Date().toISOString(),
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('overview: renders control state + equipment + readiness cards', async () => {
    renderWorkspace('overview')
    expect(await screen.findByText('任务总览')).toBeInTheDocument()
    expect(await screen.findByText(/Run Control（后端权威状态）/)).toBeInTheDocument()
    expect(screen.getByText(/Equipment DEMO-FS-LASER-01/)).toBeInTheDocument()
    expect(screen.getByText('Scientific Capability')).toBeInTheDocument()
    expect(screen.getByText('已生成 ToolpathPlan')).toBeInTheDocument()
  })

  it('capability section renders the dependency chain', async () => {
    renderWorkspace('capability')
    expect(await screen.findByText('执行能力依赖图')).toBeInTheDocument()
    expect(await screen.findByText('输入解析器')).toBeInTheDocument()
  })

  it('knowledge section renders needs + reading + lineage', async () => {
    renderWorkspace('knowledge')
    expect(await screen.findByText(/Scientific Needs/)).toBeInTheDocument()
    expect(await screen.findByText(/文献精读/)).toBeInTheDocument()
    expect(await screen.findByText(/Requirements/)).toBeInTheDocument()
  })

  it('calibration section renders the parameter registry', async () => {
    renderWorkspace('calibration')
    expect(await screen.findByText(/参数 Registry/)).toBeInTheDocument()
  })

  it('simulation section renders heatmap + cross-section', async () => {
    renderWorkspace('simulation')
    expect(await screen.findByText('Simulation 仿真')).toBeInTheDocument()
    expect(await screen.findByRole('img', { name: 'predicted morphology heatmap' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'cross-section profile' })).toBeInTheDocument()
  })

  it('planning section renders candidate comparison + lineage', async () => {
    renderWorkspace('planning')
    expect(await screen.findByText('Planning 规划')).toBeInTheDocument()
    expect(await screen.findByText('推荐依据（可追溯）')).toBeInTheDocument()
    expect(screen.getAllByText(/最优/).length).toBeGreaterThan(0)
  })

  it('rail shows all six sections without pending markers', async () => {
    renderWorkspace('overview')
    await screen.findByText('任务总览')
    for (const label of ['总览', '能力', '知识', '标定', '仿真', '规划']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
    await waitFor(() => {
      expect(screen.queryByText('下一迭代')).not.toBeInTheDocument()
    })
  })
})
