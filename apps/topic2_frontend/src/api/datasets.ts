/** Datasets / experiments / scope capability API (read-only + import). */

import { config } from '../config'
import { buildQuery, jsonBody, request } from './client'

export interface ExperimentRow {
  [key: string]: unknown
}

export interface MaterialEntry {
  material: string
  is_synthetic?: number
  data_origin?: string
}

export interface EquipmentEntry {
  equipment_id: string
  samples?: number
  laser_id?: string | null
  machine_id?: string | null
}

export interface DatasetEntry {
  dataset_version: string
  dataset_hash: string
  n_samples: number
  created_at: string
}

export interface EquipmentProfileEntry {
  equipment_profile_id: string
  revision_id: string | null
  profile_name: string
  source_quality: 'RESEARCH_AGENT'
  machine_id?: string | null
  manufacturer?: string | null
  model?: string | null
  status?: string | null
  is_active?: number | boolean | null
  laser_source?: Record<string, unknown>
  optical_setup?: Record<string, unknown>
  motion_system?: Record<string, unknown>
  process_capability?: Record<string, unknown>
  field_verification?: Record<string, EquipmentFieldVerification>
  revisions?: EquipmentRevisionEntry[]
}

export type EquipmentFieldVerification =
  | 'MEASURED'
  | 'MANUFACTURER_SPEC'
  | 'ESTIMATED'
  | 'UNVERIFIED'

export interface EquipmentRevisionEntry {
  revision_id: string
  revision_number?: number | null
  changed_by?: string | null
  changed_at?: string | null
  change_summary?: string | null
}

export interface EquipmentProfileCreatePayload {
  profile_name: string
  machine_id?: string
  manufacturer?: string
  model?: string
  created_by?: string
  notes?: string
  laser_source: Record<string, number | string>
  optical_setup: Record<string, number | string>
  motion_system: Record<string, number | string>
  process_capability?: Record<string, number | string | string[]>
  field_verification: Record<string, EquipmentFieldVerification>
  set_active: boolean
}

export interface EquipmentProfileMutationResult {
  equipment_profile_id: string
  revision_id: string
  is_active: boolean
}

export interface CalibrationObservationSetEntry {
  observation_set_id: string
  schema_version: string
  material: string
  equipment_profile_id: string
  origin: string
  count: number
}

export interface LiteratureEntry {
  paper_id: string
  canonical_title: string
  authors?: string | null
  year?: number | null
  material?: string | null
  source?: string | null
  pdf_ref?: string | null
  scientific_document_ref?: string | null
}

export interface ScopeCapabilityResponse {
  n_samples: number
  n_unique_designs: number
  targets: string[]
  available_equipment: string[]
  equipment_samples: Record<string, number>
  available_geometries: string[]
  meets_identification: boolean
  meets_modeling: boolean
}

export interface ImportResult {
  imported: number
  total_rows: number
  skipped_duplicates: number
}

export interface ExperimentFilter {
  material?: string
  laser_type?: string
  equipment?: string
  limit?: number
  offset?: number
}

type QueryValue = string | number | boolean | null | undefined

export interface StatisticsResponse {
  [key: string]: unknown
}

export const datasetsApi = {
  async materials(): Promise<MaterialEntry[]> {
    const response = await request<{ items: MaterialEntry[] }>(config.topic2ApiUrl, '/materials')
    return response.items
  },

  async equipment(): Promise<EquipmentEntry[]> {
    const response = await request<{ items: EquipmentEntry[] }>(config.topic2ApiUrl, '/equipment')
    return response.items
  },

  async datasets(): Promise<DatasetEntry[]> {
    const response = await request<{ items: DatasetEntry[] }>(config.topic2ApiUrl, '/datasets')
    return response.items
  },

  async equipmentProfiles(): Promise<EquipmentProfileEntry[]> {
    const profiles = await request<Omit<EquipmentProfileEntry, 'source_quality'>[]>(
      config.agentApiUrl,
      '/equipment/profiles',
    )
    return profiles.map((profile) => ({
      ...profile,
      source_quality: 'RESEARCH_AGENT' as const,
    }))
  },

  createEquipmentProfile(
    payload: EquipmentProfileCreatePayload,
  ): Promise<EquipmentProfileMutationResult> {
    return request(config.agentApiUrl, '/equipment/profiles', {
      method: 'POST',
      ...jsonBody(payload),
    })
  },

  updateEquipmentProfile(
    equipmentProfileId: string,
    payload: Partial<EquipmentProfileCreatePayload> & { changed_by?: string },
  ): Promise<EquipmentProfileMutationResult> {
    return request(
      config.agentApiUrl,
      `/equipment/profiles/${encodeURIComponent(equipmentProfileId)}`,
      {
        method: 'PATCH',
        ...jsonBody(payload),
      },
    )
  },

  equipmentProfileRevision(
    equipmentProfileId: string,
    revisionId: string,
  ): Promise<EquipmentProfileEntry> {
    return request(
      config.agentApiUrl,
      `/equipment/profiles/${encodeURIComponent(equipmentProfileId)}/revisions/${encodeURIComponent(revisionId)}`,
    )
  },

  async calibrationObservationSets(): Promise<CalibrationObservationSetEntry[]> {
    const response = await request<{ items: CalibrationObservationSetEntry[] }>(
      config.topic2ApiUrl,
      '/calibration-observation-sets',
    )
    return response.items
  },

  async literature(): Promise<LiteratureEntry[]> {
    const response = await request<{ items: LiteratureEntry[] }>(config.topic2ApiUrl, '/literature')
    return response.items
  },

  async experiments(filter: ExperimentFilter = {}): Promise<ExperimentRow[]> {
    const response = await request<{ items: ExperimentRow[] }>(
      config.topic2ApiUrl,
      `/experiments${buildQuery(filter as Record<string, QueryValue>)}`,
    )
    return response.items
  },

  importExperiments(csvText: string): Promise<ImportResult> {
    return request(config.topic2ApiUrl, '/experiments/import', {
      method: 'POST',
      ...jsonBody({ csv: csvText }),
    })
  },

  scopeCapability(filter: ExperimentFilter = {}): Promise<ScopeCapabilityResponse> {
    return request(
      config.topic2ApiUrl,
      `/scope-capability${buildQuery(filter as Record<string, QueryValue>)}`,
    )
  },

  statistics(): Promise<StatisticsResponse> {
    return request(config.topic2ApiUrl, '/database/statistics')
  },
}
