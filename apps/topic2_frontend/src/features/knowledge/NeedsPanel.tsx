/** Needs + Reading panels (M6): four-way need classification and the
 * corpus → LLM reading → validation chain from LiteratureResolutionResult.
 */

import { useMemo } from 'react'
import type { ArtifactSnapshot } from '../../domain/artifact'
import {
  buildNeedsView,
  NEED_TONE,
  NEED_TYPE_LABEL,
  RESOLUTION_TARGET_LABEL,
  type ScientificNeedType,
} from '../../domain/needs'
import { buildResolutionView } from '../../domain/resolution'
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

export function ReadingPanel({ artifact }: { artifact?: ArtifactSnapshot }) {
  const view = useMemo(
    () => buildResolutionView(artifact?.content as Record<string, unknown>),
    [artifact],
  )
  if (!artifact || view.sources.length === 0) return null

  const cacheLabel =
    view.mapping.fromCache > 0
      ? `${view.mapping.fromCache}/${view.mapping.sources} 来自预录缓存`
      : `${view.mapping.completed} 篇精读完成`

  return (
    <Card
      title={`文献精读（${view.sources.length} 篇论文）`}
      actions={<StatusBadge tone="ok" label={cacheLabel} />}
    >
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
