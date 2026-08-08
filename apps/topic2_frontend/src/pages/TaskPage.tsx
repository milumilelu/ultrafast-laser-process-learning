/** 工艺任务：材料 / 激光 / 设备（数据集设备 + 设备档案） / 加工任务 / 加工目标。
 *  每次正式修改都生成新版本；任务参数随上下文进入 Agent 对话。 */

import { useCallback, useEffect, useState } from 'react'

import type { LaserType, MaterialItem } from '../api/types'
import { agentApi } from '../api/agent'
import { topic2Api } from '../api/topic2'
import { ErrorBanner } from '../components/Banners'
import { EquipmentManager } from '../components/EquipmentManager'
import type { ScopeCapability } from '../components/EquipmentManager'
import { ScientificAnalysisPanel } from '../components/ScientificAnalysisPanel'
import { StatusBadge } from '../components/StatusBadge'
import {
  OBJECTIVE_LABELS,
  OBJECTIVE_OPTIONS,
  PROCESS_TASK_LABELS,
  PROCESS_TASK_OPTIONS,
  processParamLabel,
} from '../lib/canonical'
import { useScienceStore } from '../stores/science'
import { useTaskContextStore } from '../stores/taskContext'
import type { ObjectiveMode, ProcessTaskType } from '../stores/taskContext'

const PROCESS_TASK_PARAM_FIELDS: Record<ProcessTaskType, string[]> = {
  rectangular_groove: ['groove_width_um', 'groove_depth_um'],
  circular_hole: ['hole_diameter_um', 'hole_depth_um'],
  single_line: ['line_length_um'],
  custom: ['custom_description'],
}

