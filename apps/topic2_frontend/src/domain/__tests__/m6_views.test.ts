/** M6: domain view-model tests over the REAL golden scenario payload
 * (exported by scripts/export_golden_frontend_fixture.py). */

import goldenRun from '../../__fixtures__/goldenRun.json'
import { buildRunControl } from '../control'
import { buildEquipmentView } from '../equipment'
import { buildNeedsView } from '../needs'
import { buildResolutionView } from '../resolution'
import {
  buildApplicabilityView,
  buildConditionSetView,
  buildLedgerView,
  buildReconstructibilityView,
} from '../condition'
import { buildSimulationView } from '../simulation'
import { buildPlanView } from '../planning'

function contentOf(artifact: Record<string, unknown>) {
  return artifact as { content: Record<string, unknown> }
}

describe('M6 view models over the golden scenario fixture', () => {
  const artifacts = goldenRun.artifacts as Record<string, { content: Record<string, unknown> }>

  it('control state: gates authoritative, provisional off for DEMO_FIXTURE', () => {
    const control = buildRunControl(
      (goldenRun.run.result as { runControlState?: Record<string, unknown> }).runControlState,
    )
    expect(control.executionMode).toBe('DEMO_FIXTURE')
    expect(control.provisional).toBe(false)
    expect(control.phaseStatus).toMatch(/COMPLETED|PARTIAL/)
    expect(control.gates.A.status).toBe('READY')
    expect(control.gates.C.status).toBe('READY')
    expect(control.gates.D.status).toBe('READY')
    expect(control.gates.B.status).toMatch(/READY|PARTIAL/)
    expect(control.blockingReasons).toEqual([])
    expect(control.completedStages).toContain('plan_process')
  })

  it('equipment snapshot: fixture quality, power + derived beam radius', () => {
    const equipment = buildEquipmentView(contentOf(artifacts.MachineProfileSnapshot).content)
    expect(equipment.sourceQuality).toBe('DEMO_FIXTURE')
    expect(equipment.resourceStatus).toBe('READY')
    expect(equipment.missingRequired).toEqual([])
    const power = equipment.fields.find((field) => field.parameter === 'actual_power_W')
    expect(power?.value).toBe(10)
    const beam = equipment.fields.find((field) => field.parameter === 'beam_radius_um')
    expect(beam?.status).toBe('DERIVED')
    expect(beam?.value).toBe(8)
    expect(equipment.machineBounds.length).toBeGreaterThan(0)
  })

  it('needs: knowledge + observation classified, resource resolved', () => {
    const needs = buildNeedsView(contentOf(artifacts.ScientificNeedSet).content)
    expect(needs.needs.length).toBeGreaterThan(0)
    expect(needs.counts.RESOURCE_INPUT).toBe(0)
    expect(needs.counts.SCIENTIFIC_KNOWLEDGE).toBeGreaterThan(0)
    expect(needs.counts.CALIBRATION_OBSERVATION).toBeGreaterThan(0)
  })

  it('corpus pack: corpus -> cache reading', () => {
    const resolution = buildResolutionView(contentOf(artifacts.ScientificCorpusPack).content)
    expect(resolution.sources.length).toBeGreaterThanOrEqual(4)
    expect(resolution.mapping.fromCache).toBeGreaterThanOrEqual(4)
    expect(resolution.sources.every((source) => source.paperId)).toBe(true)
  })

  it('mid-chain: ledger -> conditions -> reconstructibility -> evidence traceability', () => {
    const ledger = buildLedgerView(contentOf(artifacts.CandidateLedger).content)
    expect(ledger.candidates.length).toBeGreaterThanOrEqual(8)
    expect(ledger.candidates.every((candidate) => candidate.sourceType === 'LLM_DISCOVERY')).toBe(true)

    const conditions = buildConditionSetView(contentOf(artifacts.SourceConditionSet).content)
    expect(conditions.length).toBeGreaterThanOrEqual(1)
    expect(conditions.every((condition) => condition.fields.length > 0)).toBe(true)

    const reports = buildReconstructibilityView(
      contentOf(artifacts.ReconstructibilityReportSet).content,
    )
    expect(reports.length).toBe(conditions.length)
    expect(reports.every((report) => report.reconstructibilityStatus)).toBe(true)

    const applicability = buildApplicabilityView(
      contentOf(artifacts.ApplicabilityReportSet).content,
    )
    expect(applicability.length).toBeGreaterThanOrEqual(6)
    expect(applicability.every((item) => item.transferLevel)).toBe(true)

    // EvidenceIR carries the traceability refs
    const evidence = contentOf(artifacts.EvidenceIRSet).content.items as Array<Record<string, unknown>>
    const threshold = evidence.find(
      (item) => item.claim_type === 'threshold' && (item as { parameter?: string }).parameter === 'F_th_eff',
    )
    expect(threshold?.ledger_ref).toMatchObject({ type: 'CandidateLedger' })
    expect((threshold?.condition_refs as unknown[]).length).toBeGreaterThan(0)
    expect((threshold?.reconstructibility_refs as unknown[]).length).toBeGreaterThan(0)
  })

  it('evidence set: F_th threshold literature evidence present', () => {
    const evidence = contentOf(artifacts.EvidenceIRSet).content.items as Array<Record<string, unknown>>
    const types = new Set(evidence.map((item) => item.claim_type))
    expect(types.has('threshold')).toBe(true)
    const fth = evidence.find(
      (item) => item.claim_type === 'threshold' && (item as { parameter?: string }).parameter === 'F_th_eff',
    )
    expect(fth).toBeTruthy()
    expect((fth?.claim as Record<string, unknown>).lower).toBe(0.65)
    expect((fth?.claim as Record<string, unknown>).upper).toBe(0.95)
  })

  it('priors: F_th parameter prior + POWER_LAW_INCUBATION + CROSS_HATCH planning', () => {
    const priors = contentOf(artifacts.PriorObjectSet).content.priors as Array<Record<string, unknown>>
    const types = priors.map((prior) => prior.prior_type)
    expect(types).toContain('ParameterPrior')
    expect(types).toContain('MechanismModelPrior')
    expect(types).toContain('PlanningPreferencePrior')
    const fth = priors.find(
      (prior) => prior.prior_type === 'ParameterPrior' && prior.parameter === 'F_th_eff',
    )
    expect(fth?.lower).toBe(0.65)
    expect(fth?.upper).toBe(0.95)
    const mechanism = priors.find((prior) => prior.prior_type === 'MechanismModelPrior')
    expect(mechanism?.model_family).toBe('POWER_LAW_INCUBATION')
    const planning = priors.find(
      (prior) => prior.prior_type === 'PlanningPreferencePrior' && (prior.path_families as string[])?.length,
    )
    expect(planning?.path_families).toEqual(['CROSS_HATCH'])
  })

  it('simulation: metrics, height field and cross-section present', () => {
    const simulation = buildSimulationView(contentOf(artifacts.MorphologySimulationResult).content)
    expect(simulation.simulationId).toBeTruthy()
    expect(simulation.pulseCount).toBeGreaterThan(0)
    expect(simulation.meanDepthUm).toBeGreaterThan(0)
    expect(simulation.heightField.length).toBeGreaterThan(0)
    expect(simulation.crossSection.length).toBeGreaterThan(0)
    expect(simulation.fidelity).toMatch(/^F\d/)
  })

  it('planning: recommended plan with both path families compared', () => {
    const plan = buildPlanView(contentOf(artifacts.ToolpathPlan).content)
    expect(plan.status).toBe('DEMO_CANDIDATE')
    const families = new Set(plan.candidates.map((candidate) => candidate.pathFamily))
    expect(families).toEqual(new Set(['RASTER', 'CROSS_HATCH']))
    expect(plan.pathFamily).toBe('CROSS_HATCH')
    expect(plan.candidates.some((candidate) => candidate.morphologyRmseUm !== null)).toBe(true)
    expect(plan.simulationRef?.type).toBe('MorphologySimulationResult')
  })

  it('calibration: fitted estimates match the fixture truth model', () => {
    const calibration = contentOf(artifacts.CalibrationResult).content.parameters as Array<Record<string, unknown>>
    const estimates = new Map(
      calibration
        .filter((item) => item.estimate !== null)
        .map((item) => [item.parameter, item.estimate]),
    )
    expect(estimates.get('F_th_eff')).toBeCloseTo(0.8, 1)
    expect(estimates.get('incubation_S')).toBeCloseTo(0.78, 1)
    expect(estimates.get('delta_eff')).toBeCloseTo(0.45, 1)
  })
})
