/** UI-P3 scientific status semantics: Unknown is never rendered as Mismatch.
 *  Statuses: AVAILABLE/VERIFIED/KNOWN -> green, PARTIAL/UNVERIFIED -> yellow,
 *  UNKNOWN/NOT_REPORTED/BLOCKED -> gray, MISMATCH/ERROR/CONTRADICTED -> red,
 *  evidence/literature -> purple. */

export type ScientificStatus =
  | 'AVAILABLE'
  | 'VERIFIED'
  | 'KNOWN'
  | 'PARTIAL'
  | 'UNVERIFIED'
  | 'UNKNOWN'
  | 'NOT_REPORTED'
  | 'BLOCKED'
  | 'MISMATCH'
  | 'ERROR'
  | 'CONTRADICTED'

export type StatusTone = 'ok' | 'warn' | 'neutral' | 'err' | 'info'

const POSITIVE = new Set(['AVAILABLE', 'VERIFIED', 'KNOWN', 'READY', 'IDENTIFIABLE', 'CALIBRATED', 'RECOMMENDED'])
const WARNING_SET = new Set(['PARTIAL', 'UNVERIFIED', 'PENDING', 'WEAKLY_IDENTIFIABLE'])
const ERROR_SET = new Set(['MISMATCH', 'ERROR', 'CONTRADICTED', 'FAILED'])
const NEUTRAL_SET = new Set(['UNKNOWN', 'MISSING', 'NOT_REPORTED', 'BLOCKED', 'NOT_YET_CALIBRATED', 'NOT_IDENTIFIABLE'])

/** Map a scientific status to a UI tone. UNKNOWN / BLOCKED are gray (neutral),
 *  never red - only explicit mismatches are red. */
export function scientificTone(status: string | null | undefined): StatusTone {
  if (!status) return 'neutral'
  const upper = status.toUpperCase()
  if (POSITIVE.has(upper)) return 'ok'
  if (WARNING_SET.has(upper)) return 'warn'
  if (ERROR_SET.has(upper)) return 'err'
  if (NEUTRAL_SET.has(upper)) return 'neutral'
  if (upper.startsWith('UNCALIBRATED')) return 'neutral'
  if (upper.startsWith('UN')) return 'neutral'
  return 'info'
}

export const SCIENTIFIC_LABELS: Record<string, string> = {
  AVAILABLE: '可用',
  VERIFIED: '已确认',
  KNOWN: '已知',
  READY: '就绪',
  PARTIAL: '部分',
  UNVERIFIED: '待确认',
  PENDING: '待处理',
  UNKNOWN: '未知',
  MISSING: '缺失',
  NOT_REPORTED: '未报告',
  BLOCKED: '不可判断',
  NOT_YET_CALIBRATED: '未校准',
  MISMATCH: '不匹配',
  ERROR: '错误',
  CONTRADICTED: '矛盾',
  COMPARABLE: '可比较',
  INCOMPARABLE: '不可比较',
  DEPENDENCY_MISSING: '依赖缺失',
  UNREACHABLE: '不可达',
  REACHABLE: '可达',
  IDENTIFIABLE: '可辨识',
  WEAKLY_IDENTIFIABLE: '弱可辨识',
  NOT_IDENTIFIABLE: '当前数据不可辨识',
  CALIBRATED: '已校准',
  RECOMMENDED: '推荐',
}

export function scientificLabel(status: string | null | undefined): string {
  if (!status) return '—'
  return SCIENTIFIC_LABELS[status.toUpperCase()] ?? status
}

/** CFA facet summary keys (canonical). */
export const CFA_FACETS = [
  'Material',
  'Task',
  'InteractionState',
  'Reconstructibility',
  'Reachability',
] as const
