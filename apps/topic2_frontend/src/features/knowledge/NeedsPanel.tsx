/** Needs + Reading panels (M6): four-way need classification and the
 * corpus → LLM reading → validation chain from LiteratureResolutionResult.
 */

import { useMemo } from 'react'
import type { ArtifactSnapshot } from '../../domain/artifact'
import {
  ANALYSIS_METHOD_LABEL,
  buildResolutionView,
} from '../../domain/resolution'
import {
  buildNeedsView,
  NEED_TONE,
  NEED_TYPE_LABEL,
  RESOLUTION_TARGET_LABEL,
  type ScientificNeedType,
} from '../../domain/needs'
import { Card, EmptyState } from '../../components/ui/Card'
import { StatusBadge } from '../../components/ui/StatusBadge'

const NEED_ORDER: ScientificNeedType[] = [
  'RESOURCE_INPUT',
  'SCIENTIFIC_KNOWLEDGE',
  'CALIBRATION_OBSERVATION',
  'TARGET_DATA',
]

export function NeedsPanel({ artifact }: { artifact?: ArtifactSnapshot }) {
  const view = useMemo(
    () => buildNeedsView(artifact?.content as Record<string, unknown>),
    [artifact],
  )
  if (!artifact || view.needs.length === 0) return null

  return (
    <Card title={`Scientific Needs（${view.needs.length}）`}>
      <div className="needs-grid">
        {NEED_ORDER.map((type) => {
          const needs = view.byType[type]
          if (needs.length === 0) return null
          return (
            <div key={type} className="need-group">
              <div className="need-group-head">
                <StatusBadge tone={NEED_TONE[type]} label={`${NEED_TYPE_LABEL[type]} ${needs.length}`} />
              </div>
              <ul className="need-list">
                {needs.map((need) => (
                  <li key={need.needId} className="need-item">
                    <div className="need-item-head">
                      <span className="need-target">{need.target}</span>
                      <span className="need-resolution">{RESOLUTION_TARGET_LABEL[need.resolutionTarget] ?? need.resolutionTarget}</span>
                    </div>
                    <div className="need-question">{need.question}</div>
                  </li>
                ))}
              </ul>
            </div>
          )
        })}
      </div>
    </Card>
  )
}

export const RESOLUTION_PHASES = [
  { id: 'retrieving', label: '检索' },
  { id: 'selecting', label: '选文' },
  { id: 'reading', label: 'LLM 精读' },
  { id: 'validating', label: '确定性验证' },
  { id: 'compiling_ledger', label: '候选账本' },
  { id: 'compiling_conditions', label: '条件编译' },
  { id: 'assessing_reconstructibility', label: '可重建性' },
  { id: 'assessing_applicability', label: '适用性' },
  { id: 'compiling_prior', label: '先验编译' },
] as const

export function ReadingPanel({
  artifact,
  events,
}: {
  artifact?: ArtifactSnapshot
  /** Workflow events drive the live phase progress (阶段三 T3). */
  events?: Array<{ details?: Record<string, unknown> }>
}) {
  const view = useMemo(
    () => buildResolutionView(artifact?.content as Record<string, unknown>),
    [artifact],
  )
  const progress = useMemo(() => {
    const byPhase = new Map<string, { current?: number; total?: number }>()
    for (const event of events ?? []) {
      const phase = String(event.details?.phase ?? '')
      if (phase) {
        byPhase.set(phase, {
          current: event.details?.current as number | undefined,
          total: event.details?.total as number | undefined,
        })
      }
    }
    return byPhase
  }, [events])

  if (!artifact && view.sources.length === 0) return null

  const latestPhaseIndex = RESOLUTION_PHASES.reduce(
    (latest, phase, index) =>
      progress.has(phase.id) ? Math.max(latest, index) : latest,
    -1,
  )

  return (
    <Card
      title={`文献精读（${view.sources.length} 篇论文）`}
      actions={
        <StatusBadge
          tone={
            view.analysisMethod === 'LLM_LIVE' || view.analysisMethod === 'LLM_CACHED'
              ? 'ok'
              : view.analysisMethod === 'PENDING_LLM'
                ? 'warn'
                : 'neutral'
          }
          label={ANALYSIS_METHOD_LABEL[view.analysisMethod] ?? view.analysisMethod}
        />
      }
    >
      {events && events.length > 0 && (
        <ol className="phase-list">
          {RESOLUTION_PHASES.map((phase, index) => {
            const state = progress.has(phase.id)
              ? index < latestPhaseIndex || (phase.id !== 'reading' && progress.has(phase.id))
                ? 'done'
                : 'active'
              : index <= latestPhaseIndex
                ? 'done'
                : 'pending'
            const reading = progress.get('reading')
            return (
              <li key={phase.id} className={`phase-item phase-${state}`}>
                <span className="phase-mark">
                  {state === 'done' ? '✓' : state === 'active' ? '●' : '○'}
                </span>
                <span className="phase-label">{phase.label}</span>
                {phase.id === 'reading' && reading && reading.total ? (
                  <span className="phase-progress">
                    {reading.current ?? 0} / {reading.total}
                  </span>
                ) : null}
              </li>
            )
          })}
        </ol>
      )}
      <div className="reading-stats">
        <div className="reading-stat">
          <span className="reading-stat-value">{view.mapping.sources}</span>
          <span className="reading-stat-label">来源</span>
        </div>
        <div className="reading-stat">
          <span className="reading-stat-value">{view.mapping.completed}</span>
          <span className="reading-stat-label">精读完成</span>
        </div>
        <div className="reading-stat">
          <span className="reading-stat-value">{view.mapping.fromCache}</span>
          <span className="reading-stat-label">预录缓存</span>
        </div>
        <div className="reading-stat">
          <span className="reading-stat-value">{view.mapping.failed}</span>
          <span className="reading-stat-label">失败</span>
        </div>
      </div>
      <ol className="paper-list">
        {view.sources.map((source) => (
          <li key={source.sourceId} className="paper-item">
            <span className="paper-title">{source.title || source.paperId}</span>
            <span className="paper-meta">
              {source.paperId} · {source.sectionTypes.join(' / ') || 'no sections'}
            </span>
          </li>
        ))}
      </ol>
      {view.sources.length === 0 && (
        <EmptyState message="解析链未产出论文来源" hint="语料为空或检索无命中。" />
      )}
    </Card>
  )
}
