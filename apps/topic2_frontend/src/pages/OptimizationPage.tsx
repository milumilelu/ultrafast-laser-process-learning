/** 工艺优化：设备机器边界优先，其次数据范围 → Backend 执行 GP-UCB（E2P Soft Prior / Vanilla 对照）。 */

import { useCallback, useEffect, useMemo, useState } from 'react'

import type { Evidence } from '../api/types'
import { agentApi } from '../api/agent'
import { topic2Api } from '../api/topic2'
import { ErrorBanner, EmptyState } from '../components/Banners'
import { OptimizationResultPanel } from '../components/OptimizationResultPanel'
import { StatusBadge } from '../components/StatusBadge'
import { objectiveLabel, processTaskLabel } from '../lib/canonical'
import { defaultBoundsFromRows } from '../lib/params'
import type { CoreParameter, ParameterBounds } from '../lib/params'
import { taskContextToScope } from '../lib/scope'
import { useScopeExperiments } from '../lib/scopeData'
import { parameterLabel } from '../lib/canonical'
import { usePageContextStore } from '../stores/pageContext'
import { useScienceStore } from '../stores/science'
import { useTaskContextStore } from '../stores/taskContext'

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

export function OptimizationPage() {
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

  /** 边界初始化：设备档案（与数据集设备显式映射的档案）机器边界优先；
   *  设备只覆盖部分参数（如缺 hatch/passes）时，用当前 scope 数据范围补齐，
   *  保证五个核心参数始终完整可用。 */
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

  const runOptimization = useCallback(() => {
    let scope
    try {
      scope = taskContextToScope(context)
    } catch (error) {
      setOptimization(null, error instanceof Error ? error.message : '任务不完整')
      return
    }
    if (!boundsInitialized || !bounds) {
      setOptimization(null, '参数允许范围未初始化（设备机器边界或数据范围均不可用）。')
      return
    }
    if (!gates?.optimization) {
      setOptimization(null, '当前 scope 数据不足（优化需 ≥5 条完整样本）。')
      return
    }
    const valid = CORE_ORDER.every((name) => bounds[name].lower < bounds[name].upper)
    if (!valid) {
      setOptimization(null, '存在下界 ≥ 上界的参数范围，请修正。')
      return
    }
    setOptimization(null, null, true)
    topic2Api
      // RAG/Scientific 输出是候选，不可在浏览器中直接转为 BO prior。
      // 未取得服务器签发的 GovernedPriorArtifact 时显式运行 Vanilla BO。
      .recommend({
        scope,
        machine_bounds: { ...bounds },
        model_id: context.selectedModelId,
        model_policy_run_id: modelPolicy?.run_id ?? null,
      })
      .then((result) => {
        setOptimization(result)
        setActiveRun(result.run_id)
      })
      .catch((error) =>
        setOptimization(null, error instanceof Error ? error.message : '优化失败'),
      )
  }, [context, modelPolicy, boundsInitialized, bounds, gates, setOptimization, setActiveRun])

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

  useEffect(() => {
    if (optimization) {
      setQuickActions([
        { label: '解释推荐参数', prompt: `请解释 run_id=${optimization.run_id} 的推荐参数与预测区间。` },
        { label: '比较 Vanilla 与 E2P', prompt: `请基于 run_id=${optimization.run_id} 对比 Vanilla 与 E2P 推荐结果及其差异原因。` },
        { label: '下一步建议', prompt: `基于 run_id=${optimization.run_id}，下一轮实验最值得验证什么？` },
      ])
    } else {
      setQuickActions([])
    }
    return () => setQuickActions([])
  }, [optimization, setQuickActions])

  return (
    <div>
      <h1>工艺优化</h1>
      <p className="card-sub">
        基于当前 Task Context（{context.taskContextId}:v{context.version}）与所选模型执行
        GP-UCB 优化。只有经服务器审核、签发并复核的 GovernedPriorArtifact 可影响候选排序；
        当前页面未取得治理 artifact 时执行 Vanilla BO。
      </p>

      <ErrorBanner message={optimizationError} />
      {machineBoundsError && <ErrorBanner message={machineBoundsError} />}
      {ragEvidenceError && <ErrorBanner message={ragEvidenceError} />}

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
                        value={bounds[name].lower}
                        onChange={(event) => updateBound(name, 'lower', Number(event.target.value))}
                      />
                    </td>
                    <td>
                      <input
                        type="number"
                        step="any"
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
            disabled={ragEvidenceLoading || loading || !gates?.optimization}
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
            className="btn primary"
            onClick={runOptimization}
            disabled={optimizationLoading || loading || !gates?.optimization}
            title={gates?.optimization ? undefined : '当前 scope 数据不足（优化需 ≥5 条完整样本）'}
          >
            {optimizationLoading ? (
              <>
                <span className="spinner" /> Backend 优化中…
              </>
            ) : (
              '执行工艺优化（Vanilla）'
            )}
          </button>
          {ragEvidenceMeta && (
            <StatusBadge tone={ragEvidence.length > 0 ? 'ok' : 'warn'}>
              待审核候选：{ragEvidence.length} 条（检索 {ragEvidenceMeta.retrievedHits} / 来源可用 {ragEvidenceMeta.reviewedHits}）
            </StatusBadge>
          )}
        </div>
      </div>

      {optimization && (
        <div className="card">
          <div className="card-title">工艺推荐结果</div>
          <OptimizationResultPanel result={optimization} />
        </div>
      )}

      {!optimization && !optimizationLoading && !optimizationError && (
        <EmptyState message="尚未执行优化。完成后将展示推荐参数、预测区间、约束状态与 E2P/Vanilla 对照。" />
      )}
    </div>
  )
}

