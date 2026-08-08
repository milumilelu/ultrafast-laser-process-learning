import type { ReactNode } from 'react'

export function Card({
  title,
  actions,
  children,
  className = '',
}: {
  title?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-header">
          <h3 className="card-title">{title}</h3>
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      <div className="card-body">{children}</div>
    </section>
  )
}

export function Spinner() {
  return <span className="spinner" aria-label="loading" />
}

export function EmptyState({ message, hint }: { message: string; hint?: ReactNode }) {
  return (
    <div className="empty-state">
      <div className="empty-state-message">{message}</div>
      {hint && <div className="empty-state-hint">{hint}</div>}
    </div>
  )
}

export function ErrorBanner({ message }: { message: string | null }) {
  if (!message) return null
  return <div className="error-banner">{message}</div>
}
