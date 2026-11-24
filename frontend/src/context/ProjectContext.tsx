import { useQuery } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router'
import { api, type Project } from '../api'

export const ACTIVE_PROJECT_STORAGE_KEY = 'shorty.activeProjectId'

export interface ProjectContextValue {
  projects: Project[]
  activeProjectId: string | null
  activeProject: Project | null
  isLoading: boolean
  isError: boolean
  error: Error | null
  selectProject: (projectId: string) => void
  setActiveProjectId: (projectId: string) => void
  retryProjects: () => void
}

const ProjectContext = createContext<ProjectContextValue | null>(null)

export function readStoredProjectId(): string | null {
  try {
    const value = window.localStorage.getItem(ACTIVE_PROJECT_STORAGE_KEY)
    return value && value.trim() ? value.trim() : null
  } catch {
    return null
  }
}

export function writeStoredProjectId(projectId: string | null): void {
  try {
    if (projectId) {
      window.localStorage.setItem(ACTIVE_PROJECT_STORAGE_KEY, projectId)
    } else {
      window.localStorage.removeItem(ACTIVE_PROJECT_STORAGE_KEY)
    }
  } catch {
    // Ignore storage quota or restricted-context errors
  }
}

export function ProjectProvider({ children }: { children: ReactNode }) {
  const { projectId: urlProjectId } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const [selectedId, setSelectedId] = useState<string | null>(() => readStoredProjectId())

  const projectsQuery = useQuery({
    queryKey: ['projects'],
    queryFn: api.projects,
  })

  const projects = useMemo(() => projectsQuery.data ?? [], [projectsQuery.data])

  useEffect(() => {
    if (!projectsQuery.isSuccess) return

    if (projects.length === 0) {
      if (selectedId !== null) setSelectedId(null)
      writeStoredProjectId(null)
      return
    }

    // Deep-linked /projects/:projectId/... URLs align the active project when valid.
    if (urlProjectId && projects.some((p) => p.id === urlProjectId)) {
      if (selectedId !== urlProjectId) {
        setSelectedId(urlProjectId)
      }
      writeStoredProjectId(urlProjectId)
      return
    }

    if (selectedId && projects.some((p) => p.id === selectedId)) {
      writeStoredProjectId(selectedId)
      return
    }

    // Stored ID is missing, deleted, or inaccessible: fall back to default or first project.
    const fallback = projects.find((p) => p.is_default) ?? projects[0]
    setSelectedId(fallback.id)
    writeStoredProjectId(fallback.id)
  }, [projectsQuery.isSuccess, projects, urlProjectId, selectedId])

  const activeProject = useMemo(
    () => projects.find((p) => p.id === selectedId) ?? null,
    [projects, selectedId],
  )
  const activeProjectId = activeProject?.id ?? null

  const setActiveProjectId = useCallback((projectId: string) => {
    setSelectedId(projectId)
    writeStoredProjectId(projectId)
  }, [])

  const selectProject = useCallback(
    (projectId: string) => {
      setSelectedId(projectId)
      writeStoredProjectId(projectId)
      const match = location.pathname.match(/^\/projects\/[^/]+(.*)$/)
      if (match) {
        const suffix = match[1] || '/runs'
        navigate(`/projects/${encodeURIComponent(projectId)}${suffix}`)
      }
    },
    [location.pathname, navigate],
  )

  const retryProjects = useCallback(() => {
    void projectsQuery.refetch()
  }, [projectsQuery])

  const value = useMemo<ProjectContextValue>(
    () => ({
      projects,
      activeProjectId,
      activeProject,
      isLoading: projectsQuery.isLoading,
      isError: projectsQuery.isError,
      error: projectsQuery.error instanceof Error ? projectsQuery.error : null,
      selectProject,
      setActiveProjectId,
      retryProjects,
    }),
    [
      projects,
      activeProjectId,
      activeProject,
      projectsQuery.isLoading,
      projectsQuery.isError,
      projectsQuery.error,
      selectProject,
      setActiveProjectId,
      retryProjects,
    ],
  )

  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>
}

export function useProject(): ProjectContextValue {
  const ctx = useContext(ProjectContext)
  if (!ctx) {
    throw new Error('useProject must be used within a ProjectProvider')
  }
  return ctx
}

export function useProjectOptional(): ProjectContextValue | null {
  return useContext(ProjectContext)
}

