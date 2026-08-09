import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom'
import { AppShell } from '../components/layout/AppShellOutlet'
import { EvidencePriorPage } from '../features/evidencePrior/EvidencePriorPage'
import { ResourcesPage, SettingsPage } from '../pages/ResourcesPages'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/evidence-prior" replace /> },
      { path: 'evidence-prior', element: <EvidencePriorPage /> },
      { path: 'resources/equipment', element: <ResourcesPage kind="machines" /> },
      { path: 'resources/literature', element: <ResourcesPage kind="literature" /> },
      { path: 'settings', element: <SettingsPage /> },
      { path: '*', element: <Navigate to="/evidence-prior" replace /> },
    ],
  },
])

export function App() {
  return <RouterProvider router={router} />
}
