/** IntelligentProcessApplication (UI-2): 工艺智能应用核心页面。
 *  三个最终应用结果：参数辨识 → 工艺建模 → 工艺优化；科学基础设施（Physics /
 *  Literature / Evidence / CFA / Agent）作为支撑层出现，不再割裂成主导航功能。 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { applicationGateway, continueRunInPlace } from '../api/application'
import { topic2Api } from '../api/topic2'
import type { ModelMetrics, ModelTrainingResult, Topic2ApplicationResult } from '../api/types'
import { friendlyApiError } from '../lib/errors'
import { ErrorBanner, EmptyState } from '../components/Banners'
import { StatusBadge } from '../components/StatusBadge'
import { IdentificationWorkspace } from '../components/learning/IdentificationWorkspace'
import { ModelingWorkspace } from '../components/learning/ModelingWorkspace'
import { OptimizationWorkspace } from '../components/optimization/OptimizationWorkspace'
import {
  PhysicsToPlanningWorkspace,
  type PhysicsToPlanningView,
} from '../components/physics/PhysicsToPlanningWorkspace'
import { scientificLabel, scientificTone, type StatusTone } from '../lib/status'
import { formatNumber } from '../lib/format'
import { objectiveToTarget, processTaskLabel } from '../lib/canonical'
import { taskContextToScope } from '../lib/scope'
import { useModeStore } from '../stores/mode'
import { useApplicationStore, type ApplicationTab } from '../stores/application'
import { useScienceStore } from '../stores/science'
import { useTaskContextStore } from '../stores/taskContext'
import { useWorkflowStore } from '../stores/workflow'

const TABS: { key: ApplicationTab; label: string }[] = [
  { key: 'summary', label: '综合结果' },
  { key: 'capability', label: '任务 / Capability' },
  { key: 'knowledge', label: '科学知识' },
  { key: 'calibration', label: '物理标定' },
  { key: 'simulation', label: '形貌仿真' },
  { key: 'planning', label: '路径规划' },
  { key: 'identification', label: '诊断 · 参数辨识' },
  { key: 'modeling', label: '诊断 · 统计建模' },
  { key: 'optimization', label: '诊断 · 旧 BO' },
]

export const APPLICATION_CHECKPOINTS = {
  capability: ['prepare_task', 'assess_capability'],
  knowledgeRequirements: [
    'assess_data',
    'baseline_learning',
    'analyze_knowledge_requirements',
  ],
  knowledgePreparation: ['prepare_knowledge', 'satisfy_requirements'],
  physicsCalibration: ['calibrate_physics', 'establish_process_model'],
  processPlanning: ['plan_process'],
} as const

function tabFromParam(param: string | null): ApplicationTab {
  if (TABS.some((tab) => tab.key === param)) {
    return param as ApplicationTab
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
  const activeApplicationRunId = useApplicationStore((state) => state.activeApplicationRunId)
  const selectedTab = tabFromParam(searchParams.get('tab'))
  const workflow = useWorkflowStore()

  const [applicationResult, setApplicationResult] = useState<Topic2ApplicationResult | null>(null)
  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)
  const [developerMode, setDeveloperMode] = useState(false)
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

  /** Canonical checkpoint：Capability 和 KnowledgeRequirement 均来自后端 stage。 */
  const runToCapability = useCallback(() => {
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
      applicationGateway
        .runFullApplication({
          mode: 'research',
          task_spec: taskSpec,
          stages: [...APPLICATION_CHECKPOINTS.capability],
          random_seed: 42,
          client_request_id: crypto.randomUUID(),
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

  const continueStages = useCallback((stages: string[]) => {
    const runId = workflow.activeRunId
    if (!runId) {
      setRunError('请先创建一个 ApplicationRun checkpoint。')
      return
    }
    setRunError(null)
    setRunning(true)
    workflow.resume()
    continueRunInPlace(runId, stages, workflow.lastSequence)
      .then(({ run, events }) => {
        workflow.append(events)
        if (run.result) setApplicationResult(run.result)
        if (run.status === 'completed') workflow.complete()
        setRunRefs({ runId, mode: run.mode })
        setRunning(false)
      })
      .catch((error) => {
        setRunning(false)
        setRunError(friendlyApiError(error))
      })
  }, [workflow, setRunRefs])

  const continueKnowledgeRequirements = useCallback(
    () => continueStages([...APPLICATION_CHECKPOINTS.knowledgeRequirements]),
    [continueStages],
  )
  const continueKnowledgePreparation = useCallback(
    () => continueStages([...APPLICATION_CHECKPOINTS.knowledgePreparation]),
    [continueStages],
  )
  const continuePhysicsCalibration = useCallback(
    () => continueStages([...APPLICATION_CHECKPOINTS.physicsCalibration]),
    [continueStages],
  )
  const continueProcessPlanning = useCallback(
    () => continueStages([...APPLICATION_CHECKPOINTS.processPlanning]),
    [continueStages],
  )

  const analysisComplete = applicationResult !== null

  const physicsResult = applicationResult?.physicsToPlanning
  const stageCompleted = (stage: string) =>
    workflow.events.some((event) => event.type === 'STAGE_COMPLETED' && event.stage === stage)
  const statusBar = (
    <div className="app-status-bar">
      <StatusBadge tone={physicsResult?.capability ? 'ok' : 'neutral'}>1 Capability</StatusBadge>
      <span className="status-link">───</span>
      <StatusBadge tone={physicsResult?.priorObjectSet ? 'ok' : 'neutral'}>2 Knowledge / Prior</StatusBadge>
      <span className="status-link">───</span>
      <StatusBadge tone={physicsResult?.calibrationResult ? 'ok' : 'neutral'}>3 Calibration</StatusBadge>
      <span className="status-link">───</span>
      <StatusBadge tone={physicsResult?.morphologySimulation ? 'ok' : 'neutral'}>4 Simulation</StatusBadge>
      <span className="status-link">───</span>
      <StatusBadge tone={physicsResult?.toolpathPlan ? 'ok' : 'neutral'}>5 ToolpathPlan</StatusBadge>
    </div>
  )

  return (
    <div className="application-page">
      <h1>工艺智能应用</h1>
      <p className="card-sub">
        主链围绕目标形貌组织：Task → Capability → Knowledge → Calibration → LocalRemovalModel
        → Stateful Simulation → Recommended ToolpathPlan。所有 UI 数值均直接来自 ApplicationRun artifacts。
      </p>

      <div className="row" style={{ marginBottom: 10, alignItems: 'center' }}>
        <button
          className="btn primary"
          onClick={runFullAnalysis}
          disabled={running}
          title="一键完整分析：Task → Capability → Knowledge → Calibration → Simulation → ToolpathPlan"
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
              onClick={runToCapability}
              disabled={running}
              title="Checkpoint：Task → Scientific Capability"
            >
              运行到 Capability
            </button>
            <button
              className="btn"
              onClick={continueKnowledgeRequirements}
              disabled={running || !stageCompleted('assess_capability')}
              title="Checkpoint：Capability → 数据/基线 → Knowledge Requirements"
            >
              继续到 Knowledge Requirements
            </button>
            <button
              className="btn"
              onClick={continueKnowledgePreparation}
              disabled={running || !stageCompleted('analyze_knowledge_requirements')}
              title="继续同一 ApplicationRun：知识检索与满足评估（不重复已执行阶段）"
            >
              继续准备科学知识
            </button>
            <button
              className="btn"
              onClick={continuePhysicsCalibration}
              disabled={running || !stageCompleted('satisfy_requirements')}
              title="继续同一 ApplicationRun：typed Prior → Calibration → LocalRemovalModel"
            >
              继续 Physics Calibration
            </button>
            <button
              className="btn"
              onClick={continueProcessPlanning}
              disabled={running || !stageCompleted('establish_process_model')}
              title="继续同一 ApplicationRun：Simulator → ToolpathPlan"
            >
              继续 Process Planning
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
        <label className="dev-mode-toggle" style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
          <input type="checkbox" checked={developerMode} onChange={(event) => setDeveloperMode(event.target.checked)} />
          Developer Mode
        </label>
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
          {(['capability', 'knowledge', 'calibration', 'simulation', 'planning'] as ApplicationTab[]).includes(selectedTab) && (
            <PhysicsToPlanningWorkspace
              runId={workflow.activeRunId ?? activeApplicationRunId}
              view={selectedTab as PhysicsToPlanningView}
              developerMode={developerMode}
              artifactRevision={workflow.events.filter((event) => event.type === 'STAGE_COMPLETED').length}
            />
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

/** 执行状态树：从真实 WorkflowEvent 渲染 canonical checkpoint（✓ 完成 / ● 进行中 / ○ 未开始），
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
    { key: 'assess_capability', label: '科学能力预检' },
    { key: 'assess_data', label: '数据评估' },
    { key: 'baseline_learning', label: '基线学习' },
    { key: 'analyze_knowledge_requirements', label: '计算缺口 → 知识需求' },
    { key: 'prepare_knowledge', label: '科学知识准备' },
    { key: 'satisfy_requirements', label: '知识满足度评估' },
    { key: 'calibrate_physics', label: '物理标定 / 可辨识性' },
    { key: 'establish_process_model', label: 'LocalRemovalModel' },
    { key: 'plan_process', label: '仿真驱动路径规划' },
  ]

  return (
    <div className="execution-tree" data-testid="execution-tree">
      {stageRows.map((row) => {
        const state = stageState(row.key)
        return (
          <div key={row.key} className={`et-row et-${state}`}>
            <span className="et-mark">{state === 'done' ? '✓' : state === 'active' ? '●' : '○'}</span>
            <span className="et-label">{row.label}</span>
            {row.key === 'analyze_knowledge_requirements' && state === 'done' && requirements.length > 0 && (
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
            {row.key === 'analyze_knowledge_requirements' && state === 'done' && requirements.length > 0 && (
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

  const physics = result.physicsToPlanning
  const capability = physics?.capability
  const calibration = physics?.calibrationResult
  const simulation = physics?.morphologySimulation
  const plan = physics?.toolpathPlan

  return (
    <>
      <div className="card">
        <div className="card-title">Task → Physics → Planning</div>
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
        <div className="card-title">Scientific Capability</div>
        <div className="row" style={{ marginBottom: 8 }}>
          <StatusBadge tone={scientificTone(capability?.status)}>{scientificLabel(capability?.status)}</StatusBadge>
          <StatusBadge tone={capability?.simulation_supported ? 'ok' : 'neutral'}>
            Simulator {capability?.simulation_supported ? 'SUPPORTED' : 'UNKNOWN'}
          </StatusBadge>
          <span className="badge neutral">{capability?.interaction_topology ?? 'UNKNOWN'}</span>
        </div>
        <div className="muted">
          已有输入 {capability?.available.length ?? 0} · 缺失输入 {capability?.missing.length ?? 0} ·
          Knowledge Requirements {result.knowledgeState?.requirements?.length ?? 0}
        </div>
        <button className="btn small" onClick={() => onNavigate('capability')}>
          查看 Capability 与知识需求
        </button>
      </div>

      <div className="card">
        <div className="card-title">Physics Calibration</div>
        <div className="row" style={{ marginBottom: 8 }}>
          <StatusBadge tone={scientificTone(calibration?.status)}>{scientificLabel(calibration?.status)}</StatusBadge>
          <span className="badge neutral">Parameters {calibration?.parameters.length ?? 0}</span>
          <span className="badge neutral">LocalRemovalModel {physics?.localRemovalModel?.mode ?? '—'}</span>
        </div>
        {calibration && (
          <table className="table">
            <thead><tr><th>Parameter</th><th>Estimate</th><th>Identifiability</th><th>Semantics</th></tr></thead>
            <tbody>
              {calibration.parameters.slice(0, 5).map((parameter) => (
                <tr key={parameter.parameter}>
                  <td className="mono">{parameter.parameter}</td>
                  <td className="mono">{parameter.estimate == null ? '—' : `${formatNumber(parameter.estimate)} ${parameter.unit}`}</td>
                  <td><StatusBadge tone={scientificTone(parameter.identifiability)}>{scientificLabel(parameter.identifiability)}</StatusBadge></td>
                  <td>{parameter.parameter_semantics}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <button className="btn small" onClick={() => onNavigate('calibration')}>
          查看 Prior / Fit / Identifiability
        </button>
      </div>

      <div className="card planning-hero">
        <div className="card-title">Recommended ToolpathPlan</div>
        <div className="row" style={{ marginTop: 8 }}>
          <StatusBadge tone={scientificTone(plan?.status)}>{scientificLabel(plan?.status)}</StatusBadge>
          <span className="badge info">{plan?.path_family ?? '尚未生成'}</span>
          <span className="badge neutral">Fidelity {simulation?.fidelity ?? '—'}</span>
          <span className="badge neutral">Expected RMSE {formatNumber(plan?.predicted_metrics.morphology_rmse_um)} µm</span>
          <span className="badge neutral">Machining time {formatNumber(plan?.predicted_metrics.machining_time_s)} s</span>
        </div>
        <button className="btn small" onClick={() => onNavigate('simulation')}>查看预测形貌</button>{' '}
        <button className="btn small" onClick={() => onNavigate('planning')}>
          查看路径与仿真依据
        </button>
      </div>

      <div className="card">
        <div className="card-title">兼容诊断（非最终规划锚点）</div>
        <div className="muted">
          RAW / PHYSICS / HYBRID 与旧 BO 比较仅保留为诊断；最终可执行建议以 ToolpathPlan artifact 为准。
        </div>
        <button className="btn small" onClick={() => onNavigate('identification')}>参数辨识诊断</button>{' '}
        <button className="btn small" onClick={() => onNavigate('modeling')}>统计模型诊断</button>{' '}
        <button className="btn small" onClick={() => onNavigate('optimization')}>旧 BO 诊断</button>
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
