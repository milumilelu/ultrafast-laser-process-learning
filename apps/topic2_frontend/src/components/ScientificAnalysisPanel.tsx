/** 工艺任务分析面板：执行流程 stepper + 实时进度 + LLM 结果中文展示。
 *  界面不暴露内部标识符/函数名/原始报错串；轮询由全局单例负责。 */

import { useEffect } from 'react'

import { agentApi } from '../api/agent'
import { candidatesToEvidence } from '../lib/candidatesToEvidence'
import { ensureAnalysisPolling, retryPollingNow } from '../stores/analysisPolling'
import { useScienceStore } from '../stores/science'
import { useTaskContextStore } from '../stores/taskContext'

export const ANALYSIS_STAGES = [
  { key: 'queued', label: '排队' },
  { key: 'retrieving', label: '文献检索' },
  { key: 'mapping', label: '智能精读' },
  { key: 'validating', label: '确定性验证' },
  { key: 'coverage', label: '覆盖检查' },
  { key: 'reducing', label: '全局综合' },
  { key: 'criticizing', label: '关键审查' },
  { key: 'completed', label: '完成' },
]

const STAGE_ORDER = ANALYSIS_STAGES.map((stage) => stage.key)

const TYPE_LABELS: Record<string, string> = {
  parameter_value: '参数取值',
  parameter_range: '参数范围',
  parameter_effect: '参数影响',
  relative_importance: '相对重要性',
  interaction: '交互作用',
  functional_shape: '函数关系',
  material_property: '材料属性',
  optical_property: '光学属性',
  threshold: '阈值',
  formula: '公式',
  mechanism: '机理',
  reported_optimum: '报道最优',
  experimental_condition: '实验条件',
  historical_pattern: '历史规律',
  historical_model: '历史模型',
}

const ROLE_LABELS: Record<string, string> = {
  experimental_condition: '实验条件',
  scanned_range: '扫描范围',
  reported_optimum: '报道最优',
  observed_relation: '观测关系',
  reported_result: '报道结果',
  control_value: '对照值',
  property_constant: '属性常数',
  assumption: '假设',
}

interface MappingEntry {
  title?: string
  items?: number
  types?: string[]
  gaps?: number
  status?: string
  cached?: boolean
}

interface KnowledgeCandidate {
  candidate_id: string
  type: string
  name?: string | null
  parameter?: string | null
  value?: number | null
  lower?: number | null
  upper?: number | null
  unit?: string | null
  expression?: string | null
  semantic_role?: string
}

function typeLabel(type: string): string {
  return TYPE_LABELS[type] ?? type
}

function roleLabel(role: string | null | undefined): string {
  if (!role) return '—'
  return ROLE_LABELS[role] ?? role
}

