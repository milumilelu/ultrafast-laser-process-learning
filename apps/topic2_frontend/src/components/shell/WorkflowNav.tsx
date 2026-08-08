/** WorkflowNav (UI-1): 按应用问题组织的导航，取代功能模块式导航。 */

import { NavLink } from 'react-router-dom'

interface NavItem {
  to: string
  label: string
}

interface NavGroup {
  title: string
  items: NavItem[]
}

const NAV_GROUPS: NavGroup[] = [
  { title: '项目', items: [{ to: '/', label: '项目概览' }] },
  {
    title: '研究',
    items: [
      { to: '/task', label: '任务与数据' },
      { to: '/evidence', label: '科学知识' },
    ],
  },
  {
    title: '应用',
    items: [{ to: '/application', label: '工艺智能应用' }],
  },
  { title: '追溯', items: [{ to: '/runs', label: '运行与审计' }] },
  {
    title: '资源',
    items: [
      { to: '/resources/data', label: '实验数据' },
      { to: '/resources/literature', label: '文献库' },
      { to: '/resources/equipment', label: '设备档案' },
    ],
  },
]

export function WorkflowNav() {
  return (
    <nav className="workflow-nav" data-testid="workflow-nav">
      {NAV_GROUPS.map((group) => (
        <div key={group.title} className="nav-group">
          <div className="nav-group-title">{group.title}</div>
          {group.items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) => (isActive ? 'active' : '')}
            >
              {item.label}
            </NavLink>
          ))}
        </div>
      ))}
    </nav>
  )
}
