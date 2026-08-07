/** 运行记录：浏览 Backend 持久化的所有 Run，并查看完整审计清单（Scientific Audit Trail）。 */

import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { topic2Api } from '../api/topic2'
import type { RunRecord, RunSummary } from '../api/types'
import { ErrorBanner, EmptyState } from '../components/Banners'
import { RunTracePanel } from '../components/RunTracePanel'
import { ScientificRunTraceSection } from '../components/ScientificRunTraceSection'
import { formatTimestamp, runTypeLabel } from '../lib/format'
import { usePageContextStore } from '../stores/pageContext'

const RUN_TYPES = ['', 'parameter_identification', 'model_policy', 'model_training', 'optimization']

export function RunsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [runType, setRunType] = useState('')
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [detail, setDetail] = useState<RunRecord | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const setActiveRun = usePageContextStore((state) => state.setActiveRun)
  const setQuickActions = usePageContextStore((state) => state.setQuickActions)

  const openFromQuery = useCallback(
    (runId: string | null) => {
      if (!runId) return
      setDetailLoading(true)
      topic2Api
        .getRun(runId)
        .then((record) => {
          setDetail(record)
          setActiveRun(record.run_id)
        })
        .catch((err) => setError(err instanceof Error ? err.message : '读取运行详情失败'))
        .finally(() => setDetailLoading(false))
    },
    [setActiveRun],
  )

  useEffect(() => {
    openFromQuery(searchParams.get('run'))
  }, [searchParams, openFromQuery])

  useEffect(() => {
    setQuickActions([
      { label: '解释运行记录', prompt: `请解释运行记录页面当前展示的 run（${detail ? `run_id=${detail.run_id}` : '未选中' }）发生了什么，基于真实结果。` },
    ])
    return () => setQuickActions([])
  }, [detail, setQuickActions])

  const loadRuns = useCallback(
    (type: string) => {
      setLoading(true)
      setError(null)
      topic2Api
        .listRuns(type || null)
        .then((result) => setRuns(result.items))
        .catch((err) => setError(err instanceof Error ? err.message : '读取运行记录失败'))
        .finally(() => setLoading(false))
    },
    [],
  )

  useEffect(() => {
    loadRuns(runType)
  }, [runType, loadRuns])

  return (
    <div>
      <h1>运行记录</h1>
      <p className="card-sub">
        所有 Run 均由 Topic2 Backend 持久化（task_context / dataset / model / evidence / optimization
        / agent 全链路可追溯）。
      </p>

      <div className="row" style={{ marginBottom: 16 }}>
        <div className="field" style={{ marginBottom: 0 }}>
          <label>运行类型</label>
          <select
            value={runType}
            onChange={(event) => {
              setRunType(event.target.value)
              setSearchParams({})
            }}
          >
            {RUN_TYPES.map((type) => (
              <option key={type} value={type}>
                {type === '' ? '全部' : runTypeLabel(type)}
              </option>
            ))}
          </select>
        </div>
      </div>

      <ErrorBanner message={error} />

      <ScientificRunTraceSection />

      <div className="card">
        <div className="card-title">运行列表</div>
        {loading ? (
          <div className="empty-state">
            <span className="spinner" /> 读取中…
          </div>
        ) : runs.length === 0 ? (
          <EmptyState message="暂无运行记录。完成参数辨识 / 建模 / 优化后自动生成。" />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Run ID</th>
                <th>类型</th>
                <th>任务</th>
                <th>时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.run_id}>
                  <td className="mono">{run.run_id}</td>
                  <td>{runTypeLabel(run.run_type)}</td>
                  <td className="mono">{run.task_id}</td>
                  <td>{formatTimestamp(run.created_at)}</td>
                  <td>
                    <button
                      className="btn small"
                      onClick={() => {
                        setSearchParams({ run: run.run_id })
                        setDetailLoading(true)
                        topic2Api
                          .getRun(run.run_id)
                          .then((record) => {
                            setDetail(record)
                            setActiveRun(record.run_id)
                          })
                          .catch((err) => setError(err instanceof Error ? err.message : '读取运行详情失败'))
                          .finally(() => setDetailLoading(false))
                      }}
                    >
                      详情
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {detail && (
        <div className="card">
          <div className="card-title">
            运行详情
            <button className="btn small" onClick={() => setDetail(null)}>
              关闭
            </button>
          </div>
          {detailLoading ? (
            <div className="empty-state">
              <span className="spinner" /> 读取中…
            </div>
          ) : (
            <RunTracePanel run={detail} />
          )}
        </div>
      )}
    </div>
  )
}
