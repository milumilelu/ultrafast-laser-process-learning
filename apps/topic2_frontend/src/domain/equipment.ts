/** MachineProfileSnapshot view model (M6) — canonical equipment resource. */

export interface EquipmentFieldView {
  parameter: string
  value: number | null
  unit: string | null
  status: 'VERIFIED' | 'DERIVED' | 'MISSING'
  provenance: string[]
}

export interface EquipmentBoundsView {
  name: string
  lower: number | null
  upper: number | null
}

export interface EquipmentView {
  schemaVersion: string
  equipmentProfileId: string
  revisionId: string | null
  sourceQuality: 'RESEARCH_AGENT' | 'UNRESOLVED' | 'UNKNOWN'
  resourceStatus: 'READY' | 'PARTIAL' | 'BLOCKED'
  fields: EquipmentFieldView[]
  machineBounds: EquipmentBoundsView[]
  missingRequired: string[]
  warnings: string[]
}

export interface EquipmentContent {
  schema_version?: string
  equipment_profile_id?: string
  revision_id?: string | null
  source_quality?: string
  resource_status?: string
  fields?: Record<
    string,
    { parameter?: string; value?: number | null; unit?: string | null; status?: string; provenance?: string[] }
  >
  machine_bounds?: Record<string, { lower?: number | null; upper?: number | null }>
  missing_required?: string[]
  warnings?: string[]
}

export const EQUIPMENT_FIELD_LABEL: Record<string, string> = {
  wavelength_nm: '波长',
  workpiece_incident_power_min_W: '材料表面入射平均功率下限',
  workpiece_incident_power_max_W: '材料表面入射平均功率上限',
  beam_radius_um: '光束半径',
  pulse_width_min_fs: '脉宽下限',
  pulse_width_max_fs: '脉宽上限',
  frequency_min_kHz: '频率下限',
  frequency_max_kHz: '频率上限',
  scan_speed_min_mm_s: '扫描速度下限',
  scan_speed_max_mm_s: '扫描速度上限',
}

export const SOURCE_QUALITY_LABEL: Record<EquipmentView['sourceQuality'], string> = {
  RESEARCH_AGENT: '研究模式（设备档案库）',
  UNRESOLVED: '未解析',
  UNKNOWN: '未知',
}

export function buildEquipmentView(content: EquipmentContent | null | undefined): EquipmentView {
  const raw = content ?? {}
  const fieldsRaw = (raw.fields ?? {}) as EquipmentContent['fields']
  const fields: EquipmentFieldView[] = []
  for (const [name, state] of Object.entries(fieldsRaw ?? {})) {
    const status = String(state?.status ?? 'MISSING').toUpperCase()
    fields.push({
      parameter: String(state?.parameter ?? name),
      value: state?.value ?? null,
      unit: state?.unit ?? null,
      status: status === 'VERIFIED' || status === 'DERIVED' ? status : 'MISSING',
      provenance: Array.isArray(state?.provenance) ? state.provenance.map(String) : [],
    })
  }
  const boundsRaw = (raw.machine_bounds ?? {}) as EquipmentContent['machine_bounds']
  const machineBounds: EquipmentBoundsView[] = Object.entries(boundsRaw ?? {}).map(
    ([name, bound]) => ({
      name,
      lower: bound?.lower ?? null,
      upper: bound?.upper ?? null,
    }),
  )
  const quality = String(raw.source_quality ?? '').toUpperCase()
  return {
    schemaVersion: String(raw.schema_version ?? ''),
    equipmentProfileId: String(raw.equipment_profile_id ?? ''),
    revisionId: raw.revision_id ?? null,
    sourceQuality:
      quality === 'RESEARCH_AGENT' || quality === 'UNRESOLVED'
        ? quality
        : 'UNKNOWN',
    resourceStatus:
      String(raw.resource_status ?? 'BLOCKED').toUpperCase() === 'READY'
        ? 'READY'
        : String(raw.resource_status ?? '').toUpperCase() === 'PARTIAL'
          ? 'PARTIAL'
          : 'BLOCKED',
    fields,
    machineBounds,
    missingRequired: Array.isArray(raw.missing_required) ? raw.missing_required.map(String) : [],
    warnings: Array.isArray(raw.warnings) ? raw.warnings.map(String) : [],
  }
}
