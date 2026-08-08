/** AppShell (UI-1): 新式布局 - Header（模式/健康）+ Global Context Bar +
 *  Workflow Nav + Main + 底部状态摘要 + 右下 AI 助手 Drawer。 */

import { useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'

import { agentApi } from '../../api/agent'
import { topic2Api } from '../../api/topic2'
import { APP_BUILD_TIME, APP_VERSION, config } from '../../config'
import { useAgentStore } from '../../stores/agent'
import { useModeStore } from '../../stores/mode'
import { usePageContextStore } from '../../stores/pageContext'
import { useTaskContextStore } from '../../stores/taskContext'
import { AssistantDrawer } from '../assistant/AssistantDrawer'
import { StatusBadge } from '../StatusBadge'
import { TaskContextSync } from '../TaskContextSync'
import { GlobalContextBar } from './GlobalContextBar'
import { ModeSwitcher } from './ModeSwitcher'
import { WorkflowNav } from './WorkflowNav'

export function AppShell() {
  const [topic2Ok, setTopic2Ok] = useState<boolean | null>(null)
  const setDegraded = useAgentStore((state) => state.setDegraded)
  const agentDegraded = useAgentStore((state) => state.degraded)
  const mode = useModeStore((state) => state.mode)
  const context = useTaskContextStore((state) => state.context)
  const location = useLocation()
  const setPage = usePageContextStore((state) => state.setPage)

  useEffect(() => {
    const path = location.pathname
    if (path === '/') setPage('home')
    else if (path.startsWith('/task')) setPage('task')
    else if (path.startsWith('/identification')) setPage('identification')
    else if (path.startsWith('/application')) setPage('application')
    else if (path.startsWith('/modeling')) setPage('modeling')
    else if (path.startsWith('/optimization')) setPage('optimization')
    else if (path.startsWith('/runs')) setPage('runs')
  }, [location.pathname, setPage])

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

  return (
    <div className="app-shell">
      <TaskContextSync />
      <header className="app-header">
        <span className="brand">超快激光加工工艺智能规划系统</span>
        {config.acceptanceMode && <StatusBadge tone="info">验收模式</StatusBadge>}
        <span className="spacer" />
        <ModeSwitcher />
        <StatusBadge tone="neutral">
          {APP_VERSION}
          <span className="muted" style={{ marginLeft: 4 }} title={`构建时间 ${APP_BUILD_TIME}`}>
            {APP_BUILD_TIME.slice(5, 16).replace('T', ' ')}
          </span>
        </StatusBadge>
        <StatusBadge tone={topic2Ok === false ? 'err' : 'ok'}>
          Topic2 {topic2Ok === false ? '离线' : '在线'}
        </StatusBadge>
        <StatusBadge tone={agentDegraded ? 'warn' : 'ok'}>
          Agent {agentDegraded ? '降级' : '在线'}
        </StatusBadge>
      </header>
      <GlobalContextBar />
      <div className="app-body">
        <WorkflowNav />
        <main className="app-main">
          <Outlet />
        </main>
      </div>
      <footer className="app-footer">
        <span className="mono">
          {context.taskContextId}:v{context.version}
        </span>
        <span>Task</span>
        <span className="spacer" />
        <span className="mono">{mode === 'demo' ? 'DEMO' : 'RESEARCH'}</span>
        <span>模式</span>
      </footer>
      <AssistantDrawer />
    </div>
  )
}
