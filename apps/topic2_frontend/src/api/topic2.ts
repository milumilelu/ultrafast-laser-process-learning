/** Topic2 Backend adapter. All scientific results flow through here; no direct fetch in components. */

import { config } from '../config'
import { buildUrl, request } from './client'
import type {
  DataProfile,
  DatabaseStatistics,
  EquipmentItem,
  Evidence,
  EvidenceCompileResult,
  ExperimentRow,
  HealthResponse,
  GovernedPriorArtifactPayload,
  MaterialItem,
  ModelInfo,
  ModelPolicyResult,
  ModelTrainingResult,
  OptimizationResult,
  RunRecord,
  RunSummary,
  TaskScope,
} from './types'

export interface ModelPolicyRequest {
  scope: TaskScope
  data_profile: DataProfile
  evidence: Evidence[]
}

export interface OptimizationRequest {
  scope: TaskScope
  machine_bounds: Record<string, { lower: number; upper: number }>
  model_id?: string | null
  model_policy_run_id?: string | null
  governed_prior_artifact?: GovernedPriorArtifactPayload | null
  n_candidates?: number
  random_seed?: number
}

export const topic2Api = {
  health(): Promise<HealthResponse> {
    return request(config.topic2ApiUrl, 'GET', '/health')
  },

  materials(): Promise<{ items: MaterialItem[] }> {
    return request(config.topic2ApiUrl, 'GET', '/materials')
  },

  equipment(): Promise<{ items: EquipmentItem[] }> {
    return request(config.topic2ApiUrl, 'GET', '/equipment')
  },

  experiments(filters: {
    material?: string | null
    laser_type?: string | null
    equipment_id?: string | null
    geometry_type?: string | null
    target?: string | null
  } = {}): Promise<{ items: ExperimentRow[] }> {
    return request(
      config.topic2ApiUrl,
      'GET',
      buildUrl('/experiments', filters),
    )
  },

  statistics(): Promise<DatabaseStatistics> {
    return request(config.topic2ApiUrl, 'GET', '/database/statistics')
  },

  scopeCapability(filters: {
    material?: string | null
    laser_type?: string | null
    equipment_id?: string | null
    geometry_type?: string | null
  } = {}): Promise<{
    n_samples: number
    n_unique_designs: number
    targets: {
      depth_um: { n_samples: number; n_unique_designs: number }
      roughness_um: { n_samples: number; n_unique_designs: number }
    }
    available_equipment: string[]
    equipment_samples: Record<string, number>
    available_geometries: string[]
    meets_identification: boolean
    meets_modeling: boolean
  }> {
    return request(
      config.topic2ApiUrl,
      'GET',
      buildUrl('/scope-capability', filters),
    )
  },

  getParameterIdentification(runId: string): Promise<RunRecord> {
    return request(config.topic2ApiUrl, 'GET', `/parameter-identification/${runId}`)
  },

  compileEvidence(
    scope: TaskScope,
    evidence: Evidence[],
  ): Promise<EvidenceCompileResult> {
    return request(config.topic2ApiUrl, 'POST', '/e2p/evidence/compile', { scope, evidence })
  },

  modelPolicy(requestBody: ModelPolicyRequest): Promise<ModelPolicyResult> {
    return request(config.topic2ApiUrl, 'POST', '/e2p/model-policy', requestBody)
  },

  trainModels(
    scope: TaskScope,
    candidateModels: string[] | null = null,
    modelPolicyRunId: string | null = null,
  ): Promise<ModelTrainingResult> {
    return request(config.topic2ApiUrl, 'POST', '/models/train', {
      scope,
      candidate_models: candidateModels,
      model_policy_run_id: modelPolicyRunId,
    })
  },

  models(): Promise<{ items: ModelInfo[] }> {
    return request(config.topic2ApiUrl, 'GET', '/models')
  },

  getModel(modelId: string): Promise<ModelInfo> {
    return request(config.topic2ApiUrl, 'GET', `/models/${modelId}`)
  },

  recommend(requestBody: OptimizationRequest): Promise<OptimizationResult> {
    return request(config.topic2ApiUrl, 'POST', '/optimization/recommend', requestBody)
  },

  getOptimization(runId: string): Promise<RunRecord> {
    return request(config.topic2ApiUrl, 'GET', `/optimization/${runId}`)
  },

  listRuns(runType?: string | null): Promise<{ items: RunSummary[] }> {
    return request(
      config.topic2ApiUrl,
      'GET',
      buildUrl('/runs', { run_type: runType ?? undefined }),
    )
  },

  getRun(runId: string): Promise<RunRecord> {
    return request(config.topic2ApiUrl, 'GET', `/runs/${runId}`)
  },

  saveTaskContext(
    taskContextId: string,
    version: number,
    snapshot: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    return request(
      config.topic2ApiUrl,
      'PUT',
      `/task-contexts/${encodeURIComponent(taskContextId)}/versions/${version}`,
      snapshot,
    )
  },
}
