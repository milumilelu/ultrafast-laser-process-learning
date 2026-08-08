/** Physics-to-Planning V1 frontend gates F1-F6. */

import { render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  ApplicationArtifactSnapshot,
  CalibrationResultArtifact,
  EvidenceIRSetArtifact,
  KnowledgeRequirementSetArtifact,
  LocalRemovalModelArtifact,
  MorphologySimulationArtifact,
  PriorObjectSetArtifact,
  RetrievalQueryPlanArtifact,
  ScientificCapabilityArtifact,
  ToolpathPlanArtifact,
  WorkflowEvent,
} from '../../api/types'
import {
  CalibrationArtifactView,
  CapabilityArtifactView,
  KnowledgeArtifactView,
  PlanningArtifactView,
  PhysicsToPlanningWorkspace,
  SimulationArtifactView,
} from '../physics/PhysicsToPlanningWorkspace'
import { FlowTab } from '../../pages/AuditWorkspace'
import { APPLICATION_CHECKPOINTS } from '../../pages/IntelligentProcessApplication'
import { useWorkflowStore } from '../../stores/workflow'
import { applicationApi } from '../../api/application'

function snapshot<T>(
  type: string,
  content: T,
  inputRefs: { type: string; id: string }[] = [],
): ApplicationArtifactSnapshot<T> {
  return {
    id: `${type}-artifact-1`,
    type,
    schema_version: 'physics-to-planning-v1',
    input_refs: inputRefs,
    content,
    created_at: '2026-08-08T00:00:00Z',
  }
}

const capability = snapshot<ScientificCapabilityArtifact>('ScientificCapabilityReport', {
  capability_id: 'capability-1',
  task_ref: { type: 'TaskState', id: 'task-1' },
  input_refs: [{ type: 'TaskState', id: 'task-1' }],
  interaction_topology: 'SHALLOW_2_5D',
  simulation_supported: true,
  supported_fidelity: ['F0_FIXED_KERNEL', 'F1_INCUBATION', 'F2_DEFOCUS_RECURSION'],
  available: [
    {
      name: 'actual_power_W',
      value: 10,
      unit: 'W',
      status: 'AVAILABLE',
      source_refs: [{ type: 'MachineProfile', id: 'machine-1' }],
    },
  ],
  missing: [
    { name: 'absorptance', value: null, unit: 'dimensionless', status: 'MISSING', source_refs: [] },
  ],
  identifiability: [
    {
      parameter: 'thermal_diffusivity',
      status: 'NOT_IDENTIFIABLE',
      reason_codes: ['terminal_depth_has_no_transient_information'],
      required_observations: ['time_resolved_temperature'],
    },
  ],
  recommended_requirements: [],
  status: 'UNKNOWN',
  reason_codes: ['capability_partial'],
  provenance: [
    { source_type: 'DETERMINISTIC_COMPUTATION', source_ref: 'Capability:v1', role: 'preflight' },
  ],
})

const requirements = snapshot<KnowledgeRequirementSetArtifact>('KnowledgeRequirementSet', {
  requirements: [
    {
      requirement_id: 'KR-FTH',
      type: 'PARAMETER_PRIOR',
      scientific_question: 'SiC 的有效烧蚀阈值范围是什么？',
      required_for: 'LocalRemovalModel.F_th_eff',
      priority: 'high',
      trigger_reasons: ['threshold_missing'],
      required_evidence_roles: ['threshold'],
      satisfaction_criteria: ['threshold evidence exists'],
      status: 'UNKNOWN',
      provenance: [{ type: 'ScientificCapabilityReport', id: capability.id }],
    },
  ],
  diagnostics: {},
})

