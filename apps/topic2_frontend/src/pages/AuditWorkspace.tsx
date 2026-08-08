/** AuditWorkspace (UI-10): 运行与审计 - Application Run 列表 + Timeline + Artifact
 *  导航 + Replay。所有结果可追溯到 Task / Dataset / Model / Evidence / Prior / BO Run。 */

import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { applicationApi } from '../api/application'
import type { ApplicationRunSummary, Topic2ApplicationResult } from '../api/types'
import { ErrorBanner, EmptyState } from '../components/Banners'
import { StatusBadge } from '../components/StatusBadge'
import { formatTimestamp } from '../lib/format'
import { RunsPage } from './RunsPage'

export function AuditWorkspace() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [runs, setRuns] = useState<ApplicationRunSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<ApplicationRunSummary | null>(null)
  const [result, setResult] = useState<Topic2ApplicationResult | null>(null)
  const [artifacts, setArtifacts] = useState<{ artifact_id: string; artifact_type: string; created_at: string }[]>([])
  const [replayResult, setReplayResult] = useState<Record<string, unknown> | null>(null)
  const [selectedArtifact, setSelectedArtifact] = useState<{ artifact_id: string; artifact_type: string; content: Record<string, unknown> } | null>(null)

  const openRun = useCallback((runId: string) => {
    setReplayResult(null)
    setSelectedArtifact(null)
    applicationApi
      .getRun(runId)
      .then((run) => {
        setSelected(run)
        setResult(run.result)
        return applicationApi.getArtifacts(runId)
      })
      .then((items) => setArtifacts(items.items))
      .catch((err) => setError(err instanceof Error ? err.message : '读取应用运行失败'))
  }, [])

  useEffect(() => {
    const queryRun = searchParams.get('run')
    if (queryRun) openRun(queryRun)
  }, [searchParams, openRun])

  const loadRuns = useCallback(() => {
    setLoading(true)
    applicationApi
      .listRuns()
      .then((result) => setRuns(result.items))
      .catch((err) => setError(err instanceof Error ? err.message : '读取运行记录失败'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    loadRuns()
  }, [loadRuns])

  const replay = useCallback(() => {
    if (!selected) return
    setReplayResult(null)
    applicationApi
      .replay(selected.application_run_id)
      .then(setReplayResult)
      .catch((err) => setError(err instanceof Error ? err.message : 'Replay 失败'))
  }, [selected])

  const artifactKinds = artifacts.map((item) => item.artifact_type)
  const audit = result?.audit

  return (
    <div>
      <h1>运行与审计</h1>
      <p className="card-sub">
        Application Run 完整时间线：Task Context → Dataset → Process Learning → Evidence → CFA →
        Governed Prior → Vanilla BO → Assisted BO → Recommendation。所有正式结果由后端持久化并可重放。
      </p>

      <ErrorBanner message={error} />

      <div className="grid grid-2">
        <div className="card">
          <div className="card-title">Application Runs</div>
          {loading ? (
            <div className="empty-state">
              <span className="spinner" /> 读取中…
            </div>
          ) : runs.length === 0 ? (
            <EmptyState message="暂无 Application Run。在工艺智能应用页运行完整分析后自动生成。" />
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Run ID</th>
                  <th>模式</th>
                  <th>Task</th>
                  <th>状态</th>
                  <th>时间</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr
                    key={run.application_run_id}
                    className={selected?.application_run_id === run.application_run_id ? 'row-selected' : ''}
                    onClick={() => {
                      setSearchParams({ run: run.application_run_id })
                      openRun(run.application_run_id)
                    }}
                  >
                    <td className="mono">{run.application_run_id}</td>
                    <td>{run.mode === 'demo' ? '演示' : '研究'}</td>
                    <td className="mono">{run.task_context_ref}</td>
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

        {selected && (
          <div className="card">
            <div className="card-title">
              Run 时间线
              <span className="id-chip muted">{selected.application_run_id}</span>
              <button className="btn small" onClick={replay} disabled={selected.mode !== 'demo'}>
                Replay
              </button>
            </div>
            {selected.mode !== 'demo' && (
              <div className="card-sub">Replay 仅对冻结 Demo 场景可用。</div>
            )}
            <ul className="detail-list">
              {[
                'Task Context',
                'Dataset',
                'Process Learning',
                'Evidence',
                'CFA',
                'Governed Prior',
                'Vanilla BO',
                'Assisted BO',
                'Recommendation',
              ].map((step) => (
                <li key={step}>
                  <span className="dl-key">{step}</span>
                  <span className="dl-value">
                    {step === 'Recommendation' ? (
                      <StatusBadge tone={audit ? 'ok' : 'warn'}>
                        {audit ? '生成' : '—'}
                      </StatusBadge>
                    ) : (
                      <StatusBadge tone="neutral">记录</StatusBadge>
                    )}
                  </span>
                </li>
              ))}
            </ul>
            {replayResult && (
              <div className="warn-banner" style={{ marginTop: 8 }}>
                Scientific payload identical: {replayResult.scientific_payload_identical ? '✓' : '✗'} · Runtime
                IDs changed: {replayResult.runtime_ids_changed ? 'expected' : '—'}
              </div>
            )}
          </div>
        )}
      </div>

      {selected && result && (
        <div className="card">
          <div className="card-title">Artifact 面板</div>
          <div className="row" style={{ marginBottom: 8 }}>
            {artifactKinds.map((kind) => (
              <button
                key={kind}
                className="btn small"
                onClick={() => {
                  const artifact = artifacts.find((item) => item.artifact_type === kind)
                  if (artifact) {
                    applicationApi
                      .getArtifact(artifact.artifact_id)
                      .then((payload) =>
                        setSelectedArtifact({ artifact_id: payload.artifact_id, artifact_type: payload.artifact_type, content: payload.content }),
                      )
                      .catch(() => undefined)
                  }
                }}
              >
                {kind}
              </button>
            ))}
          </div>
          <ul className="detail-list">
            <li>
              <span className="dl-key">evidence_ids</span>
              <span className="dl-value mono">{audit?.evidenceIds?.join(', ') || '—'}</span>
            </li>
            <li>
              <span className="dl-key">prior_content_hash</span>
              <span className="dl-value mono">{audit?.priorContentHash ?? '—'}</span>
            </li>
            <li>
              <span className="dl-key">bo_run_ids</span>
              <span className="dl-value mono">{audit?.boRunIds?.filter(Boolean).join(', ') || '—'}</span>
            </li>
            <li>
              <span className="dl-key">model_version</span>
              <span className="dl-value mono">{audit?.modelVersion ?? '—'}</span>
            </li>
            <li>
              <span className="dl-key">replayable</span>
              <span className="dl-value">{audit?.replayable ? '✓（冻结 Demo 场景）' : '—'}</span>
            </li>
          </ul>
          {selectedArtifact && (
            <div className="card" style={{ marginTop: 8 }}>
              <div className="card-title">
                {selectedArtifact.artifact_type}
                <span className="id-chip muted">{selectedArtifact.artifact_id}</span>
              </div>
              <pre className="artifact-json mono">
                {JSON.stringify(selectedArtifact.content, null, 2).slice(0, 6000)}
              </pre>
            </div>
          )}
        </div>
      )}

      <details style={{ marginTop: 16 }}>
        <summary className="card-sub" style={{ cursor: 'pointer' }}>
          科学 Run 记录（Topic2 Backend 持久化）
        </summary>
        <RunsPage />
      </details>
    </div>
  )
}
