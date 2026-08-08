import { buildCapabilityView, buildChainStatus, recommendNextAction } from '../capability'

const capabilityFixture = {
  capability_id: 'cap-001',
  interaction_topology: 'SHALLOW_2_5D',
  simulation_supported: true,
  supported_fidelity: ['F0_FIXED_KERNEL', 'F1_INCUBATION', 'F2_DEFOCUS_RECURSION'],
  available: [
    { name: 'frequency_kHz', value: 100, unit: 'kHz', status: 'AVAILABLE', source_refs: [{ type: 'MachineProfile', id: 'm1' }] },
    { name: 'scan_speed_mm_s', value: 100, unit: 'mm/s', status: 'AVAILABLE', source_refs: [{ type: 'DataState', id: 'd1' }] },
  ],
  missing: [
    { name: 'actual_power', value: null, unit: 'W', status: 'MISSING', source_refs: [] },
    { name: 'beam_radius', value: null, unit: 'um', status: 'MISSING', source_refs: [] },
    { name: 'F_th', value: null, unit: 'J/cm2', status: 'MISSING', source_refs: [] },
  ],
  identifiability: [
    { parameter: 'thermal_diffusivity', status: 'NOT_IDENTIFIABLE', reason_codes: ['terminal_depth_only'], required_observations: ['transient'] },
  ],
  recommended_requirements: [
    {
      requirement_id: 'KR-001',
      type: 'PARAMETER_PRIOR',
      scientific_question: 'need SiC F_th',
      required_for: 'LogAblationModel.F_th',
      priority: 'high',
      trigger_reasons: ['computation_gap'],
      required_evidence_roles: ['THRESHOLD'],
      satisfaction_criteria: ['range'],
      status: 'UNKNOWN',
    },
  ],
  status: 'PARTIAL',
  reason_codes: ['missing_inputs'],
}

describe('buildCapabilityView', () => {
  it('returns null for missing artifact (empty state must be explicit)', () => {
    expect(buildCapabilityView(null)).toBeNull()
    expect(buildCapabilityView(undefined)).toBeNull()
  })

  it('merges available + missing into resolver rows', () => {
    const view = buildCapabilityView(capabilityFixture)
    expect(view).not.toBeNull()
    expect(view?.inputs).toHaveLength(5)
    expect(view?.inputs.map((i) => i.name)).toContain('actual_power')
  })

  it('classifies sources from backend refs only (spec §八)', () => {
    const view = buildCapabilityView(capabilityFixture)
    const freq = view?.inputs.find((i) => i.name === 'frequency_kHz')
    const speed = view?.inputs.find((i) => i.name === 'scan_speed_mm_s')
    const power = view?.inputs.find((i) => i.name === 'actual_power')
    expect(freq?.source).toBe('MACHINE_PROFILE')
    expect(speed?.source).toBe('MEASURED')
    expect(power?.source).toBe('MISSING')
  })

  it('derives Required For from capability requirements', () => {
    const view = buildCapabilityView(capabilityFixture)
    const fth = view?.inputs.find((i) => i.name === 'F_th')
    expect(fth?.requiredBy).toContain('KR-001')
  })
})

describe('buildChainStatus (spec §七)', () => {
  it('no report → NOT_RUN (execution namespace, never UNKNOWN)', () => {
    const { overall, nodes } = buildChainStatus(null)
    expect(overall).toBe('NOT_RUN')
    expect(nodes).toHaveLength(0)
  })

  it('missing actual_power blocks the power → pulse energy → fluence chain', () => {
    const { nodes } = buildChainStatus(buildCapabilityView(capabilityFixture))
    const power = nodes.find((n) => n.node.id === 'power')
    const planning = nodes.find((n) => n.node.id === 'planning')
    expect(power?.status).toBe('BLOCKED')
    expect(power?.blockingInputs).toContain('actual_power')
    expect(planning?.status).toBe('BLOCKED')
  })

  it('all available inputs → READY', () => {
    const view = buildCapabilityView({
      ...capabilityFixture,
      available: [
        { name: 'actual_power', value: 10, unit: 'W', status: 'AVAILABLE', source_refs: [{ type: 'MachineProfile', id: 'm1' }] },
        { name: 'beam_radius', value: 20, unit: 'um', status: 'AVAILABLE', source_refs: [{ type: 'MachineProfile', id: 'm1' }] },
        { name: 'F_th', value: 1, unit: 'J/cm2', status: 'AVAILABLE', source_refs: [{ type: 'EvidenceIR', id: 'e1' }] },
        { name: 'peak_fluence', value: 5, unit: 'J/cm2', status: 'AVAILABLE', source_refs: [{ type: 'CanonicalPhysicsState', id: 'c1' }] },
        { name: 'delta_eff', value: 0.5, unit: 'um', status: 'AVAILABLE', source_refs: [{ type: 'CalibrationResult', id: 'k1' }] },
        { name: 'normalized_fluence', value: 5, unit: '-', status: 'AVAILABLE', source_refs: [{ type: 'CanonicalPhysicsState', id: 'c1' }] },
      ],
      missing: [],
    })
    const { overall, nodes } = buildChainStatus(view)
    expect(overall).toBe('READY')
    expect(nodes.every((n) => n.status === 'READY')).toBe(true)
  })
})

describe('recommendNextAction (spec §六/§三十一)', () => {
  it('no report → continue to capability', () => {
    const action = recommendNextAction(null, null)
    expect(action.kind).toBe('CONTINUE')
  })

  it('missing inputs surface as the single next action', () => {
    const action = recommendNextAction(buildCapabilityView(capabilityFixture), 'running')
    expect(action.kind).toBe('FILL_INPUTS')
    expect(action.missingInputs).toContain('actual_power')
  })
})
