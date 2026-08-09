// @vitest-environment node
/** Frontend HTTP E2E over original machining files and an original paper PDF.
 *
 * Scientific incompleteness is asserted as a truthful BLOCKED result. The test
 * never manufactures equipment, calibration observations, priors, or papers to
 * force a visually complete run.
 */

import { spawn, type ChildProcess } from 'node:child_process'
import { existsSync } from 'node:fs'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

const REPO = join(__dirname, '..', '..', '..', '..')
const HELPER = join(REPO, 'scripts', 'run_frontend_e2e_backend.py')
const VENV_PYTHON = process.platform === 'win32'
  ? join(REPO, '.venv', 'Scripts', 'python.exe')
  : join(REPO, '.venv', 'bin', 'python')
const PYTHON = process.env.PYTHON ?? (existsSync(VENV_PYTHON) ? VENV_PYTHON : 'python')

function waitForReady(child: ChildProcess, onLine: (line: string) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error('backend did not become READY within 120s')),
      120_000,
    )
    child.stdout?.on('data', (chunk: Buffer) => {
      for (const line of chunk.toString().split('\n')) {
        if (!line.trim()) continue
        onLine(line.trim())
        if (line.includes('READY')) {
          clearTimeout(timeout)
          resolve()
        }
      }
    })
    child.stderr?.on('data', (chunk: Buffer) => onLine(chunk.toString().trim()))
    child.on('exit', (code) => {
      clearTimeout(timeout)
      reject(new Error(`backend exited early with code ${code}`))
    })
  })
}

describe('frontend clients over real backend resources', () => {
  it(
    'uses only real observations, auto-resolves provenance scope, and fails closed',
    { timeout: 300_000 },
    async () => {
      const scratch = await mkdtemp(join(tmpdir(), 'topic2-real-fe-e2e-'))
      const port = 8199 + Math.floor(Math.random() * 100)
      const backend = spawn(PYTHON, [HELPER, '--port', String(port), '--root', scratch], {
        cwd: REPO,
        stdio: ['ignore', 'pipe', 'pipe'],
      })
      const log: string[] = []
      try {
        await waitForReady(backend, (line) => log.push(line))
        vi.stubEnv('VITE_TOPIC2_API_URL', `http://127.0.0.1:${port}/api/v1`)
        const { datasetsApi } = await import('../api/datasets')
        const { runsApi } = await import('../api/runs')

        const datasets = await datasetsApi.datasets()
        expect(datasets).toHaveLength(1)
        expect(datasets[0].n_samples).toBeGreaterThan(500)

        const observations = await datasetsApi.experiments({ limit: 100 })
        expect(observations.length).toBeGreaterThan(0)
        expect(observations.every((row) => row.is_synthetic === 0)).toBe(true)
        expect(observations.every((row) => row.data_origin === 'real_machining_data')).toBe(true)

        const modelingResponse = await fetch(`http://127.0.0.1:${port}/api/v1/models/evaluate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            scope: {
              material: 'SiC',
              laser_type: 'fs',
              equipment_id: 'EQ-REAL',
              geometry_type: 'rectangular_groove',
              target: 'depth_um',
            },
            candidate_models: ['RSM'],
            cv_folds: 3,
            random_seed: 42,
          }),
        })
        expect(modelingResponse.ok).toBe(true)
        const modeling = await modelingResponse.json() as Record<string, unknown>
        expect(modeling.dataset_version).toBe(datasets[0].dataset_version)
        expect(modeling.selected_model).toBe('RSM')
        expect(modeling.cv_strategy).toBe('GroupKFold(parameter_combination_id)')

        const literature = await datasetsApi.literature()
        expect(literature).toHaveLength(1)
        expect(literature[0].source).toBe('pilot_pdf')
        expect(literature[0].pdf_ref).toMatch(/14bd5786dcb52033_11_arxiv_2404\.09906\.pdf$/)

        const run = await runsApi.createRun({
          mode: 'research',
          task_spec: {
            material: 'SiC',
            laser_type: 'fs',
            process_type: 'fs_laser_processing',
            dataset_ref: datasets[0].dataset_version,
            equipment_profile_id: 'UNRESOLVED-EQUIPMENT',
            execution_equipment_ref: {
              equipment_profile_id: 'UNRESOLVED-EQUIPMENT',
              revision_id: 'UNRESOLVED-REVISION',
            },
            geometry_type: 'rectangular_groove',
            objective_metric: 'depth_um',
            execution_mode: 'RESEARCH',
            target_geometry: {
              width_um: 30,
              height_um: 24,
              target_depth_um: 20,
              grid_spacing_um: 2,
            },
          },
          client_request_id: `real-e2e-${Date.now()}`,
        })
        expect(run.status).toBe('blocked')

        const { items } = await runsApi.getArtifacts(run.application_run_id)
        const artifacts = new Map<string, Record<string, unknown>>()
        for (const meta of items) {
          const envelope = await runsApi.getArtifact<Record<string, unknown>>(meta.artifact_id)
          artifacts.set(meta.artifact_type, envelope.content.content)
        }
        expect(artifacts.get('DatasetRef')).toMatchObject({
          equipment_scope_id: 'EQ-REAL',
          status: 'READY',
        })
        expect(artifacts.get('MachineProfileSnapshot')).toMatchObject({
          resource_status: 'BLOCKED',
          source_quality: 'UNRESOLVED',
        })

        const stored = await runsApi.getRun(run.application_run_id)
        expect(stored.task_spec).not.toHaveProperty('dataset_equipment_scope_id')
        const control = (stored.result as { runControlState?: Record<string, unknown> })
          .runControlState as { execution_mode?: string; phase_status?: string }
        expect(control.execution_mode).toBe('RESEARCH')
        expect(control.phase_status).toBe('BLOCKED')
      } finally {
        backend.kill()
        await rm(scratch, { recursive: true, force: true })
        vi.unstubAllEnvs()
      }
    },
  )
})
