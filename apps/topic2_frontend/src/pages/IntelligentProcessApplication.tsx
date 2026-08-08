/** IntelligentProcessApplication (UI-2): 工艺智能应用核心页面。
 *  三个最终应用结果：参数辨识 → 工艺建模 → 工艺优化；科学基础设施（Physics /
 *  Literature / Evidence / CFA / Agent）作为支撑层出现，不再割裂成主导航功能。 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { applicationApi, applicationGateway } from '../api/application'
import { topic2Api } from '../api/topic2'
import type { ModelMetrics, ModelTrainingResult, Topic2ApplicationResult } from '../api/types'
import { friendlyApiError } from '../lib/errors'
import { ErrorBanner, EmptyState } from '../components/Banners'
import { StatusBadge } from '../components/StatusBadge'
import { IdentificationWorkspace } from '../components/learning/IdentificationWorkspace'
import { ModelingWorkspace } from '../components/learning/ModelingWorkspace'
import { OptimizationWorkspace } from '../components/optimization/OptimizationWorkspace'
import { scientificTone, type StatusTone } from '../lib/status'
import { formatNumber } from '../lib/format'
import { objectiveToTarget, parameterLabel, processTaskLabel } from '../lib/canonical'
import { taskContextToScope } from '../lib/scope'
import { useModeStore } from '../stores/mode'
import { useApplicationStore, type ApplicationTab } from '../stores/application'
import { useScienceStore } from '../stores/science'
import { useTaskContextStore } from '../stores/taskContext'
import { useWorkflowStore } from '../stores/workflow'

const TABS: { key: ApplicationTab; label: string }[] = [
  { key: 'summary', label: '综合结果' },
  { key: 'identification', label: '参数辨识' },
  { key: 'modeling', label: '工艺建模' },
  { key: 'optimization', label: '工艺优化' },
]

function tabFromParam(param: string | null): ApplicationTab {
  if (param === 'identification' || param === 'modeling' || param === 'optimization' || param === 'summary') {
    return param
  }
  return 'summary'
}

export function IntelligentProcessApplication() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const context = useTaskContextStore((state) => state.context)
  const softwareMode = useModeStore((state) => state.mode)
  const setSelectedTab = useApplicationStore((state) => state.setSelectedTab)
  const setRunRefs = useApplicationStore((state) => state.setRunRefs)
  const selectedTab = tabFromParam(searchParams.get('tab'))
  const training = useScienceStore((state) => state.training)
  const workflow = useWorkflowStore()

  const [applicationResult, setApplicationResult] = useState<Topic2ApplicationResult | null>(null)
  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)
  const pollTimer = useRef<number | null>(null)

  useEffect(() => {
    setSelectedTab(selectedTab)
  }, [selectedTab, setSelectedTab])

  const syncTab = useCallback(
    (tab: ApplicationTab) => {
      setSearchParams({ tab })
      navigate(`/application?tab=${tab}`, { replace: true })
    },
    [navigate, setSearchParams],
  )

  const pollResult = useCallback(
    (runId: string) => {
      let cancelled = false
      const tick = async () => {
        if (cancelled) return
        try {
          const run = await applicationGateway.getRun(runId)
          if (run.status === 'completed' && run.result) {
            setApplicationResult(run.result)
            workflow.complete()
            setRunRefs({
              runId,
              processLearningArtifactId: null,
              governedPriorArtifactId:
                run.result.scientificBasis.governedPrior?.artifact_id != null
                  ? String(run.result.scientificBasis.governedPrior.artifact_id)
                  : null,
              vanillaBoRunId: run.result.optimization.vanilla?.run_id ?? null,
              assistedBoRunId: run.result.optimization.evidenceAssisted?.run_id ?? null,
              mode: run.mode,
            })
            setRunning(false)
            return
          }
          if (run.status === 'failed') {
            workflow.fail('应用运行失败')
            setRunning(false)
            setRunError('应用运行失败，请查看执行流。')
            return
          }
          pollTimer.current = window.setTimeout(() => void tick(), 2000)
        } catch {
          pollTimer.current = window.setTimeout(() => void tick(), 3000)
        }
      }
      void tick()
      return () => {
        cancelled = true
        if (pollTimer.current) window.clearTimeout(pollTimer.current)
      }
    },
    [workflow, setRunRefs],
  )

  useEffect(() => {
    const activeRunId = workflow.activeRunId
    if (!activeRunId) return undefined
    const abort = new AbortController()
    applicationGateway
      .streamEvents(
        activeRunId,
        workflow.lastSequence,
        {
          onEvent: (event) => workflow.append([event]),
          onError: () => undefined,
          onDone: () => undefined,
        },
        abort.signal,
      )
      .catch(() => undefined)
    const stop = pollResult(activeRunId)
    return () => {
      abort.abort()
      stop()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflow.activeRunId])

  const buildTaskSpec = useCallback(() => {
    const scope = taskContextToScope(context)
    return {
      task_context_id: scope.task_context_id,
      task_context_version: scope.task_context_version,
      material: scope.material,
      laser_type: scope.laser_type,
      equipment_profile_id: scope.equipment_id,
      geometry_type: scope.geometry_type,
      objective_metric: scope.target,
      process_parameters: scope.process_parameters,
      device_properties: scope.device_properties,
      random_seed: 42,
    }
  }, [context])

  /** 运行前预检：当前组合是否有实验数据（无数据不发请求，直接友好提示）。 */
  const preflightScope = useCallback(async (): Promise<boolean> => {
    try {
      const capability = await topic2Api.scopeCapability({
        material: context.materialId,
        laser_type: context.laserType,
        equipment_id: context.datasetEquipmentId,
        geometry_type: context.processType ?? null,
      })
      if (capability.n_samples === 0) {
        setRunError(
          `当前组合（${context.materialId ?? '?'} / ${context.laserType ?? '?'} / ${context.datasetEquipmentId ?? '?'} / ${context.processType ?? '?'}）在数据库中没有实验数据。请到「任务与数据」页更换组合后再运行。`,
        )
        return false
      }
      if (!capability.meets_identification) {
        setRunError('当前组合数据量不足以执行参数辨识（需 ≥4 样本 / ≥2 独立设计）。请补充数据或更换组合。')
        return false
      }
      return true
    } catch (error) {
      setRunError(friendlyApiError(error))
      return false
    }
  }, [context.materialId, context.laserType, context.datasetEquipmentId, context.processType, setRunError])

  const runFullAnalysis = useCallback(() => {
    let taskSpec
    try {
      taskSpec = buildTaskSpec()
    } catch (error) {
      setRunError(error instanceof Error ? error.message : '任务不完整')
      return
    }
    void preflightScope().then((ok) => {
      if (!ok) return
      setRunError(null)
      setApplicationResult(null)
      setRunning(true)
      workflow.clear()
      const clientRequestId = crypto.randomUUID()
      applicationGateway
        .runFullApplication({
          mode: softwareMode,
          task_spec: taskSpec,
          random_seed: 42,
          client_request_id: clientRequestId,
        })
        .then((summary) => {
          workflow.start(summary.application_run_id)
          setRunRefs({ runId: summary.application_run_id, mode: summary.mode })
        })
        .catch((error) => {
          setRunning(false)
          setRunError(friendlyApiError(error))
        })
    })
  }, [buildTaskSpec, preflightScope, softwareMode, workflow, setRunRefs])

  /** 两段式入口（checkpoint）：运行到知识缺口（1-4 阶段），检查 Requirement 后由
   *  「继续准备科学知识」续跑同一 ApplicationRun（5-8 阶段），不重复已执行阶段。 */
  const runToKnowledgeGap = useCallback(() => {
    let taskSpec
    try {
      taskSpec = buildTaskSpec()
    } catch (error) {
      setRunError(error instanceof Error ? error.message : '任务不完整')
      return
    }
    void preflightScope().then((ok) => {
      if (!ok) return
      setRunError(null)
      setApplicationResult(null)
      setRunning(true)
      workflow.clear()
      const clientRequestId = crypto.randomUUID()
      applicationGateway
        .runFullApplication({
          mode: 'research',
          task_spec: taskSpec,
          stages: ['prepare_task', 'assess_data', 'baseline_learning', 'analyze_knowledge_gaps'],
          random_seed: 42,
          client_request_id: clientRequestId,
        })
        .then((summary) => {
          workflow.start(summary.application_run_id)
          setRunRefs({ runId: summary.application_run_id, mode: summary.mode })
        })
        .catch((error) => {
          setRunning(false)
          setRunError(friendlyApiError(error))
        })
    })
  }, [buildTaskSpec, preflightScope, workflow, setRunRefs])

  const continueKnowledgePreparation = useCallback(() => {
    const runId = workflow.activeRunId
    if (!runId) {
      setRunError('请先「运行到知识缺口」创建检查点。')
      return
    }
    setRunError(null)
    setRunning(true)
    applicationApi
      .continueRun(runId, {
        stages: ['prepare_knowledge', 'satisfy_requirements', 'apply_knowledge', 'optimization'],
        random_seed: 42,
        client_request_id: crypto.randomUUID(),
      })
      .catch((error) => {
        setRunning(false)
        setRunError(friendlyApiError(error))
      })
  }, [workflow])

  const analysisComplete = applicationResult !== null

  const statusBar = (
    <div className="app-status-bar">
      <StatusBadge tone={training || analysisComplete ? 'ok' : 'neutral'}>1 参数辨识</StatusBadge>
      <span className="status-link">───</span>
      <StatusBadge tone={training || analysisComplete ? 'ok' : 'neutral'}>2 工艺建模</StatusBadge>
      <span className="status-link">───</span>
      <StatusBadge tone={analysisComplete ? 'ok' : 'neutral'}>3 工艺优化</StatusBadge>
    </div>
  )

  return (
    <div className="application-page">
      <h1>工艺智能应用</h1>
      <p className="card-sub">
        围绕三个核心问题组织：哪些工艺参数和物理特征最重要（参数辨识）→ 哪个模型最可靠（工艺建模）
        → 下一轮实验最值得做什么（工艺优化）。所有结果可追溯至 Task / Dataset / Model / Evidence / Prior / BO Run。
      </p>

      <div className="row" style={{ marginBottom: 10, alignItems: 'center' }}>
        <button
          className="btn primary"
          onClick={runFullAnalysis}
          disabled={running}
          title="一键完整分析：任务 → 数据评估 → 基线学习 → 知识缺口 → 知识准备 → 满足评估 → 知识应用 → BO"
        >
          {running ? (
            <>
              <span className="spinner" /> 运行中…
            </>
          ) : (
            '运行完整分析'
          )}
        </button>
        {softwareMode === 'research' && (
          <>
            <button
              className="btn"
              onClick={runToKnowledgeGap}
              disabled={running}
              title="检查点：先运行到知识缺口（任务/数据/基线/需求），检查 KnowledgeRequirement 后再继续"
            >
              运行到知识缺口
            </button>
            <button
              className="btn"
              onClick={continueKnowledgePreparation}
              disabled={running || !workflow.activeRunId}
              title="继续同一 ApplicationRun：知识准备 → 满足评估 → 知识应用 → BO（不重复已执行阶段）"
            >
              继续准备科学知识
            </button>
          </>
        )}
        {softwareMode === 'demo' && <StatusBadge tone="warn">展示模式（冻结场景）</StatusBadge>}
        <span className="spacer" />
        {analysisComplete && (
          <StatusBadge tone="ok">
            应用结果：{applicationResult.runId}
          </StatusBadge>
        )}
        {workflow.activeRunId && !analysisComplete && (
          <StatusBadge tone="warn">检查点：{workflow.activeRunId}</StatusBadge>
        )}
      </div>

      <ErrorBanner message={runError} />

      {softwareMode === 'research' && (
        <ExecutionStatusTree
          events={workflow.events}
          requirements={applicationResult?.knowledgeState?.requirements ?? []}
        />
      )}

      {statusBar}

      <div className="app-tabs" data-testid="application-tabs">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            className={selectedTab === tab.key ? 'active' : ''}
            onClick={() => syncTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="app-workspace">
        <div className="app-main-column">
          {selectedTab === 'summary' && (
            <SummaryTab result={applicationResult} onNavigate={syncTab} />
          )}
          {selectedTab === 'identification' && (
            <IdentificationWorkspace
              readonly={softwareMode === 'demo'}
              rankingOverride={applicationResult?.processLearning.controllableRanking ?? null}
            />
          )}
          {selectedTab === 'modeling' && (
            <ModelingWorkspace
              readonly={softwareMode === 'demo'}
              trainingOverride={modelingTrainingOverride(applicationResult)}
            />
          )}
          {selectedTab === 'optimization' && (
            <OptimizationWorkspace
              readonly={softwareMode === 'demo'}
              governedPriorOverride={
                (applicationResult?.scientificBasis.governedPrior as Record<string, unknown> | null) ?? null
              }
              comparisonOverride={
                applicationResult
                  ? {
                      vanilla: applicationResult.optimization.vanilla as never,
                      evidence_assisted: applicationResult.optimization.evidenceAssisted as never,
                      prior_applied_evidence: applicationResult.optimization.priorAppliedEvidence,
                    }
                  : null
              }
            />
          )}
        </div>
        {selectedTab === 'summary' && (
          <ScientificBasisSidebar result={applicationResult} />
        )}
      </div>
    </div>
  )
}

