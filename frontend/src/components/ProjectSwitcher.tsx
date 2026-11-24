import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, Plus } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { api, type Project } from '../api'
import { useProject } from '../context/ProjectContext'
import { Button, Input, cn } from './ui'

export function ProjectSwitcher({ compact = false }: { compact?: boolean }) {
  const queryClient = useQueryClient()
  const { projects, activeProject, isLoading, isError, selectProject, retryProjects } = useProject()
  const [open, setOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onMouseDown = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false)
        setCreating(false)
      }
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false)
        setCreating(false)
      }
    }
    document.addEventListener('mousedown', onMouseDown)
    window.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onMouseDown)
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  const createProject = useMutation({
    mutationFn: () => api.createProject({ name: name.trim() }),
    onSuccess: (project) => {
      queryClient.setQueryData<Project[]>(['projects'], (prev) => [...(prev ?? []), project])
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      selectProject(project.id)
      setName('')
      setCreating(false)
      setOpen(false)
      toast.success(`Project "${project.name}" created`)
    },
    onError: (err) => toast.error(err.message),
  })

  if (isLoading) {
    return (
      <div className={cn('border border-line bg-paper', compact ? 'px-2.5 py-1.5' : 'px-3 py-2')}>
        <p className="label !text-[10px] text-faint">Project</p>
        <p className="mt-0.5 text-xs text-muted">Loading…</p>
      </div>
    )
  }

  if (isError) {
    return (
      <div className={cn('border border-bad/40 bg-bad-soft', compact ? 'px-2.5 py-1.5' : 'px-3 py-2')}>
        <div className="flex items-center justify-between gap-2">
          <span className="label !text-[10px] text-bad">Projects error</span>
          <button
            type="button"
            onClick={retryProjects}
            className="label !text-[10px] cursor-pointer text-ink underline underline-offset-2"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  return (
    <div ref={containerRef} className="relative">
      {activeProject ? (
        <button
          type="button"
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-label={`Active project: ${activeProject.name}. Switch project`}
          onClick={() => {
            setOpen((v) => !v)
            setCreating(false)
          }}
          className={cn(
            'flex w-full cursor-pointer items-center justify-between gap-2 border text-left transition-colors',
            compact ? 'h-9 max-w-[180px] px-2.5' : 'px-3 py-2',
            open ? 'border-ink bg-paper' : 'border-line-strong bg-surface hover:border-ink hover:bg-paper',
          )}
        >
          <span className="min-w-0 flex-1">
            {!compact && <span className="label block !text-[10px] text-faint">Project</span>}
            <span className={cn('flex items-center gap-2', !compact && 'mt-0.5')}>
              <span className="h-2 w-2 shrink-0 bg-acid ring-1 ring-ink" />
              <span className="truncate text-[13px] font-semibold tracking-tight text-ink">
                {activeProject.name}
              </span>
            </span>
          </span>
          <span className="flex shrink-0 items-center gap-1.5">
            {!compact && <span className="label !text-[10px] text-muted">Switch</span>}
            <ChevronDown className={cn('h-3.5 w-3.5 text-muted transition-transform', open && 'rotate-180 text-ink')} />
          </span>
        </button>
      ) : (
        <button
          type="button"
          onClick={() => {
            setOpen(true)
            setCreating(true)
          }}
          className="label flex w-full cursor-pointer items-center justify-center gap-2 border border-line-strong bg-surface px-3 py-2.5 text-ink transition-colors hover:border-ink hover:bg-paper"
        >
          <Plus className="h-3.5 w-3.5" /> New project
        </button>
      )}

      {open && (
        <div
          role="listbox"
          aria-label="Projects"
          className={cn(
            'absolute top-full z-40 mt-1 border border-ink bg-surface shadow-[0_6px_0_0_rgb(11_11_11_/_0.08)]',
            compact ? 'right-0 w-[230px]' : 'left-0 right-0',
          )}
        >
          <div className="flex items-center justify-between border-b border-line px-3 py-2">
            <span className="label !text-[10px] text-faint">Project</span>
            <span className="label !text-[10px] text-faint">{projects.length}</span>
          </div>

          <div className="max-h-56 overflow-y-auto py-1">
            {projects.length === 0 ? (
              <p className="px-3 py-2 text-xs text-muted">No projects yet.</p>
            ) : (
              projects.map((project) => {
                const isActive = project.id === activeProject?.id
                return (
                  <button
                    key={project.id}
                    type="button"
                    role="option"
                    aria-selected={isActive}
                    onClick={() => {
                      selectProject(project.id)
                      setOpen(false)
                      setCreating(false)
                    }}
                    className={cn(
                      'flex w-full cursor-pointer items-center gap-2.5 px-3 py-2 text-left text-[13px] transition-colors',
                      isActive ? 'bg-sunk font-semibold text-ink' : 'text-body hover:bg-paper hover:text-ink',
                    )}
                  >
                    <span
                      className={cn(
                        'h-2 w-2 shrink-0',
                        isActive ? 'bg-acid ring-1 ring-ink' : 'border border-line-strong bg-transparent',
                      )}
                    />
                    <span className="min-w-0 flex-1 truncate">{project.name}</span>
                    {project.is_default && <span className="label !text-[9px] text-faint">Default</span>}
                  </button>
                )
              })
            )}
          </div>

          <div className="border-t border-line p-2">
            {creating ? (
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  if (name.trim()) createProject.mutate()
                }}
              >
                <Input
                  aria-label="New project name"
                  placeholder="Project name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="h-8 text-xs"
                  autoFocus
                />
                <div className="mt-2 flex justify-end gap-1.5">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2 text-xs"
                    onClick={() => {
                      setCreating(false)
                      setName('')
                      if (!activeProject) setOpen(false)
                    }}
                  >
                    Cancel
                  </Button>
                  <Button
                    type="submit"
                    variant="acid"
                    size="sm"
                    className="h-7 px-2.5 text-xs"
                    loading={createProject.isPending}
                    disabled={!name.trim()}
                  >
                    Create
                  </Button>
                </div>
              </form>
            ) : (
              <button
                type="button"
                onClick={() => setCreating(true)}
                className="label flex w-full cursor-pointer items-center gap-2 px-2 py-1.5 text-ink transition-colors hover:bg-paper"
              >
                <Plus className="h-3.5 w-3.5" /> New project
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
