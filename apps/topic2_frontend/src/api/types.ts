/**
 * Types mirroring the real Topic2 Backend and Agent API contracts
 * (apps/topic2_backend/api/app.py, packages/process_contracts/schemas.py,
 * ultrafast_memory apps/api). No invented fields.
 */

export type LaserType = 'fs' | 'ps'
export type TargetName = 'depth_um' | 'roughness_um'

export interface HealthResponse {
  status: string
  version: string
  agent_required: boolean
  llm_required: boolean
  internet_required: boolean
  database_path: string
}

export interface MaterialItem {
  material: string
  is_synthetic: number
  data_origin: string
}

export interface EquipmentItem {
  equipment_id: string
  laser_id: string | null
  machine_id: string | null
}

export interface ExperimentRow {
  experiment_id: string
  material: string
  laser_type: LaserType
  equipment_id: string
  laser_id: string | null
  machine_id: string | null
  geometry_type: string
  target: TargetName
  pulse_width_ps: number | null
  frequency_kHz: number | null
  hatch_spacing_um: number | null
  passes: number | null
  scan_speed_mm_s: number | null
  depth_um: number | null
  roughness_um: number | null
  roughness_type: 'Sa' | 'Ra' | null
  measurement_device_id: string | null
  measurement_method: string | null
  experiment_batch_id: string
  parameter_combination_id: string
  source_file: string | null
  data_origin: string
  is_synthetic: number
  valid_flag: number
}

export interface DatabaseStatistics {
  material_count: number
  verified_material_count: number
  synthetic_material_count: number
  materials: string[]
  fs_record_count: number
  ps_record_count: number
  experiment_count: number
  model_count: number
  recommendation_count: number
  schema_version: string
}

export interface TaskScope {
  task_context_id?: string | null
  task_context_version?: number | null
  material: string
  material_grade?: string | null
  laser_type: LaserType
  equipment_id: string
  laser_id?: string | null
  machine_id?: string | null
  geometry_type: string
  target: TargetName
  process_parameters?: Record<string, unknown>
  device_properties?: Record<string, unknown>
}

export interface ProcessParameters {
  pulse_width_ps?: number | null
  frequency_kHz?: number | null
  hatch_spacing_um?: number | null
  passes?: number | null
  scan_speed_mm_s?: number | null
}

export interface EvidenceScope {
  material?: string | null
  laser_type?: LaserType | null
  geometry_type?: string | null
  equipment_id?: string | null
  target?: TargetName | null
}

export interface Evidence {
  evidence_id: string
  source_type: 'literature' | 'process_prior' | 'historical' | 'validated_rule'
  claim_type: string
  parameter: string | null
  target: string | null
  claim: Record<string, unknown>
  scope: EvidenceScope
  provenance: { source_id: string; review_id: string | null }
  review_status: 'pending' | 'approved' | 'rejected'
  version: string
}

export interface ApplicabilityResult {
  evidence_id: string
  material_match: boolean | null
  laser_type_match: boolean | null
  geometry_match: boolean | null
  equipment_match: boolean | null
  target_match: boolean | null
  transfer_level: 'strong' | 'medium' | 'weak' | 'none'
}

export interface EvidenceCompileResult {
  version: string
  candidates: Evidence[]
  accepted: Evidence[]
  rejected: { evidence_id: string; reason: string }[]
  applicability_results: ApplicabilityResult[]
}

export interface DataProfile {
  n_samples: number
  n_unique_designs: number
  n_features: number
  replicate_ratio: number
  missing_rate: number
  batch_count: number
  equipment_count: number
  coverage_score: number | null
}

export interface ModelPolicyResult {
  run_id: string
  model_policy_version: string
  candidate_models: string[]
  preferred_models: string[]
  requirements: { uncertainty_required: boolean; interpretability_preferred: boolean }
  reason_codes: string[]
  final_selection_rule: string
  scope: TaskScope
}

export interface ModelMetrics {
  RMSE: number
  MAE: number
  R2: number
  n_samples: number
  n_unique_designs: number
  cv_folds: number
  uncertainty_available: boolean
}

export interface ModelTrainingResult {
  run_id: string
  model_id: string | null
  model_version: string
  dataset_version: string
  selected_model: string
  validation_metrics: Record<string, ModelMetrics>
  comparison: {
    baseline: { model: string } & ModelMetrics
    optimized: { model: string } & ModelMetrics
    comparison_basis: string
    improved: boolean
  }
  cv_strategy: string
}

export interface ModelInfo {
  model_id: string
  model_version: string
  dataset_version: string
  material: string
  target: TargetName
  model_name: string
  metrics: Record<string, number>
  artifact_path: string | null
  created_at: string
}

