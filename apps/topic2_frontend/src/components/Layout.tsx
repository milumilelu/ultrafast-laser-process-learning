/** App layout: header (health + acceptance badge), left navigation, main content, Agent sidebar. */

import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'

import { agentApi } from '../api/agent'
import { topic2Api } from '../api/topic2'
import { config } from '../config'
import { useAgentStore } from '../stores/agent'
import { usePageContextStore } from '../stores/pageContext'
import type { PageName } from '../stores/pageContext'
import { AgentSidebar } from './AgentSidebar'
import { StatusBadge } from './StatusBadge'
import { TaskContextBar } from './TaskContextBar'
import { TaskContextSync } from './TaskContextSync'

const NAV_ITEMS: { to: string; label: string; page: PageName }[] = [
  { to: '/', label: '首页', page: 'home' },
  { to: '/task', label: '工艺任务', page: 'task' },
  { to: '/identification', label: '参数辨识', page: 'identification' },
  { to: '/modeling', label: '工艺建模', page: 'modeling' },
  { to: '/optimization', label: '工艺优化', page: 'optimization' },
  { to: '/database', label: '工艺数据库', page: 'database' },
  { to: '/runs', label: '运行记录', page: 'runs' },
]

function useHealth() {
  const [topic2Ok, setTopic2Ok] = useState<boolean | null>(null)
  const setDegraded = useAgentStore((state) => state.setDegraded)

  useEffect(() => {
    topic2Api
      .health()
      .then(() => setTopic2Ok(true))
      .catch(() => setTopic2Ok(false))
    agentApi
      .health()
      .then(() => setDegraded(false))
      .catch(() => setDegraded(true))
  }, [setDegraded])

  return topic2Ok
}

export function Layout() {
  const topic2Ok = useHealth()
  const location = useLocation()
  const setPage = usePageContextStore((state) => state.setPage)
  const agentDegraded = useAgentStore((state) => state.degraded)

  useEffect(() => {
    const item = NAV_ITEMS.find((nav) =>
      nav.to === '/' ? location.pathname === '/' : location.pathname.startsWith(nav.to),
    )
    if (item) setPage(item.page)
  }, [location.pathname, setPage])

  return (
    <div className="app-shell">
      <TaskContextSync />
      <header className="app-header">
        <span className="brand">超快激光加工工艺智能规划系统</span>
        {config.acceptanceMode && <StatusBadge tone="info">验收模式</StatusBadge>}
        <span className="spacer" />
        <StatusBadge tone={topic2Ok === false ? 'err' : 'ok'}>
          Topic2 {topic2Ok === false ? '离线' : '在线'}
        </StatusBadge>
        <StatusBadge tone={agentDegraded ? 'warn' : 'ok'}>
          Agent {agentDegraded ? '降级' : '在线'}
        </StatusBadge>
      </header>
      <TaskContextBar />
      <div className="app-body">
        <nav className="app-nav">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => (isActive ? 'active' : '')}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <main className="app-main">
          <Outlet />
        </main>
        <AgentSidebar />
      </div>
    </div>
  )
}
