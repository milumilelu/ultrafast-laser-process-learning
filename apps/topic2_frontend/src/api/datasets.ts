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
