/** Mid-chain artifact views (阶段一): CandidateLedger / SourceConditionSet /
 * ReconstructibilityReportSet — the literature traceability layer. */

export interface LedgerCandidateView {
  candidateId: string
  paperId: string
  candidateKind: string
  conceptLabel: string
  rawStatement: string
  sourceType: string
  sourceLocator: string
  provenancePapers: string[]
  promotionStatus: string
}

export interface LedgerView {
  ledgerVersionId: string
  paperId: string
  documentVersionId: string
  candidates: LedgerCandidateView[]
  metrics: Record<string, number>
  byKind: Record<string, number>
}

export interface SourceFieldView {
  parameter: string
  values: number[]
  unit: string
  fieldStatus: string
  valueShape: string
}

export interface SourceConditionView {
  conditionId: string
  paperId: string
  documentVersionId: string
  role: string
  scope: string
  coverageStatus: string
  fields: SourceFieldView[]
}

export interface CoordinateView {
  coordinate: string
  status: string
  value: number | null
  unit: string | null
  missingInputs: string[]
}

export interface ReconstructibilityView {
  paperId: string
  conditionId: string
  reportedFields: string[]
  ambiguousFields: string[]
  missingFields: string[]
  coverageBlockedFields: string[]
  computableCoordinates: CoordinateView[]
  blockedCoordinates: CoordinateView[]
  blockingDependencies: string[]
  reconstructibilityStatus: 'FULL' | 'PARTIAL' | 'BLOCKED'
  warnings: string[]
}

export interface ApplicabilityItemView {
  evidenceId: string
  transferLevel: string
  materialMatch: boolean | null
  laserTypeMatch: boolean | null
  geometryMatch: boolean | null
}

/* ------------------------------ CandidateLedger ------------------------------ */

export interface LedgerContent {
  ledger_version_id?: string
  paper_id?: string
  document_version_id?: string
  candidates?: Array<{
    candidate_id?: string
    paper_id?: string
    candidate_kind?: string
    concept_label?: string
    raw_statement?: string
    source_type?: string
    source_locator?: string
    provenance_anchors?: Array<{ paper_id?: string }>
    promotion_status?: string
  }>
  metrics?: Record<string, number>
}

export function buildLedgerView(content: LedgerContent | null | undefined): LedgerView {
  const raw = content ?? {}
  const candidates = (raw.candidates ?? []).map((candidate) => ({
    candidateId: String(candidate.candidate_id ?? ''),
    paperId: String(candidate.paper_id ?? ''),
    candidateKind: String(candidate.candidate_kind ?? ''),
    conceptLabel: String(candidate.concept_label ?? ''),
    rawStatement: String(candidate.raw_statement ?? ''),
    sourceType: String(candidate.source_type ?? ''),
    sourceLocator: String(candidate.source_locator ?? ''),
    provenancePapers: (candidate.provenance_anchors ?? [])
      .map((anchor) => String(anchor.paper_id ?? ''))
      .filter(Boolean),
    promotionStatus: String(candidate.promotion_status ?? ''),
  }))
  const byKind: Record<string, number> = {}
  for (const candidate of candidates) {
    byKind[candidate.candidateKind] = (byKind[candidate.candidateKind] ?? 0) + 1
  }
  return {
    ledgerVersionId: String(raw.ledger_version_id ?? ''),
    paperId: String(raw.paper_id ?? ''),
    documentVersionId: String(raw.document_version_id ?? ''),
    candidates,
    metrics: raw.metrics ?? {},
    byKind,
  }
}

/* ---------------------------- SourceConditionSet ---------------------------- */

export interface ConditionSetContent {
  conditions?: Array<{
    condition_id?: string
    paper_id?: string
    document_version_id?: string
    role?: string
    scope?: string
    coverage_status?: string
    fields?: Array<{
      parameter?: string
      values?: number[]
      unit?: string
      field_status?: string
      value_shape?: string
    }>
  }>
}

