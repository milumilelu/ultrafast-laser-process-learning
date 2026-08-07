/** 科学分析 Run Trace：task → job → corpus → knowledge → pipeline 统计（审阅 §9）。
 *  回答"为什么系统推荐这个参数"的贯穿追溯。 */

import { useEffect, useState } from 'react'

import { agentApi } from '../api/agent'
import { formatTimestamp } from '../lib/format'
import { EmptyState } from './Banners'

interface AnalysisRun {
  run_id: string
  task_id: string | null
  job_id: string | null
  corpus_pack_id: string | null
  knowledge_pack_id: string | null
  pipeline_stats: Record<string, unknown>
  status: string
  created_at: string
}

export function ScientificRunTraceSection() {
  const [runs, setRuns] = useState<AnalysisRun[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    agentApi
      .listAnalysisRuns()
      .then((result) => setRuns(result.items))
      .catch((err) => setError(err instanceof Error ? err.message : '读取科学分析记录失败'))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="card-title">科学分析运行记录（RAG → LLM → E2P 贯穿追溯）</div>
      {error && <div className="error-text">{error}</div>}
      {loading ? (
        <div className="empty-state">
          <span className="spinner" /> 读取中…
        </div>
      ) : runs.length === 0 ? (
        <EmptyState message="暂无科学分析记录。在工艺任务页运行「科学检索与精读」后生成。" />
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Run</th>
              <th>任务</th>
              <th>Knowledge Pack</th>
              <th>精读/综合/批判</th>
              <th>覆盖</th>
              <th>时间</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => {
              const stats = run.pipeline_stats as {
                completed?: number
                reduce_candidates?: number
                critic_issues?: number
                coverage_ratio?: number
              }
              return (
                <tr key={run.run_id}>
                  <td className="mono">{run.run_id}</td>
                  <td className="mono">{run.task_id ?? '—'}</td>
                  <td className="mono" title={run.knowledge_pack_id ?? ''}>
                    {(run.knowledge_pack_id ?? '—').slice(0, 18)}
                  </td>
                  <td className="mono">
                    精读 {stats.completed ?? 0} 篇 · 候选 {stats.reduce_candidates ?? 0} · 批判问题 {stats.critic_issues ?? 0}
                  </td>
                  <td className="mono">
                    {stats.coverage_ratio != null ? `${Math.round(stats.coverage_ratio * 100)}%` : '—'}
                  </td>
                  <td>{formatTimestamp(run.created_at)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}
