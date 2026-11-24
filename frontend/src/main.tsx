import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, Navigate, RouterProvider, useParams } from 'react-router'
import { Layout } from './components/AppShell'
import './index.css'
import { NewRunPage } from './pages/NewRun'
import { ProjectChannelsPage } from './pages/ProjectChannels'
import { ProjectRunsPage } from './pages/ProjectRuns'
import { ProjectsPage } from './pages/Projects'
import { ProjectSettingsPage } from './pages/ProjectSettings'
import { RunDetailPage } from './pages/RunDetail'
import { RunsPage } from './pages/Runs'
import { SettingsPage } from './pages/Settings'

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } })

function ProjectIndexRedirect() {
  const { projectId = '' } = useParams()
  return <Navigate to={`/projects/${projectId}/runs`} replace />
}

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: '/', element: <NewRunPage /> },
      { path: '/projects', element: <ProjectsPage /> },
      { path: '/projects/:projectId', element: <ProjectIndexRedirect /> },
      { path: '/projects/:projectId/runs', element: <ProjectRunsPage /> },
      { path: '/projects/:projectId/channels', element: <ProjectChannelsPage /> },
      { path: '/projects/:projectId/settings', element: <ProjectSettingsPage /> },
      { path: '/runs', element: <RunsPage /> },
      { path: '/runs/:runId', element: <RunDetailPage /> },
      { path: '/settings', element: <SettingsPage /> },
    ],
  },
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
