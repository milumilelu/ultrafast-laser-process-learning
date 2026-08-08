/** TaskAndDataWorkspace（任务说明 §7）：三阶段 - Step 1 研究任务 / Step 2 数据与设备 /
 *  Step 3 Readiness Check。正式修改升级 Task Context 版本；Readiness 状态来自
 *  后端报告（ApplicationRun 产物），前端不自行判定 dependency。 */

import { useCallback, useEffect, useState } from 'react'

import type { LaserType, MaterialItem } from '../api/types'
import { agentApi } from '../api/agent'
import { applicationApi } from '../api/application'
import { topic2Api } from '../api/topic2'
import { ErrorBanner } from '../components/Banners'
import { EquipmentManager } from '../components/EquipmentManager'
import type { ScopeCapability } from '../components/EquipmentManager'
import { KnowledgeGapSection } from '../components/KnowledgeGapSection'
import { PhysicsReadinessMatrix } from '../components/learning/PhysicsReadinessMatrix'
import { StatusBadge } from '../components/StatusBadge'
import {
  OBJECTIVE_OPTIONS,
  PROCESS_TASK_OPTIONS,
  processParamLabel,
} from '../lib/canonical'
import { scientificLabel, scientificTone, type StatusTone } from '../lib/status'
import type { PhysicsCoordinateStatus } from '../api/types'
import { useApplicationStore } from '../stores/application'
import { useTaskContextStore } from '../stores/taskContext'
import type { ObjectiveMode, ProcessTaskType } from '../stores/taskContext'

const PROCESS_TASK_PARAM_FIELDS: Record<ProcessTaskType, string[]> = {
  rectangular_groove: ['groove_width_um', 'groove_depth_um'],
  circular_hole: ['hole_diameter_um', 'hole_depth_um'],
  single_line: ['line_length_um'],
  custom: ['custom_description'],
}

