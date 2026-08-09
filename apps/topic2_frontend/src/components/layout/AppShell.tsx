import { NavLink } from 'react-router-dom'

const NAV_ITEMS = [
  { to: '/evidence-prior', label: '证据 → 先验', match: '/evidence-prior' },
  { to: '/resources/equipment', label: '设备档案', match: '/resources/equipment' },
  { to: '/resources/literature', label: '文献库', match: '/resources/literature' },
  { to: '/settings', label: '系统', match: '/settings' },
]

export function NavRail() {
  return (
    <nav className="nav-rail" aria-label="主导航">
      <div className="nav-brand">Ultrafast Evidence→Prior</div>
      <ul className="nav-list">
        {NAV_ITEMS.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              className={({ isActive }) => (isActive ? 'nav-item nav-item-active' : 'nav-item')}
            >
              {item.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}

export function GlobalContextBar() {
  return (
    <header className="global-bar">
      <div className="global-context">
        <span className="context-chip"><strong>Evidence Pipeline V1</strong></span>
        <span className="context-chip">Requirement × Paper 独立抽取</span>
      </div>
      <div className="global-modes">
        <span className="mode-label">治理非阻断 · 先验仅为软引导</span>
      </div>
    </header>
  )
}
