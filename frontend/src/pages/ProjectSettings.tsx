import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'
import { api } from '../api'
import { ProjectHeader } from '../components/ProjectHeader'
import { Button, Field, Input, Panel, Textarea } from '../components/ui'
import { useProjectOptional } from '../context/ProjectContext'

export function ProjectSettingsPage() {
  const { projectId: paramProjectId } = useParams()
  const projectCtx = useProjectOptional()
  const projectId = paramProjectId || projectCtx?.activeProjectId || ''
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const project = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.project(projectId),
    enabled: !!projectId,
  })
  const projects = useQuery({ queryKey: ['projects'], queryFn: api.projects })

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  useEffect(() => {
    if (project.data) {
      setName(project.data.name)
      setDescription(project.data.description ?? '')
    }
  }, [project.data])

  const update = useMutation({
    mutationFn: () => api.updateProject(projectId, { name: name.trim(), description: description.trim() || '' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project', projectId] })
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      toast.success('Project updated')
    },
    onError: (err) => toast.error(err.message),
  })

  const remove = useMutation({
    mutationFn: () => api.deleteProject(projectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      toast.success('Project deleted')
      navigate('/projects')
    },
    onError: (err) => toast.error(err.message),
  })

  if (project.isLoading) return <p className="text-sm text-muted">Loading project…</p>
  if (project.error || !project.data) {
    return (
      <div className="flex flex-col gap-3">
        <p className="display text-3xl">Project not found</p>
        <Link to="/projects" className="label underline underline-offset-4">
          Back to projects
        </Link>
      </div>
    )
  }

  const canDelete = (projects.data?.length ?? 0) > 1
  const dirty = name.trim() !== project.data.name || description.trim() !== (project.data.description ?? '')

  return (
    <div className="flex flex-col gap-8">
      <ProjectHeader project={project.data} />

      <Panel className="p-6">
        <form
          className="flex max-w-xl flex-col gap-5"
          onSubmit={(e) => {
            e.preventDefault()
            if (name.trim()) update.mutate()
          }}
        >
          <Field label="Project name">
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Description">
            <Textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          <div className="flex justify-end">
            <Button type="submit" loading={update.isPending} disabled={!dirty || !name.trim()}>
              {dirty ? 'Save changes' : 'Saved'}
            </Button>
          </div>
        </form>
      </Panel>

      <Panel className="flex flex-wrap items-center justify-between gap-4 border-bad/30 p-6">
        <div>
          <p className="font-semibold text-ink">Delete project</p>
          <p className="text-sm text-muted">
            {canDelete
              ? 'Deletes this project, its runs, and disconnects all associated channels.'
              : 'At least one project is required.'}
          </p>
        </div>
        <Button
          variant="danger"
          disabled={!canDelete}
          loading={remove.isPending}
          onClick={() => {
            if (confirm(`Delete project "${project.data.name}" and all of its runs and channels?`)) {
              remove.mutate()
            }
          }}
        >
          <Trash2 className="h-4 w-4" /> Delete project
        </Button>
      </Panel>
    </div>
  )
}

