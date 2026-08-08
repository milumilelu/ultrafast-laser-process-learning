/** ScientificAnalysisPanel：工艺任务分析独立栏。
 *  单开一栏展示完整执行流程（排队→检索→精读→验证→覆盖→综合→批判→完成）、
 *  实时进度与 LLM 推理摘要（known / candidates / unknown / conflicts），
 *  轮询错误直接显示在栏内，不再藏在 Agent Drawer 中。 */

import { Fragment, useEffect, useState } from 'react'

import { agentApi } from '../api/agent'
import { candidatesToEvidence } from '../lib/candidatesToEvidence'
import { useScienceStore } from '../stores/science'

export const ANALYSIS_STAGES = [
  { key: 'queued', label: '排队' },
  { key: 'retrieving', label: 'RAG 检索' },
  { key: 'mapping', label: 'LLM 精读' },
  { key: 'validating', label: '确定性验证' },
  { key: 'coverage', label: '覆盖检查' },
  { key: 'reducing', label: '全局综合' },
  { key: 'criticizing', label: '关键批判' },
  { key: 'completed', label: '完成' },
]

const STAGE_ORDER = ANALYSIS_STAGES.map((stage) => stage.key)

interface MappingEntry {
  title?: string
  items?: number
  types?: string[]
  gaps?: number
  status?: string
  cached?: boolean
  paper_id?: string | null
}

interface KnowledgeCandidate {
  candidate_id: string
  type: string
  name?: string | null
  parameter?: string | null
  target?: string | null
  relation?: string | null
  value?: number | null
  lower?: number | null
  upper?: number | null
  unit?: string | null
  expression?: string | null
  variables?: Record<string, string>
  assumptions?: string[]
  property?: string | null
  conditions?: Record<string, unknown>
  semantic_role?: string
  supporting_sources?: {
    paper_id?: string | null
    page?: number | null
    chunk_ids?: string[]
    knowledge_id?: string | null
  }[]
  extraction_notes?: string[]
  llm_extraction?: boolean
  confidence?: number | null
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
  const [pollingError, setPollingError] = useState<string | null>(null)

