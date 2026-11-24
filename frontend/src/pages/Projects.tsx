import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, FolderPlus, Radio, Video } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { toast } from 'sonner'
import { api, type Project } from '../api'
import { Button, Eyebrow, Field, Input, Panel, cn } from '../components/ui'
import { useProjectOptional } from '../context/ProjectContext'

export function ProjectsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const projectCtx = useProjectOptional()
  const projects = useQuery({ queryKey: ['projects'], queryFn: api.projects })
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  const create = useMutation({
    mutationFn: () => api.createProject({ name: name.trim(), description: description.trim() || null }),
    onSuccess: (project) => {
      queryClient.setQueryData<Project[]>(['projects'], (prev) => [...(prev ?? []), project])
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      projectCtx?.setActiveProjectId(project.id)
      toast.success(`Project "${project.name}" created`)
      setName('')
      setDescription('')
      setCreating(false)
      navigate(`/projects/${project.id}/channels`)
    },
    onError: (err) => toast.error(err.message),
  })

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-3">
          <Eyebrow>Workspace</Eyebrow>
          <h1 className="display text-4xl">Projects</h1>
          <p className="max-w-xl text-[15px] text-body">
            Organize your video runs and connected social channels by brand or channel group.
          </p>
        </div>
        <Button variant={creating ? 'line' : 'ink'} onClick={() => setCreating(!creating)}>
          <FolderPlus className="h-4 w-4" /> {creating ? 'Cancel' : 'New project'}
        </Button>
      </header>

      {creating && (
        <Panel className="border-l-4 border-l-acid p-6">
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault()
              if (name.trim()) create.mutate()
            }}
          >
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Project name">
                <Input
                  placeholder="e.g. GTA 6"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  autoFocus
                />
              </Field>
              <Field label="Description" hint="Optional">
                <Input
                  placeholder="Clips and Shorts for GTA 6"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </Field>
            </div>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => setCreating(false)}>
                Cancel
              </Button>
              <Button type="submit" variant="acid" loading={create.isPending} disabled={!name.trim()}>
                Create project <ArrowRight className="h-4 w-4" />
              </Button>
            </div>
          </form>
        </Panel>
      )}

      {projects.isLoading ? (
        <Panel className="p-6 text-sm text-muted">Loading projects…</Panel>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {(projects.data ?? []).map((project) => {
            const isActive = project.id === projectCtx?.activeProjectId
            return (
            <Panel key={project.id} className={cn('flex flex-col justify-between gap-5 p-6', isActive && 'border-ink')}>
              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="label text-faint">{project.slug}</span>
                  <div className="flex items-center gap-1.5">
                    {isActive && (
                      <span className="label px-sm bg-acid px-2 py-0.5 !text-[10px] text-ink">Active</span>
                    )}
                    {project.is_default && (
                      <span className="label px-sm bg-sunk px-2 py-0.5 !text-[10px] text-muted">Default</span>
                    )}
                  </div>
                </div>
                <Link to={`/projects/${project.id}/runs`} className="text-xl font-semibold tracking-tight hover:underline">
                  {project.name}
                </Link>
                {project.description && <p className="text-[13px] leading-relaxed text-muted">{project.description}</p>}
              </div>

              <div className="flex flex-col gap-4 border-t border-line pt-4">
                <div className="label flex items-center gap-4 text-muted">
                  <span className="inline-flex items-center gap-1.5">
                    <Video className="h-3.5 w-3.5" /> {project.run_count} runs
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <Radio className="h-3.5 w-3.5" /> {project.channel_count} channels
                  </span>
                </div>
                <div className="flex gap-2">
                  {!isActive && projectCtx && (
                    <Button variant="line" size="sm" onClick={() => projectCtx.setActiveProjectId(project.id)}>
                      Set active
                    </Button>
                  )}
                  <Link to={`/projects/${project.id}/runs`} className="flex-1">
                    <Button variant="line" size="sm" className="w-full">
                      Runs
                    </Button>
                  </Link>
                  <Link to={`/projects/${project.id}/channels`} className="flex-1">
                    <Button variant="ink" size="sm" className="w-full">
                      Channels
                    </Button>
                  </Link>
                </div>
              </div>
            </Panel>
            )
          })}
        </div>
      )}
    </div>
  )
}

