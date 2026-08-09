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

export function TaskForm({ taskId, onSaved }: { taskId: string; onSaved: () => void }) {
  const initial = getTaskDraft(taskId)
  const [form, setForm] = useState({
    name: initial?.name ?? '',
    material: initial?.material || '',
    laserType: initial?.laserType || 'fs',
    geometryType: initial?.geometryType || 'rectangular_groove',
    objectiveMetric: initial?.objectiveMetric || 'depth_um',
    equipmentProfileId: initial?.equipmentProfileId || '',
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
  const equipmentQuery = useQuery({
    queryKey: ['equipment-list'],
    queryFn: () => datasetsApi.equipment(),
  })

  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }))

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
    if (!form.equipmentProfileId) {
      setError('请选择设备')
      return
    }
    saveTaskDraft({
      ...initial,
      name: form.name,
      material: form.material,
      laserType: form.laserType as 'fs' | 'ps',
      geometryType: form.geometryType,
      objectiveMetric: form.objectiveMetric as 'depth_um' | 'roughness_um',
      equipmentProfileId: form.equipmentProfileId,
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
          <select value={form.material} onChange={(e) => set('material', e.target.value)}>
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
          <span>设备</span>
          <select value={form.equipmentProfileId} onChange={(e) => set('equipmentProfileId', e.target.value)}>
            <option value="">选择设备…</option>
            {(equipmentQuery.data ?? []).map((entry) => (
              <option key={entry.equipment_id} value={entry.equipment_id}>
                {entry.equipment_id}
                {entry.samples !== undefined ? `（${entry.samples} 样本）` : ''}
              </option>
            ))}
          </select>
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
