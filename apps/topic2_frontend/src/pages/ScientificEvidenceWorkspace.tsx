/** ScientificEvidenceWorkspace (UI-6): 科学知识 - 三栏结构。
 *  论文 | Evidence 生命周期 | 适用性 / CFA。CFA 只做审计（UNCALIBRATED），
 *  Unknown 从不渲染为 Mismatch，界面永不出现概率字段。 */

import { useEffect, useMemo, useState } from 'react'

import { applicationApi } from '../api/application'
import type { Evidence, Topic2ApplicationResult } from '../api/types'
import { ErrorBanner } from '../components/Banners'
import { StatusBadge } from '../components/StatusBadge'
import {
  CFAFacetInspector,
} from '../components/evidence/CFAFacetInspector'
import {
  CFAMatrix,
  type CFARow,
} from '../components/evidence/CFAMatrix'
import { EvidenceLifecycle } from '../components/evidence/EvidenceLifecycle'
import { PaperNavigator, summarizePapers } from '../components/evidence/PaperNavigator'
import { useApplicationStore } from '../stores/application'
import { useScienceStore } from '../stores/science'

export function ScientificEvidenceWorkspace() {
  const {
    ragEvidence,
    ragEvidenceMeta,
    ragEvidenceError,
    evidence,
    setRagEvidence,
    setEvidence,
  } = useScienceStore()
  const activeApplicationRunId = useApplicationStore((state) => state.activeApplicationRunId)

  const [selectedPaper, setSelectedPaper] = useState<string | null>(null)
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(null)
  const [inspectedCell, setInspectedCell] = useState<{ rowId: string; facet: string; details: Record<string, unknown> | null } | null>(null)
  const [cfaRows, setCfaRows] = useState<CFARow[]>([])
  const [cfaMeta, setCfaMeta] = useState<{ calibrationStatus: string; warnings: string[] } | null>(null)
  const [governedPriorEvidenceIds, setGovernedPriorEvidenceIds] = useState<string[]>([])

  /** 只读 ApplicationRun 的 EvidenceCompileResult artifact（prepare_knowledge 产物）。
   *  页面不再直接调用 /e2p/evidence-candidates——科学链以 ApplicationRun 为唯一执行源。 */
  useEffect(() => {
    let cancelled = false
    if (!activeApplicationRunId) {
      setRagEvidence([], null)
      setEvidence(null)
      return () => {
        cancelled = true
      }
    }
    setRagEvidence([], null, null, true)
    applicationApi
      .getArtifacts(activeApplicationRunId)
      .then((items) => {
        if (cancelled) return
        const artifact = items.items.find(
          (item) => item.artifact_type === 'EvidenceCompileResult',
        )
        if (!artifact) {
          setRagEvidence([], null)
          setEvidence(null)
          return
        }
        return applicationApi.getArtifact(artifact.artifact_id)
      })
      .then((payload) => {
        if (cancelled) return
        if (!payload) return
        // artifact 为科学状态快照：{id, type, schema_version, input_refs, content, created_at}
        const snapshot = payload.content as {
          content?: {
            candidates?: Evidence[]
            accepted?: Evidence[]
            rejected?: { evidence_id: string; reason: string }[]
            applicability_results?: {
              evidence_id: string
              material_match: boolean | null
              laser_type_match: boolean | null
              geometry_match: boolean | null
              equipment_match: boolean | null
              target_match: boolean | null
              transfer_level: 'strong' | 'medium' | 'weak' | 'none'
            }[]
            version?: string
          }
        }
        const content = snapshot.content ?? {}
        setRagEvidence(content.candidates ?? [], {
          retrievedHits: (content.candidates ?? []).length,
          reviewedHits: (content.accepted ?? []).length,
          evidenceStatus: 'application_run',
        })
        setEvidence({
          version: content.version ?? 'application-run',
          candidates: content.candidates ?? [],
          accepted: content.accepted ?? [],
          rejected: content.rejected ?? [],
          applicability_results: content.applicability_results ?? [],
        })
      })
      .catch(() => {
        if (!cancelled) {
          setRagEvidence([], null)
          setEvidence(null)
        }
      })
    return () => {
      cancelled = true
    }
  }, [activeApplicationRunId, setRagEvidence, setEvidence])

  const papers = useMemo(
    () => summarizePapers(ragEvidence, new Set(evidence?.accepted.map((item) => item.evidence_id) ?? [])),
    [ragEvidence, evidence],
  )

  const paperEvidence = useMemo(
    () =>
      selectedPaper
        ? ragEvidence.filter((item) => item.provenance.source_id === selectedPaper)
        : ragEvidence,
    [selectedPaper, ragEvidence],
  )

  const selectedEvidence = paperEvidence.find((item) => item.evidence_id === selectedEvidenceId) ?? paperEvidence[0] ?? null

  useEffect(() => {
    if (paperEvidence.length > 0 && !paperEvidence.some((item) => item.evidence_id === selectedEvidenceId)) {
      setSelectedEvidenceId(paperEvidence[0].evidence_id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paperEvidence])

  /** CFA 行：优先应用运行报告（逐 claim），否则按 facet 汇总单行（目标侧）。 */
  useEffect(() => {
    let cancelled = false
    if (!activeApplicationRunId) {
      setCfaRows([])
      setCfaMeta(null)
      return () => {
        cancelled = true
      }
    }
    applicationApi
      .getResult(activeApplicationRunId)
      .then((result) => {
        if (cancelled) return
        buildCfaRows(result, setCfaRows, setCfaMeta)
        setGovernedPriorEvidenceIds(
          result.scientificBasis.governedPrior?.evidence_ids as string[] | undefined ?? [],
        )
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [activeApplicationRunId])

  return (
    <div>
      <h1>科学知识</h1>
      <p className="card-sub">
        系统使用了哪些文献？抽取了哪些科学信息？哪些能进入 E2P？为什么？
        证据链路：EvidenceIR 通过 provenance 引用 SourceCondition → Applicability → GovernedPriorArtifact（引用式，非严格单线链）。
      </p>

      <div className="row" style={{ marginBottom: 12 }}>
        {ragEvidenceMeta && (
          <StatusBadge tone={ragEvidence.length > 0 ? 'ok' : 'warn'}>
            证据候选 {ragEvidence.length} 条（已审核 {ragEvidenceMeta.reviewedHits}）
          </StatusBadge>
        )}
        {!activeApplicationRunId && (
          <StatusBadge tone="neutral">运行完整分析后展示 ApplicationRun 的证据产物</StatusBadge>
        )}
      </div>

      <ErrorBanner message={ragEvidenceError} />

      <div className="evidence-workspace">
        <div className="col-papers">
          <PaperNavigator
            papers={papers}
            selectedPaperId={selectedPaper}
            onSelect={(paperId) => {
              setSelectedPaper(paperId)
              setInspectedCell(null)
            }}
          />
        </div>

        <div className="col-evidence">
          <div className="card">
            <div className="card-title">Evidence 生命周期</div>
            {selectedEvidence ? (
              <EvidenceLifecycle
                evidence={selectedEvidence}
                applicabilityLevel={
                  evidence?.applicability_results.find(
                    (item) => item.evidence_id === selectedEvidence.evidence_id,
                  )?.transfer_level ?? null
                }
                governedPriorEvidenceIds={governedPriorEvidenceIds}
              />
            ) : (
              <div className="empty-state">
                无证据。请先在工艺智能应用页运行完整分析（科学证据由 ApplicationRun 主链生成）。
              </div>
            )}
          </div>
          <div className="card">
            <div className="card-title">证据列表（{paperEvidence.length}）</div>
            {paperEvidence.length === 0 ? (
              <div className="empty-state">无证据。运行完整分析后自动生成（ApplicationRun 产物）。</div>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Evidence ID</th>
                    <th>参数</th>
                    <th>声明</th>
                    <th>审核</th>
                  </tr>
                </thead>
                <tbody>
                  {paperEvidence.map((item) => (
                    <tr
                      key={item.evidence_id}
                      className={selectedEvidenceId === item.evidence_id ? 'row-selected' : ''}
                      onClick={() => setSelectedEvidenceId(item.evidence_id)}
                    >
                      <td className="mono">{item.evidence_id}</td>
                      <td>{item.parameter ?? '—'}</td>
                      <td className="muted">{item.claim_type}</td>
                      <td>
                        <StatusBadge
                          tone={item.review_status === 'approved' ? 'ok' : item.review_status === 'rejected' ? 'err' : 'warn'}
                        >
                          {item.review_status}
                        </StatusBadge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        <div className="col-cfa">
          <div className="card">
            <div className="card-title">Applicability / CFA</div>
            <CFAMatrix
              rows={cfaRows}
              onCellClick={(rowId, facet) => {
                const row = cfaRows.find((item) => item.rowId === rowId)
                setInspectedCell({
                  rowId,
                  facet,
                  details: (row?.cells[facet]?.details as Record<string, unknown>) ?? null,
                })
              }}
            />
            <div className="cfa-fixed-status" data-testid="cfa-fixed-status">
              <div>
                Method: Uncalibrated CFA
              </div>
              <div>
                Calibration: {cfaMeta?.calibrationStatus ?? 'NOT_YET_CALIBRATED'}
              </div>
              <div>Independent Validation: Partial / Research Prototype</div>
            </div>
            {cfaMeta?.warnings.map((warning, index) => (
              <div key={index} className="warn-banner" style={{ marginTop: 8 }}>
                {warning}
              </div>
            ))}
          </div>
          {inspectedCell && (
            <CFAFacetInspector facet={inspectedCell.facet} details={inspectedCell.details} />
          )}
        </div>
      </div>
    </div>
  )
}

/** 从 Application Result 构建 CFA 矩阵行（逐 claim 报告或目标侧汇总）。 */
function buildCfaRows(
  result: Topic2ApplicationResult,
  setRows: (rows: CFARow[]) => void,
  setMeta: (meta: { calibrationStatus: string; warnings: string[] }) => void,
): void {
  const rows: CFARow[] = []
  const reports = result.cfa.reports ?? []
  if (reports.length > 0) {
    for (const report of reports) {
      const facets = (report.facets as { facet: string; status: string }[]) ?? []
      const cells: Record<string, { facet: string; status: string; details: Record<string, unknown> }> = {}
      for (const facet of facets) {
        cells[facet.facet] = {
          facet: facet.facet,
          status: facet.status,
          details: report as Record<string, unknown>,
        }
      }
      rows.push({
        rowId: String(report.evidence_claim_id ?? `row-${rows.length}`),
        label: String(report.evidence_claim_id ?? `evidence-${rows.length}`),
        cells,
      })
    }
  } else if (Object.keys(result.cfa.facetSummary ?? {}).length > 0) {
    const cells: Record<string, { facet: string; status: string }> = {}
    for (const [facet, status] of Object.entries(result.cfa.facetSummary ?? {})) {
      cells[facet] = { facet, status }
    }
    rows.push({ rowId: 'target', label: 'Target（目标侧汇总）', cells })
  }
  setRows(rows)
  setMeta({
    calibrationStatus: result.cfa.calibrationStatus,
    warnings:
      result.cfa.warnings.length > 0
        ? result.cfa.warnings
        : ['source evidence 未完成文献侧 canonical state 重建；未校准 CFA 仅作审计'],
  })
}
