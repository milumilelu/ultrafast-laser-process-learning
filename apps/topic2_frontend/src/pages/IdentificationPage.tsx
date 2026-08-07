/** 参数辨识 V2：raw / physics / hybrid 三模式 + 双排名输出。
 *  设备光学/材料属性从工艺任务页（TaskPage）设置后自动读取；
 *  物理特征由公式引擎构建（缺属性时如实显示 unavailable 与原因，不静默假设）。 */

import { useCallback, useEffect, useState } from 'react'

import { agentApi } from '../api/agent'
import { ErrorBanner, EmptyState } from '../components/Banners'
import { DataProfileCard } from '../components/DataProfileCard'
import { StatusBadge } from '../components/StatusBadge'
import { effectClass, effectLabel, formatNumber } from '../lib/format'
import { objectiveLabel, parameterLabel } from '../lib/canonical'
import { taskContextToScope } from '../lib/scope'
import { useScopeExperiments } from '../lib/scopeData'
import { usePageContextStore } from '../stores/pageContext'
import { useScienceStore } from '../stores/science'
import { useTaskContextStore } from '../stores/taskContext'

type Mode = 'raw' | 'physics' | 'hybrid'

interface V2Result {
  mode: Mode
  target: string
  cv_strategy: string
  controllable_ranking: {
    feature: string
    importance: number
    effect_direction: string
    rank: number
  }[]
  mechanism_ranking: {
    feature: string
    importance: number
    effect_direction: string
    rank: number
  }[]
  mechanism_group_importance: Record<string, number>
  feature_build?: {
    available_features: string[]
    unavailable_features: string[]
    missing_device_properties: string[]
  }
  claim_boundary?: string
}

