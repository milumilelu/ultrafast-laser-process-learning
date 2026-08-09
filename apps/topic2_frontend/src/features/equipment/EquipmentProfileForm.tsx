import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  datasetsApi,
  type EquipmentFieldVerification,
  type EquipmentProfileCreatePayload,
  type EquipmentProfileEntry,
  type EquipmentProfileMutationResult,
} from '../../api/datasets'
import { Button } from '../../components/ui/Button'
import { ErrorBanner } from '../../components/ui/Card'

const REQUIRED_PHYSICAL_FIELDS = [
  { key: 'wavelength_nm', section: 'laser_source', label: '激光波长', unit: 'nm' },
  { key: 'pulse_width_min_fs', section: 'laser_source', label: '可调脉宽下限', unit: 'fs' },
  { key: 'pulse_width_max_fs', section: 'laser_source', label: '可调脉宽上限', unit: 'fs' },
  { key: 'workpiece_incident_power_min_W', section: 'laser_source', label: '材料表面入射平均功率下限', unit: 'W' },
  { key: 'workpiece_incident_power_max_W', section: 'laser_source', label: '材料表面入射平均功率上限', unit: 'W' },
  { key: 'frequency_min_kHz', section: 'laser_source', label: '重复频率下限', unit: 'kHz' },
  { key: 'frequency_max_kHz', section: 'laser_source', label: '重复频率上限', unit: 'kHz' },
  { key: 'spot_diameter_um', section: 'optical_setup', label: '焦点光斑直径', unit: 'μm' },
  { key: 'scan_speed_min_mm_s', section: 'motion_system', label: '扫描速度下限', unit: 'mm/s' },
  { key: 'scan_speed_max_mm_s', section: 'motion_system', label: '扫描速度上限', unit: 'mm/s' },
] as const

const OPTIONAL_PHYSICAL_FIELDS = [
  { key: 'rated_max_power_W', section: 'laser_source', label: '激光器额定最大平均功率（铭牌）', unit: 'W' },
] as const

const PHYSICAL_FIELDS = [...REQUIRED_PHYSICAL_FIELDS, ...OPTIONAL_PHYSICAL_FIELDS] as const

type PhysicalField = (typeof PHYSICAL_FIELDS)[number]
type PhysicalFieldKey = PhysicalField['key']
type VerificationInput = EquipmentFieldVerification | ''

const VERIFICATION_OPTIONS: Array<{
  value: EquipmentFieldVerification
  label: string
}> = [
  { value: 'MEASURED', label: '实测 / 机器读数' },
  { value: 'MANUFACTURER_SPEC', label: '厂商规格' },
  { value: 'ESTIMATED', label: '估算（不可直接执行）' },
  { value: 'UNVERIFIED', label: '未核验（不可直接执行）' },
]

function initialValues(profile?: EquipmentProfileEntry): Record<PhysicalFieldKey, string> {
  return Object.fromEntries(
    PHYSICAL_FIELDS.map((field) => {
      const section = profile?.[field.section] as Record<string, unknown> | undefined
      const value = section?.[field.key]
      return [field.key, value === null || value === undefined ? '' : String(value)]
    }),
  ) as Record<PhysicalFieldKey, string>
}

function initialVerification(
  profile?: EquipmentProfileEntry,
): Record<PhysicalFieldKey, VerificationInput> {
  return Object.fromEntries(
    PHYSICAL_FIELDS.map((field) => [
      field.key,
      profile?.field_verification?.[field.key] ?? '',
    ]),
  ) as Record<PhysicalFieldKey, VerificationInput>
}

