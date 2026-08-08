/** 新建设备档案：通过 Agent 服务创建（波长/脉宽/功率/频率/光斑/扫描速度等设备参数）。 */

import { useState } from 'react'

import { agentApi } from '../api/agent'
import { ErrorBanner } from './Banners'

interface FormState {
  profile_name: string
  machine_id: string
  manufacturer: string
  model: string
  wavelength_nm: string
  pulse_width_min_fs: string
  pulse_width_max_fs: string
  frequency_min_kHz: string
  frequency_max_kHz: string
  rated_max_power_W: string
  actual_max_power_W: string
  spot_diameter_um: string
  spot_definition: string
  scan_speed_min_mm_s: string
  scan_speed_max_mm_s: string
  set_active: boolean
}

const INITIAL: FormState = {
  profile_name: '',
  machine_id: '',
  manufacturer: '',
  model: '',
  wavelength_nm: '',
  pulse_width_min_fs: '',
  pulse_width_max_fs: '',
  frequency_min_kHz: '',
  frequency_max_kHz: '',
  rated_max_power_W: '',
  actual_max_power_W: '',
  spot_diameter_um: '',
  spot_definition: '',
  scan_speed_min_mm_s: '',
  scan_speed_max_mm_s: '',
  set_active: true,
}

function toNumber(value: string): number | null {
  if (value.trim() === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

export function NewEquipmentModal({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated: (equipmentProfileId: string) => void
}) {
  const [form, setForm] = useState<FormState>(INITIAL)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const set = (key: keyof FormState, value: string | boolean) =>
    setForm((current) => ({ ...current, [key]: value }))

  const submit = async () => {
    if (!form.profile_name.trim()) {
      setError('请填写设备名称。')
      return
    }
    const laser_source: Record<string, number> = {}
    const setLaser = (key: string, value: string) => {
      const parsed = toNumber(value)
      if (parsed !== null) laser_source[key] = parsed
    }
    setLaser('wavelength_nm', form.wavelength_nm)
    setLaser('pulse_width_min_fs', form.pulse_width_min_fs)
    setLaser('pulse_width_max_fs', form.pulse_width_max_fs)
    setLaser('frequency_min_kHz', form.frequency_min_kHz)
    setLaser('frequency_max_kHz', form.frequency_max_kHz)
    setLaser('rated_max_power_W', form.rated_max_power_W)
    setLaser('actual_max_power_W', form.actual_max_power_W)

    const optical_setup: Record<string, number | string> = {}
    const spot = toNumber(form.spot_diameter_um)
    if (spot !== null) optical_setup.spot_diameter_um = spot
    if (form.spot_definition.trim()) {
      optical_setup.spot_definition = form.spot_definition.trim()
    }

    // 热扩散系数 / 烧蚀阈值是材料参数，不随设备档案管理（在任务定义的材料中设置）
    const process_capability: Record<string, number> = {}

    const motion_system: Record<string, number> = {}
    const speedMin = toNumber(form.scan_speed_min_mm_s)
    const speedMax = toNumber(form.scan_speed_max_mm_s)
    if (speedMin !== null) motion_system.scan_speed_min_mm_s = speedMin
    if (speedMax !== null) motion_system.scan_speed_max_mm_s = speedMax

    setSubmitting(true)
    setError(null)
    try {
      const result = await agentApi.createEquipmentProfile({
        profile_name: form.profile_name.trim(),
        machine_id: form.machine_id.trim() || null,
        manufacturer: form.manufacturer.trim() || null,
        model: form.model.trim() || null,
        notes: null,
        laser_source,
        optical_setup,
        motion_system,
        process_capability,
        set_active: form.set_active,
      })
      onCreated(result.equipment_profile_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : '新建设备失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="modal-overlay" data-testid="new-equipment-modal">
      <div className="modal">
        <h2>新建设备</h2>
        <div className="card-sub">
          设备档案由 Agent 服务管理（波长、脉宽、功率、频率、光斑直径、扫描速度等），创建后可在任务中选用。
          热扩散系数 / 烧蚀阈值是材料参数，请在任务定义的材料中设置（可选）。
        </div>
        <ErrorBanner message={error} />
        <div className="grid grid-2">
          <div className="field">
            <label>设备名称 *</label>
            <input value={form.profile_name} onChange={(e) => set('profile_name', e.target.value)} placeholder="例如 飞秒激光器-01" />
          </div>
          <div className="field">
            <label>机器编号 machine_id</label>
            <input value={form.machine_id} onChange={(e) => set('machine_id', e.target.value)} placeholder="例如 01" />
          </div>
          <div className="field">
            <label>厂商</label>
            <input value={form.manufacturer} onChange={(e) => set('manufacturer', e.target.value)} />
          </div>
          <div className="field">
            <label>型号</label>
            <input value={form.model} onChange={(e) => set('model', e.target.value)} />
          </div>
          <div className="field">
            <label>波长 wavelength_nm</label>
            <input type="number" value={form.wavelength_nm} onChange={(e) => set('wavelength_nm', e.target.value)} placeholder="1030" />
          </div>
          <div className="field">
            <label>光斑直径 spot_diameter_um</label>
            <input type="number" value={form.spot_diameter_um} onChange={(e) => set('spot_diameter_um', e.target.value)} placeholder="5" />
          </div>
          <div className="field">
            <label>光斑定义 spot_definition（必须与直径成对）</label>
            <select value={form.spot_definition} onChange={(e) => set('spot_definition', e.target.value)}>
              <option value="">— 选择定义 —</option>
              <option value="1/e2">1/e²</option>
              <option value="fwhm">FWHM</option>
            </select>
          </div>
          <div className="field-pair">
            <div className="field">
              <label>最小脉宽 pulse_width_min_fs</label>
              <input type="number" value={form.pulse_width_min_fs} onChange={(e) => set('pulse_width_min_fs', e.target.value)} />
            </div>
            <div className="field">
              <label>最大脉宽 pulse_width_max_fs</label>
              <input type="number" value={form.pulse_width_max_fs} onChange={(e) => set('pulse_width_max_fs', e.target.value)} />
            </div>
          </div>
          <div className="field-pair">
            <div className="field">
              <label>最小频率 frequency_min_kHz</label>
              <input type="number" value={form.frequency_min_kHz} onChange={(e) => set('frequency_min_kHz', e.target.value)} />
            </div>
            <div className="field">
              <label>最大频率 frequency_max_kHz</label>
              <input type="number" value={form.frequency_max_kHz} onChange={(e) => set('frequency_max_kHz', e.target.value)} />
            </div>
          </div>
          <div className="field-pair">
            <div className="field">
              <label>额定最大功率 rated_max_power_W</label>
              <input type="number" value={form.rated_max_power_W} onChange={(e) => set('rated_max_power_W', e.target.value)} />
            </div>
            <div className="field">
              <label>实际最大功率 actual_max_power_W</label>
              <input type="number" value={form.actual_max_power_W} onChange={(e) => set('actual_max_power_W', e.target.value)} />
            </div>
          </div>
          <div className="field-pair">
            <div className="field">
              <label>最小扫描速度 scan_speed_min_mm_s</label>
              <input type="number" value={form.scan_speed_min_mm_s} onChange={(e) => set('scan_speed_min_mm_s', e.target.value)} />
            </div>
            <div className="field">
              <label>最大扫描速度 scan_speed_max_mm_s</label>
              <input type="number" value={form.scan_speed_max_mm_s} onChange={(e) => set('scan_speed_max_mm_s', e.target.value)} />
            </div>
          </div>
        </div>
        <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', marginBottom: 12 }}>
          <input
            type="checkbox"
            checked={form.set_active}
            onChange={(e) => set('set_active', e.target.checked)}
          />
          创建后设为当前设备（提供机器边界约束）
        </label>
        <div className="row">
          <button className="btn primary" onClick={() => void submit()} disabled={submitting}>
            {submitting ? '创建中…' : '创建'}
          </button>
          <button className="btn" onClick={onClose}>取消</button>
        </div>
      </div>
    </div>
  )
}