const queryPlans = snapshot<RetrievalQueryPlanArtifact>('LiteratureRetrievalQueryPlan', {
  schema_version: 'requirement-retrieval-v1',
  geometry_policy: 'SOFT_RANKING_HINT_ONLY',
  plans: [
    {
      query_plan_id: 'query-1',
      requirement_id: 'KR-FTH',
      requirement_type: 'PARAMETER_PRIOR',
      scientific_question: 'SiC 的有效烧蚀阈值范围是什么？',
      hard_facets: { material_or_family: ['SiC'], pulse_regime: ['fs'] },
      soft_facets: { target_geometry_hint: ['rectangular_groove'] },
      query_terms: ['SiC', 'ablation threshold'],
      geometry_is_hard_filter: false,
      reason_codes: ['exact_geometry_is_ranking_hint_only'],
    },
  ],
})

const evidence = snapshot<EvidenceIRSetArtifact>('EvidenceIRSet', {
  schema_version: 'evidence-ir-set-v1',
  query_plan_ref: queryPlans.id,
  items: [
    {
      evidence_id: 'E-CIRCLE-FTH',
      title: 'Femtosecond SiC circular crater threshold study',
      claim_type: 'threshold',
      source_geometry: 'circular_crater',
      applicability_status: 'PARTIAL',
    },
  ],
})

const priors = snapshot<PriorObjectSetArtifact>('PriorObjectSet', {
  prior_set_id: 'prior-set-1',
  input_refs: [{ type: 'EvidenceIRSet', id: evidence.id }],
  priors: [
    {
      prior_id: 'prior-fth-1',
      prior_type: 'ParameterPrior',
      parameter: 'F_th_eff',
      lower: 0.65,
      upper: 0.95,
      unit: 'J/cm2',
      parameter_semantics: 'PROVISIONAL',
      evidence_refs: [{ type: 'EvidenceIR', id: 'E-CIRCLE-FTH' }],
      applicability_refs: [],
      provenance: [{ type: 'EvidenceIR', id: 'E-CIRCLE-FTH' }],
      uncertainty: 'HIGH',
      status: 'EXTERNAL_PRIOR',
      conflict_status: 'NONE',
    },
  ],
  conflicts: [],
  warnings: [],
  provenance: [{ type: 'EvidenceIRSet', id: evidence.id }],
})

const calibration = snapshot<CalibrationResultArtifact>(
  'CalibrationResult',
  {
    calibration_id: 'calibration-1',
    input_refs: [{ type: 'PriorObjectSet', id: priors.id }],
    parameters: [
      {
        parameter: 'F_th_eff',
        estimate: 0.81234,
        lower: 0.79,
        upper: 0.84,
        unit: 'J/cm2',
        identifiability: 'IDENTIFIABLE',
        parameter_semantics: 'EFFECTIVE',
        prior_refs: [{ type: 'ParameterPrior', id: 'prior-fth-1' }],
        data_refs: [{ type: 'DataProfile', id: 'data-1' }],
        assumptions: [],
      },
      {
        parameter: 'thermal_diffusivity',
        estimate: null,
        lower: null,
        upper: null,
        unit: 'm2/s',
        identifiability: 'NOT_IDENTIFIABLE',
        parameter_semantics: 'PHYSICAL',
        prior_refs: [],
        data_refs: [{ type: 'DataProfile', id: 'data-1' }],
        assumptions: ['terminal response cannot identify transient diffusivity'],
      },
    ],
    fit_metrics: { rmse: 0.123, mae: 0.1, r2: 0.9, target_unit: 'um', n_observations: 12 },
    status: 'CALIBRATED',
    validation_data_refs: [],
    assumptions: [],
    provenance: [
      { source_type: 'SYNTHETIC_TEST_FIXTURE', source_ref: 'fixture-1', role: 'fit_only' },
    ],
  },
  [{ type: 'PriorObjectSet', id: priors.id }],
)

const model = snapshot<LocalRemovalModelArtifact>('LocalRemovalModel', {
  model_id: 'local-removal-1',
  input_refs: [{ type: 'CalibrationResult', id: calibration.id }],
  mode: 'RECONSTRUCTED',
  threshold_J_cm2: 0.81234,
  incubation_S: 0.78,
  delta_um: 0.45,
  alpha_defocus_per_um: 0.02,
  thermal_memory_eff: 0,
  parameter_semantics: { F_th_eff: 'EFFECTIVE' },
  status: 'PARTIAL',
  assumptions: [],
  provenance: [
    { source_type: 'MODEL_RECONSTRUCTION', source_ref: 'factory-v1', role: 'local_removal' },
  ],
})

