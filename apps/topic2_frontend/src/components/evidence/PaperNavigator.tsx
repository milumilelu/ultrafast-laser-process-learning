/** PaperNavigator (8.2/8.3): 论文列表 + 每篇统计（候选/已映射证据/适用性）。 */

import type { Evidence } from '../../api/types'
import { scientificTone, type StatusTone } from '../../lib/status'
import { StatusBadge } from '../StatusBadge'

export interface PaperSummary {
  paperId: string
  material: string | null
  laserType: string | null
  candidateCount: number
  acceptedCount: number
  applicability: string | null
}

function paperKey(evidence: Evidence): string {
  return evidence.provenance.source_id || evidence.evidence_id
}

export function summarizePapers(
  evidence: Evidence[],
  acceptedIds: Set<string>,
): PaperSummary[] {
  const byPaper = new Map<string, Evidence[]>()
  for (const item of evidence) {
    const key = paperKey(item)
    byPaper.set(key, [...(byPaper.get(key) ?? []), item])
  }
  const summaries: PaperSummary[] = []
  for (const [paperId, items] of byPaper) {
    const scope = items[0].scope
    const accepted = items.filter((item) => acceptedIds.has(item.evidence_id))
    const levels = items
      .map((item) => item.review_status)
      .filter((value) => value !== 'pending')
    summaries.push({
      paperId,
      material: scope.material ?? null,
      laserType: scope.laser_type ?? null,
      candidateCount: items.length,
      acceptedCount: accepted.length,
      applicability: levels.length > 0 ? 'PARTIAL' : 'UNKNOWN',
    })
  }
  return summaries.sort((a, b) => a.paperId.localeCompare(b.paperId))
}

export function PaperNavigator({
  papers,
  selectedPaperId,
  onSelect,
}: {
  papers: PaperSummary[]
  selectedPaperId: string | null
  onSelect: (paperId: string) => void
}) {
  if (papers.length === 0) {
    return <div className="empty-state">暂无论文证据。请先在科学分析/证据检索中获取候选。</div>
  }
  return (
    <div className="paper-navigator" data-testid="paper-navigator">
      {papers.map((paper) => (
        <button
          key={paper.paperId}
          className={`paper-card ${selectedPaperId === paper.paperId ? 'selected' : ''}`}
          onClick={() => onSelect(paper.paperId)}
        >
          <div className="paper-title">{paper.paperId}</div>
          <div className="paper-tags">
            <StatusBadge tone="neutral">{paper.material ?? '—'}</StatusBadge>
            <StatusBadge tone="neutral">{paper.laserType ?? '—'}</StatusBadge>
          </div>
          <ul className="paper-stats">
            <li>候选 {paper.candidateCount}</li>
            <li>已映射证据 {paper.acceptedCount}</li>
          </ul>
          <StatusBadge tone={scientificTone(paper.applicability) as StatusTone}>
            适用性 {paper.applicability}
          </StatusBadge>
        </button>
      ))}
    </div>
  )
}