/** 执行状态树：从真实 WorkflowEvent 渲染 8 阶段 checkpoint（✓ 完成 / ● 进行中 / ○ 未开始），
 *  prepare_knowledge 子操作（已有知识检查/文献检索等）与 KnowledgeRequirement 逐条展开。 */
function ExecutionStatusTree({
  events,
  requirements,
}: {
  events: import('../api/types').WorkflowEvent[]
  requirements: { requirement_id: string; question: string }[]
}) {
  const stageState = (stage: string): 'done' | 'active' | 'pending' => {
    const completed = events.some((event) => event.type === 'STAGE_COMPLETED' && event.stage === stage)
    const started = events.some((event) => event.type === 'STAGE_STARTED' && event.stage === stage)
    if (completed) return 'done'
    if (started) return 'active'
    return 'pending'
  }
  const prepareSubs = events.filter(
    (event) => event.stage === 'prepare_knowledge' && (event.type === 'TOOL_STARTED' || event.type === 'TOOL_COMPLETED'),
  )
  const prepareActive = stageState('prepare_knowledge')

  const stageRows: { key: string; label: string }[] = [
    { key: 'prepare_task', label: '任务准备' },
    { key: 'assess_data', label: '数据评估' },
    { key: 'baseline_learning', label: '基线学习' },
    { key: 'analyze_knowledge_gaps', label: '知识缺口分析' },
    { key: 'prepare_knowledge', label: '科学知识准备' },
    { key: 'satisfy_requirements', label: '知识满足度评估' },
    { key: 'apply_knowledge', label: '知识应用' },
    { key: 'optimization', label: '工艺优化' },
  ]

  return (
    <div className="execution-tree" data-testid="execution-tree">
      {stageRows.map((row) => {
        const state = stageState(row.key)
        return (
          <div key={row.key} className={`et-row et-${state}`}>
            <span className="et-mark">{state === 'done' ? '✓' : state === 'active' ? '●' : '○'}</span>
            <span className="et-label">{row.label}</span>
            {row.key === 'analyze_knowledge_gaps' && state === 'done' && requirements.length > 0 && (
              <span className="muted">发现 {requirements.length} 个 Knowledge Requirements</span>
            )}
            {row.key === 'prepare_knowledge' && prepareSubs.length > 0 && (
              <div className="et-children">
                {prepareSubs.map((event) => (
                  <div key={event.event_id} className="et-child">
                    <span className="et-mark">{event.type === 'TOOL_COMPLETED' ? '✓' : '●'}</span>
                    {event.summary}
                  </div>
                ))}
                {prepareActive === 'active' && (
                  <div className="et-child muted">Evidence forming...</div>
                )}
              </div>
            )}
            {row.key === 'analyze_knowledge_gaps' && state === 'done' && requirements.length > 0 && (
              <div className="et-children">
                {requirements.map((requirement) => (
                  <div key={requirement.requirement_id} className="et-child">
                    <span className="et-mark">├</span>
                    {requirement.requirement_id} {requirement.question}
                  </div>
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

/** 从 ApplicationRun 结果构造建模 Tab 可消费的 training 视图（模型比较 + 选中模型）。 */
function modelingTrainingOverride(
  result: Topic2ApplicationResult | null,
): ModelTrainingResult | null {
  if (!result?.processLearning?.modelComparison) return null
  const comparison = result.processLearning.modelComparison
  if (typeof comparison !== 'object' || Array.isArray(comparison)) return null
  const metrics = comparison as Record<string, ModelMetrics>
  const selected = result.processLearning.selectedModel ?? Object.keys(metrics)[0] ?? null
  if (!selected || !metrics[selected]) return null
  return {
    run_id: result.processLearning.trainingRunId ?? `app-run:${result.runId}`,
    model_id: null,
    model_version: '',
    dataset_version: '',
    selected_model: selected,
    validation_metrics: metrics,
    comparison: {
      baseline: { model: selected, ...metrics[selected] },
      optimized: { model: selected, ...metrics[selected] },
      comparison_basis: 'Group-CV (application run)',
      improved: false,
    },
    cv_strategy: 'GroupKFold(parameter_combination_id)',
  }
}

function SummaryTab({
  result,
  onNavigate,
}: {
  result: Topic2ApplicationResult | null
  onNavigate: (tab: ApplicationTab) => void
}) {
  const context = useTaskContextStore((state) => state.context)
  const training = useScienceStore((state) => state.training)
  const dataProfile = useScienceStore((state) => state.dataProfile)
  const target = objectiveToTarget(context.objective)

  if (!result) {
    return (
      <>
        <div className="card">
          <div className="card-title">当前任务</div>
          <ul className="detail-list">
            <li>
              <span className="dl-key">Task Context</span>
              <span className="dl-value mono">
                {context.taskContextId}:v{context.version}
              </span>
            </li>
            <li>
              <span className="dl-key">材料 / 激光</span>
              <span className="dl-value">
                {context.materialId ?? '—'} / {context.laserType ?? '—'}
              </span>
            </li>
            <li>
              <span className="dl-key">工艺 / 目标</span>
              <span className="dl-value">
                {context.processType ? processTaskLabel(context.processType) : '—'} /{' '}
                {target ?? '—'} {target === 'depth_um' ? '↑' : target === 'roughness_um' ? '↓' : ''}
              </span>
            </li>
            <li>
              <span className="dl-key">数据</span>
              <span className="dl-value">
                {dataProfile
                  ? dataProfile.n_samples > 0
                    ? `${dataProfile.n_samples} 样本 / ${dataProfile.n_unique_designs} 独立设计`
                    : '当前组合无实验数据（请到任务与数据页更换组合）'
                  : '—'}
              </span>
            </li>
            <li>
              <span className="dl-key">选中模型</span>
              <span className="dl-value">{training?.selected_model ?? '未训练'}</span>
            </li>
          </ul>
        </div>
        <EmptyState message="运行完整分析后将在此生成综合结果（答辩 / 组会 / Demo 用途）。" />
      </>
    )
  }

  const learning = result.processLearning
  const ranking = learning.controllableRanking ?? []
  const comparisonMetrics = learning.modelComparison as Record<string, Record<string, unknown>> | undefined
  const selectedMetrics = comparisonMetrics?.[learning.selectedModel ?? ''] ?? null
  const assisted = result.optimization.evidenceAssisted
  const prior = result.optimization.priorAppliedEvidence
  const parameters = Object.keys(assisted?.recommended_parameters ?? {})

  return (
    <>
      <div className="card">
        <div className="card-title">任务 → 参数辨识 → 工艺建模 → 工艺优化</div>
        <div className="grid grid-2">
          <div className="stat-card">
            <div className="stat-label">材料</div>
            <div className="stat-value" style={{ fontSize: 16 }}>
              {result.targetTask.material}
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-label">激光 / 工艺</div>
            <div className="stat-value" style={{ fontSize: 16 }}>
              {result.targetTask.laserType} · {result.targetTask.geometry}
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-label">目标</div>
            <div className="stat-value" style={{ fontSize: 16 }}>
              {result.targetTask.target} {result.targetTask.target === 'depth_um' ? '↑' : '↓'}
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-label">样本</div>
            <div className="stat-value" style={{ fontSize: 16 }}>
              {result.targetTask.sampleCount ?? '—'}
            </div>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-title">参数辨识</div>
        <div className="row" style={{ marginBottom: 8 }}>
          <StatusBadge tone="info">Feature View: {learning.selectedFeatureView}</StatusBadge>
        </div>
        {ranking.length > 0 ? (
          <ol className="top-params">
            {ranking.slice(0, 5).map((item, index) => (
              <li key={item.feature}>
                <b>{index + 1}. {parameterLabel(item.feature)}</b>{' '}
                <span className="mono">{formatNumber(item.importance, 4)}</span>{' '}
                <span className="badge neutral">{item.effect_direction}</span>
              </li>
            ))}
          </ol>
        ) : (
          <EmptyState message="无可控参数排名（结果来自后端辨识 Run）。" />
        )}
        <button className="btn small" onClick={() => onNavigate('identification')}>
          查看完整辨识结果
        </button>
      </div>

      <div className="card">
        <div className="card-title">工艺建模</div>
        <div className="row" style={{ marginBottom: 8 }}>
          <StatusBadge tone="ok">选中模型：{learning.selectedModel ?? '—'}</StatusBadge>
          {learning.cvFolds && <StatusBadge tone="neutral">CV 折数 {learning.cvFolds}</StatusBadge>}
        </div>
        {selectedMetrics && (
          <table className="table">
            <thead>
              <tr>
                <th>模型</th>
                <th>RMSE</th>
                <th>MAE</th>
                <th>R²</th>
                <th>不确定性</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(comparisonMetrics ?? {}).map(([name, metrics]) => (
                <tr key={name}>
                  <td>
                    {name}
                    {name === learning.selectedModel && <span className="badge ok">选中</span>}
                  </td>
                  <td className="mono">{formatNumber(metrics.RMSE as number)}</td>
                  <td className="mono">{formatNumber(metrics.MAE as number)}</td>
                  <td className="mono">{formatNumber(metrics.R2 as number)}</td>
                  <td>{metrics.uncertainty_available ? '✓' : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <button className="btn small" onClick={() => onNavigate('modeling')}>
          查看模型比较
        </button>
      </div>

      <div className="card">
        <div className="card-title">工艺优化 · 推荐下一实验点</div>
        <table className="table">
          <thead>
            <tr>
              <th>工艺参数</th>
              <th>推荐值（Assisted）</th>
            </tr>
          </thead>
          <tbody>
            {parameters.map((name) => (
              <tr key={name}>
                <td>{parameterLabel(name)}</td>
                <td className="mono">{formatNumber(assisted?.recommended_parameters?.[name])}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="row" style={{ marginTop: 8 }}>
          <StatusBadge tone="neutral">
            E2P Prior:{' '}
            {prior?.assisted_search_prior_applied ? 'APPLIED' : 'NOT APPLIED'}
          </StatusBadge>
          <StatusBadge tone="neutral">
            CFA: {result.cfa.calibrationStatus === 'NOT_YET_CALIBRATED' ? 'AUDIT ONLY' : result.cfa.calibrationStatus}
          </StatusBadge>
          <StatusBadge tone="neutral">
            Prediction {formatNumber((assisted?.prediction as { mean?: number })?.mean)} ±{' '}
            {formatNumber((assisted?.prediction as { std?: number })?.std)}
            {typeof (assisted?.prediction as { mean?: number })?.mean === 'number' &&
              (assisted?.prediction as { mean?: number }).mean! < 0 && (
                <span className="muted" style={{ fontSize: 11 }}>
                  （高斯过程外推预测，可能低于物理下限）
                </span>
              )}
          </StatusBadge>
        </div>
        <button className="btn small" onClick={() => onNavigate('optimization')}>
          查看优化依据
        </button>
      </div>
    </>
  )
}

function ScientificBasisSidebar({ result }: { result: Topic2ApplicationResult | null }) {
  if (!result) {
    return (
      <aside className="scientific-basis">
        <div className="card">
          <div className="card-title">Scientific Basis</div>
          <div className="empty-state">运行完整分析后展示。</div>
        </div>
      </aside>
    )
  }
  const basis = result.scientificBasis
  const facets = result.cfa.facetSummary ?? {}
  return (
    <aside className="scientific-basis">
      <div className="card">
        <div className="card-title">Scientific Basis</div>
        <ul className="detail-list">
          <li>
            <span className="dl-key">文献</span>
            <span className="dl-value">{basis.paperCount ?? '—'} papers</span>
          </li>
          <li>
            <span className="dl-key">Evidence Claims</span>
            <span className="dl-value">
              {basis.governedEvidenceCount ?? 0} / {basis.evidenceCount ?? 0} governed
            </span>
          </li>
          <li>
            <span className="dl-key">CFA</span>
            <span className="dl-value">
              <StatusBadge tone="neutral">{result.cfa.calibrationStatus}</StatusBadge>
            </span>
          </li>
          {Object.entries(facets).map(([facet, status]) => (
            <li key={facet}>
              <span className="dl-key">{facet}</span>
              <span className="dl-value">
                <StatusBadge tone={scientificTone(status) as StatusTone}>{status}</StatusBadge>
              </span>
            </li>
          ))}
          <li>
            <span className="dl-key">Governed Prior</span>
            <span className="dl-value">
              <StatusBadge tone={(basis.governedEvidenceCount ?? 0) > 0 ? 'ok' : 'neutral'}>
                {(basis.governedEvidenceCount ?? 0) > 0 ? 'VERIFIED' : 'N/A'}
              </StatusBadge>
            </span>
          </li>
        </ul>
        <Link className="btn small" to="/evidence">
          查看完整科学证据
        </Link>
      </div>
    </aside>
  )
}