const morphology = snapshot<MorphologySimulationArtifact>(
  'MorphologySimulationResult',
  {
    simulation_id: 'simulation-1',
    input_refs: [{ type: 'LocalRemovalModel', id: model.id }],
    local_removal_model_ref: { type: 'LocalRemovalModel', id: model.id },
    fidelity: 'F2_DEFOCUS_RECURSION',
    state: {
      height_field_um: [[-1.8, -2.1], [-2.0, -1.9]],
      effective_pulse_count: [[1, 2], [2, 1]],
      accumulated_fluence_J_cm2: [[2, 4], [4, 2]],
      thermal_memory_proxy: [[0, 0], [0, 0]],
      grid_spacing_um: 2,
      validity_flags: [],
    },
    target_depth_field_um: [[2, 2], [2, 2]],
    predicted_depth_field_um: [[1.8, 2.1], [2, 1.9]],
    difference_field_um: [[-0.2, 0.1], [0, -0.1]],
    metrics: {
      mean_depth_um: 1.95,
      max_depth_um: 2.1,
      removed_volume_um3: 31.2,
      morphology_rmse_um: 0.321,
      machining_time_s: 1.75,
    },
    pulse_count: 44,
    deterministic_seed: 42,
    status: 'PARTIAL',
    warnings: [],
    provenance: [
      { source_type: 'DETERMINISTIC_COMPUTATION', source_ref: 'Simulator:v1', role: 'F2_DEFOCUS_RECURSION' },
    ],
  },
  [{ type: 'LocalRemovalModel', id: model.id }],
)

const toolpath = snapshot<ToolpathPlanArtifact>(
  'ToolpathPlan',
  {
    plan_id: 'toolpath-plan-1',
    input_refs: [{ type: 'MorphologySimulationResult', id: morphology.id }],
    path_family: 'CROSS_HATCH',
    path_parameters: { hatch_um: 6.25, passes: 2, angle_deg: 0, angle_change_per_pass_deg: 90 },
    laser_parameters: { frequency_kHz: 100, scan_speed_mm_s: 50, peak_fluence_J_cm2: 3.2 },
    predicted_metrics: morphology.content.metrics,
    machine_constraints: [{ name: 'scan_speed_mm_s', lower: 20, upper: 200, unit: 'mm/s' }],
    simulation_ref: { type: 'MorphologySimulationResult', id: morphology.id },
    planning_prior_refs: [{ type: 'PlanningPreferencePrior', id: 'path-prior-1' }],
    status: 'RECOMMENDED',
    objective_value: 0.3385,
    candidate_summary: [{ path_family: 'RASTER' }, { path_family: 'CROSS_HATCH' }],
    provenance: [
      { source_type: 'DETERMINISTIC_COMPUTATION', source_ref: 'Planner:v1', role: 'simulator_in_the_loop' },
    ],
  },
  [{ type: 'MorphologySimulationResult', id: morphology.id }],
)

describe('F1/F2 artifact and state semantics', () => {
  it('renders Capability values and preserves UNKNOWN / NOT_IDENTIFIABLE semantics', () => {
    render(<CapabilityArtifactView snapshot={capability} requirements={requirements} developerMode={false} />)
    expect(screen.getByText('10 W')).toBeInTheDocument()
    expect(screen.getAllByText('未知').length).toBeGreaterThan(0)
    expect(screen.getByText('当前数据不可辨识')).toBeInTheDocument()
    expect(screen.queryByText('不匹配')).not.toBeInTheDocument()
  })

  it('renders backend Prior and fitted values without inventing an unidentifiable estimate', () => {
    render(
      <CalibrationArtifactView
        capability={capability}
        priors={priors}
        calibration={calibration}
        developerMode={false}
      />,
    )
    expect(screen.getByText('[0.65, 0.95] J/cm2')).toBeInTheDocument()
    expect(screen.getByText(/0.812.*J\/cm2/)).toBeInTheDocument()
    const thermalRow = screen.getByText('thermal_diffusivity').closest('tr')
    expect(thermalRow).not.toBeNull()
    expect(within(thermalRow!).getAllByText(/当前数据不可辨识/).length).toBeGreaterThan(0)
    expect(thermalRow).not.toHaveTextContent('0.81234')
  })
})

