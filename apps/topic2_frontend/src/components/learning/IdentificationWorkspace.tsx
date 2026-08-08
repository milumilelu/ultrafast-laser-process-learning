/** IdentificationWorkspace (UI-3): 参数辨识 - RAW/PHYSICS/HYBRID + 双排名 +
 *  importance chart + Physics readiness 矩阵。光斑等光学属性从设备档案读取，
 *  热扩散系数/烧蚀阈值为材料参数（任务定义中设置，可选），物理特征由公式引擎构建
 *  （缺属性时如实显示 unavailable，不静默假设）。 */

import { useCallback, useEffect, useState } from 'react'

import { agentApi } from '../../api/agent'
import { ErrorBanner, EmptyState } from '../../components/Banners'
import { DataProfileCard } from '../../components/DataProfileCard'
import { StatusBadge } from '../../components/StatusBadge'
import type { ParameterImportance, PhysicsCoordinateStatus } from '../../api/types'
import { effectClass, effectLabel, formatNumber } from '../../lib/format'
import { objectiveLabel, parameterLabel } from '../../lib/canonical'
import { taskContextToScope } from '../../lib/scope'
import { useScopeExperiments } from '../../lib/scopeData'
import { usePageContextStore } from '../../stores/pageContext'
import { useScienceStore } from '../../stores/science'
import { useTaskContextStore } from '../../stores/taskContext'
import { ParameterImportanceChart } from './ParameterImportanceChart'
import { PhysicsReadinessMatrix } from './PhysicsReadinessMatrix'
import { FeatureViewSelector, type FeatureViewMode } from './FeatureViewSelector'

export interface V2Result {
  mode: FeatureViewMode
  target: string
  cv_strategy: string
  controllable_ranking: ParameterImportance[]
  mechanism_ranking: ParameterImportance[]
  mechanism_group_importance: Record<string, number>
  feature_build?: {
    available_features: string[]
    unavailable_features: string[]
    missing_device_properties: string[]
  }
  claim_boundary?: string
}

/** Map the backend feature_build into a physics coordinate matrix.
 *  Statuses come from the backend build result; frontend never decides
 *  dependency logic. */
function physicsReadinessFromBuild(
  featureBuild: V2Result['feature_build'],
): PhysicsCoordinateStatus[] {
  if (!featureBuild) return []
  const coordinates: PhysicsCoordinateStatus[] = [
    ...featureBuild.available_features.map((feature) => ({
      coordinate: feature,
      status: 'AVAILABLE',
      dependencies: [] as string[],
      reason: null,
    })),
    ...featureBuild.unavailable_features.map((feature) => ({
      coordinate: feature,
      status: 'BLOCKED',
      dependencies: [...featureBuild.missing_device_properties],
      reason: featureBuild.missing_device_properties.length > 0
        ? `缺失属性：${featureBuild.missing_device_properties.join(', ')}`
        : '不可用',
    })),
  ]
  return coordinates
}