export function TaskAndDataWorkspace() {
  const { context, update } = useTaskContextStore()
  const activeApplicationRunId = useApplicationStore((state) => state.activeApplicationRunId)
  const [materials, setMaterials] = useState<MaterialItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [capability, setCapability] = useState<ScopeCapability | null>(null)
  const [capabilityLoading, setCapabilityLoading] = useState(false)
  const [profileOptical, setProfileOptical] = useState<Record<string, unknown> | null>(null)
  const [coordinates, setCoordinates] = useState<PhysicsCoordinateStatus[]>([])
  const [readinessMeta, setReadinessMeta] = useState<{ status: string; sampleCount?: number } | null>(null)

  // 设备档案的光学属性（新建设备时配置）：Step 2 展示 provenance
  useEffect(() => {
    if (!context.equipmentId) {
      setProfileOptical(null)
      return
    }
    let cancelled = false
    agentApi
      .getEquipmentProfile(context.equipmentId)
      .then((profile) => {
        if (cancelled) return
        const optical = (profile.optical_setup ?? {}) as Record<string, unknown>
        setProfileOptical({
          spot_diameter_um: optical.spot_diameter_um ?? null,
          spot_definition: optical.spot_definition ?? null,
        })
      })
      .catch(() => {
        if (!cancelled) setProfileOptical(null)
      })
    return () => {
      cancelled = true
    }
  }, [context.equipmentId])

  // Step 3：Readiness 来自后端报告（ApplicationRun 产物），前端不自行判定
  useEffect(() => {
    if (!activeApplicationRunId) {
      setCoordinates([])
      setReadinessMeta(null)
      return
    }
    let cancelled = false
    applicationApi
      .getResult(activeApplicationRunId)
      .then((result) => {
        if (cancelled) return
        const raw = result.processLearning.physicsReadiness ?? []
        setCoordinates(raw)
        const physics = (result.cfa.targetPhysicsReadiness as Record<string, unknown> | null) ?? null
        setReadinessMeta({
          status: String(physics?.status ?? (raw.length > 0 ? 'AVAILABLE' : 'UNKNOWN')),
          sampleCount: result.targetTask.sampleCount ?? undefined,
        })
      })
      .catch(() => {
        if (!cancelled) {
          setCoordinates([])
          setReadinessMeta(null)
        }
      })
    return () => {
      cancelled = true
    }
  }, [activeApplicationRunId])

  useEffect(() => {
    topic2Api
      .materials()
      .then((result) => setMaterials(result.items))
      .catch((err) => setError(err instanceof Error ? err.message : '读取材料失败'))
  }, [])

  const refreshCapability = useCallback(() => {
    setCapabilityLoading(true)
    setError(null)
    topic2Api
      .scopeCapability({
        material: context.materialId,
        laser_type: context.laserType,
        equipment_id: context.datasetEquipmentId,
        geometry_type: context.processType ?? null,
      })
      .then(setCapability)
      .catch((err) =>
        setError(err instanceof Error ? err.message : '读取数据能力失败'),
      )
      .finally(() => setCapabilityLoading(false))
  }, [
    context.materialId,
    context.laserType,
    context.datasetEquipmentId,
    context.processType,
  ])

  useEffect(() => {
    if (context.materialId && context.laserType) refreshCapability()
    else setCapability(null)
  }, [refreshCapability, context.materialId, context.laserType])

  const setProcessParam = (key: string, value: string) => {
    update({ processParams: { ...context.processParams, [key]: value } })
  }

  const save = () => {
    const missing: string[] = []
    if (!context.materialId) missing.push('材料')
    if (!context.laserType) missing.push('激光类型')
    if (!context.datasetEquipmentId) missing.push('数据集设备')
    if (!context.processType) missing.push('加工任务')
    if (!context.objective) missing.push('加工目标')
    if (missing.length > 0) {
      setError(`请完整填写：${missing.join(' / ')}。`)
      return
    }
    setError(null)
    update({})
    setSaved(true)
    window.setTimeout(() => setSaved(false), 2500)
  }

  const datasetHasData =
    capability !== null &&
    capability.available_equipment.includes(context.datasetEquipmentId ?? '')

  return (
    <div>
      <h1>任务与数据</h1>
      <p className="card-sub">
        Task Context 具有全局唯一 ID 与版本号（当前 {context.taskContextId}:v{context.version}），
        任何正式修改都会升级版本；Agent 始终绑定同一版本。
      </p>

      <div className="row" style={{ marginBottom: 10 }}>
        <StatusBadge tone="info">Step 1 研究任务</StatusBadge>
        <StatusBadge tone="info">Step 2 数据与设备</StatusBadge>
        <StatusBadge tone="info">Step 3 Readiness Check</StatusBadge>
      </div>

      <ErrorBanner message={error} />
      {saved && (
        <div className="warn-banner">
          任务上下文已更新为 {context.taskContextId}:v{context.version}。
        </div>
      )}

      {/* ---------------------------------------------------- Step 1 研究任务 */}
      <div className="card">
        <div className="card-title">Step 1 · 研究任务</div>
        <div className="grid grid-2">
          <div className="field">
            <label>材料 material_id</label>
            <select
              value={context.materialId ?? ''}
              onChange={(event) => update({ materialId: event.target.value || null })}
            >
              <option value="">— 选择材料 —</option>
              {materials.map((item) => (
                <option key={item.material} value={item.material}>
                  {item.material}
                  {item.is_synthetic ? '（合成测试数据）' : '（真实加工数据）'}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>激光类型 laser_type</label>
            <select
              value={context.laserType ?? ''}
              onChange={(event) => {
                const laserType = (event.target.value || null) as LaserType | null
                update({ laserType, datasetEquipmentId: null })
              }}
            >
              <option value="">— 选择激光类型 —</option>
              <option value="fs">飞秒 fs</option>
              <option value="ps">皮秒 ps</option>
            </select>
          </div>
          <div className="field">
            <label>热扩散系数（材料参数，可选）</label>
            <input
              type="number"
              step="1e-7"
              value={String(context.materialProperties?.thermalDiffusivityM2S ?? '')}
              placeholder="如 0.000001（不填则物理特征如实显示不可用）"
              onChange={(event) =>
                update({
                  materialProperties: {
                    ...context.materialProperties,
                    thermalDiffusivityM2S: event.target.value,
                  },
                })
              }
            />
          </div>
          <div className="field">
            <label>烧蚀阈值（材料参数，可选）</label>
            <input
              type="number"
              step="0.01"
              value={String(context.materialProperties?.ablationThresholdJcm2 ?? '')}
              placeholder="如 0.82（不填则物理特征如实显示不可用）"
              onChange={(event) =>
                update({
                  materialProperties: {
                    ...context.materialProperties,
                    ablationThresholdJcm2: event.target.value,
                  },
                })
              }
            />
          </div>
        </div>

        <div className="card-sub" style={{ marginTop: 8 }}>加工任务 process_type</div>
        <div className="option-cards">
          {PROCESS_TASK_OPTIONS.map((option) => (
            <div
              key={option.value}
              className={`option-card ${context.processType === option.value ? 'selected' : ''}`}
              data-testid={`process-option-${option.value}`}
              onClick={() => update({ processType: option.value as ProcessTaskType, processParams: {} })}
            >
              <div className="option-title">
                <input
                  type="radio"
                  name="process-type"
                  checked={context.processType === option.value}
                  onChange={() => undefined}
                />
                {option.label}
              </div>
              <div className="option-desc">{option.description}</div>
            </div>
          ))}
        </div>

        {context.processType && context.processType !== 'custom' && (
          <div className="grid grid-2" style={{ marginTop: 12 }}>
            {PROCESS_TASK_PARAM_FIELDS[context.processType].map((key) => (
              <div className="field" key={key}>
                <label>{processParamLabel(key)}</label>
                <input
                  type="number"
                  value={String(context.processParams[key] ?? '')}
                  placeholder="按实际任务填写"
                  onChange={(event) => setProcessParam(key, event.target.value)}
                />
              </div>
            ))}
          </div>
        )}
        {context.processType === 'custom' && (
          <div style={{ marginTop: 12 }}>
            <div className="field">
              <label>任务描述（将随 Task Context 提供给 Agent）</label>
              <textarea
                rows={2}
                value={String(context.processParams.custom_description ?? '')}
                placeholder="例如：在 CFRP 表面加工 5×5mm 阵列微孔…"
                onChange={(event) => setProcessParam('custom_description', event.target.value)}
              />
            </div>
          </div>
        )}

        <div className="card-sub" style={{ marginTop: 10 }}>加工目标 objective</div>
        <div className="option-cards">
          {OBJECTIVE_OPTIONS.map((option) => (
            <div
              key={option.value}
              className={`option-card ${context.objective === option.value ? 'selected' : ''}`}
              data-testid={`objective-option-${option.value}`}
              onClick={() => update({ objective: option.value as ObjectiveMode })}
            >
              <div className="option-title">
                <input
                  type="radio"
                  name="objective"
                  checked={context.objective === option.value}
                  onChange={() => undefined}
                />
                {option.label}
              </div>
              <div className="option-desc">{option.description}</div>
            </div>
          ))}
        </div>
        <div className="card-sub" style={{ marginBottom: 0, marginTop: 8 }}>
          加工目标映射为科学计算目标：质量优先 → roughness_um 最小化；效率优先 → depth_um 最大化。
        </div>
      </div>

      {/* ---------------------------------------------------- Step 2 数据与设备 */}
      <div className="card">
        <div className="card-title">Step 2 · 数据与设备</div>
        <EquipmentManager
          datasetEquipmentId={context.datasetEquipmentId}
          equipmentProfileId={context.equipmentId}
          onDatasetEquipmentChange={(id) => update({ datasetEquipmentId: id })}
          onEquipmentProfileChange={(id) => update({ equipmentId: id })}
          capability={capability}
          capabilityLoading={capabilityLoading}
          onRefreshCapability={refreshCapability}
        />
        {!context.datasetEquipmentId && context.materialId && context.laserType && (
          <div className="warn-banner" style={{ margin: 0, marginTop: 8 }}>
            尚未选择<b>数据集设备</b>（科学查询用）。请选择有数据的设备，否则参数辨识、建模、优化无法执行。
          </div>
        )}
        {context.datasetEquipmentId && !datasetHasData && (
          <div className="warn-banner" style={{ margin: 0, marginTop: 8 }}>
            当前组合在数据库中无实验数据。请从有数据的组合中选择（设备档案仅提供机器边界）。
          </div>
        )}
        <div className="card-sub" style={{ marginBottom: 0, marginTop: 10 }}>
          设备输入 provenance：
          <span className="badge neutral" style={{ marginLeft: 8 }}>
            光斑 {String(profileOptical?.spot_diameter_um ?? '—')} um（{String(profileOptical?.spot_definition ?? '未定义')}）
          </span>
          <span className="badge neutral">
            来源：{context.equipmentId ? `equipment_profile:${context.equipmentId}` : '未选择'}
          </span>
          <span className="badge neutral">
            状态：{profileOptical?.spot_definition ? 'VERIFIED' : 'UNVERIFIED'}
          </span>
        </div>
        <div className="card-sub" style={{ marginBottom: 0, marginTop: 6 }}>
          材料参数（任务定义中设置，可选）：
          <span className="badge neutral" style={{ marginLeft: 8 }}>
            热扩散系数 {context.materialProperties?.thermalDiffusivityM2S || '未设置'} m²/s
          </span>
          <span className="badge neutral">
            烧蚀阈值 {context.materialProperties?.ablationThresholdJcm2 || '未设置'} J/cm²
          </span>
        </div>
      </div>

      {/* ---------------------------------------------------- Step 3 Readiness */}
      <div className="card">
        <div className="card-title">Step 3 · Readiness Check（来自后端 TargetPhysicsReadinessReport）</div>
        {readinessMeta && (
          <div className="row" style={{ marginBottom: 8 }}>
            <StatusBadge tone={scientificTone(readinessMeta.status) as StatusTone}>
              {scientificLabel(readinessMeta.status)}
            </StatusBadge>
            {readinessMeta.sampleCount != null && (
              <StatusBadge tone="neutral">{readinessMeta.sampleCount} samples</StatusBadge>
            )}
          </div>
        )}
        {activeApplicationRunId ? (
          <PhysicsReadinessMatrix coordinates={coordinates} />
        ) : (
          <div className="empty-state">
            运行完整分析后，此矩阵将展示目标侧物理坐标状态（pulse_interval / pulse_spacing /
            pulse_overlap / peak_fluence / normalized_fluence 等）。状态全部来自后端报告。
          </div>
        )}
      </div>

      <div className="row">
        <button className="btn primary" onClick={save}>
          保存任务（升级为 v{context.version + 1}）
        </button>
        <StatusBadge tone="neutral">修改必须由人工确认后生效</StatusBadge>
      </div>

      <div className="card" style={{ marginTop: 12 }}>
        <div className="card-title">知识需求（ApplicationRun 主链输出）</div>
        <KnowledgeGapSection />
      </div>
    </div>
  )
}