export interface RangePreference {
  evidence_id: string
  parameter: string
  lower: number
  upper: number
  strength: string
  fixed_weight: number
}

export interface PriorSpec {
  prior_spec_version: string
  range_preferences: RangePreference[]
}

export interface GovernedPriorArtifactPayload {
  artifact_id: string
  prior_spec: PriorSpec
  review_ids: string[]
  evidence_ids: string[]
  approval_trace: Record<string, unknown>[]
  compiler_version: string
  scope: Record<string, unknown>
  content_hash: string
  verification: 'repository_verified'
}

export interface OptimizationResult {
  run_id: string
  recommendation_id: string
  model_id: string | null
  model_policy_run_id: string | null
  model_source: 'fitted_for_optimization' | 'persisted_model_artifact'
  optimization_method: string
  recommended_parameters: Record<string, number>
  vanilla_recommended_parameters: Record<string, number>
  recommendation_changed_by_evidence: boolean
  prediction: { mean: number; std: number }
  acquisition: {
    normalized_ucb: number
    log_prior: number
    lambda_t: number
    score: number
  }
  machine_bounds: Record<string, { lower: number; upper: number }>
  prior_spec: PriorSpec
  governed_prior_artifact: GovernedPriorArtifactPayload | null
}

export interface RunSummary {
  run_id: string
  task_id: string
  run_type: string
  created_at: string
}

export interface RunRecord extends RunSummary {
  payload: Record<string, unknown>
}

/* ------------------------------ Agent API ------------------------------ */

export interface AgentSession {
  session_id: string
  title: string
  mode: string
  created_at: string
}

export interface AgentChatResponse {
  session_id: string
  assistant_message: string
  selected_skill: string | null
  route_plan: Record<string, unknown> | null
  evidence_gap: Record<string, unknown> | null
  knowledge_bootstrap: Record<string, unknown> | null
  progress: Record<string, unknown> | null
  thinking_status: Record<string, unknown>[]
  workflow_state: Record<string, unknown> | null
  execution_trace: Record<string, unknown>[]
  tool_calls: Record<string, unknown>[]
  audit_trace: Record<string, unknown>[]
  rag_evidence: Record<string, unknown> | null
  citations: Record<string, unknown>[]
  current_stage: string | null
  current_stage_code: string | null
  completed_stages: string[]
  pending_stages: string[]
  blocked_stages: string[]
  next_required_action: Record<string, unknown>
}

/* --------------------------- Equipment profiles --------------------------- */

export interface EquipmentProfileBase {
  equipment_profile_id: string
  profile_name: string
  machine_id: string | null
  manufacturer: string | null
  model: string | null
  location: string | null
  status: string
  is_active: number
  created_by: string | null
  created_at: string
  updated_at: string
  calibration_date: string | null
  valid_until: string | null
  notes: string | null
}

export interface EquipmentProfile extends EquipmentProfileBase {
  laser_source: Record<string, number | string | null>
  optical_setup: Record<string, number | string | null>
  motion_system: Record<string, number | string | null>
  process_capability: Record<string, number | string | null>
  revision_id: string | null
}

export interface EquipmentProfileCreate {
  profile_name: string
  machine_id?: string | null
  manufacturer?: string | null
  model?: string | null
  location?: string | null
  notes?: string | null
  laser_source: Record<string, unknown>
  optical_setup: Record<string, unknown>
  motion_system: Record<string, unknown>
  process_capability: Record<string, unknown>
  set_active: boolean
}

export interface EquipmentProfileCreated {
  equipment_profile_id: string
  revision_id: string
  is_active: boolean
}

export interface TunableCapability {
  min: number
  max: number
  unit: string
  role: string
}

export interface MachineBoundsResponse {
  active: boolean
  equipment_profile_id?: string
  profile_name?: string
  revision_id?: string
  fixed_conditions: Record<string, number>
  tunable_capabilities: Record<string, TunableCapability>
  machine_bounds: Record<string, [number, number]>
  missing_equipment_fields: string[]
}

/* ---------------------- Application Run / WorkflowEvent ---------------------- */

export type WorkflowEventType =
  | 'RUN_STARTED'
  | 'RUN_COMPLETED'
  | 'RUN_FAILED'
  | 'STAGE_STARTED'
  | 'STAGE_PROGRESS'
  | 'STAGE_COMPLETED'
  | 'TOOL_STARTED'
  | 'TOOL_COMPLETED'
  | 'ENTITY_CREATED'
  | 'ARTIFACT_CREATED'
  | 'VALIDATION'
  | 'WARNING'
  | 'ERROR'

