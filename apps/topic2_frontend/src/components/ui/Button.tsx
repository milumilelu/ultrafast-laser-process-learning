export function Button({
  children,
  onClick,
  disabled,
  variant = 'primary',
  busy,
}: {
  children: React.ReactNode
  onClick?: () => void
  disabled?: boolean
  variant?: 'primary' | 'ghost' | 'danger'
  busy?: boolean
}) {
  return (
    <button
      className={`btn btn-${variant}`}
      onClick={onClick}
      disabled={disabled || busy}
    >
      {busy && <span className="spinner spinner-inline" />}
      {children}
    </button>
  )
}
