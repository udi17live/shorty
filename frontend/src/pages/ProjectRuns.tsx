import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router'
import { api, type Run } from '../api'
import { ProjectHeader } from '../components/ProjectHeader'
import { Empty, Panel, Squares, StatusChip, sourceHost, sourceLabel, timeAgo } from '../components/ui'
import { useProjectOptional } from '../context/ProjectContext'
import { STAGE_ORDER } from './Runs'

function progress(run: Run) {
  if (run.status === 'completed') return STAGE_ORDER.length
  if (!run.current_stage) return 0
  return STAGE_ORDER.indexOf(run.current_stage)
}

export function ProjectRunsPage() {
  const { projectId: paramProjectId } = useParams()
  const projectCtx = useProjectOptional()
  const projectId = paramProjectId || projectCtx?.activeProjectId || ''
  const navigate = useNavigate()
  const project = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.project(projectId),
    enabled: !!projectId,
  })
  const runs = useQuery({
    queryKey: ['project-runs', projectId],
    queryFn: () => api.projectRuns(projectId),
    enabled: !!projectId,
    refetchInterval: (query) =>
      query.state.data?.some((r) => r.status === 'queued' || r.status === 'running') ? 2000 : 15000,
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

  return (
    <div className="flex flex-col gap-8">
      <ProjectHeader project={project.data} />

      <Panel>
        {runs.isLoading ? (
          <p className="p-6 text-sm text-muted">Loading runs…</p>
        ) : !runs.data?.length ? (
          <Empty
            title="No runs in this project"
            action={
              <Link to="/" className="label text-ink underline underline-offset-4">
                Clip your first video
              </Link>
            }
          >
            Paste a link or drop a file to start a clipping run for {project.data.name}.
          </Empty>
        ) : (
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="label border-b border-line text-faint">
                <th className="px-5 py-3 font-medium">Source</th>
                <th className="hidden px-5 py-3 font-medium lg:table-cell">Progress</th>
                <th className="hidden px-5 py-3 font-medium sm:table-cell">Clips</th>
                <th className="hidden px-5 py-3 font-medium sm:table-cell">Format</th>
                <th className="px-5 py-3 font-medium">Status</th>
                <th className="hidden px-5 py-3 text-right font-medium md:table-cell">Created</th>
              </tr>
            </thead>
            <tbody>
              {runs.data.map((run) => (
                <tr
                  key={run.id}
                  onClick={() => navigate(`/runs/${run.id}`)}
                  className="cursor-pointer border-b border-line transition-colors hover:bg-paper last:border-0"
                >
                  <td className="max-w-0 px-5 py-4">
                    <p className="truncate font-medium">{sourceLabel(run)}</p>
                    <p className="label mt-1 truncate text-faint">
                      {sourceHost(run.source)}
                      {run.status === 'failed' && run.error ? (
                        <span className="normal-case tracking-normal text-bad"> · {run.error}</span>
                      ) : null}
                    </p>
                  </td>
                  <td className="hidden px-5 py-4 lg:table-cell">
                    <Squares total={STAGE_ORDER.length} filled={progress(run)} />
                  </td>
                  <td className="hidden px-5 py-4 font-mono text-[13px] sm:table-cell">
                    {run.status === 'completed' ? run.clip_count : '–'}
                    <span className="text-faint">/{run.options.clip_count}</span>
                  </td>
                  <td className="hidden px-5 py-4 font-mono text-[13px] sm:table-cell">{run.options.aspect_ratio}</td>
                  <td className="px-5 py-4">
                    <StatusChip status={run.status} />
                  </td>
                  <td className="hidden px-5 py-4 text-right font-mono text-[12px] text-muted md:table-cell">
                    {timeAgo(run.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  )
}