export interface WorkflowEvent {
  eventId?: string
  event_id: string
  runId?: string
  run_id: string
  sequence: number
  timestamp: string
  type: WorkflowEventType
  stage?: string | null
  summary: string
  progress?: { current?: number; total?: number } | null
  entityRefs?: { type: string; id: string }[]
  artifactRefs?: { type: string; id: string }[]
  details?: Record<string, unknown>
}

export type FacetName =
  | 'Material'
  | 'Task'
  | 'InteractionState'
  | 'Reconstructibility'
  | 'Reachability'

export type FacetStatus = 'KNOWN' | 'PARTIAL' | 'UNKNOWN' | 'MISMATCH'

export interface ParameterImportance {
  feature: string
  importance: number
  effect_direction: string
  rank: number
}

export interface PhysicsCoordinateStatus {
  coordinate: string
  status: string
  dependencies: string[]
  reason: string | null
  source?: string | null
  target?: string | null
  comparison?: string | null
}

export interface BOResult {
  run_id: string
  bo_run_id?: string
  model_id: string | null
  model_source: string
  optimization_method: string
  recommended_parameters: Record<string, number>
  vanilla_recommended_parameters?: Record<string, number>
  recommendation_changed_by_evidence?: boolean
  search_prior_applied?: boolean
  prediction: { mean: number; std: number } | Record<string, unknown>
  acquisition: Record<string, unknown>
  machine_bounds: Record<string, { lower: number; upper: number }>
  prior_spec?: { prior_spec_version?: string; range_preferences: unknown[] }
  governed_prior?: Record<string, unknown> | null
  [key: string]: unknown
}

export interface PriorAppliedEvidence {
  vanilla_search_prior_applied: boolean
  assisted_search_prior_applied: boolean
  assisted_prior_guidance: string | null
  governed_prior_hash: string | null
  assisted_prior_evidence_ids: string[]
}

export interface Topic2ApplicationResult {
  runId: string
  workflowVersion: string
  targetTask: {
    material: string
    laserType: string
    geometry: string
    equipment: string
    target: string
    randomSeed?: number
    sampleCount?: number | null
  }
  processLearning: {
    selectedFeatureView: string
    selectedModel: string | null
    controllableRanking?: ParameterImportance[]
    mechanismRanking?: ParameterImportance[]
    modelComparison: Record<string, ModelMetrics> | string[] | Record<string, unknown>
    physicsReadiness?: PhysicsCoordinateStatus[]
    cvFolds?: number
    featureViews?: Record<string, unknown>
    identificationRunId?: string | null
    trainingRunId?: string | null
    [key: string]: unknown
  }
  scientificBasis: {
    paperCount?: number
    candidateCount?: number
    evidenceCount?: number
    governedEvidenceCount?: number
    priorCount?: number
    governedPrior?: Record<string, unknown> | null
  }
  cfa: {
    version: string | null
    calibrationStatus: 'NOT_YET_CALIBRATED' | string
    facetSummary: Record<string, string>
    warnings: string[]
    targetPhysicsReadiness?: Record<string, unknown> | null
    reports?: Record<string, unknown>[]
  }
  knowledgeState?: {
    requirements?: {
      requirement_id: string
      type: string
      question: string
      required_for?: string
      priority?: string
      trigger_reasons?: string[]
    }[]
    satisfactions?: {
      requirement_id: string
      status: string
      assessment_method?: string
      unresolved_reasons?: string[]
    }[]
    existing_knowledge?: Record<string, unknown>
    missing_topics?: string[]
    assessment_version?: string | null
  } | null
  optimization: {
    vanilla: BOResult
    evidenceAssisted: BOResult
    priorAppliedEvidence: PriorAppliedEvidence
  }
  audit: {
    evidenceIds: string[]
    priorContentHash: string | null
    boRunIds: (string | null)[]
    modelVersion?: string | null
    replayable: boolean
    ledgerVersionIds?: string[]
  }
}

export interface ApplicationRunSummary {
  application_run_id: string
  status: 'running' | 'completed' | 'failed'
  task_context_ref: string
  mode: 'demo' | 'research'
  workflow_version: string
  stage_status: Record<string, { status: string }>
  created_at: string
  completed_at: string | null
}

export interface OptimizationComparison {
  vanilla: BOResult
  evidence_assisted: BOResult
  prior_applied_evidence: PriorAppliedEvidence
}

export interface E2PPrepareResult {
  e2p_run_id: string
  dataset_version: string
  evidence: {
    candidates: string[]
    accepted: string[]
    rejected: string[]
  }
  applicability: ApplicabilityResult[]
  model_policy: ModelPolicyResult
  prior_spec: { prior_spec_version: string; range_preferences: RangePreference[] }
  governed_prior_artifact: GovernedPriorArtifactPayload | null
  conflict_state: { status: string }
}
