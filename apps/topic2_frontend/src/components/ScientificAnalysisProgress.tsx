/** 科学分析实时进度面板（Agent 抽屉内只读展示）。
 *  轮询由全局单例（stores/analysisPolling）负责，本组件只订阅 store，
 *  避免与任务页分析面板的轮询互相打断。 */

import { useEffect } from 'react'

import { ensureAnalysisPolling } from '../stores/analysisPolling'
import { useScienceStore } from '../stores/science'

const STAGE_LABELS: Record<string, string> = {
  queued: '排队中',
  retrieving: 'RAG 检索语料',
  mapping: '科学精读（Source Map）',
  validating: '确定性验证',
  coverage: '覆盖检查',
  reducing: '全局综合（Reduce）',
  criticizing: '关键知识批判（Selective Critic）',
  completed: '已完成',
  failed: '失败',
}

export function ScientificAnalysisProgress() {
  const analysisJob = useScienceStore((state) => state.analysisJob)
  const analysisJobPolling = useScienceStore((state) => state.analysisJobPolling)

  useEffect(() => {
    if (!analysisJob || !analysisJobPolling) return
    ensureAnalysisPolling(analysisJob.jobId)
  }, [analysisJob?.jobId, analysisJobPolling])

  if (!analysisJob) return null

  const stageLabel = STAGE_LABELS[analysisJob.stage] ?? analysisJob.stage
  const progress = analysisJob.progress as {
    current?: number
    total?: number
    detail?: string
    source_list?: { paper_id: string | null; title: string; sections: number }[]
  }
  const sourceList = progress.source_list ?? []
  const current = progress.current ?? 0
  const total = progress.total ?? 0
  const percent =
    total > 0 ? Math.min(100, Math.round((current / total) * 100)) : null
  const isActive = analysisJob.status !== 'completed' && analysisJob.status !== 'failed'
  const recentStages = analysisJob.detail.slice(-6)

  return (
    <div className="card" style={{ margin: 8 }} data-testid="scientific-progress">
      <div className="card-title-row" style={{ display: 'flex', justifyContent: 'space-between' }}>
        <span style={{ fontWeight: 600, fontSize: 13 }}>科学分析进度</span>
        <span className="id-chip">{analysisJob.jobId}</span>
      </div>

      <div style={{ marginTop: 6, fontSize: 13 }}>
        <span className={isActive ? '' : 'muted'}>
          {isActive ? '⏳' : analysisJob.status === 'completed' ? '✓' : '✗'} {stageLabel}
        </span>
        {percent !== null && (
          <span className="mono" style={{ marginLeft: 8 }}>
            {current}/{total}（{percent}%）
          </span>
        )}
      </div>

      {isActive && percent !== null && (
        <div
          className="progress-track"
          style={{
            height: 6,
            background: 'var(--border, #e5e7eb)',
            borderRadius: 3,
            marginTop: 6,
            overflow: 'hidden',
          }}
        >
          <div
            className="progress-fill"
            style={{
              width: `${percent}%`,
              height: '100%',
              background: 'var(--accent, #2563eb)',
              transition: 'width 0.5s',
            }}
          />
        </div>
      )}

      {progress.detail && (
        <div className="muted" style={{ marginTop: 4, fontSize: 12 }}>
          {String(progress.detail)}
        </div>
      )}

      {/* RAG 检索结果：语料列表 */}
      {analysisJob.stage === 'retrieving' && sourceList.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <div className="card-sub">检索到 {sourceList.length} 篇语料：</div>
          <ul style={{ margin: '4px 0 0', paddingLeft: 18, fontSize: 12 }}>
            {sourceList.map((source, index) => (
              <li key={`src-${index}`}>
                <code>{(source.paper_id ?? '?').slice(-8)}</code>{' '}
                {(source.title || '(无标题)').slice(0, 60)}
                <span className="muted"> · {source.sections} 段</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 每篇 Source 的分析结果摘要 */}
      {analysisJob.detail.some((entry) => entry.stage === 'mapping' && entry.title) && (
        <div style={{ marginTop: 8 }}>
          <div className="card-sub">已精读分析：</div>
          <ul style={{ margin: '4px 0 0', paddingLeft: 18, fontSize: 12 }}>
            {analysisJob.detail
              .filter((entry) => entry.stage === 'mapping' && entry.title)
              .slice(-8)
              .map((entry, index) => (
                <li key={`map-${index}`}>
                  <b>{(entry.title as string).slice(0, 50)}</b>{' '}
                  <span className={entry.status === 'failed' ? 'error-text' : ''}>
                    {entry.status === 'failed'
                      ? '分析失败'
                      : `提取 ${entry.items} 条${entry.cached ? '（缓存）' : ''}`}
                  </span>
                  {Array.isArray(entry.types) && (entry.types as string[]).length > 0 && (
                    <span className="muted">
                      {' '}
                      [{(entry.types as string[]).slice(0, 4).join(', ')}
                      {(entry.types as string[]).length > 4 ? '…' : ''}]
                    </span>
                  )}
                  {typeof entry.gaps === 'number' && entry.gaps > 0 && (
                    <span className="muted"> · 缺口 {entry.gaps}</span>
                  )}
                </li>
              ))}
          </ul>
        </div>
      )}

      {recentStages.length > 0 && (
        <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 12 }} className="muted">
          {recentStages.map((entry, index) => (
            <li key={`${entry.stage}-${index}`}>
              {STAGE_LABELS[entry.stage] ?? entry.stage}
              {'sources' in entry ? `（${entry.sources} 篇来源）` : ''}
              {entry.current != null && entry.total != null
                ? ` ${entry.current}/${entry.total}`
                : ''}
              {entry.candidate_id ? ` ${String(entry.candidate_id).slice(0, 12)}…` : ''}
            </li>
          ))}
        </ul>
      )}

      {analysisJob.error && (
        <div className="warn-banner" style={{ marginTop: 6 }}>
          {analysisJob.error}
        </div>
      )}
    </div>
  )
}
