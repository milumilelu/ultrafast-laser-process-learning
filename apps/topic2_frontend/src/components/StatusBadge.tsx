export function StatusBadge({ tone, children }: { tone: 'ok' | 'warn' | 'err' | 'neutral' | 'info'; children: React.ReactNode }) {
  return <span className={`badge ${tone}`}>{children}</span>
}