export function EquipmentProfileForm({
  profile,
  onCompleted,
}: {
  profile?: EquipmentProfileEntry
  onCompleted?: (result: EquipmentProfileMutationResult) => void
}) {
  const queryClient = useQueryClient()
  const [identity, setIdentity] = useState({
    profileName: profile?.profile_name ?? '',
    machineId: profile?.machine_id ?? '',
    manufacturer: profile?.manufacturer ?? '',
    model: profile?.model ?? '',
    notes: '',
  })
  const [values, setValues] = useState(() => initialValues(profile))
  const [verification, setVerification] = useState(() => initialVerification(profile))
  const [validationError, setValidationError] = useState<string | null>(null)
  const [saved, setSaved] = useState<EquipmentProfileMutationResult | null>(null)

  const mutation = useMutation({
    mutationFn: async () => {
      const payload = buildPayload(identity, values, verification)
      if (profile) {
        const {
          set_active: _setActive,
          created_by: _createdBy,
          ...update
        } = payload
        return datasetsApi.updateEquipmentProfile(profile.equipment_profile_id, {
          ...update,
          changed_by: 'physics-to-planning-ui',
        })
      }
      return datasetsApi.createEquipmentProfile(payload)
    },
    onSuccess: (result) => {
      setSaved(result)
      setValidationError(null)
      void queryClient.invalidateQueries({ queryKey: ['equipment-profiles', 'RESEARCH'] })
      onCompleted?.(result)
    },
  })

  const submit = () => {
    try {
      buildPayload(identity, values, verification)
    } catch (error) {
      setValidationError((error as Error).message)
      return
    }
    setSaved(null)
    mutation.mutate()
  }

  return (
    <div className="equipment-profile-form">
      <p className="card-hint">
        设备档案只记录能力边界，不记录本次任务设定值。材料表面入射功率必须是在当前光路和聚焦条件下的实测范围；额定功率仅作可选铭牌信息。
      </p>
      <ErrorBanner message={validationError ?? (mutation.error as Error | null)?.message ?? null} />
      {saved && (
        <div className="success-banner">
          已保存设备档案 <span className="mono">{saved.equipment_profile_id}</span>，新版本{' '}
          <span className="mono">{saved.revision_id}</span>。
        </div>
      )}
      <div className="form-grid equipment-identity-grid">
        <label className="field">
          <span>设备档案名称 *</span>
          <input
            value={identity.profileName}
            onChange={(event) => setIdentity((previous) => ({ ...previous, profileName: event.target.value }))}
            placeholder="例如：实验室飞秒激光加工系统 A"
          />
        </label>
        <label className="field">
          <span>机器编号</span>
          <input
            value={identity.machineId}
            onChange={(event) => setIdentity((previous) => ({ ...previous, machineId: event.target.value }))}
            placeholder="资产编号或实验室编号"
          />
        </label>
        <label className="field">
          <span>厂商</span>
          <input
            value={identity.manufacturer}
            onChange={(event) => setIdentity((previous) => ({ ...previous, manufacturer: event.target.value }))}
          />
        </label>
        <label className="field">
          <span>型号</span>
          <input
            value={identity.model}
            onChange={(event) => setIdentity((previous) => ({ ...previous, model: event.target.value }))}
          />
        </label>
      </div>

      <div className="equipment-fields" role="group" aria-label="设备物理参数">
        {PHYSICAL_FIELDS.map((field) => (
          <div className="equipment-input-row" key={field.key}>
            <label className="field">
              <span>{field.label}{REQUIRED_PHYSICAL_FIELDS.some((item) => item.key === field.key) ? ' *' : ''} ({field.unit})</span>
              <input
                aria-label={field.label}
                type="number"
                min={0}
                step="any"
                value={values[field.key]}
                onChange={(event) => setValues((previous) => ({ ...previous, [field.key]: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>数据来源{REQUIRED_PHYSICAL_FIELDS.some((item) => item.key === field.key) || values[field.key].trim() ? ' *' : ''}</span>
              <select
                aria-label={`${field.label} 数据来源`}
                value={verification[field.key]}
                onChange={(event) => setVerification((previous) => ({
                  ...previous,
                  [field.key]: event.target.value as VerificationInput,
                }))}
              >
                <option value="">选择来源…</option>
                {VERIFICATION_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
          </div>
        ))}
      </div>

      <label className="field equipment-notes">
        <span>备注</span>
        <input
          value={identity.notes}
          onChange={(event) => setIdentity((previous) => ({ ...previous, notes: event.target.value }))}
          placeholder="测量条件、标定日期或限制说明"
        />
      </label>
      <div className="form-actions">
        <Button onClick={submit} busy={mutation.isPending}>
          {profile ? '保存并生成新 revision' : '创建设备档案'}
        </Button>
      </div>
    </div>
  )
}

function buildPayload(
  identity: {
    profileName: string
    machineId: string
    manufacturer: string
    model: string
    notes: string
  },
  values: Record<PhysicalFieldKey, string>,
  verification: Record<PhysicalFieldKey, VerificationInput>,
): EquipmentProfileCreatePayload {
  if (!identity.profileName.trim()) throw new Error('请填写设备档案名称')
  const missingValue = REQUIRED_PHYSICAL_FIELDS.find((field) => values[field.key].trim() === '')
  if (missingValue) throw new Error(`请填写${missingValue.label}`)
  const missingVerification = PHYSICAL_FIELDS.find(
    (field) => values[field.key].trim() !== '' && !verification[field.key],
  )
  if (missingVerification) throw new Error(`请选择${missingVerification.label}的数据来源`)

  const numeric = Object.fromEntries(
    PHYSICAL_FIELDS.map((field) => [
      field.key,
      values[field.key].trim() === '' ? Number.NaN : Number(values[field.key]),
    ]),
  ) as Record<PhysicalFieldKey, number>
  const invalid = PHYSICAL_FIELDS.find(
    (field) => values[field.key].trim() !== '' && (!Number.isFinite(numeric[field.key]) || numeric[field.key] < 0),
  )
  if (invalid) throw new Error(`${invalid.label}必须是非负数`)
  if (numeric.pulse_width_min_fs > numeric.pulse_width_max_fs) {
    throw new Error('可调脉宽下限不能高于上限')
  }
  if (numeric.workpiece_incident_power_min_W > numeric.workpiece_incident_power_max_W) {
    throw new Error('材料表面入射平均功率下限不能高于上限')
  }
  if (
    Number.isFinite(numeric.rated_max_power_W)
    && numeric.workpiece_incident_power_max_W > numeric.rated_max_power_W
  ) {
    throw new Error('材料表面入射平均功率上限不能高于激光器额定最大平均功率')
  }
  for (const key of ['workpiece_incident_power_min_W', 'workpiece_incident_power_max_W'] as const) {
    if (verification[key] !== 'MEASURED') {
      throw new Error(`${PHYSICAL_FIELDS.find((field) => field.key === key)?.label}必须选择“实测 / 机器读数”`)
    }
  }
  if (numeric.frequency_min_kHz > numeric.frequency_max_kHz) {
    throw new Error('重复频率下限不能高于上限')
  }
  if (numeric.scan_speed_min_mm_s > numeric.scan_speed_max_mm_s) {
    throw new Error('扫描速度下限不能高于上限')
  }

  return {
    profile_name: identity.profileName.trim(),
    machine_id: identity.machineId.trim() || undefined,
    manufacturer: identity.manufacturer.trim() || undefined,
    model: identity.model.trim() || undefined,
    created_by: 'physics-to-planning-ui',
    notes: identity.notes.trim() || undefined,
    laser_source: {
      wavelength_nm: numeric.wavelength_nm,
      pulse_width_min_fs: numeric.pulse_width_min_fs,
      pulse_width_max_fs: numeric.pulse_width_max_fs,
      workpiece_incident_power_min_W: numeric.workpiece_incident_power_min_W,
      workpiece_incident_power_max_W: numeric.workpiece_incident_power_max_W,
      ...(Number.isFinite(numeric.rated_max_power_W)
        ? { rated_max_power_W: numeric.rated_max_power_W }
        : {}),
      frequency_min_kHz: numeric.frequency_min_kHz,
      frequency_max_kHz: numeric.frequency_max_kHz,
    },
    optical_setup: {
      spot_diameter_um: numeric.spot_diameter_um,
    },
    motion_system: {
      scan_speed_min_mm_s: numeric.scan_speed_min_mm_s,
      scan_speed_max_mm_s: numeric.scan_speed_max_mm_s,
    },
    process_capability: {},
    field_verification: Object.fromEntries(
      PHYSICAL_FIELDS
        .filter((field) => values[field.key].trim() !== '')
        .map((field) => [field.key, verification[field.key]]),
    ) as Record<PhysicalFieldKey, EquipmentFieldVerification>,
    set_active: true,
  }
}
