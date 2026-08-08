import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom'

import { AppShell } from './components/shell/AppShell'
import { LEGACY_ROUTE_REDIRECTS } from './lib/routes'
import { AuditWorkspace } from './pages/AuditWorkspace'
import { DataResourcePage } from './pages/DataResourcePage'
import { EquipmentResourcePage } from './pages/EquipmentResourcePage'
import { IntelligentProcessApplication } from './pages/IntelligentProcessApplication'
import { LiteratureResourcePage } from './pages/LiteratureResourcePage'
import { ProjectWorkspace } from './pages/ProjectWorkspace'
import { ScientificEvidenceWorkspace } from './pages/ScientificEvidenceWorkspace'
import { TaskAndDataWorkspace } from './pages/TaskAndDataWorkspace'
import { Topic2DemoWorkspace } from './pages/Topic2DemoWorkspace'

const legacyRoutes = Object.entries(LEGACY_ROUTE_REDIRECTS)

const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <ProjectWorkspace /> },
      { path: 'task', element: <TaskAndDataWorkspace /> },
      { path: 'evidence', element: <ScientificEvidenceWorkspace /> },
      { path: 'application', element: <IntelligentProcessApplication /> },
      { path: 'runs', element: <AuditWorkspace /> },
      { path: 'demo', element: <Topic2DemoWorkspace /> },
      { path: 'resources/data', element: <DataResourcePage /> },
      { path: 'resources/literature', element: <LiteratureResourcePage /> },
      { path: 'resources/equipment', element: <EquipmentResourcePage /> },
      // 旧路由兼容（UI1-G4）：自动跳转新页面
      ...legacyRoutes.map(([from, to]) => ({
        path: from,
        element: <Navigate to={to} replace />,
      })),
      { path: '*', element: <Navigate to="/" replace /> },
    ],
  },
])

export function App() {
  return <RouterProvider router={router} />
}
