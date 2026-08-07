/** Scientific results produced by the Topic2 Backend, kept outside components. */

import { create } from 'zustand'

import { computeDataProfile } from '../lib/dataProfile'
import type {
  DataProfile,
  Evidence,
  EvidenceCompileResult,
  ExperimentRow,
  ModelPolicyResult,
  ModelTrainingResult,
  OptimizationResult,
  RunSummary,
} from '../api/types'

export interface ScientificPackState {
  corpus: Record<string, unknown> | null
  knowledge: Record<string, unknown> | null
  validation: {
    validated_candidates: string[]
    rejected_candidates: string[]
    issues: { candidate_id: string; code: string; message: string; severity: string }[]
  } | null
  degraded: boolean
  llmModel: string
}

interface ScienceStore {
  modelPolicy: ModelPolicyResult | null
  modelPolicyLoading: boolean
  modelPolicyError: string | null
  training: ModelTrainingResult | null
  trainingLoading: boolean
  trainingError: string | null
  optimization: OptimizationResult | null
  optimizationLoading: boolean
  optimizationError: string | null
  evidence: EvidenceCompileResult | null
  evidenceLoading: boolean
  evidenceError: string | null
  /** RAG 检索编译出的 Topic2 Evidence[]（证据篮子，供 compile/policy/BO 使用） */
  ragEvidence: Evidence[]
  ragEvidenceMeta: {
    retrievedHits: number
    reviewedHits: number
    evidenceStatus: string
  } | null
  ragEvidenceLoading: boolean
  ragEvidenceError: string | null
  /** RAG→LLM→E2P 科学知识链（EvidenceCorpusPack → ScientificKnowledgePack → 验证） */
  scientificPack: ScientificPackState | null
  scientificLoading: boolean
  scientificError: string | null
  /** 异步科学分析 Job 实时进度（任务页触发，Agent 侧边栏展示） */
  analysisJob: {
    jobId: string
    status: string
    stage: string
    progress: Record<string, unknown>
    detail: { stage: string; [key: string]: unknown }[]
    error: string | null
  } | null
  analysisJobPolling: boolean
  experiments: ExperimentRow[]
  experimentsLoading: boolean
  experimentsError: string | null
  dataProfile: DataProfile | null
  recentRuns: RunSummary[]
  recentRunsLoading: boolean
  recentRunsError: string | null
  selectedModelId: string | null
  selectionMode: 'system' | 'manual' | null
  setModelPolicy: (value: ModelPolicyResult | null, error?: string | null, loading?: boolean) => void
  setTraining: (value: ModelTrainingResult | null, error?: string | null, loading?: boolean) => void
  setOptimization: (value: OptimizationResult | null, error?: string | null, loading?: boolean) => void
  setEvidence: (value: EvidenceCompileResult | null, error?: string | null, loading?: boolean) => void
  setRagEvidence: (
    evidence: Evidence[],
    meta: { retrievedHits: number; reviewedHits: number; evidenceStatus: string } | null,
    error?: string | null,
    loading?: boolean,
  ) => void
  setScientificPack: (
    value: ScientificPackState | null,
    error?: string | null,
    loading?: boolean,
  ) => void
  setAnalysisJob: (
    value: {
      jobId: string
      status: string
      stage: string
      progress: Record<string, unknown>
      detail: { stage: string; [key: string]: unknown }[]
      error: string | null
    } | null,
    polling?: boolean,
  ) => void
  setExperiments: (
    rows: ExperimentRow[],
    error?: string | null,
    loading?: boolean,
  ) => void
  setRecentRuns: (runs: RunSummary[], error?: string | null, loading?: boolean) => void
  setSelection: (modelId: string | null, mode: 'system' | 'manual') => void
  clearAll: () => void
}

const initialData = {
  modelPolicy: null,
  modelPolicyLoading: false,
  modelPolicyError: null,
  training: null,
  trainingLoading: false,
  trainingError: null,
  optimization: null,
  optimizationLoading: false,
  optimizationError: null,
  evidence: null,
  evidenceLoading: false,
  evidenceError: null,
  ragEvidence: [],
  ragEvidenceMeta: null,
  ragEvidenceLoading: false,
  ragEvidenceError: null,
  scientificPack: null,
  scientificLoading: false,
  scientificError: null,
  analysisJob: null,
  analysisJobPolling: false,
  experiments: [] as ExperimentRow[],
  experimentsLoading: false,
  experimentsError: null,
  dataProfile: null as DataProfile | null,
  recentRuns: [] as RunSummary[],
  recentRunsLoading: false,
  recentRunsError: null,
  selectedModelId: null,
  selectionMode: null as 'system' | 'manual' | null,
}

export const useScienceStore = create<ScienceStore>()((set) => ({
  ...initialData,
  setModelPolicy: (modelPolicy, modelPolicyError = null, modelPolicyLoading = false) =>
    set({ modelPolicy, modelPolicyError, modelPolicyLoading }),
  setTraining: (training, trainingError = null, trainingLoading = false) =>
    set({ training, trainingError, trainingLoading }),
  setOptimization: (optimization, optimizationError = null, optimizationLoading = false) =>
    set({ optimization, optimizationError, optimizationLoading }),
  setEvidence: (evidence, evidenceError = null, evidenceLoading = false) =>
    set({ evidence, evidenceError, evidenceLoading }),
  setRagEvidence: (ragEvidence, ragEvidenceMeta, ragEvidenceError = null, ragEvidenceLoading = false) =>
    set({ ragEvidence, ragEvidenceMeta, ragEvidenceError, ragEvidenceLoading }),
  setScientificPack: (scientificPack, scientificError = null, scientificLoading = false) =>
    set({ scientificPack, scientificError, scientificLoading }),
  setAnalysisJob: (analysisJob, analysisJobPolling = false) =>
    set({ analysisJob, analysisJobPolling }),
  setExperiments: (experiments, experimentsError = null, experimentsLoading = false) => {
    const profile = computeDataProfile(experiments)
    return set({ experiments, experimentsError, experimentsLoading, dataProfile: profile })
  },
  setRecentRuns: (recentRuns, recentRunsError = null, recentRunsLoading = false) =>
    set({ recentRuns, recentRunsError, recentRunsLoading }),
  setSelection: (selectedModelId, selectionMode) => set({ selectedModelId, selectionMode }),
  clearAll: () => set({ ...initialData }),
}))