describe('F4 requirement-first literature behavior', () => {
  it('shows cross-geometry threshold evidence and the soft geometry policy', () => {
    render(
      <KnowledgeArtifactView
        requirements={requirements}
        queryPlans={queryPlans}
        evidence={evidence}
        priors={priors}
        developerMode={false}
      />,
    )
    expect(screen.getByText('Geometry policy: SOFT_RANKING_HINT_ONLY')).toBeInTheDocument()
    expect(screen.getByText('exact geometry hard filter = false')).toBeInTheDocument()
    expect(screen.getByText('Femtosecond SiC circular crater threshold study')).toBeInTheDocument()
    expect(screen.getByText('Source geometry: circular_crater')).toBeInTheDocument()
  })
})

describe('F1 morphology and planning artifact consistency', () => {
  it('renders all three backend fields, fidelity, model mode, and exact RMSE', () => {
    render(<SimulationArtifactView simulation={morphology} model={model} developerMode={false} />)
    expect(screen.getByText('Fidelity F2_DEFOCUS_RECURSION')).toBeInTheDocument()
    expect(screen.getByText('LocalRemovalModel RECONSTRUCTED')).toBeInTheDocument()
    expect(screen.getByText('Target surface / depth')).toBeInTheDocument()
    expect(screen.getByText('Predicted surface / depth')).toBeInTheDocument()
    expect(screen.getByText('Difference / error')).toBeInTheDocument()
    expect(screen.getByText('0.321 µm')).toBeInTheDocument()
  })

  it('renders ToolpathPlan values directly from the artifact', () => {
    render(<PlanningArtifactView plan={toolpath} simulation={morphology} developerMode={false} />)
    expect(screen.getByText('Path Family CROSS_HATCH')).toBeInTheDocument()
    expect(screen.getByText('6.25')).toBeInTheDocument()
    expect(screen.getByText('0.321 µm')).toBeInTheDocument()
    expect(screen.getByText('1.75 s')).toBeInTheDocument()
    expect(screen.getByText(`Simulation ${morphology.id}`)).toBeInTheDocument()
  })
})

describe('F3 checkpoint/resume consistency', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useWorkflowStore.getState().clear()
  })

  it('uses canonical stages and appends resume events to the same run monotonically', () => {
    expect(APPLICATION_CHECKPOINTS.capability).toEqual(['prepare_task', 'assess_capability'])
    expect(APPLICATION_CHECKPOINTS.knowledgeRequirements).toEqual([
      'assess_data',
      'baseline_learning',
      'analyze_knowledge_requirements',
    ])
    expect(APPLICATION_CHECKPOINTS.physicsCalibration).toEqual(['calibrate_physics', 'establish_process_model'])
    expect(APPLICATION_CHECKPOINTS.processPlanning).toEqual(['plan_process'])

    const first: WorkflowEvent = {
      event_id: 'event-1', run_id: 'app-1', sequence: 1, timestamp: '2026-08-08T00:00:00Z',
      type: 'STAGE_COMPLETED', stage: 'assess_capability', summary: 'Capability complete',
    }
    const resumed: WorkflowEvent = {
      event_id: 'event-2', run_id: 'app-1', sequence: 2, timestamp: '2026-08-08T00:01:00Z',
      type: 'STAGE_COMPLETED', stage: 'analyze_knowledge_requirements', summary: 'Requirements complete',
    }
    useWorkflowStore.getState().start('app-1')
    useWorkflowStore.getState().append([first])
    useWorkflowStore.getState().append([resumed])
    const state = useWorkflowStore.getState()
    expect(state.activeRunId).toBe('app-1')
    expect(state.events.map((item) => item.sequence)).toEqual([1, 2])
    expect(state.lastSequence).toBe(2)
  })

  it('refreshes artifacts after a completed stage without changing the run id', async () => {
    const metadataSpy = vi.spyOn(applicationApi, 'getArtifacts').mockResolvedValue({
      items: [
        {
          artifact_id: capability.id,
          artifact_type: 'ScientificCapabilityReport',
          created_at: capability.created_at,
        },
      ],
    })
    vi.spyOn(applicationApi, 'getArtifact').mockResolvedValue({
      artifact_id: capability.id,
      application_run_id: 'app-1',
      artifact_type: 'ScientificCapabilityReport',
      content: capability,
    })
    const { rerender } = render(
      <PhysicsToPlanningWorkspace
        runId="app-1"
        view="capability"
        developerMode={false}
        artifactRevision={1}
      />,
    )
    await screen.findByTestId('capability-view')
    rerender(
      <PhysicsToPlanningWorkspace
        runId="app-1"
        view="capability"
        developerMode={false}
        artifactRevision={2}
      />,
    )
    await waitFor(() => expect(metadataSpy).toHaveBeenCalledTimes(2))
    expect(metadataSpy).toHaveBeenNthCalledWith(1, 'app-1')
    expect(metadataSpy).toHaveBeenNthCalledWith(2, 'app-1')
  })
})

