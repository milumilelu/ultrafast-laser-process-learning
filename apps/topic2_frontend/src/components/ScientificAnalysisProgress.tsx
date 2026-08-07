/** 科学分析实时进度面板（Agent 右侧界面）。
 *  轮询异步 Job（RAG 检索 → 精读 i/N → 验证 → 覆盖 → 综合 → 批判 → 完成），
 *  实时展示阶段与进展细节。 */

import { useEffect } from 'react'

import { agentApi } from '../api/agent'
import { candidatesToEvidence } from '../lib/candidatesToEvidence'
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
  const setAnalysisJob = useScienceStore((state) => state.setAnalysisJob)
  const setScientificPack = useScienceStore((state) => state.setScientificPack)
  const setRagEvidence = useScienceStore((state) => state.setRagEvidence)

  useEffect(() => {
    if (!analysisJob || !analysisJobPolling) return
    let cancelled = false
    let failures = 0
    const poll = async () => {
      try {
        const job = await agentApi.getAnalysisJob(analysisJob.jobId)
        if (cancelled) return
        failures = 0
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
          // 完成后结果写入共享科学包（辨识/建模/优化页共享）
          const knowledge = job.result as Record<string, unknown>
          setScientificPack({
            corpus: null,
            knowledge,
            validation: null,
            degraded: false,
            llmModel: String(knowledge.llm_model ?? 'unknown'),
          })
          // 数值候选 → 证据篮（建模页编译/模型策略直接消费）
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
          window.setTimeout(poll, 2000)
        }
      } catch {
        // 轮询失败不停止：重试（3 次后提示并暂停 10s 自动恢复轮询，
        // 服务恢复后进度自动续上，避免界面永久卡在错误态）
        if (cancelled) return
        failures += 1
        if (failures >= 3) {
          setAnalysisJob(
            { ...analysisJob, error: '分析任务状态查询失败（服务可能已重启）——正在自动重试……' },
            false,
          )
          failures = 0
          window.setTimeout(poll, 10_000)
          return
        }
        window.setTimeout(poll, 2000)
      }
    }
    void poll()
    return () => {
      cancelled = true
    }
  }, [analysisJob, analysisJobPolling, setAnalysisJob, setScientificPack, setRagEvidence])

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
