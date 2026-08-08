/** FeatureViewSelector (12.2): RAW / PHYSICS / HYBRID。研究模式可切换，演示模式锁定。 */

export type FeatureViewMode = 'raw' | 'physics' | 'hybrid'

const VIEWS: { value: FeatureViewMode; label: string; hint: string }[] = [
  { value: 'raw', label: 'RAW', hint: '仅可控参数' },
  { value: 'physics', label: 'PHYSICS', hint: '仅机理特征' },
  { value: 'hybrid', label: 'HYBRID', hint: '混合' },
]

export function FeatureViewSelector({
  value,
  onChange,
  readonly = false,
  selectedViewLabel,
}: {
  value: FeatureViewMode
  onChange: (mode: FeatureViewMode) => void
  readonly?: boolean
  selectedViewLabel?: string | null
}) {
  return (
    <div className="row" data-testid="feature-view-selector" style={{ marginBottom: 12 }}>
      {VIEWS.map((view) => (
        <label key={view.value} style={{ marginRight: 16 }}>
          <input
            type="radio"
            name="feature-view"
            value={view.value}
            checked={value === view.value}
            disabled={readonly}
            onChange={() => onChange(view.value)}
          />
          {view.label}（{view.hint}）
        </label>
      ))}
      {selectedViewLabel && (
        <span className="badge info">系统选择：{selectedViewLabel}</span>
      )}
    </div>
  )
}
