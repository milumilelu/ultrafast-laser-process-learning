import { NavLink, useParams } from 'react-router-dom'
import { useUiStore } from '../../stores/ui'
import { getTaskDraft } from '../../stores/taskDrafts'
import { useApplicationRun } from '../../features/workspace/useRunState'

const NAV_ITEMS = [
  { to: '/workspace', label: '工作台', match: '/workspace' },
  { to: '/knowledge', label: '科学知识', match: '/knowledge' },
  { to: '/data', label: '实验数据', match: '/data' },
  { to: '/runs', label: '运行记录', match: '/runs' },
  { to: '/resources/materials', label: '资源', match: '/resources' },
  { to: '/settings', label: '系统', match: '/settings' },
]

export function NavRail() {
  return (
    <nav className="nav-rail" aria-label="主导航">
      <div className="nav-brand">Physics-to-Planning</div>
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

/** Global context bar: task / material / process / target / dataset / machine / run. */
export function GlobalContextBar() {
  const { taskId } = useParams()
  const draft = taskId ? getTaskDraft(taskId) : null
  const developerMode = useUiStore((state) => state.developerMode)
  const toggleDeveloperMode = useUiStore((state) => state.toggleDeveloperMode)
  const run = useApplicationRun(draft?.runId ?? null)

  return (
    <header className="global-bar">
      <div className="global-context">
        {draft ? (
          <>
            <span className="context-chip">
              Task: <strong>{draft.taskId}</strong>
              {draft.taskContextRef ? `:v${draft.version}` : ''}
            </span>
            {draft.material && (
              <span className="context-chip">Material: <strong>{draft.material}</strong></span>
            )}
            {draft.laserType && (
              <span className="context-chip">Process: <strong>{draft.laserType} laser</strong></span>
            )}
            {draft.objectiveMetric && (
              <span className="context-chip">
                Target: <strong>{draft.objectiveMetric.replace('_um', '')} ↓</strong>
              </span>
            )}
            {draft.equipmentProfileId && (
              <span className="context-chip">Machine: <strong>{draft.equipmentProfileId}</strong></span>
            )}
            {draft.runId && (
              <span className="context-chip">
                Run: <strong>{draft.runId.slice(0, 12)}…</strong>{' '}
                {run ? `(${run.status})` : ''}
              </span>
            )}
          </>
        ) : (
          <span className="context-chip">未选择任务</span>
        )}
      </div>
      <div className="global-modes">
        <span className="mode-label">Research</span>
        <button
          className={`mode-toggle ${developerMode ? 'mode-toggle-on' : ''}`}
          onClick={toggleDeveloperMode}
          role="switch"
          aria-checked={developerMode}
        >
          Developer Mode
        </button>
      </div>
    </header>
  )
}
