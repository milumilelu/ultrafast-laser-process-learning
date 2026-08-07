/** Scientific Evidence 折叠面板（文档 §47）：展示 RAG→LLM→E2P 科学知识链结果。
 *  显示：检索文献数 / 提炼知识数 / 审核知识数 + Known / Unknown / Conflicting。 */

import { useState } from 'react'

import type { ScientificPackState } from '../stores/science'
import { StatusBadge } from './StatusBadge'

interface Props {
  pack: ScientificPackState | null
  loading: boolean
  error: string | null
}

export function ScientificEvidencePanel({ pack, loading, error }: Props) {
  const [open, setOpen] = useState(false)

  const knowledge = pack?.knowledge ?? null
  const validation = pack?.validation ?? null
  const corpus = pack?.corpus ?? null

  const corpusSources =
    corpus && typeof corpus.sources === 'object' && corpus.sources
      ? Object.keys(corpus.sources as object).length
      : (corpus?.sources as unknown[] | undefined)?.length ?? 0
  const knownCount =
    knowledge && Array.isArray(knowledge.known) ? knowledge.known.length : 0
  const unknownCount =
    knowledge && Array.isArray(knowledge.unknown) ? knowledge.unknown.length : 0
  const conflictsCount =
    knowledge && Array.isArray(knowledge.conflicts) ? knowledge.conflicts.length : 0
  const candidateCount =
    knowledge && Array.isArray(knowledge.candidates)
      ? (knowledge.candidates as unknown[]).length
      : 0
  const validatedCount = validation?.validated_candidates.length ?? 0
  const rejectedCount = validation?.rejected_candidates.length ?? 0

  return (
    <div className="card">
      <button
        type="button"
        className="card-title-row"
        style={{
          display: 'flex',
          width: '100%',
          justifyContent: 'space-between',
          alignItems: 'center',
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          padding: 0,
        }}
        onClick={() => setOpen((value) => !value)}
        data-testid="scientific-evidence-toggle"
      >
        <span>科学证据（RAG → LLM → E2P）</span>
        <span>{open ? '▾' : '▸'}</span>
      </button>

      {loading && <div className="muted">科学检索与精读执行中…</div>}
      {error && <div className="error-text">{error}</div>}

      {pack && (
        <div className="row" style={{ margin: '8px 0', gap: 8, flexWrap: 'wrap' }}>
          <StatusBadge tone="ok">LLM: {pack.llmModel || '已配置'}</StatusBadge>
          <StatusBadge tone="ok">文献 {corpusSources}</StatusBadge>
          <StatusBadge tone="ok">知识 {candidateCount}</StatusBadge>
          <StatusBadge tone={validatedCount > 0 ? 'ok' : 'warn'}>通过 {validatedCount}</StatusBadge>
          {rejectedCount > 0 && (
            <StatusBadge tone="warn">拒绝 {rejectedCount}</StatusBadge>
          )}
        </div>
      )}

      {open && pack && knowledge && (
        <div className="scientific-evidence-detail" data-testid="scientific-evidence-detail">
          {validation && validation.issues.length > 0 && (
            <div className="warn-banner" style={{ margin: '8px 0' }}>
              验证问题 {validation.issues.length} 条（
              {validation.issues.filter((issue) => issue.severity === 'error').length} 条致命）
            </div>
          )}

          {knownCount > 0 && (
            <div className="section">
              <div className="card-sub">已知（Known）</div>
              <ul style={{ margin: 0, paddingLeft: 20 }}>
                {(knowledge.known as { claim: string }[]).map((item, index) => (
                  <li key={`known-${index}`}>{item.claim}</li>
                ))}
              </ul>
            </div>
          )}

          {unknownCount > 0 && (
            <div className="section" style={{ marginTop: 8 }}>
              <div className="card-sub">未知（Unknown）</div>
              <ul style={{ margin: 0, paddingLeft: 20 }}>
                {(knowledge.unknown as { topic: string; description: string }[]).map(
                  (item, index) => (
                    <li key={`unknown-${index}`}>
                      <b>{item.topic}</b>：{item.description}
                    </li>
                  ),
                )}
              </ul>
            </div>
          )}

          {conflictsCount > 0 && (
            <div className="section" style={{ marginTop: 8 }}>
              <div className="card-sub">冲突（Conflicting）</div>
              <ul style={{ margin: 0, paddingLeft: 20 }}>
                {(knowledge.conflicts as { topic: string; description: string }[]).map(
                  (item, index) => (
                    <li key={`conflict-${index}`}>
                      <b>{item.topic}</b>：{item.description}
                    </li>
                  ),
                )}
              </ul>
            </div>
          )}

          {candidateCount > 0 && (
            <div className="section" style={{ marginTop: 8 }}>
              <div className="card-sub">提炼候选（{candidateCount}）</div>
              <div style={{ maxHeight: 200, overflowY: 'auto' }}>
                {(knowledge.candidates as {
                  candidate_id: string
                  type: string
                  parameter?: string | null
                  value?: number | null
                  unit?: string | null
                  semantic_role?: string | null
                }[]).map((candidate) => (
                  <div
                    key={candidate.candidate_id}
                    style={{ fontSize: 12, padding: '2px 0', borderBottom: '1px solid var(--border, #eee)' }}
                  >
                    <code>{candidate.type}</code>{' '}
                    {candidate.parameter ?? '—'}
                    {candidate.value != null ? ` = ${candidate.value} ${candidate.unit ?? ''}` : ''}{' '}
                    <span className="muted">[{candidate.semantic_role ?? '?'}]</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
