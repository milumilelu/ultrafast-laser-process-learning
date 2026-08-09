/** Task draft form (Draft State; submits to backend only on run creation).
 *
 * Material is chosen from the backend /materials catalog — never free text.
 */

import { useState } from 'react'
import { getTaskDraft, saveTaskDraft } from '../../stores/taskDrafts'
import { Card, ErrorBanner } from '../../components/ui/Card'
import { Button } from '../../components/ui/Button'
import { datasetsApi } from '../../api/datasets'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

export function TaskForm({ taskId, onSaved }: { taskId: string; onSaved: () => void }) {
  const initial = getTaskDraft(taskId)
  const [form, setForm] = useState({
    name: initial?.name ?? '',
    material: initial?.material || '',
    laserType: initial?.laserType || 'fs',
    geometryType: initial?.geometryType || 'rectangular_groove',
    objectiveMetric: initial?.objectiveMetric || 'depth_um',
    datasetRef: initial?.datasetRef || '',
    equipmentProfileId: initial?.equipmentProfileId || '',
    equipmentRevisionId: initial?.equipmentRevisionId || '',
    workpieceIncidentPowerW: initial?.workpieceIncidentPowerW
      ? String(initial.workpieceIncidentPowerW)
      : '',
    targetWidthUm: initial?.targetGeometry?.width_um ?? 30,
    targetHeightUm: initial?.targetGeometry?.height_um ?? 24,
    targetDepthUm: initial?.targetGeometry?.target_depth_um ?? 20,
    gridSpacingUm: initial?.targetGeometry?.grid_spacing_um ?? 2,
  })
  const [error, setError] = useState<string | null>(null)

  const materialsQuery = useQuery({
    queryKey: ['materials'],
    queryFn: () => datasetsApi.materials(),
  })
  const datasetsQuery = useQuery({
    queryKey: ['datasets'],
    queryFn: () => datasetsApi.datasets(),
  })
  const profilesQuery = useQuery({
    queryKey: ['equipment-profiles', 'RESEARCH'],
    queryFn: () => datasetsApi.equipmentProfiles(),
  })

  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }))

  const selectedProfile = (profilesQuery.data ?? []).find(
    (profile) => profile.equipment_profile_id === form.equipmentProfileId,
  )
  const availableRevisions = selectedProfile?.revisions?.length
    ? selectedProfile.revisions
    : selectedProfile?.revision_id
      ? [{ revision_id: selectedProfile.revision_id }]
      : []
  const selectedLaserSource = selectedProfile?.laser_source ?? {}
  const powerLower = Number(selectedLaserSource.workpiece_incident_power_min_W)
  const powerUpper = Number(selectedLaserSource.workpiece_incident_power_max_W)
  const hasPowerBounds = Number.isFinite(powerLower) && Number.isFinite(powerUpper)

  const handleSave = () => {
    if (!initial) return
    if (!form.material) {
      setError('请选择材料')
      return
    }
    if (!form.laserType || !form.geometryType || !form.objectiveMetric) {
      setError('material / laser / geometry / target 必填')
      return
    }
    if (!form.datasetRef) {
      setError('请选择真实数据集')
      return
    }
    if (!form.equipmentProfileId || !form.equipmentRevisionId) {
      setError('请选择目标执行设备及其版本')
      return
    }
    if (!selectedProfile) {
      setError('目标执行设备不在当前运行模式的设备档案库中，请重新选择')
      return
    }
    if (!availableRevisions.some((revision) => revision.revision_id === form.equipmentRevisionId)) {
      setError('设备版本无效，请从档案中选择已有 revision')
      return
    }
    const setpoint = Number(form.workpieceIncidentPowerW)
    if (!Number.isFinite(setpoint) || setpoint <= 0) {
      setError('请填写本次任务在材料表面处的入射平均功率设定值')
      return
    }
    if (!hasPowerBounds) {
      setError('所选设备版本缺少材料表面入射平均功率范围，请先更新设备档案')
      return
    }
    if (setpoint < powerLower || setpoint > powerUpper) {
      setError(`本次功率必须在所选设备的实测范围 ${powerLower}–${powerUpper} W 内`)
      return
    }
    saveTaskDraft({
      ...initial,
      name: form.name,
      material: form.material,
      laserType: form.laserType as 'fs' | 'ps',
      geometryType: form.geometryType,
      objectiveMetric: form.objectiveMetric as 'depth_um' | 'roughness_um',
      datasetRef: form.datasetRef,
      equipmentProfileId: form.equipmentProfileId,
      equipmentRevisionId: form.equipmentRevisionId,
      workpieceIncidentPowerW: setpoint,
      executionMode: 'RESEARCH',
      targetGeometry: {
        geometry_type: form.geometryType,
        width_um: Number(form.targetWidthUm),
        height_um: Number(form.targetHeightUm),
        target_depth_um: Number(form.targetDepthUm),
        grid_spacing_um: Number(form.gridSpacingUm),
      },
    })
    setError(null)
    onSaved()
  }

  return (
    <Card title="任务定义">
      <ErrorBanner message={error} />
      <div className="form-grid">
        <label className="field">
          <span>任务名</span>
          <input value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="可选" />
        </label>
        <label className="field">
          <span>材料</span>
          <select aria-label="材料" value={form.material} onChange={(e) => set('material', e.target.value)}>
            <option value="">选择材料…</option>
            {(materialsQuery.data ?? []).map((entry) => (
              <option key={entry.material} value={entry.material}>
                {entry.material}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>激光体制</span>
          <select value={form.laserType} onChange={(e) => set('laserType', e.target.value as 'fs' | 'ps')}>
            <option value="fs">fs</option>
            <option value="ps">ps</option>
          </select>
        </label>
        <label className="field">
          <span>目标几何</span>
          <select value={form.geometryType} onChange={(e) => set('geometryType', e.target.value)}>
            <option value="rectangular_groove">rectangular groove</option>
            <option value="surface_raster">surface raster</option>
            <option value="circular_pocket">circular pocket</option>
            <option value="rectangular_pocket">rectangular pocket</option>
          </select>
        </label>
        <label className="field">
          <span>目标指标</span>
          <select value={form.objectiveMetric} onChange={(e) => set('objectiveMetric', e.target.value as 'depth_um' | 'roughness_um')}>
            <option value="depth_um">depth (μm)</option>
            <option value="roughness_um">roughness (μm)</option>
          </select>
        </label>
        <label className="field">
          <span>真实实验数据集</span>
          <select value={form.datasetRef} onChange={(e) => set('datasetRef', e.target.value)}>
            <option value="">选择 DatasetRef…</option>
            {(datasetsQuery.data ?? []).map((entry) => (
              <option key={entry.dataset_version} value={entry.dataset_version}>
                {entry.dataset_version}（{entry.n_samples} 样本）
              </option>
            ))}
          </select>
          <small className="field-hint">
            历史设备来源由后端根据数据集和任务条件自动解析，用户无需输入。
          </small>
        </label>
        <label className="field">
          <span>执行设备（版本化档案）</span>
          <select
            aria-label="执行设备"
            value={form.equipmentProfileId}
            onChange={(e) => {
              const profileId = e.target.value
              const profile = (profilesQuery.data ?? []).find((item) => item.equipment_profile_id === profileId)
              setForm((previous) => ({
                ...previous,
                equipmentProfileId: profileId,
                equipmentRevisionId: profile?.revision_id ?? profile?.revisions?.[0]?.revision_id ?? '',
              }))
            }}
          >
            <option value="">
              {profilesQuery.isLoading ? '正在读取设备档案…' : '选择实际执行设备…'}
            </option>
            {(profilesQuery.data ?? []).map((entry) => (
              <option key={`${entry.equipment_profile_id}:${entry.revision_id}`} value={entry.equipment_profile_id}>
                {entry.profile_name || entry.equipment_profile_id}
                {entry.model ? ` · ${entry.model}` : ''}
              </option>
            ))}
          </select>
          <small className="field-hint">
            规划将在该设备上执行；后端会冻结所选版本的波长、材料表面功率范围、光斑和机器边界。
            {' '}<Link to="/resources/equipment">没有可选设备？前往设备档案创建</Link>
          </small>
          {profilesQuery.isError && (
            <small className="field-error">设备档案服务不可用：{(profilesQuery.error as Error).message}</small>
          )}
        </label>
        <label className="field">
          <span>本次材料表面入射平均功率 (W)</span>
          <input
            type="number"
            min={hasPowerBounds ? powerLower : 0}
            max={hasPowerBounds ? powerUpper : undefined}
            step="any"
            value={form.workpieceIncidentPowerW}
            onChange={(e) => set('workpieceIncidentPowerW', e.target.value)}
          />
          <small className="field-hint">
            {hasPowerBounds
              ? `所选设备当前版本的实测可调范围：${powerLower}–${powerUpper} W。这里填写的是本次任务设定值。`
              : '请先选择包含材料表面实测功率范围的设备版本。'}
          </small>
        </label>
        <label className="field">
          <span>执行设备版本（revision）</span>
          <select
            aria-label="执行设备版本"
            value={form.equipmentRevisionId}
            onChange={(e) => set('equipmentRevisionId', e.target.value)}
            disabled={!selectedProfile}
          >
            <option value="">选择不可变版本…</option>
            {availableRevisions.map((revision) => (
              <option key={revision.revision_id} value={revision.revision_id}>
                {revision.revision_number ? `v${revision.revision_number} · ` : ''}
                {revision.revision_id}
              </option>
            ))}
          </select>
          <small className="field-hint">revision 由后台创建，只能选择，不能手填。</small>
        </label>
        <label className="field">
          <span>目标宽度 (μm)</span>
          <input type="number" min={1} value={form.targetWidthUm} onChange={(e) => set('targetWidthUm', Number(e.target.value))} />
        </label>
        <label className="field">
          <span>目标高度 (μm)</span>
          <input type="number" min={1} value={form.targetHeightUm} onChange={(e) => set('targetHeightUm', Number(e.target.value))} />
        </label>
        <label className="field">
          <span>目标深度 (μm)</span>
          <input type="number" min={1} value={form.targetDepthUm} onChange={(e) => set('targetDepthUm', Number(e.target.value))} />
        </label>
        <label className="field">
          <span>网格间距 (μm)</span>
          <input type="number" min={1} value={form.gridSpacingUm} onChange={(e) => set('gridSpacingUm', Number(e.target.value))} />
        </label>
      </div>
      <div className="form-actions">
        <Button onClick={handleSave}>保存任务</Button>
      </div>
    </Card>
  )
}