  useEffect(() => {
    if (!analysisJob || !analysisJobPolling) return
    let cancelled = false
    let failures = 0
    const poll = async () => {
      try {
        const job = await agentApi.getAnalysisJob(analysisJob.jobId)
        if (cancelled) return
        failures = 0
        setPollingError(null)
        const finished = job.status === 'completed' || job.status === 'failed'
        setAnalysisJob(
          {
            jobId: job.analysis_run_id,
            status: job.status,
            stage: job.stage,
            progress: job.progress,
            detail: job.detail,
            error: job.error,
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
        if (!finished && !cancelled) {
          window.setTimeout(poll, 3000)
        }
      } catch {
        if (cancelled) return
        failures += 1
        if (failures >= 3) {
          setPollingError('分析任务状态查询失败（服务可能已重启）——正在自动重试……')
          failures = 0
          window.setTimeout(poll, 10_000)
          return
        }
        window.setTimeout(poll, 3000)
      }
    }
    void poll()
    return () => {
      cancelled = true
    }
  }, [analysisJob, analysisJobPolling, setAnalysisJob, setScientificPack, setRagEvidence])

  if (!analysisJob) return null

  const status = analysisJob.status
  const stage = analysisJob.stage
  const activeIndex = status === 'completed' ? STAGE_ORDER.length - 1 : Math.max(0, STAGE_ORDER.indexOf(stage))
  const isActive = status !== 'completed' && status !== 'failed'
  const progress = analysisJob.progress as {
    current?: number
    total?: number
    detail?: string
    source_list?: { paper_id: string | null; title: string; sections: number }[]
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
  const known = (knowledge?.known ?? []) as { claim: string; sources?: { paper_id?: string | null }[] }[]
  const unknown = (knowledge?.unknown ?? []) as { topic: string; description?: string }[]
  const conflicts = (knowledge?.conflicts ?? []) as { topic: string; description?: string }[]

  return (
    <div className="card" data-testid="scientific-analysis-panel">
      <div className="card-title">
        工艺任务分析（RAG → LLM → E2P）
        <span className="id-chip muted">{analysisJob.jobId}</span>
        {knowledge && (
          <span className="badge ok">
            已完成 · {scientificPack?.llmModel || String(knowledge.llm_model ?? 'unknown')}
          </span>
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
            <span className="mono muted">
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
          分析失败：{String(analysisJob.error ?? '未知错误')}
        </div>
      )}
      {pollingError && (
        <div className="warn-banner" style={{ marginTop: 8 }}>
          {pollingError}
        </div>
      )}
      {analysisJob.error && status !== 'failed' && (
        <div className="warn-banner" style={{ marginTop: 8 }}>{analysisJob.error}</div>
      )}

      {stage === 'retrieving' && sourceList.length > 0 && (
        <div className="analysis-sub" style={{ marginTop: 8 }}>
          <div className="card-sub">检索到 {sourceList.length} 篇语料：</div>
          <ul className="analysis-list">
            {sourceList.map((source, index) => (
              <li key={`src-${index}`}>
                <code>{source.paper_id?.slice(-8) ?? '?'}</code> {(source.title || '(无标题)').slice(0, 70)}
                <span className="muted"> · {source.sections} 段</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {mappingEntries.length > 0 && (
        <div className="analysis-sub" style={{ marginTop: 8 }}>
          <div className="card-sub">
            LLM 精读摘要（{mappingEntries.length}/{mappingEntries.length} 篇）
          </div>
          <ul className="analysis-list">
            {mappingEntries.map((entry, index) => (
              <li key={`map-${index}`}>
                <b>{(entry.title ?? '?').slice(0, 55)}</b>
                <span className={entry.status === 'failed' ? 'error-text' : ''}>
                  {entry.status === 'failed'
                    ? ' 分析失败'
                    : ` 提取 ${entry.items ?? 0} 条`}
                  {Array.isArray(entry.types) && entry.types.length > 0 && (
                    <span className="muted"> [{entry.types.slice(0, 5).join(', ')}]</span>
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
            <span className="badge info">Known {String(reduceEntry.known)}</span>
          )}
        </div>
      )}

      {knowledge && (
        <div className="analysis-result" style={{ marginTop: 10 }}>
          <div className="analysis-sub">
            <div className="card-sub">ScientificKnowledgePack 元信息</div>
            <ul className="detail-list">
              <li>
                <span className="dl-key">knowledge_pack_id</span>
                <span className="dl-value mono">{String(knowledge.knowledge_pack_id ?? '—')}</span>
              </li>
              <li>
                <span className="dl-key">source_corpus_pack_id</span>
                <span className="dl-value mono">{String(knowledge.source_corpus_pack_id ?? '—')}</span>
              </li>
              <li>
                <span className="dl-key">llm_model</span>
                <span className="dl-value mono">{String(knowledge.llm_model ?? '—')}</span>
              </li>
              <li>
                <span className="dl-key">prompt_version</span>
                <span className="dl-value mono">{String(knowledge.prompt_version ?? '—')}</span>
              </li>
              <li>
                <span className="dl-key">created_at</span>
                <span className="dl-value mono">{String(knowledge.created_at ?? '—')}</span>
              </li>
              <li>
                <span className="dl-key">task_scope</span>
                <span className="dl-value mono">
                  {knowledge.task_scope ? JSON.stringify(knowledge.task_scope) : '—'}
                </span>
              </li>
            </ul>
          </div>

          {known.length > 0 && (
            <div className="analysis-sub">
              <div className="card-sub">LLM 推理摘要 · 已知事实（Known · {known.length}）</div>
              <ul className="analysis-list">
                {known.map((item, index) => (
                  <li key={`known-${index}`}>
                    {item.claim}
                    {item.sources && item.sources.length > 0 && (
                      <span className="muted">
                        {' '}
                        [{item.sources.map((s) => s.paper_id?.slice(-8) ?? '?').join(', ')}]
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {candidates.length > 0 && (
            <div className="analysis-sub">
              <div className="card-sub">知识候选（Knowledge Candidates · {candidates.length}，点击行展开全部字段）</div>
              <table className="table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>类型</th>
                    <th>参数 / 名称</th>
                    <th>数值</th>
                    <th>语义角色</th>
                  </tr>
                </thead>
                <tbody>
                  {candidates.map((candidate) => (
                    <Fragment key={candidate.candidate_id}>
                      <tr>
                        <td className="mono">{candidate.candidate_id}</td>
                        <td>{candidate.type}</td>
                        <td>{candidate.parameter ?? candidate.name ?? '—'}</td>
                        <td className="mono">
                          {candidate.value ?? candidate.lower ?? candidate.expression ?? '—'}
                          {candidate.unit ? ` ${candidate.unit}` : ''}
                        </td>
                        <td className="muted">{candidate.semantic_role ?? '—'}</td>
                      </tr>
                      <tr className="candidate-detail">
                        <td colSpan={5}>
                          <details>
                            <summary>完整字段</summary>
                            <ul className="detail-list">
                              <li>
                                <span className="dl-key">type</span>
                                <span className="dl-value">{candidate.type}</span>
                              </li>
                              <li>
                                <span className="dl-key">name / parameter / target</span>
                                <span className="dl-value mono">
                                  {candidate.name ?? '—'} / {candidate.parameter ?? '—'} / {candidate.target ?? '—'}
                                </span>
                              </li>
                              <li>
                                <span className="dl-key">relation / property</span>
                                <span className="dl-value mono">
                                  {candidate.relation ?? '—'} / {candidate.property ?? '—'}
                                </span>
                              </li>
                              <li>
                                <span className="dl-key">value / range / unit</span>
                                <span className="dl-value mono">
                                  {candidate.value ?? '—'} / [{candidate.lower ?? '—'}, {candidate.upper ?? '—'}] /{' '}
                                  {candidate.unit ?? '—'}
                                </span>
                              </li>
                              <li>
                                <span className="dl-key">expression</span>
                                <span className="dl-value mono">{candidate.expression ?? '—'}</span>
                              </li>
                              <li>
                                <span className="dl-key">variables</span>
                                <span className="dl-value mono">
                                  {candidate.variables && Object.keys(candidate.variables).length > 0
                                    ? JSON.stringify(candidate.variables)
                                    : '—'}
                                </span>
                              </li>
                              <li>
                                <span className="dl-key">conditions</span>
                                <span className="dl-value mono">
                                  {candidate.conditions && Object.keys(candidate.conditions).length > 0
                                    ? JSON.stringify(candidate.conditions)
                                    : '—'}
                                </span>
                              </li>
                              <li>
                                <span className="dl-key">semantic_role</span>
                                <span className="dl-value">{candidate.semantic_role ?? '—'}</span>
                              </li>
                              <li>
                                <span className="dl-key">assumptions</span>
                                <span className="dl-value mono">
                                  {candidate.assumptions && candidate.assumptions.length > 0
                                    ? candidate.assumptions.join('; ')
                                    : '—'}
                                </span>
                              </li>
                              <li>
                                <span className="dl-key">extraction_notes</span>
                                <span className="dl-value mono">
                                  {candidate.extraction_notes && candidate.extraction_notes.length > 0
                                    ? candidate.extraction_notes.join('; ')
                                    : '—'}
                                </span>
                              </li>
                              <li>
                                <span className="dl-key">supporting_sources</span>
                                <span className="dl-value mono">
                                  {candidate.supporting_sources && candidate.supporting_sources.length > 0
                                    ? JSON.stringify(candidate.supporting_sources)
                                    : '—'}
                                </span>
                              </li>
                              <li>
                                <span className="dl-key">llm_extraction / confidence</span>
                                <span className="dl-value mono">
                                  {String(candidate.llm_extraction ?? '—')} / {candidate.confidence ?? '—'}
                                </span>
                              </li>
                            </ul>
                          </details>
                        </td>
                      </tr>
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {unknown.length > 0 && (
            <div className="analysis-sub">
              <div className="card-sub">知识缺口（Unknown · {unknown.length}）</div>
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
              <div className="card-sub">文献冲突（Conflicts · {conflicts.length}）</div>
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

          <div className="analysis-sub">
            <details>
              <summary className="card-sub" style={{ cursor: 'pointer' }}>
                完整 result JSON（ScientificKnowledgePack 原文）
              </summary>
              <pre className="artifact-json mono">{JSON.stringify(knowledge, null, 2)}</pre>
            </details>
          </div>
        </div>
      )}
    </div>
  )
}

function itemLabel(stage: string): string {
  return ANALYSIS_STAGES.find((item) => item.key === stage)?.label ?? stage
}
