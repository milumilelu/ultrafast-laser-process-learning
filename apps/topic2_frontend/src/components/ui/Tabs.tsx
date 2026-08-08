import type { ReactNode } from 'react'

export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: { id: string; label: string }[]
  active: string
  onChange: (id: string) => void
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          role="tab"
          aria-selected={tab.id === active}
          className={`tab ${tab.id === active ? 'tab-active' : ''}`}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}

export function DataTable<T>({
  columns,
  rows,
  keyOf,
  emptyMessage = '暂无数据',
}: {
  columns: { key: string; label: string; render?: (row: T) => ReactNode; width?: string }[]
  rows: T[]
  keyOf: (row: T) => string
  emptyMessage?: string
}) {
  if (rows.length === 0) return <EmptyTable message={emptyMessage} />
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col.key} style={col.width ? { width: col.width } : undefined}>
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={keyOf(row)}>
              {columns.map((col) => (
                <td key={col.key}>{col.render ? col.render(row) : String((row as Record<string, unknown>)[col.key] ?? '—')}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function EmptyTable({ message }: { message: string }) {
  return <div className="table-empty">{message}</div>
}
