// @vitest-environment node
/** M6: frontend HTTP e2e — the real frontend API client drives the REAL
 * topic2 backend over HTTP through the golden scenario.
 *
 * Spawns scripts/run_frontend_e2e_backend.py (fixture prep + uvicorn),
 * then exercises the exact code path the UI uses (runsApi): create run with
 * gap stages -> continue with knowledge stages -> poll artifacts -> assert
 * the full chain.  Kills the backend afterwards.
 */

import { spawn, type ChildProcess } from 'node:child_process'
import { existsSync } from 'node:fs'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

const REPO = join(__dirname, '..', '..', '..', '..') // apps/topic2_frontend/src/tests -> repo
const HELPER = join(REPO, 'scripts', 'run_frontend_e2e_backend.py')
const VENV_PYTHON =
  process.platform === 'win32'
    ? join(REPO, '.venv', 'Scripts', 'python.exe')
    : join(REPO, '.venv', 'bin', 'python')
const PYTHON = process.env.PYTHON ?? (existsSync(VENV_PYTHON) ? VENV_PYTHON : 'python')

const GOLDEN_TASK = {
  task_context_id: 'DEMO-P2P-001',
  task_context_version: 1,
  material: 'SiC',
  laser_type: 'fs',
  process_type: 'fs_laser_processing',
  equipment_profile_id: 'DEMO-FS-LASER-01',
  execution_equipment_ref: 'DEMO-FS-LASER-01',
  geometry_type: 'rectangular_groove',
  objective_metric: 'depth_um',
  execution_mode: 'DEMO_FIXTURE',
  target_geometry: {
    width_um: 30.0,
    height_um: 24.0,
    target_depth_um: 20.0,
    grid_spacing_um: 2.0,
  },
}

function waitForReady(child: ChildProcess, onLine: (line: string) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error('backend did not become READY within 120s')),
      120_000,
    )
    child.stdout?.on('data', (chunk: Buffer) => {
      for (const line of chunk.toString().split('\n')) {
        if (line.trim()) {
          onLine(line.trim())
          if (line.includes('READY')) {
            clearTimeout(timeout)
            resolve()
          }
        }
      }
    })
    child.stderr?.on('data', (chunk: Buffer) => {
      onLine(chunk.toString().trim())
    })
    child.on('exit', (code) => {
      clearTimeout(timeout)
      reject(new Error(`backend exited early with code ${code}`))
    })
  })
}

