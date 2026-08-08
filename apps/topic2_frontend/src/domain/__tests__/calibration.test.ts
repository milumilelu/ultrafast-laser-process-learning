import { buildParameterRegistry } from '../calibration'
import type { CapabilityReportView } from '../capability'
import type { PriorView } from '../knowledge'

const capability = {
  capabilityId: 'cap-001',
  interactionTopology: 'SHALLOW_2_5D',
  simulationSupported: true,
  supportedFidelity: ['F2_DEFOCUS_RECURSION'],
  inputs: [
    { name: 'wavelength', value: 1030, unit: 'nm', status: 'AVAILABLE' as const, source: 'MACHINE_PROFILE' as const, sourceRefTypes: ['MachineProfile'], requiredBy: [] },
    { name: 'beam_radius', value: null, unit: 'um', status: 'MISSING' as const, source: 'MISSING' as const, sourceRefTypes: [], requiredBy: [] },
    { name: 'actual_power', value: null, unit: 'W', status: 'MISSING' as const, source: 'MISSING' as const, sourceRefTypes: [], requiredBy: [] },
  ],
  identifiability: [
    { parameter: 'thermal_diffusivity', status: 'NOT_IDENTIFIABLE' as const, reasonCodes: ['terminal_depth_only'], requiredObservations: [] },
  ],
  recommendedRequirements: [],
  status: 'PARTIAL',
  reasonCodes: [],
} satisfies CapabilityReportView

const priors: PriorView[] = [
  {
    priorId: 'p-1',
    priorType: 'ParameterPrior',
    parameter: 'F_th',
    range: [0.6, 1.1],
    unit: 'J/cm2',
    uncertainty: 'HIGH',
    status: 'EXTERNAL_PRIOR',
    conflictStatus: 'NONE',
    evidenceRefs: [{ type: 'EvidenceIR', id: 'e1' }],
    applicabilityRefs: [],
  },
]

describe('buildParameterRegistry (spec §十二 / FE-6)', () => {
  it('registry size is driven by backend data, never fixed at five', () => {
    const rows = buildParameterRegistry({ capability, calibration: null, identifiabilityReport: null, priors })
    expect(rows.length).toBeGreaterThanOrEqual(5)
  })

  it('a different backend dataset yields a different registry size (dynamic count)', () => {
    const empty = buildParameterRegistry({ capability: null, calibration: null, identifiabilityReport: null, priors: [] })
    expect(empty).toHaveLength(0)
    const withIdent = buildParameterRegistry({
      capability: null,
      calibration: null,
      identifiabilityReport: { parameters: [{ parameter: 'a', status: 'IDENTIFIABLE' }, { parameter: 'b', status: 'NOT_IDENTIFIABLE' }] },
      priors: [],
    })
    expect(withIdent).toHaveLength(2)
  })

  it('sources: machine input → MEASURED, missing → MISSING, prior-only → PRIOR_ONLY', () => {
    const rows = buildParameterRegistry({ capability, calibration: null, identifiabilityReport: null, priors })
    const wavelength = rows.find((r) => r.parameter === 'wavelength')
    const beam = rows.find((r) => r.parameter === 'beam_radius')
    const fth = rows.find((r) => r.parameter === 'F_th')
    expect(wavelength?.source).toBe('MEASURED')
    expect(beam?.source).toBe('MISSING')
    expect(fth?.source).toBe('PRIOR_ONLY')
    expect(fth?.lower).toBe(0.6)
    expect(fth?.upper).toBe(1.1)
  })

  it('NOT_IDENTIFIABLE parameters never show a fitted value source', () => {
    const rows = buildParameterRegistry({ capability, calibration: null, identifiabilityReport: null, priors })
    const thermal = rows.find((r) => r.parameter === 'thermal_diffusivity')
    expect(thermal?.source).toBe('NOT_IDENTIFIABLE')
    expect(thermal?.value).toBeNull()
  })

  it('calibrated estimates override prior-only status (backend says calibrated)', () => {
    const rows = buildParameterRegistry({
      capability: null,
      calibration: {
        calibrationId: 'c1',
        parameters: [
          {
            parameter: 'F_th_eff',
            estimate: 0.83,
            lower: 0.7,
            upper: 0.95,
            unit: 'J/cm2',
            identifiability: 'IDENTIFIABLE',
            semantics: 'EFFECTIVE',
            priorRefs: [{ type: 'PriorObjectSet', id: 'p' }],
            dataRefs: [],
            assumptions: [],
          },
        ],
        fitMetrics: { rmse: 1, mae: 1, r2: null, targetUnit: 'um', nObservations: 120 },
        status: 'CALIBRATED',
        validationDataRefs: [],
        assumptions: [],
      },
      identifiabilityReport: null,
      priors: [],
    })
    const fth = rows.find((r) => r.parameter === 'F_th_eff')
    expect(fth?.source).toBe('CALIBRATED')
    expect(fth?.value).toBe(0.83)
    expect(fth?.semantics).toBe('EFFECTIVE')
  })
})
