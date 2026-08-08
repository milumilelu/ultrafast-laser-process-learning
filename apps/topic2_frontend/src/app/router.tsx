import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom'
import { AppShell } from '../components/layout/AppShellOutlet'
import { WorkspaceLanding, WorkspacePage } from '../features/workspace/WorkspacePage'
import { RunInspectorPage, RunsPage } from '../features/runs/RunInspectorPage'
import { KnowledgeAssetsPage } from '../pages/KnowledgeAssetsPage'
import { DataPage } from '../pages/DataPage'
import { ResourcesPage, SettingsPage } from '../pages/ResourcesPages'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/workspace" replace /> },
      { path: 'workspace', element: <WorkspaceLanding /> },
      { path: 'workspace/:taskId', element: <WorkspacePage /> },
      { path: 'workspace/:taskId/:section', element: <WorkspacePage /> },
      { path: 'knowledge', element: <KnowledgeAssetsPage /> },
      { path: 'data', element: <DataPage /> },
      { path: 'data/:datasetId', element: <DataPage /> },
      { path: 'runs', element: <RunsPage /> },
      { path: 'runs/:runId', element: <RunInspectorPage /> },
      { path: 'resources/materials', element: <ResourcesPage kind="materials" /> },
      { path: 'resources/machines', element: <ResourcesPage kind="machines" /> },
      { path: 'resources/literature', element: <ResourcesPage kind="literature" /> },
      { path: 'settings', element: <SettingsPage /> },
    ],
  },
])

export function App() {
  return <RouterProvider router={router} />
}