export function TaskPage() {
  const { context, update } = useTaskContextStore()
  const [materials, setMaterials] = useState<MaterialItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [capability, setCapability] = useState<ScopeCapability | null>(null)
  const [capabilityLoading, setCapabilityLoading] = useState(false)
  const [profileOptical, setProfileOptical] = useState<Record<string, unknown> | null>(null)
  const { scientificPack, setScientificPack, setAnalysisJob } = useScienceStore()
  const analysisJobRunning = useScienceStore(
    (state) =>
      state.analysisJob !== null &&
      state.analysisJob.status !== 'completed' &&
      state.analysisJob.status !== 'failed',
  )

  // 设备档案的光学属性（新建设备时配置）：读取展示，供辨识页自动使用
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

  /** 任务级科学检索与精读（RAG → LLM → E2P）：结果供辨识/建模/优化共享 */
  const runScientificAnalysis = useCallback(() => {
    if (!context.materialId || !context.laserType) {
      setError('请先选择材料与激光类型')
      return
    }
    setError(null)
    setScientificPack(null, null, true)
    agentApi
      .createAnalysisJob({
        task_scope: {
          material: context.materialId,
          laser_type: context.laserType,
          geometry_type: context.processType ?? null,
          equipment_id: context.datasetEquipmentId,
          target: context.objective === 'quality_first' ? 'roughness_um' : 'depth_um',
          task_context_id: context.taskContextId,
        },
        retrieval_intents: [
          'parameter_effect',
          'parameter_condition',
          'material_property',
          'threshold',
          'formula',
          'reported_optimum',
        ],
      })
      .then((job) => {
        setAnalysisJob(
          {
            jobId: job.analysis_run_id,
            status: job.status,
            stage: job.stage,
            progress: {},
            detail: [],
            error: null,
          },
          true,
        )
      })
      .catch((err) => {
        const message = err instanceof Error ? err.message : '创建科学分析任务失败'
        const hint = message.includes('503') || message.includes('llm_not_configured')
          ? '（LLM 未配置：Agent 侧边栏 → 配置 → 保存 API Key 并测试连接后重试）'
          : ''
        setError(`${message}${hint}`)
      })
  }, [context, setScientificPack, setAnalysisJob])

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

  const setProcessType = (type: ProcessTaskType) => {
    update({ processType: type, processParams: {} })
  }

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
      <h1>工艺任务</h1>
      <p className="card-sub">
        通过结构化界面定义加工任务。任务上下文具有全局唯一 ID 与版本号，任何正式修改都会升级版本
        （当前 {context.taskContextId}:v{context.version}），Agent 始终绑定同一版本。
      </p>

      <ErrorBanner message={error} />
      {saved && (
        <div className="warn-banner">
          任务上下文已更新为 {context.taskContextId}:v{context.version}。
        </div>
      )}

      <div className="card">
        <div className="card-title">任务定义</div>
        <div className="grid grid-2">
          <div className="field">
            <label>材料（Canonical ID）</label>
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
            <div className="card-sub" style={{ marginBottom: 0, marginTop: 6 }}>
              当前 Topic2 数据库包含真实加工数据（SiCp/Al/CFRP/SiC/ZrO2/金刚石，共 540 条）与验收夹具数据。
            </div>
          </div>

          <div className="field">
            <label>激光类型</label>
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
            <div className="card-sub" style={{ marginBottom: 0, marginTop: 6 }}>
              数据集设备将按所选激光类型列出实际有数据的设备（不再按名称猜测兼容性）。
            </div>
          </div>
        </div>

        <div className="grid grid-2" style={{ marginTop: 12 }}>
          <div className="field">
            <label>热扩散系数 thermal_diffusivity_m2_s（材料参数，可选）</label>
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
            <label>烧蚀阈值 ablation_threshold_J_cm2（材料参数，可选）</label>
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
      </div>

      <div className="card">
        <div className="card-title">设备管理</div>
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
            尚未选择<b>数据集设备</b>（科学查询用）。请在上方下拉中选择有数据的设备（如
            EQ-REAL · 120 样本），否则参数辨识、建模、优化无法执行。
          </div>
        )}
        {context.datasetEquipmentId && !datasetHasData && (
          <div className="warn-banner" style={{ margin: 0, marginTop: 8 }}>
            当前组合（材料/激光/数据集设备/加工任务）在数据库中无实验数据，参数辨识、建模、优化将无法执行。
            请从有数据的组合中选择（设备档案仅提供机器边界，不影响数据量）。
          </div>
        )}

        {context.equipmentId && profileOptical && (
          <div className="card-sub" style={{ marginBottom: 0, marginTop: 12 }}>
            设备档案光学属性（新建设备时配置，供物理特征构建）：
            <span className="badge neutral" style={{ marginLeft: 8 }}>
              光斑 {String(profileOptical.spot_diameter_um ?? '—')} um（{String(profileOptical.spot_definition ?? '未定义')}）
            </span>
          </div>
        )}
        {context.equipmentId && !profileOptical && (
          <div className="card-sub" style={{ marginBottom: 0, marginTop: 12 }}>
            设备档案未配置光学属性——涉及光斑的物理特征将不可用。请在「设备管理」中编辑该设备档案（光斑直径/定义）。
          </div>
        )}
        <div className="card-sub" style={{ marginBottom: 0, marginTop: 6 }}>
          材料参数（可选，随材料定义设置）：
          <span className="badge neutral" style={{ marginLeft: 8 }}>
            热扩散系数 {context.materialProperties?.thermalDiffusivityM2S || '未设置'} m²/s
          </span>
          <span className="badge neutral">
            烧蚀阈值 {context.materialProperties?.ablationThresholdJcm2 || '未设置'} J/cm²
          </span>
        </div>
      </div>

      <div className="card">
        <div className="card-title">加工任务</div>
        <div className="option-cards">
          {PROCESS_TASK_OPTIONS.map((option) => (
            <div
              key={option.value}
              className={`option-card ${context.processType === option.value ? 'selected' : ''}`}
              data-testid={`process-option-${option.value}`}
              onClick={() => setProcessType(option.value)}
            >
              <div className="option-title">
                <input type="radio" name="process-type" checked={context.processType === option.value} onChange={() => undefined} />
                {option.label}
              </div>
              <div className="option-desc">{option.description}</div>
            </div>
          ))}
        </div>
        {capability && capability.available_geometries.length > 0 && (
          <div className="card-sub" style={{ marginBottom: 0, marginTop: 8 }}>
            数据库当前仅支持几何：{capability.available_geometries.join('、')}
          </div>
        )}

        {context.processType && context.processType !== 'custom' && (
          <div className="grid grid-2" style={{ marginTop: 14 }}>
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
          <div style={{ marginTop: 14 }}>
            <div className="field">
              <label>任务描述（将随 Task Context 提供给 Agent）</label>
              <textarea
                rows={3}
                value={String(context.processParams.custom_description ?? '')}
                placeholder="例如：在 CFRP 表面加工 5×5mm 阵列微孔，孔径 200μm…"
                onChange={(event) => setProcessParam('custom_description', event.target.value)}
              />
            </div>
            <div className="card-sub">
              自定义任务的参数通过右侧 Agent 对话进一步说明与确认；科学计算仍以 Task Context 中的结构化字段为准。
            </div>
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-title">加工目标</div>
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
          加工目标映射为科学计算目标：质量优先 → roughness_um 最小化；效率优先 → depth_um 最大化（由 Topic2 Backend 执行）。
        </div>
      </div>

      <div className="row">
        <button className="btn primary" onClick={save}>
          保存任务（升级为 v{context.version + 1}）
        </button>
        <StatusBadge tone="neutral">修改必须由人工确认后生效</StatusBadge>
      </div>

      <div className="card">
        <div className="card-title">工艺任务分析（独立栏）</div>
        <div className="row" style={{ marginBottom: 10 }}>
          <button
            className="btn primary"
            onClick={runScientificAnalysis}
            disabled={!context.materialId || !context.laserType || analysisJobRunning}
            title="任务级工艺任务分析（RAG→LLM→E2P）：结果由参数辨识/工艺建模/工艺优化共享"
          >
            运行工艺任务分析
          </button>
          <StatusBadge tone="neutral">
            执行流程：任务校验 → RAG 检索 → LLM 精读 → 确定性验证 → 覆盖检查 → 全局综合 → 关键批判 → 完成
          </StatusBadge>
        </div>
        <ScientificAnalysisPanel />
      </div>

      {scientificPack && (
        <div className="card" style={{ marginTop: 16 }}>
          <div className="card-title">共享科学知识（供辨识 / 建模 / 优化使用）</div>
          <div className="row" style={{ margin: '8px 0', gap: 8, flexWrap: 'wrap' }}>
            <StatusBadge tone="ok">LLM: {scientificPack.llmModel || '已配置'}</StatusBadge>
            <StatusBadge tone="ok">
              知识候选：{(scientificPack.knowledge?.candidates as unknown[] | undefined)?.length ?? 0}
            </StatusBadge>
            <StatusBadge tone="ok">
              Known：{(scientificPack.knowledge?.known as unknown[] | undefined)?.length ?? 0}
            </StatusBadge>
            <StatusBadge tone="warn">
              Unknown：{(scientificPack.knowledge?.unknown as unknown[] | undefined)?.length ?? 0}
            </StatusBadge>
          </div>
          <div className="muted" style={{ fontSize: 12 }}>
            分析结果已共享：辨识页自动使用其中提炼的阈值/材料属性；建模页与优化页共用此知识包。
          </div>
        </div>
      )}

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-title">当前 Task Context</div>
        <ul className="detail-list">
          <li>
            <span className="dl-key">task_context_id / version</span>
            <span className="dl-value mono">{context.taskContextId} : v{context.version}</span>
          </li>
          <li>
            <span className="dl-key">material_id</span>
            <span className="dl-value mono">{context.materialId ?? '—'}</span>
          </li>
          <li>
            <span className="dl-key">material_properties（材料参数，可选）</span>
            <span className="dl-value mono">
              {context.materialProperties
                ? `thermal_diffusivity_m2_s=${context.materialProperties.thermalDiffusivityM2S || '—'}, ablation_threshold_J_cm2=${context.materialProperties.ablationThresholdJcm2 || '—'}`
                : '—'}
            </span>
          </li>
          <li>
            <span className="dl-key">laser_type</span>
            <span className="dl-value mono">{context.laserType ?? '—'}</span>
          </li>
          <li>
            <span className="dl-key">dataset_equipment_id（科学查询）</span>
            <span className="dl-value mono">{context.datasetEquipmentId ?? '—'}</span>
          </li>
          <li>
            <span className="dl-key">equipment_id（设备档案/机器边界）</span>
            <span className="dl-value mono">{context.equipmentId ?? '—'}</span>
          </li>
          <li>
            <span className="dl-key">process_type（加工任务）</span>
            <span className="dl-value mono">
              {context.processType ? `${PROCESS_TASK_LABELS[context.processType]} / ${context.processType}` : '—'}
            </span>
          </li>
          <li>
            <span className="dl-key">process_params（任务参数）</span>
            <span className="dl-value mono">
              {Object.keys(context.processParams).length > 0
                ? JSON.stringify(context.processParams)
                : '—'}
            </span>
          </li>
          <li>
            <span className="dl-key">objective（加工目标）</span>
            <span className="dl-value mono">
              {context.objective ? `${OBJECTIVE_LABELS[context.objective]} / ${context.objective}` : '—'}
            </span>
          </li>
          <li>
            <span className="dl-key">updated_at</span>
            <span className="dl-value mono">{context.updatedAt}</span>
          </li>
        </ul>
      </div>
    </div>
  )
}
