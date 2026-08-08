/** AssistantDrawer (UI-1/5.3): 右下 AI 助手可展开 Drawer，三个 Tab：
 *  [对话] [执行流] [引用与审计]。不再永久占据主工作区 380px。 */

import { useState } from 'react'

import { ActivityTimeline } from './ActivityTimeline'
import { AuditReferences } from './AuditReferences'
import { ChatTab } from './ChatTab'
import { StatusBadge } from '../StatusBadge'
import { useAgentStore } from '../../stores/agent'

type DrawerTab = 'chat' | 'activity' | 'audit'

export function AssistantDrawer() {
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState<DrawerTab>('chat')
  const status = useAgentStore((state) => state.status)
  const degraded = useAgentStore((state) => state.degraded)

  return (
    <>
      <button
        className="assistant-fab"
        onClick={() => {
          setOpen((value) => !value)
          setTab('chat')
        }}
        data-testid="assistant-fab"
      >
        AI 助手
        {degraded && <span className="fab-dot warn" />}
        {(status === 'thinking' ||
          status === 'calling_tool' ||
          status === 'waiting_backend') && <span className="fab-dot ok" />}
      </button>

      {open && (
        <div className="assistant-drawer" data-testid="assistant-drawer">
          <div className="drawer-header">
            <span className="drawer-title">AI 助手</span>
            <StatusBadge tone={degraded ? 'warn' : 'ok'}>
              {degraded ? '降级' : '在线'}
            </StatusBadge>
            <span className="spacer" />
            <button className="btn small" onClick={() => setOpen(false)}>
              收起
            </button>
          </div>
          <div className="drawer-tabs">
            <button
              className={tab === 'chat' ? 'active' : ''}
              onClick={() => setTab('chat')}
            >
              对话
            </button>
            <button
              className={tab === 'activity' ? 'active' : ''}
              onClick={() => setTab('activity')}
            >
              执行流
            </button>
            <button
              className={tab === 'audit' ? 'active' : ''}
              onClick={() => setTab('audit')}
            >
              引用与审计
            </button>
          </div>
          <div className="drawer-body">
            {tab === 'chat' && <ChatTab />}
            {tab === 'activity' && <ActivityTimeline />}
            {tab === 'audit' && <AuditReferences />}
          </div>
        </div>
      )}
    </>
  )
}