describe('frontend runsApi over the real backend (M6 golden e2e)', () => {
  it(
    'drives the golden vertical slice end-to-end over HTTP',
    { timeout: 300_000 },
    async () => {
      const scratch = await mkdtemp(join(tmpdir(), 'topic2-fe-e2e-'))
      const port = 8199 + Math.floor(Math.random() * 100)
      const backend = spawn(PYTHON, [HELPER, '--port', String(port), '--root', scratch], {
        cwd: REPO,
        stdio: ['ignore', 'pipe', 'pipe'],
      })
      const log: string[] = []
      try {
        await waitForReady(backend, (line) => log.push(line))

        vi.stubEnv('VITE_TOPIC2_API_URL', `http://127.0.0.1:${port}/api/v1`)
        const { runsApi } = await import('../api/runs')

        // 1. gap stages (task carries IDs only)
        const gap = await runsApi.createRun({
          mode: 'research',
          task_spec: GOLDEN_TASK,
          stages: [
            'prepare_task',
            'assess_capability',
            'assess_data',
            'baseline_learning',
            'analyze_knowledge_requirements',
          ],
          client_request_id: `task-e2e-${Date.now()}`,
        })
        expect(gap.status).toBe('completed')

        // 2. continue with knowledge + physics + planning stages
        const resumed = await runsApi.continueRun(gap.application_run_id, {
          stages: [
            'prepare_knowledge',
            'satisfy_requirements',
            'calibrate_physics',
            'establish_process_model',
            'plan_process',
          ],
        })
        expect(resumed.status).toBe('completed')

        // 3. fetch every artifact through the frontend API layer
        const { items } = await runsApi.getArtifacts(gap.application_run_id)
        const artifacts = new Map<string, Record<string, unknown>>()
        for (const meta of items) {
          const envelope = await runsApi.getArtifact<Record<string, unknown>>(meta.artifact_id)
          artifacts.set(meta.artifact_type, envelope.content.content)
        }

        // equipment: canonical snapshot resolved from the fixture store
        const equipment = artifacts.get('MachineProfileSnapshot') as Record<string, unknown>
        expect(equipment.resource_status).toBe('READY')
        expect(equipment.source_quality).toBe('DEMO_FIXTURE')
        const fields = equipment.fields as Record<string, { value?: number; status?: string }>
        expect(fields.actual_power_W?.value).toBe(10)
        expect(fields.beam_radius_um?.status).toBe('DERIVED')

        // needs: knowledge classified, resource resolved
        const needs = artifacts.get('ScientificNeedSet') as { needs?: Array<{ need_type?: string }> }
        const needTypes = new Set((needs.needs ?? []).map((need) => need.need_type))
        expect(needTypes.has('SCIENTIFIC_KNOWLEDGE')).toBe(true)
        expect(needTypes.has('RESOURCE_INPUT')).toBe(false)

        // literature chain: five frozen artifacts (手册 §9)
        const corpusPack = artifacts.get('ScientificCorpusPack') as {
          corpus_pack?: { sources?: unknown[] }
          analysis_mapping?: { from_cache?: number }
        }
        expect((corpusPack.corpus_pack?.sources ?? []).length).toBeGreaterThanOrEqual(4)
        expect(corpusPack.analysis_mapping?.from_cache).toBeGreaterThanOrEqual(4)

        const ledger = artifacts.get('CandidateLedger') as {
          metrics?: Record<string, number>
          candidates?: Array<{ source_type?: string }>
        }
        expect((ledger.metrics?.candidates ?? 0)).toBeGreaterThanOrEqual(8)
        expect(ledger.candidates?.every((candidate) => candidate.source_type === 'LLM_DISCOVERY')).toBe(true)

        const conditions = artifacts.get('SourceConditionSet') as {
          conditions?: Array<{ condition_id?: string }>
        }
        expect((conditions.conditions ?? []).length).toBeGreaterThanOrEqual(1)

        const reconstructibility = artifacts.get('ReconstructibilityReportSet') as {
          reports?: Array<{ condition_id?: string; reconstructibility_status?: string }>
        }
        expect((reconstructibility.reports ?? []).length).toBe(
          (conditions.conditions ?? []).length,
        )
        expect(
          (reconstructibility.reports ?? []).every((report) =>
            ['FULL', 'PARTIAL', 'BLOCKED'].includes(report.reconstructibility_status ?? ''),
          ),
        ).toBe(true)

        const applicability = artifacts.get('ApplicabilityReportSet') as {
          items?: Array<{ evidence_id?: string; transfer_level?: string }>
        }
        expect((applicability.items ?? []).length).toBeGreaterThanOrEqual(6)
        expect(applicability.items?.every((item) => item.transfer_level)).toBe(true)

        const evidenceSet = artifacts.get('EvidenceIRSet') as {
          items?: Array<Record<string, unknown>>
        }
        const evidenceItems = evidenceSet.items ?? []
        expect(evidenceItems.length).toBeGreaterThanOrEqual(6)
        const thresholdItem = evidenceItems.find(
          (item) => item.claim_type === 'threshold',
        )
        expect(thresholdItem?.ledger_ref).toMatchObject({ type: 'CandidateLedger' })
        expect((thresholdItem?.condition_refs as unknown[]).length).toBeGreaterThan(0)
        expect((thresholdItem?.reconstructibility_refs as unknown[]).length).toBeGreaterThan(0)

        // typed priors
        const priors = artifacts.get('PriorObjectSet') as { priors?: Array<Record<string, unknown>> }
        const priorTypes = new Set((priors.priors ?? []).map((prior) => prior.prior_type))
        expect([...priorTypes]).toEqual(
          expect.arrayContaining(['ParameterPrior', 'MechanismModelPrior', 'PlanningPreferencePrior']),
        )
        const fth = (priors.priors ?? []).find(
          (prior) => prior.prior_type === 'ParameterPrior' && prior.parameter === 'F_th_eff',
        )
        expect(fth?.lower).toBe(0.65)
        expect(fth?.upper).toBe(0.95)

        // calibration matches the fixture truth model
        const calibration = artifacts.get('CalibrationResult') as {
          parameters?: Array<{ parameter?: string; estimate?: number | null }>
        }
        const estimates = new Map(
          (calibration.parameters ?? [])
            .filter((item) => item.estimate !== null)
            .map((item) => [item.parameter, item.estimate as number]),
        )
        expect(estimates.get('F_th_eff')).toBeCloseTo(0.8, 1)
        expect(estimates.get('incubation_S')).toBeCloseTo(0.78, 1)

        // model + simulation + plan
        const model = artifacts.get('LocalRemovalModel') as { mode?: string }
        expect(model.mode).toBe('RECONSTRUCTED')
        const simulation = artifacts.get('MorphologySimulationResult') as {
          simulation_id?: string
          predicted_depth_field_um?: number[][]
        }
        expect(simulation.simulation_id).toBeTruthy()
        expect((simulation.predicted_depth_field_um ?? []).length).toBeGreaterThan(0)
        const plan = artifacts.get('ToolpathPlan') as {
          status?: string
          candidate_summary?: Array<{ path_family?: string }>
        }
        expect(plan.status).toBe('DEMO_CANDIDATE')
        const families = new Set((plan.candidate_summary ?? []).map((c) => c.path_family))
        expect(families).toEqual(new Set(['RASTER', 'CROSS_HATCH']))

        // authoritative run control: lives in run result (手册 §15), gates not blocked
        const run = await runsApi.getRun(gap.application_run_id)
        expect(run.status).toBe('completed')
        const control = (
          run.result as { runControlState?: Record<string, unknown> }
        ).runControlState as {
          execution_mode?: string
          provisional?: boolean
          blocking_reasons?: string[]
          phase_status?: string
          gates?: Record<string, { status?: string }>
        }
        expect(control.execution_mode).toBe('DEMO_FIXTURE')
        expect(control.provisional).toBe(false)
        expect(control.blocking_reasons ?? []).toEqual([])
        expect(control.phase_status).toMatch(/COMPLETED|PARTIAL/)
        expect(control.gates?.A?.status).toBe('READY')
        expect(control.gates?.C?.status).toBe('READY')
        expect(control.gates?.D?.status).toBe('READY')
      } finally {
        backend.kill()
        await rm(scratch, { recursive: true, force: true })
      }
    },
  )
})