export function IdentificationPage() {
  const context = useTaskContextStore((state) => state.context)
  const setQuickActions = usePageContextStore((state) => state.setQuickActions)
  const { dataProfile } = useScienceStore()
  const { gates, loading, experiments } = useScopeExperiments()

  const [mode, setMode] = useState<Mode>('raw')
  const [v2Result, setV2Result] = useState<V2Result | null>(null)
  const [v2Loading, setV2Loading] = useState(false)
  const [v2Error, setV2Error] = useState<string | null>(null)
  // 设备档案光学/材料属性（新建设备时配置，任务页选择档案后自动读取）
  const [profileProperties, setProfileProperties] = useState<Record<string, unknown> | null>(null)

  useEffect(() => {
    if (!context.equipmentId) {
      setProfileProperties(null)
      return
    }
    let cancelled = false
    agentApi
      .getEquipmentProfile(context.equipmentId)
      .then((profile) => {
        if (cancelled) return
        const optical = (profile.optical_setup ?? {}) as Record<string, unknown>
        const capability_ = (profile.process_capability ?? {}) as Record<string, unknown>
        setProfileProperties({
          spot_diameter_um: optical.spot_diameter_um ?? null,
          spot_definition: optical.spot_definition ?? null,
          thermal_diffusivity_m2_s: capability_.thermal_diffusivity_m2_s ?? null,
          ablation_threshold_J_cm2: capability_.ablation_threshold_J_cm2 ?? null,
        })
      })
      .catch(() => {
        if (!cancelled) setProfileProperties(null)
      })
    return () => {
      cancelled = true
    }
  }, [context.equipmentId])

  const profileSpotDiameter = profileProperties?.spot_diameter_um
  const profileSpotDefinition = profileProperties?.spot_definition
  const profileSpotReady =
    typeof profileSpotDiameter === 'number' &&
    typeof profileSpotDefinition === 'string' &&
    profileSpotDefinition === '1/e2'
  const profileDiffusivity = profileProperties?.thermal_diffusivity_m2_s
  const profileThreshold = profileProperties?.ablation_threshold_J_cm2

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
    // 物理输入只能来自已持久化设备档案。Scientific/RAG 输出是待审核知识，
    // 前端不得把它直接提升为设备参数。
    const spotDiameter = profileProperties?.spot_diameter_um
    const spotDefinition = profileProperties?.spot_definition
    if (typeof spotDiameter === 'number' && typeof spotDefinition === 'string' && spotDefinition) {
      // 档案存储为直径；物理特征输入为 1/e² 半径。定义一致时 radius = diameter / 2。
      // spot_definition 非 1/e2 时保守不推导（防止半径/直径混淆）。
      if (spotDefinition === '1/e2') {
        devicePropertiesPayload.spot_radius_um = {
          value: spotDiameter / 2,
          unit: 'um',
        }
      }
    }
    const diffusivity = profileProperties?.thermal_diffusivity_m2_s
    if (typeof diffusivity === 'number' && Number.isFinite(diffusivity)) {
      devicePropertiesPayload.thermal_diffusivity_m2_s = {
        value: diffusivity,
        unit: 'm2/s',
      }
    }
    const threshold = profileProperties?.ablation_threshold_J_cm2
    if (typeof threshold === 'number' && Number.isFinite(threshold)) {
      devicePropertiesPayload.ablation_threshold_J_m2 = {
        value: threshold,
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
  }, [context, experiments, mode, profileProperties])

  const featureBuild = v2Result?.feature_build

  return (
    <div>
      <h1>参数辨识</h1>
      <p className="card-sub">
        基于当前 Task Context（{context.taskContextId}:v{context.version}）。支持 raw /
        physics / hybrid 三模式与双排名（可控参数 + 机理特征）；设备光学/材料属性从
        工艺任务页设置后自动读取，物理特征由公式引擎构建。
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
        <div className="card-title">参数辨识 V2：三模式 + 物理特征工程</div>
        <div className="row" style={{ marginBottom: 12 }}>
          {(['raw', 'physics', 'hybrid'] as Mode[]).map((value) => (
            <label key={value} style={{ marginRight: 16 }}>
              <input
                type="radio"
                name="mode"
                value={value}
                checked={mode === value}
                onChange={() => setMode(value)}
              />
              {value === 'raw' ? 'raw（仅可控参数）' : value === 'physics' ? 'physics（仅机理特征）' : 'hybrid（混合）'}
            </label>
          ))}
        </div>

        {mode !== 'raw' && (
          <div style={{ marginBottom: 12, fontSize: 13 }}>
            <StatusBadge tone={profileSpotReady ? 'ok' : 'warn'}>
              设备档案光斑：{typeof profileSpotDiameter === 'number' ? `${profileSpotDiameter} um` : '—'}
              （{profileSpotDefinition ? String(profileSpotDefinition) : '未定义'}）
            </StatusBadge>{' '}
            <StatusBadge tone={typeof profileDiffusivity === 'number' ? 'ok' : 'warn'}>
              热扩散系数：{typeof profileDiffusivity === 'number' ? String(profileDiffusivity) : '—'}
            </StatusBadge>{' '}
            <StatusBadge tone={typeof profileThreshold === 'number' ? 'ok' : 'warn'}>
              烧蚀阈值：{typeof profileThreshold === 'number' ? String(profileThreshold) : '—'} J/cm²
            </StatusBadge>
            {!profileSpotReady && (
              <div className="muted" style={{ marginTop: 4 }}>
                设备档案未配置 1/e² 光斑定义——仅涉及光斑的物理特征（peak_fluence /
                normalized_fluence / pulse_overlap 等）不可用；**其余特征与 raw 模式照常运行**，
                不阻塞辨识。科学分析候选不会在浏览器中直接转成设备参数；须经审核并写入设备档案后使用。
              </div>
            )}
          </div>
        )}

        <button
          className="btn primary"
          onClick={runIdentificationV2}
          disabled={v2Loading || loading || !gates?.identification}
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
            {featureBuild.unavailable_features.length > 0 && (
              <div className="muted" style={{ marginTop: 4 }}>
                不可用特征：{featureBuild.unavailable_features.join(', ')}（不静默假设，请在工艺任务页补全属性后重试）
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
          {v2Result.controllable_ranking.length > 0 && (
            <div className="section" style={{ marginBottom: 12 }}>
              <div className="card-sub">A. 可控参数重要性（Controllable）</div>
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
          {v2Result.mechanism_ranking.length > 0 && (
            <div className="section">
              <div className="card-sub">B. 机理特征重要性（Mechanism Descriptor）</div>
              <table className="table">
                <thead>
                  <tr>
                    <th>排名</th>
                    <th>机理特征</th>
                    <th>importance</th>
                    <th>方向</th>
                  </tr>
                </thead>
                <tbody>
                  {v2Result.mechanism_ranking.map((item) => (
                    <tr key={item.feature}>
                      <td>{item.rank}</td>
                      <td>{item.feature}</td>
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
            </div>
          )}
          {v2Result.controllable_ranking.length === 0 &&
            v2Result.mechanism_ranking.length === 0 && (
              <EmptyState message={v2Result.claim_boundary ?? '无可用特征'} />
            )}
        </div>
      )}

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
