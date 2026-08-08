import { Outlet } from 'react-router-dom'
import { GlobalContextBar, NavRail } from './AppShell'

export function AppShell() {
  return (
    <div className="app-shell">
      <NavRail />
      <div className="app-main">
        <GlobalContextBar />
        <main className="app-content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
