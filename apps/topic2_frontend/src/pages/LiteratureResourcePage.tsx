/** LiteratureResourcePage (/resources/literature): 文献库资源页。
 *  展示科学分析 Run 轨迹与证据候选来源；PDF 精读由科学后端完成。 */

import { useEffect, useState } from 'react'

import { agentApi } from '../api/agent'
import { EmptyState } from '../components/Banners'
import { StatusBadge } from '../components/StatusBadge'
import { formatTimestamp } from '../lib/format'

interface AnalysisRun {
  run_id: string
  task_id: string | null
  job_id: string | null
  corpus_pack_id: string | null
  knowledge_pack_id: string | null
  status: string
  created_at: string
}

export function LiteratureResourcePage() {
  const [runs, setRuns] = useState<AnalysisRun[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    agentApi
      .listAnalysisRuns()
      .then((result) => {
        if (!cancelled) setRuns(result.items)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : '读取文献库失败')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div>
      <h1>文献库</h1>
      <p className="card-sub">
        文献 PDF → ScientificDocument → CandidateLedger → EvidenceIR 的科学信息读取由科学后端完成；
        本页展示可追溯的分析 Run 与文献来源。
      </p>
      <StatusBadge tone="info">固定 pilot 文献集：5 papers（Demo Scenario 01）</StatusBadge>
      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-title">科学分析 Run</div>
        {loading ? (
          <div className="empty-state">
            <span className="spinner" /> 读取中…
          </div>
        ) : error ? (
          <EmptyState message={`${error}（Agent 离线时该资源页降级，不影响科学主链）`} />
        ) : runs.length === 0 ? (
          <EmptyState message="暂无科学分析 Run。在科学知识页或 Agent 对话中触发检索后自动生成。" />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Run ID</th>
                <th>Task</th>
                <th>Job</th>
                <th>状态</th>
                <th>时间</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.run_id}>
                  <td className="mono">{run.run_id}</td>
                  <td className="mono">{run.task_id ?? '—'}</td>
                  <td className="mono">{run.job_id ?? '—'}</td>
                  <td>
                    <StatusBadge tone={run.status === 'completed' ? 'ok' : run.status === 'failed' ? 'err' : 'warn'}>
                      {run.status}
                    </StatusBadge>
                  </td>
                  <td>{formatTimestamp(run.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
