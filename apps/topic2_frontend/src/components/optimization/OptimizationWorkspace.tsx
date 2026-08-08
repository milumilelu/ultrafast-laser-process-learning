/** OptimizationWorkspace (UI-5): Vanilla vs Evidence-assisted BO 真实并列对照。
 *  推荐文案固定为「推荐下一实验点」；CFA 不改变 prior 权重（audit only）；
 *  无 GovernedPriorArtifact 时 assisted 如实显示 prior_applied=false。 */

import { useCallback, useEffect, useMemo, useState } from 'react'

import { agentApi } from '../../api/agent'
import { applicationApi } from '../../api/application'
import type { Evidence, OptimizationComparison as OptimizationComparisonResult, OptimizationResult } from '../../api/types'
import { topic2Api } from '../../api/topic2'
import { ErrorBanner, EmptyState } from '../../components/Banners'
import { OptimizationResultPanel } from '../../components/OptimizationResultPanel'
import { StatusBadge } from '../../components/StatusBadge'
import { objectiveLabel, processTaskLabel, parameterLabel } from '../../lib/canonical'
import { defaultBoundsFromRows } from '../../lib/params'
import type { CoreParameter, ParameterBounds } from '../../lib/params'
import { taskContextToScope } from '../../lib/scope'
import { useScopeExperiments } from '../../lib/scopeData'
import { usePageContextStore } from '../../stores/pageContext'
import { useScienceStore } from '../../stores/science'
import { useTaskContextStore } from '../../stores/taskContext'
import { EvidenceTracePanel } from './EvidenceTracePanel'
import { OptimizationComparison } from './OptimizationComparison'
import { PriorInfluencePanel } from './PriorInfluencePanel'

const CORE_ORDER: CoreParameter[] = [
  'pulse_width_ps',
  'frequency_kHz',
  'hatch_spacing_um',
  'passes',
  'scan_speed_mm_s',
]

