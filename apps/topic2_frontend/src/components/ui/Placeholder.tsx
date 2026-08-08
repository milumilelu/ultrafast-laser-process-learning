import { EmptyState, Card } from './Card'

export function PlaceholderPage({
  title,
  message,
  hint,
}: {
  title: string
  message: string
  hint: string
}) {
  return (
    <div className="section">
      <h1>{title}</h1>
      <Card>
        <EmptyState message={message} hint={hint} />
      </Card>
    </div>
  )
}
