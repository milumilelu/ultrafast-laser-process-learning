export function ErrorBanner({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <div className="error-banner" role="alert">
      <span>✕</span>
      <span>{message}</span>
    </div>
  )
}

export function WarnBanner({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <div className="warn-banner" role="alert">
      <span>△</span>
      <span>{message}</span>
    </div>
  )
}

export function EmptyState({ message }: { message: string }) {
  return <div className="empty-state">{message}</div>
}