export function buildConditionSetView(
  content: ConditionSetContent | null | undefined,
): SourceConditionView[] {
  const raw = content ?? {}
  return (raw.conditions ?? []).map((condition) => ({
    conditionId: String(condition.condition_id ?? ''),
    paperId: String(condition.paper_id ?? ''),
    documentVersionId: String(condition.document_version_id ?? ''),
    role: String(condition.role ?? ''),
    scope: String(condition.scope ?? ''),
    coverageStatus: String(condition.coverage_status ?? ''),
    fields: (condition.fields ?? []).map((field) => ({
      parameter: String(field.parameter ?? ''),
      values: (field.values ?? []).map(Number),
      unit: String(field.unit ?? ''),
      fieldStatus: String(field.field_status ?? ''),
      valueShape: String(field.value_shape ?? 'POINT'),
    })),
  }))
}

/* ------------------------- ReconstructibilityReportSet ---------------------- */

export interface ReconstructibilityContent {
  reports?: Array<{
    paper_id?: string
    condition_id?: string
    reported_fields?: string[]
    ambiguous_fields?: string[]
    missing_fields?: string[]
    coverage_blocked_fields?: string[]
    computable_coordinates?: Array<Record<string, unknown>>
    blocked_coordinates?: Array<Record<string, unknown>>
    blocking_dependencies?: string[]
    reconstructibility_status?: string
    warnings?: string[]
  }>
}

function coordinatesOf(
  items: Array<Record<string, unknown>> | undefined,
): CoordinateView[] {
  return (items ?? []).map((item) => ({
    coordinate: String(item.coordinate ?? ''),
    status: String(item.status ?? ''),
    value: item.value !== null && item.value !== undefined ? Number(item.value) : null,
    unit: item.unit !== null && item.unit !== undefined ? String(item.unit) : null,
    missingInputs: Array.isArray(item.missing_inputs)
      ? item.missing_inputs.map(String)
      : [],
  }))
}

export function buildReconstructibilityView(
  content: ReconstructibilityContent | null | undefined,
): ReconstructibilityView[] {
  const raw = content ?? {}
  return (raw.reports ?? []).map((report) => {
    const status = String(report.reconstructibility_status ?? 'BLOCKED').toUpperCase()
    return {
      paperId: String(report.paper_id ?? ''),
      conditionId: String(report.condition_id ?? ''),
      reportedFields: (report.reported_fields ?? []).map(String),
      ambiguousFields: (report.ambiguous_fields ?? []).map(String),
      missingFields: (report.missing_fields ?? []).map(String),
      coverageBlockedFields: (report.coverage_blocked_fields ?? []).map(String),
      computableCoordinates: coordinatesOf(report.computable_coordinates),
      blockedCoordinates: coordinatesOf(report.blocked_coordinates),
      blockingDependencies: (report.blocking_dependencies ?? []).map(String),
      reconstructibilityStatus:
        status === 'FULL' || status === 'PARTIAL' ? status : 'BLOCKED',
      warnings: (report.warnings ?? []).map(String),
    }
  })
}

/* ---------------------------- ApplicabilityReportSet ------------------------ */

export interface ApplicabilityContent {
  items?: Array<{
    evidence_id?: string
    transfer_level?: string
    material_match?: boolean | null
    laser_type_match?: boolean | null
    geometry_match?: boolean | null
  }>
}

export function buildApplicabilityView(
  content: ApplicabilityContent | null | undefined,
): ApplicabilityItemView[] {
  const raw = content ?? {}
  return (raw.items ?? []).map((item) => ({
    evidenceId: String(item.evidence_id ?? ''),
    transferLevel: String(item.transfer_level ?? ''),
    materialMatch: item.material_match ?? null,
    laserTypeMatch: item.laser_type_match ?? null,
    geometryMatch: item.geometry_match ?? null,
  }))
}