describe('F5/F6 real DAG and developer mode', () => {
  it('builds Flow nodes only from persisted events and artifact refs', () => {
    const events: WorkflowEvent[] = [
      { event_id: 's1', run_id: 'app-1', sequence: 1, timestamp: '2026-08-08T00:00:00Z', type: 'STAGE_STARTED', stage: 'calibrate_physics', summary: 'start' },
      { event_id: 'a1', run_id: 'app-1', sequence: 2, timestamp: '2026-08-08T00:00:01Z', type: 'ARTIFACT_CREATED', stage: 'calibrate_physics', summary: 'CalibrationResult created', artifactRefs: [{ type: 'CalibrationResult', id: calibration.id }] },
      { event_id: 's2', run_id: 'app-1', sequence: 3, timestamp: '2026-08-08T00:00:02Z', type: 'STAGE_COMPLETED', stage: 'calibrate_physics', summary: 'done' },
      { event_id: 's3', run_id: 'app-1', sequence: 4, timestamp: '2026-08-08T00:00:03Z', type: 'STAGE_STARTED', stage: 'plan_process', summary: 'start' },
      { event_id: 'a2', run_id: 'app-1', sequence: 5, timestamp: '2026-08-08T00:00:04Z', type: 'ARTIFACT_CREATED', stage: 'plan_process', summary: 'ToolpathPlan created', artifactRefs: [{ type: 'ToolpathPlan', id: toolpath.id }] },
    ]
    render(<FlowTab events={events} developerMode />)
    expect(screen.getByText('calibrate_physics')).toBeInTheDocument()
    expect(screen.getByText('plan_process')).toBeInTheDocument()
    expect(screen.getByText('CalibrationResult created')).toBeInTheDocument()
    expect(screen.getByText(`→ CalibrationResult:${calibration.id}`)).toBeInTheDocument()
    expect(screen.queryByText('prepare_knowledge')).not.toBeInTheDocument()
  })

  it('shows IDs, refs, schema, provenance, and raw payload only in Developer Mode', () => {
    const { rerender } = render(
      <PlanningArtifactView plan={toolpath} simulation={morphology} developerMode={false} />,
    )
    expect(screen.queryByTestId('developer-ToolpathPlan')).not.toBeInTheDocument()
    rerender(<PlanningArtifactView plan={toolpath} simulation={morphology} developerMode />)
    const panel = screen.getByTestId('developer-ToolpathPlan')
    expect(panel).toHaveTextContent(toolpath.id)
    expect(panel).toHaveTextContent('schema physics-to-planning-v1')
    expect(panel).toHaveTextContent(`MorphologySimulationResult:${morphology.id}`)
    expect(panel).toHaveTextContent('provenance')
    expect(panel).toHaveTextContent('candidate_summary')
  })
})
