import type { Tone } from '../../domain/status'

const TONE_CLASS: Record<Tone, string> = {
  ok: 'badge-ok',
  warn: 'badge-warn',
  err: 'badge-err',
  neutral: 'badge-neutral',
  info: 'badge-info',
}

export function StatusBadge({ tone, label }: { tone: Tone; label: string }) {
  return <span className={`status-badge ${TONE_CLASS[tone]}`}>{label}</span>
}

export function Badge({ label, tone = 'info' }: { label: string; tone?: Tone }) {
  return <span className={`status-badge ${TONE_CLASS[tone]}`}>{label}</span>
}
