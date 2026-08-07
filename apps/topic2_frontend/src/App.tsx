import { createBrowserRouter, RouterProvider } from 'react-router-dom'

import { Layout } from './components/Layout'
import { DatabasePage } from './pages/DatabasePage'
import { HomePage } from './pages/HomePage'
import { IdentificationPage } from './pages/IdentificationPage'
import { ModelingPage } from './pages/ModelingPage'
import { OptimizationPage } from './pages/OptimizationPage'
import { RunsPage } from './pages/RunsPage'
import { TaskPage } from './pages/TaskPage'

const router = createBrowserRouter([
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <HomePage /> },
      { path: 'task', element: <TaskPage /> },
      { path: 'identification', element: <IdentificationPage /> },
      { path: 'modeling', element: <ModelingPage /> },
      { path: 'optimization', element: <OptimizationPage /> },
      { path: 'database', element: <DatabasePage /> },
      { path: 'runs', element: <RunsPage /> },
    ],
  },
])

export function App() {
  return <RouterProvider router={router} />
}