export function ScientificAnalysisPanel() {
  const {
    analysisJob,
    analysisJobPolling,
    scientificPack,
    setAnalysisJob,
    setScientificPack,
    setRagEvidence,
  } = useScienceStore()
  const taskContextId = useTaskContextStore((state) => state.context.taskContextId)

  // 全局单例轮询：任务页面板与 Agent Drawer 共享同一轮询循环，互不打断
  useEffect(() => {
    if (!analysisJob || !analysisJobPolling) return
    ensureAnalysisPolling(analysisJob.jobId)
  }, [analysisJob?.jobId, analysisJobPolling])

  // 自动恢复最近一次分析（刷新/切页后结果不丢失）
  useEffect(() => {
    if (analysisJob) return
    let cancelled = false
    agentApi
      .listAnalysisRuns()
      .then((result) => {
        if (cancelled) return
        const items = result.items ?? []
        const ownTask = items.find((item) => item.task_id === taskContextId)
        const latest = items.find((item) => item.status === 'completed' && item.job_id)
        const candidate = (ownTask ?? latest) as { job_id?: string | null; status?: string } | undefined
        if (!candidate?.job_id) return undefined
        return agentApi.getAnalysisJob(candidate.job_id)
      })
      .then((job) => {
        if (!job || cancelled) return
        const finished = job.status === 'completed' || job.status === 'failed'
        setAnalysisJob(
          {
            jobId: job.analysis_run_id,
            status: job.status,
            stage: job.stage,
            progress: job.progress,
            detail: job.detail,
            error: job.error,
            lastUpdatedAt: new Date().toISOString(),
            pollAttempts: 0,
            lastPollError: null,
          },
          !finished,
        )
        if (job.status === 'completed' && job.result) {
          const knowledge = job.result as Record<string, unknown>
          setScientificPack({
            corpus: null,
            knowledge,
            validation: null,
            degraded: false,
            llmModel: String(knowledge.llm_model ?? 'unknown'),
          })
          const taskScope = (job.result.task_scope ?? {}) as Record<string, unknown>
          const converted = candidatesToEvidence(knowledge, {
            material: (taskScope.material as string | null) ?? null,
            laser_type: (taskScope.laser_type as string | null) ?? null,
            geometry_type: (taskScope.geometry_type as string | null) ?? null,
            equipment_id: (taskScope.equipment_id as string | null) ?? null,
            target: (taskScope.target as string | null) ?? null,
          })
          if (converted.length > 0) {
            setRagEvidence(converted, {
              retrievedHits: converted.length,
              reviewedHits: converted.length,
              evidenceStatus: 'scientific_analysis',
            })
          }
        }
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskContextId])

  if (!analysisJob) return null

  const status = analysisJob.status
  const stage = analysisJob.stage
  const activeIndex = status === 'completed' ? STAGE_ORDER.length - 1 : Math.max(0, STAGE_ORDER.indexOf(stage))
  const isActive = status !== 'completed' && status !== 'failed'
  const pollAttempts = analysisJob.pollAttempts ?? 0
  const lastUpdatedAt = analysisJob.lastUpdatedAt
  const progress = analysisJob.progress as {
    current?: number
    total?: number
    detail?: string
    source_list?: { title: string; sections: number }[]
  }
  const percent = progress.total && progress.total > 0
    ? Math.min(100, Math.round(((progress.current ?? 0) / progress.total) * 100))
    : null

  const mappingEntries = analysisJob.detail.filter(
    (entry) => entry.stage === 'mapping' && entry.title,
  ) as MappingEntry[]
  const sourceList = progress.source_list ?? []
  const validationEntry = analysisJob.detail.find((entry) => entry.stage === 'validating' && entry.validated != null)
  const reduceEntry = analysisJob.detail.find((entry) => entry.stage === 'reducing' && entry.candidates != null)

  const knowledge = scientificPack?.knowledge as Record<string, unknown> | null
  const candidates = (knowledge?.candidates ?? []) as KnowledgeCandidate[]
  const known = (knowledge?.known ?? []) as { claim: string }[]
  const unknown = (knowledge?.unknown ?? []) as { topic: string; description?: string }[]
  const conflicts = (knowledge?.conflicts ?? []) as { topic: string; description?: string }[]

  return (
    <div className="card" data-testid="scientific-analysis-panel">
      <div className="card-title">
        工艺任务分析
        {knowledge ? (
          <span className="badge ok">已完成</span>
        ) : status === 'failed' ? (
          <span className="badge err">失败</span>
        ) : (
          <span className="badge warn">进行中</span>
        )}
      </div>

      <div className="analysis-stepper" data-testid="analysis-stepper">
        {ANALYSIS_STAGES.map((item, index) => (
          <span
            key={item.key}
            className={`astep ${index < activeIndex ? 'done' : ''} ${index === activeIndex ? 'current' : ''}`}
          >
            {index < activeIndex ? '✓' : index + 1} {item.label}
          </span>
        ))}
      </div>

      {isActive && (
        <div className="row" style={{ alignItems: 'center', margin: '6px 0' }}>
          <span className="spinner" />
          <b>{itemLabel(stage)}</b>
          {percent !== null && (
            <span className="muted">
              {progress.current}/{progress.total}（{percent}%）
            </span>
          )}
          {progress.detail && <span className="muted">{String(progress.detail)}</span>}
        </div>
      )}
      {isActive && percent !== null && (
        <div className="progress-track">
          <div className="progress-fill" style={{ width: `${percent}%` }} />
        </div>
      )}

      {status === 'failed' && (
        <div className="error-banner" style={{ marginTop: 8 }}>
          分析失败：{String(analysisJob.error ?? '未知原因')}
        </div>
      )}

      {isActive && pollAttempts > 0 && (
        <div className="warn-banner" style={{ marginTop: 8 }}>
          <div className="row" style={{ alignItems: 'center', justifyContent: 'space-between' }}>
            <span>
              网络连接暂时中断，正在自动恢复……
              {lastUpdatedAt && (
                <>
                  {' '}最后更新{' '}
                  {new Date(lastUpdatedAt).toLocaleTimeString('zh-CN', { hour12: false })}（{itemLabel(stage)}）
                </>
              )}
            </span>
            <button className="btn small" onClick={() => retryPollingNow(analysisJob.jobId)}>
              立即重试
            </button>
          </div>
        </div>
      )}

      {stage === 'retrieving' && sourceList.length > 0 && (
        <div className="analysis-sub" style={{ marginTop: 8 }}>
          <div className="card-sub">检索到 {sourceList.length} 篇相关文献：</div>
          <ul className="analysis-list">
            {sourceList.map((source, index) => (
              <li key={`src-${index}`}>
                {(source.title || '(无标题)').slice(0, 70)}
                <span className="muted"> · {source.sections} 段</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {mappingEntries.length > 0 && (
        <div className="analysis-sub" style={{ marginTop: 8 }}>
          <div className="card-sub">智能精读摘要（{mappingEntries.length} 篇）</div>
          <ul className="analysis-list">
            {mappingEntries.map((entry, index) => (
              <li key={`map-${index}`}>
                <b>{(entry.title ?? '?').slice(0, 55)}</b>
                <span className={entry.status === 'failed' ? 'error-text' : ''}>
                  {entry.status === 'failed'
                    ? ' 精读失败'
                    : ` 提取 ${entry.items ?? 0} 条`}
                  {Array.isArray(entry.types) && entry.types.length > 0 && (
                    <span className="muted"> [{entry.types.slice(0, 5).map(typeLabel).join('、')}]</span>
                  )}
                  {typeof entry.gaps === 'number' && entry.gaps > 0 && (
                    <span className="muted"> · 缺口 {entry.gaps}</span>
                  )}
                  {entry.cached && <span className="muted"> · 缓存</span>}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {validationEntry && (
        <div className="row" style={{ marginTop: 8 }}>
          <span className="badge ok">验证通过 {String(validationEntry.validated)}</span>
          {validationEntry.rejected != null && (
            <span className="badge warn">拒绝 {String(validationEntry.rejected)}</span>
          )}
        </div>
      )}
      {reduceEntry && (
        <div className="row" style={{ marginTop: 4 }}>
          <span className="badge info">综合候选 {String(reduceEntry.candidates)}</span>
          {reduceEntry.known != null && (
            <span className="badge info">已知事实 {String(reduceEntry.known)}</span>
          )}
        </div>
      )}

      {knowledge && (
        <div className="analysis-result" style={{ marginTop: 10 }}>
          {known.length > 0 && (
            <div className="analysis-sub">
              <div className="card-sub">已知事实（{known.length}）</div>
              <ul className="analysis-list">
                {known.map((item, index) => (
                  <li key={`known-${index}`}>{item.claim}</li>
                ))}
              </ul>
            </div>
          )}

          {candidates.length > 0 && (
            <div className="analysis-sub">
              <div className="card-sub">知识候选（{candidates.length}）</div>
              <table className="table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>类型</th>
                    <th>参数 / 名称</th>
                    <th>数值</th>
                    <th>语义角色</th>
                  </tr>
                </thead>
                <tbody>
                  {candidates.map((candidate, index) => (
                    <tr key={candidate.candidate_id}>
                      <td>{index + 1}</td>
                      <td>{typeLabel(candidate.type)}</td>
                      <td>{candidate.parameter ?? candidate.name ?? '—'}</td>
                      <td>
                        {candidate.value ?? candidate.lower ?? candidate.expression ?? '—'}
                        {candidate.unit ? ` ${candidate.unit}` : ''}
                      </td>
                      <td className="muted">{roleLabel(candidate.semantic_role)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {unknown.length > 0 && (
            <div className="analysis-sub">
              <div className="card-sub">知识缺口（{unknown.length}）</div>
              <ul className="analysis-list">
                {unknown.map((item, index) => (
                  <li key={`unknown-${index}`}>
                    <b>{item.topic}</b>
                    {item.description && <span className="muted"> — {item.description}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {conflicts.length > 0 && (
            <div className="analysis-sub">
              <div className="card-sub">文献冲突（{conflicts.length}）</div>
              <ul className="analysis-list">
                {conflicts.map((item, index) => (
                  <li key={`conflict-${index}`}>
                    <b>{item.topic}</b>
                    {item.description && <span className="muted"> — {item.description}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function itemLabel(stage: string): string {
  return ANALYSIS_STAGES.find((item) => item.key === stage)?.label ?? stage
}