export function IdentificationWorkspace({
  readonly = false,
}: {
  readonly?: boolean
}) {
  const context = useTaskContextStore((state) => state.context)
  const setQuickActions = usePageContextStore((state) => state.setQuickActions)
  const { dataProfile } = useScienceStore()
  const { gates, loading, experiments } = useScopeExperiments()

  const [mode, setMode] = useState<FeatureViewMode>('raw')
  const [v2Result, setV2Result] = useState<V2Result | null>(null)
  const [v2Loading, setV2Loading] = useState(false)
  const [v2Error, setV2Error] = useState<string | null>(null)
  const [profileSpot, setProfileSpot] = useState<{ spot_diameter_um: number | null; spot_definition: string | null } | null>(null)

  // 设备档案：只读取光学属性（光斑）。热扩散系数/烧蚀阈值是材料参数，从 Task Context 读取。
  useEffect(() => {
    if (!context.equipmentId) {
      setProfileSpot(null)
      return
    }
    let cancelled = false
    agentApi
      .getEquipmentProfile(context.equipmentId)
      .then((profile) => {
        if (cancelled) return
        const optical = (profile.optical_setup ?? {}) as Record<string, unknown>
        setProfileSpot({
          spot_diameter_um:
            typeof optical.spot_diameter_um === 'number' ? optical.spot_diameter_um : null,
          spot_definition:
            typeof optical.spot_definition === 'string' ? optical.spot_definition : null,
        })
      })
      .catch(() => {
        if (!cancelled) setProfileSpot(null)
      })
    return () => {
      cancelled = true
    }
  }, [context.equipmentId])

  // 材料参数（可选，非必选）：任务定义材料中设置
  const materialDiffusivity = context.materialProperties?.thermalDiffusivityM2S
  const materialThreshold = context.materialProperties?.ablationThresholdJcm2

  const profileSpotDiameter = profileSpot?.spot_diameter_um
  const profileSpotDefinition = profileSpot?.spot_definition
  const profileSpotReady =
    typeof profileSpotDiameter === 'number' &&
    typeof profileSpotDefinition === 'string' &&
    profileSpotDefinition === '1/e2'
  const diffusivityReady = materialDiffusivity !== undefined && materialDiffusivity !== '' && Number.isFinite(Number(materialDiffusivity))
  const thresholdReady = materialThreshold !== undefined && materialThreshold !== '' && Number.isFinite(Number(materialThreshold))

  useEffect(() => {
    const top = v2Result?.controllable_ranking?.[0]?.feature ?? ''
    if (top || v2Result) {
      setQuickActions([
        {
          label: '让 Agent 解释结果',
          prompt: `请解释参数辨识结果（mode=${v2Result?.mode ?? 'raw'}）中可控参数与机理特征的重要性与作用方向。`,
        },
        { label: '为什么这个参数最重要？', prompt: `为什么 ${top} 排名第一？请基于真实结果解释。` },
      ])
    } else {
      setQuickActions([])
    }
    return () => setQuickActions([])
  }, [v2Result, setQuickActions])

  const runIdentificationV2 = useCallback(() => {
    let scope
    try {
      scope = taskContextToScope(context)
    } catch (error) {
      setV2Error(error instanceof Error ? error.message : '任务不完整')
      return
    }
    const rows = experiments.map((row) => ({ ...row }) as unknown as Record<string, unknown>)
    const devicePropertiesPayload: Record<string, { value: number; unit: string }> = {}
    const spotDiameter = profileSpot?.spot_diameter_um
    const spotDefinition = profileSpot?.spot_definition
    if (typeof spotDiameter === 'number' && typeof spotDefinition === 'string' && spotDefinition) {
      if (spotDefinition === '1/e2') {
        devicePropertiesPayload.spot_radius_um = {
          value: spotDiameter / 2,
          unit: 'um',
        }
      }
    }
    // 材料参数（可选）来自任务定义，不来自设备档案
    if (diffusivityReady && materialDiffusivity) {
      devicePropertiesPayload.thermal_diffusivity_m2_s = {
        value: Number(materialDiffusivity),
        unit: 'm2/s',
      }
    }
    if (thresholdReady && materialThreshold) {
      devicePropertiesPayload.ablation_threshold_J_m2 = {
        value: Number(materialThreshold),
        unit: 'J/cm2',
      }
    }
    setV2Loading(true)
    setV2Error(null)
    agentApi
      .runIdentificationV2({
        rows,
        target: scope.target,
        mode,
        device_properties: devicePropertiesPayload,
      })
      .then((result) => setV2Result(result as unknown as V2Result))
      .catch((error) =>
        setV2Error(error instanceof Error ? error.message : '参数辨识 V2 失败'),
      )
      .finally(() => setV2Loading(false))
  }, [context, experiments, mode, profileSpot, diffusivityReady, materialDiffusivity, thresholdReady, materialThreshold])

  const featureBuild = v2Result?.feature_build
  const physicsReadiness = physicsReadinessFromBuild(featureBuild)

  return (
    <div>
      <p className="card-sub">
        基于当前 Task Context（{context.taskContextId}:v{context.version}）。支持 raw /
        physics / hybrid 三模式与双排名（可控参数 + 机理特征）；光斑等光学属性从设备档案读取，
        热扩散系数 / 烧蚀阈值是材料参数（任务定义中设置，可选），物理特征由公式引擎构建。
      </p>

      <div className="row" style={{ marginBottom: 16 }}>
        <StatusBadge tone="neutral">
          加工目标：{context.objective ? objectiveLabel(context.objective) : '未定义'}
        </StatusBadge>
        <StatusBadge tone={gates?.identification ? 'ok' : 'warn'}>
          当前 scope 数据：{dataProfile ? `${dataProfile.n_samples} 样本 / ${dataProfile.n_unique_designs} 设计` : '—'}
        </StatusBadge>
      </div>

      <div className="card">
        <div className="card-title">参数辨识：三模式 + 物理特征工程</div>
        <FeatureViewSelector
          value={mode}
          onChange={setMode}
          readonly={readonly}
          selectedViewLabel={v2Result ? v2Result.mode.toUpperCase() : null}
        />

        {mode !== 'raw' && (
          <div style={{ marginBottom: 12, fontSize: 13 }}>
            <StatusBadge tone={profileSpotReady ? 'ok' : 'warn'}>
              设备档案光斑：{typeof profileSpotDiameter === 'number' ? `${profileSpotDiameter} um` : '—'}
              （{profileSpotDefinition ? String(profileSpotDefinition) : '未定义'}）
            </StatusBadge>{' '}
            <StatusBadge tone={diffusivityReady ? 'ok' : 'neutral'}>
              热扩散系数（材料）：{diffusivityReady ? String(materialDiffusivity) : '未设置'}
            </StatusBadge>{' '}
            <StatusBadge tone={thresholdReady ? 'ok' : 'neutral'}>
              烧蚀阈值（材料）：{thresholdReady ? String(materialThreshold) : '未设置'} J/cm²
            </StatusBadge>
            {!profileSpotReady && (
              <div className="muted" style={{ marginTop: 4 }}>
                设备档案未配置 1/e² 光斑定义——仅涉及光斑的物理特征不可用；其余特征照常运行，不阻塞辨识。
              </div>
            )}
            {(!diffusivityReady || !thresholdReady) && (
              <div className="muted" style={{ marginTop: 4 }}>
                材料参数（热扩散系数 / 烧蚀阈值）可选：在「任务定义 → 材料」中填写后，相关物理特征（热积累、归一化通量等）将可用；未填写的特征如实显示不可用。
              </div>
            )}
          </div>
        )}

        <button
          className="btn primary"
          onClick={runIdentificationV2}
          disabled={v2Loading || loading || !gates?.identification || readonly}
          title="三模式参数辨识：物理特征由公式引擎构建，缺设备属性时如实显示 unavailable"
        >
          {v2Loading ? (
            <>
              <span className="spinner" /> 特征构建 + 辨识中…
            </>
          ) : (
            '运行参数辨识'
          )}
        </button>
        {featureBuild && (
          <div style={{ marginTop: 8, fontSize: 13 }}>
            <StatusBadge tone={featureBuild.available_features.length > 0 ? 'ok' : 'warn'}>
              物理特征可用：{featureBuild.available_features.length}
            </StatusBadge>{' '}
            {featureBuild.missing_device_properties.length > 0 && (
              <StatusBadge tone="warn">
                缺失属性：{featureBuild.missing_device_properties.join(', ')}
              </StatusBadge>
            )}
            {featureBuild.missing_device_properties.length > 0 && (
              <div className="muted" style={{ marginTop: 4 }}>
                缺失属性请在对应位置补全：光斑定义（设备档案）、热扩散系数 / 烧蚀阈值（任务定义 → 材料，可选）。
                缺失的特征如实显示不可用，不静默假设、不阻塞其余特征。
              </div>
            )}
          </div>
        )}
      </div>

      <ErrorBanner message={v2Error} />

      {v2Result && (
        <div className="card">
          <div className="card-title">
            双排名结果（mode: {v2Result.mode}，Group-CV OOF permutation importance）
          </div>
          <div className="grid grid-2">
            <ParameterImportanceChart
              items={v2Result.controllable_ranking}
              title="A. 可控参数重要性（Controllable）"
            />
            <ParameterImportanceChart
              items={v2Result.mechanism_ranking}
              title="B. 机理特征重要性（Mechanism Descriptor）"
            />
          </div>

          {Object.keys(v2Result.mechanism_group_importance).length > 0 && (
            <div className="card-sub" style={{ marginTop: 8 }}>
              机理组重要性：{' '}
              {Object.entries(v2Result.mechanism_group_importance).map(([group, value]) => (
                <StatusBadge key={group} tone="info">
                  {group}: {formatNumber(value, 3)}
                </StatusBadge>
              ))}
            </div>
          )}
          {v2Result.controllable_ranking.length === 0 &&
            v2Result.mechanism_ranking.length === 0 && (
              <EmptyState message={v2Result.claim_boundary ?? '无可用特征'} />
            )}
        </div>
      )}

      {v2Result?.controllable_ranking && v2Result.controllable_ranking.length > 0 && (
        <div className="card">
          <div className="card-title">可控参数排名明细</div>
          <table className="table">
            <thead>
              <tr>
                <th>排名</th>
                <th>参数</th>
                <th>importance</th>
                <th>方向</th>
              </tr>
            </thead>
            <tbody>
              {v2Result.controllable_ranking.map((item) => (
                <tr key={item.feature}>
                  <td>{item.rank}</td>
                  <td>{parameterLabel(item.feature)}</td>
                  <td className="mono">{formatNumber(item.importance, 4)}</td>
                  <td>
                    <span className={effectClass(item.effect_direction)}>
                      {effectLabel(item.effect_direction)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="card">
        <div className="card-title">Physics 特征就绪矩阵</div>
        <PhysicsReadinessMatrix coordinates={physicsReadiness} />
      </div>

      {!v2Result && !v2Loading && !v2Error && (
        <EmptyState message="尚未运行参数辨识。完成后将在此展示可控参数与机理特征双排名。" />
      )}

      {dataProfile && (
        <div className="card">
          <div className="card-title">当前数据状态（DataProfile）</div>
          <DataProfileCard profile={dataProfile} />
        </div>
      )}
    </div>
  )
}
