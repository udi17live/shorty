import { ArrowRight } from 'lucide-react'
import { Link, NavLink } from 'react-router'
import type { Project } from '../api'
import { useProjectOptional } from '../context/ProjectContext'
import { Button, Eyebrow, cn } from './ui'

export function ProjectHeader({ project }: { project: Project }) {
  const projectCtx = useProjectOptional()
  const tabClass = ({ isActive }: { isActive: boolean }) =>
    cn(
      'label inline-flex h-10 items-center border-b-2 px-1 transition-colors',
      isActive ? 'border-ink text-ink' : 'border-transparent text-muted hover:text-ink',
    )

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-2.5">
          <Eyebrow>Project · {project.slug}</Eyebrow>
          <h1 className="display text-4xl">{project.name}</h1>
          {project.description && <p className="max-w-2xl text-sm text-body">{project.description}</p>}
        </div>
        <Link to="/" onClick={() => projectCtx?.setActiveProjectId(project.id)}>
          <Button variant="acid">
            New clips <ArrowRight className="h-4 w-4" />
          </Button>
        </Link>
      </div>

      <nav aria-label="Project navigation" className="flex gap-6 border-b border-line">
        <NavLink to={`/projects/${project.id}/runs`} className={tabClass}>
          Runs ({project.run_count})
        </NavLink>
        <NavLink to={`/projects/${project.id}/channels`} className={tabClass}>
          Channels ({project.channel_count})
        </NavLink>
        <NavLink to={`/projects/${project.id}/settings`} className={tabClass}>
          Settings
        </NavLink>
      </nav>
    </div>
  )
}