function toNumber(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

export function OptimizationWorkspace({
  readonly = false,
  governedPriorOverride = null,
  comparisonOverride = null,
}: {
  readonly?: boolean
  /** 来自 Application Run 的 GovernedPriorArtifact（无则走 honest vanilla fallback） */
  governedPriorOverride?: Record<string, unknown> | null
  /** ApplicationRun 的优化对照结果（optimization），存在时优先展示 */
  comparisonOverride?: OptimizationComparisonResult | null
}) {
  const context = useTaskContextStore((state) => state.context)
  const setActiveRun = usePageContextStore((state) => state.setActiveRun)
  const setQuickActions = usePageContextStore((state) => state.setQuickActions)
  const {
    optimization,
    optimizationLoading,
    optimizationError,
    experiments,
    dataProfile,
    modelPolicy,
    ragEvidence,
    ragEvidenceMeta,
    ragEvidenceLoading,
    ragEvidenceError,
    setOptimization,
    setRagEvidence,
  } = useScienceStore()
  const { gates, loading } = useScopeExperiments()
  const [bounds, setBounds] = useState<Record<CoreParameter, ParameterBounds> | null>(null)
  const [boundsSource, setBoundsSource] = useState<'equipment' | 'data' | 'mixed' | null>(null)
  const [machineBoundsError, setMachineBoundsError] = useState<string | null>(null)
  const [governedPrior, setGovernedPrior] = useState<Record<string, unknown> | null>(null)
  const [e2pLoading, setE2pLoading] = useState(false)
  const [e2pError, setE2pError] = useState<string | null>(null)
  const [comparison, setComparison] = useState<Awaited<ReturnType<typeof applicationApi.compareOptimization>> | null>(null)
  const [comparisonLoading, setComparisonLoading] = useState(false)
  const [comparisonError, setComparisonError] = useState<string | null>(null)

  useEffect(() => {
    if (governedPriorOverride && governedPriorOverride !== governedPrior) {
      setGovernedPrior(governedPriorOverride as Record<string, unknown> | null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [governedPriorOverride])

  useEffect(() => {
    if (bounds) return
    let cancelled = false
    const rows = experiments.map((row) => row as unknown as Record<string, unknown>)
    const boundsRequest = context.equipmentId
      ? agentApi.profileMachineBounds(context.equipmentId)
      : agentApi.machineBounds()
    boundsRequest
      .then((result) => {
        if (cancelled) return
        const next: Partial<Record<CoreParameter, ParameterBounds>> = {}
        const active = result.active && Object.keys(result.machine_bounds).length > 0
        if (active) {
          const pulse = result.machine_bounds['pulse_width_fs']
          const freq = result.machine_bounds['frequency_kHz']
          const speed = result.machine_bounds['scan_speed_mm_s']
          if (pulse && toNumber(pulse[0]) !== null && toNumber(pulse[1]) !== null) {
            const min = toNumber(pulse[0]) as number
            const max = toNumber(pulse[1]) as number
            if (min < max) next.pulse_width_ps = { lower: min / 1000, upper: max / 1000 }
          }
          if (freq && toNumber(freq[0]) !== null && toNumber(freq[1]) !== null) {
            const min = toNumber(freq[0]) as number
            const max = toNumber(freq[1]) as number
            if (min < max) next.frequency_kHz = { lower: min, upper: max }
          }
          if (speed && toNumber(speed[0]) !== null && toNumber(speed[1]) !== null) {
            const min = toNumber(speed[0]) as number
            const max = toNumber(speed[1]) as number
            if (min < max) next.scan_speed_mm_s = { lower: min, upper: max }
          }
        }
        const missing = CORE_ORDER.filter((name) => next[name] === undefined)
        if (missing.length > 0 && rows.length > 0) {
          const dataBounds = defaultBoundsFromRows(rows)
          for (const name of missing) next[name] = dataBounds[name]
        }
        const complete = CORE_ORDER.every((name) => next[name] !== undefined)
        if (!complete) return
        const full = next as Record<CoreParameter, ParameterBounds>
        const valid = CORE_ORDER.every((name) => full[name].lower < full[name].upper)
        if (!valid) return
        setBounds(full)
        setBoundsSource(missing.length === 0 ? 'equipment' : active ? 'mixed' : 'data')
      })
      .catch((error) => {
        if (cancelled) return
        setMachineBoundsError(
          error instanceof Error ? `设备机器边界读取失败：${error.message}` : '设备机器边界读取失败',
        )
        if (rows.length > 0) {
          const dataBounds = defaultBoundsFromRows(rows)
          setBounds(dataBounds)
          setBoundsSource('data')
        }
      })
    return () => {
      cancelled = true
    }
  }, [bounds, experiments, context.equipmentId])

  const boundsInitialized = useMemo(
    () => bounds !== null && CORE_ORDER.every((name) => bounds[name] !== undefined),
    [bounds],
  )

  const updateBound = useCallback((name: CoreParameter, side: 'lower' | 'upper', value: number) => {
    setBounds((current) => {
      if (!current) return current
      return { ...current, [name]: { ...current[name], [side]: value } }
    })
  }, [])

  const runCompare = useCallback(() => {
    let scope
    try {
      scope = taskContextToScope(context)
    } catch (error) {
      setComparisonError(error instanceof Error ? error.message : '任务不完整')
      return
    }
    if (!boundsInitialized || !bounds) {
      setComparisonError('参数允许范围未初始化（设备机器边界或数据范围均不可用）。')
      return
    }
    if (!gates?.optimization) {
      setComparisonError('当前 scope 数据不足（优化需 ≥5 条完整样本）。')
      return
    }
    const valid = CORE_ORDER.every((name) => bounds[name].lower < bounds[name].upper)
    if (!valid) {
      setComparisonError('存在下界 ≥ 上界的参数范围，请修正。')
      return
    }
    setComparisonLoading(true)
    setComparisonError(null)
    applicationApi
      .compareOptimization({
        scope: scope as unknown as Record<string, unknown>,
        machine_bounds: { ...bounds },
        governed_prior_artifact: governedPrior ?? null,
        model_id: context.selectedModelId,
        random_seed: 42,
      })
      .then((result) => {
        setComparison(result)
        setOptimization(result.vanilla as unknown as OptimizationResult)
        setActiveRun(result.vanilla.run_id)
      })
      .catch((error) =>
        setComparisonError(error instanceof Error ? error.message : '优化对照失败'),
      )
      .finally(() => setComparisonLoading(false))
  }, [context, modelPolicy, boundsInitialized, bounds, gates, governedPrior, setOptimization, setActiveRun])

  const retrieveEvidence = useCallback(() => {
    let scope
    try {
      scope = taskContextToScope(context)
    } catch (error) {
      setRagEvidence([], null, error instanceof Error ? error.message : '任务不完整')
      return
    }
    setRagEvidence([], null, null, true)
    agentApi
      .evidenceCandidates({
        task_scope: {
          material: scope.material,
          laser_type: scope.laser_type,
          geometry_type: scope.geometry_type,
          equipment_id: scope.equipment_id,
          target: scope.target,
        },
        top_k: 20,
      })
      .then((result) => {
        setRagEvidence(
          result.evidence as unknown as Evidence[],
          {
            retrievedHits: result.retrieved_hits,
            reviewedHits: result.reviewed_hits,
            evidenceStatus: result.evidence_status,
          },
        )
      })
      .catch((error) =>
        setRagEvidence([], null, error instanceof Error ? error.message : '证据检索失败'),
      )
  }, [context, setRagEvidence])

  /** E2P Prepare → GovernedPriorArtifact（服务器签发）。Agent 离线时 fails closed，
   *  assisted BO 如实显示 prior_applied=false。 */
  const prepareGovernedPrior = useCallback(() => {
    let scope
    try {
      scope = taskContextToScope(context)
    } catch (error) {
      setE2pError(error instanceof Error ? error.message : '任务不完整')
      return
    }
    if (!dataProfile) {
      setE2pError('缺少 DataProfile，无法执行 E2P Prepare。')
      return
    }
    setE2pLoading(true)
    setE2pError(null)
    topic2Api
      .prepareE2P({ scope, data_profile: dataProfile, evidence: ragEvidence })
      .then((result) => {
        setGovernedPrior(result.governed_prior_artifact as unknown as Record<string, unknown> | null)
        setE2pError(
          result.governed_prior_artifact
            ? null
            : 'E2P Prepare 未签发 GovernedPriorArtifact（无已批准证据）；assisted 将与 Vanilla 相同。',
        )
      })
      .catch((error) =>
        setE2pError(
          error instanceof Error
            ? `Governed Prior 签发失败（fails closed）：${error.message}`
            : 'Governed Prior 签发失败',
        ),
      )
      .finally(() => setE2pLoading(false))
  }, [context, dataProfile, ragEvidence])

  useEffect(() => {
    if (comparison || optimization) {
      setQuickActions([
        { label: '解释推荐参数', prompt: `请解释 Vanilla/Assisted 对照的推荐参数与预测区间。` },
        { label: '比较 Vanilla 与 Assisted', prompt: `请对比 Vanilla 与 Evidence-assisted BO 推荐结果及其差异原因。` },
        { label: '下一步建议', prompt: `下一轮实验最值得验证什么？` },
      ])
    } else {
      setQuickActions([])
    }
    return () => setQuickActions([])
  }, [comparison, optimization, setQuickActions])

  // 应用运行结果优先：完整分析已执行时直接展示正式对照
  const displayedComparison = comparisonOverride ?? comparison

  return (
    <div>
      <p className="card-sub">
        基于当前 Task Context（{context.taskContextId}:v{context.version}）与所选模型执行
        GP-UCB 优化。Vanilla 与 Evidence-assisted 由后端真实并列执行；只有经服务器审核、
        签发并复核的 GovernedPriorArtifact 可影响候选排序，未校准 CFA 仅作审计（不改变 prior 权重）。
      </p>

      <ErrorBanner message={optimizationError} />
      <ErrorBanner message={machineBoundsError} />
      <ErrorBanner message={ragEvidenceError} />
      <ErrorBanner message={e2pError} />
      <ErrorBanner message={comparisonError} />

      <div className="card">
        <div className="card-title">优化配置</div>
        <div className="row" style={{ marginBottom: 12 }}>
          <StatusBadge tone="info">
            加工目标：{context.objective ? objectiveLabel(context.objective) : '未定义'}
          </StatusBadge>
          <StatusBadge tone="info">
            加工任务：{context.processType ? processTaskLabel(context.processType) : '未定义'}
          </StatusBadge>
          <StatusBadge tone="neutral">
            数据：{dataProfile ? `${dataProfile.n_samples} 样本 / ${dataProfile.n_unique_designs} 组合` : '未加载'}
          </StatusBadge>
          <StatusBadge tone="info">
            设备档案：{context.equipmentId ?? '未选择（退回数据范围）'}
          </StatusBadge>
          <StatusBadge tone={governedPrior ? 'ok' : 'neutral'}>
            {governedPrior ? 'Governed Prior 已就绪' : 'Governed Prior 未就绪'}
          </StatusBadge>
        </div>
        {bounds ? (
          <>
            <div className="card-sub">
              参数允许范围来源：
              {boundsSource === 'equipment'
                ? '设备档案机器边界（Agent 设备档案，脉宽 fs→ps 换算）'
                : boundsSource === 'mixed'
                  ? '设备档案机器边界 + 数据范围补齐（设备未覆盖 hatch/passes 等参数）'
                  : '当前 scope 数据范围'}
              （均可编辑）
            </div>
            <table className="table">
              <thead>
                <tr>
                  <th>参数</th>
                  <th>下界</th>
                  <th>上界</th>
                </tr>
              </thead>
              <tbody>
                {CORE_ORDER.map((name) => (
                  <tr key={name}>
                    <td>{parameterLabel(name)}</td>
                    <td>
                      <input
                        type="number"
                        step="any"
                        disabled={readonly}
                        value={bounds[name].lower}
                        onChange={(event) => updateBound(name, 'lower', Number(event.target.value))}
                      />
                    </td>
                    <td>
                      <input
                        type="number"
                        step="any"
                        disabled={readonly}
                        value={bounds[name].upper}
                        onChange={(event) => updateBound(name, 'upper', Number(event.target.value))}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : (
          <div className="empty-state">
            参数范围将根据当前激活设备的机器边界或任务实际数据生成。
          </div>
        )}
        <div className="row" style={{ marginTop: 12 }}>
          <button
            className="btn"
            onClick={retrieveEvidence}
            disabled={ragEvidenceLoading || loading || readonly}
            title="只生成待审核 Evidence 候选，不会直接进入 BO"
          >
            {ragEvidenceLoading ? (
              <>
                <span className="spinner" /> 检索中…
              </>
            ) : (
              '检索待审核候选（RAG）'
            )}
          </button>
          <button
            className="btn"
            onClick={prepareGovernedPrior}
            disabled={e2pLoading || loading || readonly}
            title="E2P Prepare：服务器签发 GovernedPriorArtifact（review 实时校验，fails closed）"
          >
            {e2pLoading ? (
              <>
                <span className="spinner" /> E2P Prepare 中…
              </>
            ) : (
              '获取受治理先验（E2P Prepare）'
            )}
          </button>
          <button
            className="btn primary"
            onClick={runCompare}
            disabled={comparisonLoading || loading || !gates?.optimization || readonly}
            title={gates?.optimization ? undefined : '当前 scope 数据不足（优化需 ≥5 条完整样本）'}
          >
            {comparisonLoading ? (
              <>
                <span className="spinner" /> Backend 对照优化中…
              </>
            ) : (
              '运行 Vanilla / Assisted 对照'
            )}
          </button>
          {ragEvidenceMeta && (
            <StatusBadge tone={ragEvidence.length > 0 ? 'ok' : 'warn'}>
              待审核候选：{ragEvidence.length} 条（检索 {ragEvidenceMeta.retrievedHits} / 来源可用 {ragEvidenceMeta.reviewedHits}）
            </StatusBadge>
          )}
        </div>
      </div>

      {displayedComparison && (
        <>
          {comparisonOverride && (
            <div className="row" style={{ marginBottom: 8 }}>
              <span className="badge ok">应用运行正式结果（ApplicationRun）</span>
            </div>
          )}
          <OptimizationComparison comparison={displayedComparison} />
          <div className="grid grid-2">
            <PriorInfluencePanel result={displayedComparison.evidence_assisted} />
            <EvidenceTracePanel
              priorAppliedEvidence={displayedComparison.prior_applied_evidence}
              governedPrior={governedPrior}
            />
          </div>
        </>
      )}

      {!displayedComparison && optimization && (
        <div className="card">
          <div className="card-title">工艺推荐结果（Vanilla）</div>
          <OptimizationResultPanel result={optimization} />
        </div>
      )}

      {!displayedComparison && !optimization && !comparisonLoading && !optimizationLoading && (
        <EmptyState message="尚未执行优化对照。完成后将并列展示 Vanilla 与 Evidence-assisted 推荐、先验影响与治理追溯。" />
      )}
    </div>
  )
}
