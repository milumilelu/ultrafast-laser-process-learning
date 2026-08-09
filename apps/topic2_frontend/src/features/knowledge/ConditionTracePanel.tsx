/** ConditionTrace panel (阶段一): CandidateLedger → SourceConditionSet →
 * ReconstructibilityReportSet — the literature traceability layer. */

import { useMemo } from 'react'
import type { ArtifactSnapshot } from '../../domain/artifact'
import {
  buildConditionSetView,
  buildLedgerView,
  buildReconstructibilityView,
} from '../../domain/condition'
import { Card, EmptyState } from '../../components/ui/Card'
import { StatusBadge } from '../../components/ui/StatusBadge'

export function ConditionTracePanel({
  ledger,
  conditions,
  reconstructibility,
}: {
  ledger?: ArtifactSnapshot
  conditions?: ArtifactSnapshot
  reconstructibility?: ArtifactSnapshot
}) {
  const ledgerView = useMemo(
    () => buildLedgerView(ledger?.content as Record<string, unknown>),
    [ledger],
  )
  const conditionViews = useMemo(
    () => buildConditionSetView(conditions?.content as Record<string, unknown>),
    [conditions],
  )
  const reports = useMemo(
    () => buildReconstructibilityView(reconstructibility?.content as Record<string, unknown>),
    [reconstructibility],
  )
  if (!ledger && !conditions && !reconstructibility) return null

  return (
    <>
      {ledger && ledgerView.candidates.length > 0 && (
        <Card title={`CandidateLedger（${ledgerView.candidates.length} 条候选）`}>
          <div className="control-meta">
            <span className="control-chip">账本 {ledgerView.ledgerVersionId}</span>
            <span className="control-chip">文档 {ledgerView.documentVersionId}</span>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>候选</th>
                <th>类型</th>
                <th>来源</th>
                <th>论文</th>
              </tr>
            </thead>
            <tbody>
              {ledgerView.candidates.map((candidate) => (
                <tr key={candidate.candidateId}>
                  <td title={candidate.rawStatement}>{candidate.conceptLabel}</td>
                  <td>{candidate.candidateKind}</td>
                  <td>{candidate.sourceType}</td>
                  <td>{candidate.provenancePapers.join(', ') || candidate.paperId}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {conditions && conditionViews.length > 0 && (
        <Card title={`SourceConditions（${conditionViews.length} 组条件）`}>
          <div className="conditions-grid">
            {conditionViews.map((condition) => (
              <div key={condition.conditionId} className="condition-cell">
                <div className="condition-head">
                  <span className="condition-id">{condition.conditionId}</span>
                  <span className="condition-paper">{condition.paperId}</span>
                </div>
                <ul className="condition-fields">
                  {condition.fields.map((field) => (
                    <li key={field.parameter}>
                      <span className="condition-field-param">{field.parameter}</span>
                      <span className="condition-field-values">
                        {field.values.join(' / ')} {field.unit}
                      </span>
                      <StatusBadge
                        tone={
                          field.fieldStatus === 'REPORTED_CLEAR'
                            ? 'ok'
                            : field.fieldStatus === 'CONFLICT_PRESERVED'
                              ? 'warn'
                              : 'neutral'
                        }
                        label={field.fieldStatus}
                      />
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </Card>
      )}

      {reconstructibility && reports.length > 0 && (
        <Card title={`Reconstructibility（${reports.length} 份报告）`}>
          <div className="conditions-grid">
            {reports.map((report) => (
              <div key={report.conditionId} className="condition-cell">
                <div className="condition-head">
                  <span className="condition-id">{report.conditionId}</span>
                  <StatusBadge
                    tone={
                      report.reconstructibilityStatus === 'FULL'
                        ? 'ok'
                        : report.reconstructibilityStatus === 'PARTIAL'
                          ? 'warn'
                          : 'err'
                    }
                    label={report.reconstructibilityStatus}
                  />
                </div>
                <div className="card-hint">
                  已报告: {report.reportedFields.join(', ') || '—'}
                </div>
                {report.blockingDependencies.length > 0 && (
                  <div className="card-hint">
                    依赖缺失: {report.blockingDependencies.join(', ')}
                  </div>
                )}
                {report.computableCoordinates.length > 0 && (
                  <div className="card-hint">
                    可计算坐标: {report.computableCoordinates.map((c) => c.coordinate).join(', ')}
                  </div>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}
      {ledger && !conditions && !reconstructibility && (
        <EmptyState message="文献链中段未产出条件" hint="语料候选的条件字段为空。" />
      )}
    </>
  )
}
