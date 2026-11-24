import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  api,
  type ConnectedChannel,
  type Health,
  type PlatformDescriptor,
  type Project,
  type Run,
  type RunDetail,
  type Setting,
} from '../api'
import { Layout } from '../components/AppShell'
import { ACTIVE_PROJECT_STORAGE_KEY } from '../context/ProjectContext'
import { NewRunPage } from '../pages/NewRun'
import { ProjectChannelsPage } from '../pages/ProjectChannels'
import { ProjectRunsPage } from '../pages/ProjectRuns'
import { ProjectsPage } from '../pages/Projects'
import { ProjectSettingsPage } from '../pages/ProjectSettings'
import { RunDetailPage } from '../pages/RunDetail'
import { RunsPage } from '../pages/Runs'
import { SettingsPage } from '../pages/Settings'

const DEFAULT_PROJECT: Project = {
  id: 'default',
  name: 'Default Project',
  slug: 'default',
  description: 'Default workspace',
  owner_id: null,
  is_default: true,
  run_count: 1,
  channel_count: 1,
  created_at: '2026-11-25T00:00:00Z',
  updated_at: '2026-11-25T00:00:00Z',
}

const GTA_PROJECT: Project = {
  id: 'gta6',
  name: 'GTA 6',
  slug: 'gta-6',
  description: 'GTA 6 clips',
  owner_id: null,
  is_default: false,
  run_count: 1,
  channel_count: 1,
  created_at: '2026-11-25T01:00:00Z',
  updated_at: '2026-11-25T01:00:00Z',
}

const HEALTH: Health = {
  version: '0.1.0',
  checks: [{ name: 'llm', label: 'LLM', ok: true, required: true, detail: 'Configured' }],
  queue: { queued: 0, running: 0 },
  worker: true,
}

const SETTINGS: Setting[] = [
  {
    key: 'llm_provider',
    value: 'openrouter',
    is_set: true,
    secret: false,
    source: 'default',
    env: 'LLM_PROVIDER',
    description: 'Provider',
  },
  {
    key: 'llm_model',
    value: 'google/gemini-3.8-flash',
    is_set: true,
    secret: false,
    source: 'default',
    env: 'LLM_MODEL',
    description: 'Model',
  },
]

const RUN_DEFAULT: Run = {
  id: 'run-def',
  project_id: 'default',
  project_name: 'Default Project',
  source: 'https://youtu.be/default-vid',
  title: 'Default Video',
  status: 'completed',
  current_stage: null,
  error: null,
  options: {
    clip_count: 3,
    min_seconds: 20,
    max_seconds: 60,
    aspect_ratio: '9:16',
    captions: true,
    caption_style: 'bold',
    face_tracking: true,
    broll: false,
    language: 'auto',
    instructions: '',
    model: null,
  },
  created_at: '2026-11-25T00:00:00Z',
  updated_at: '2026-11-25T00:00:00Z',
  clip_count: 3,
}

const RUN_GTA: Run = {
  ...RUN_DEFAULT,
  id: 'run-gta',
  project_id: 'gta6',
  project_name: 'GTA 6',
  source: 'https://youtu.be/gta6-trailer',
  title: 'GTA 6 Trailer',
}

const CH_DEFAULT: ConnectedChannel = {
  id: 'ch-def',
  project_id: 'default',
  platform: 'youtube',
  external_account_id: null,
  external_channel_id: 'UC_DEF',
  display_name: 'Default Channel',
  handle: '@defaultch',
  avatar_url: null,
  status: 'connected',
  status_message: null,
  metadata: {},
  last_connected_at: '2026-11-25T00:00:00Z',
  created_at: '2026-11-25T00:00:00Z',
  updated_at: '2026-11-25T00:00:00Z',
}

const CH_GTA: ConnectedChannel = {
  ...CH_DEFAULT,
  id: 'ch-gta',
  project_id: 'gta6',
  external_channel_id: 'UC_GTA6',
  display_name: 'GTA 6 Shorts',
  handle: '@gta6shorts',
}

const PLATFORMS: PlatformDescriptor[] = [
  {
    id: 'youtube',
    name: 'YouTube',
    description: 'Connect your YouTube channel',
    status: 'available',
    configured: true,
    config_error: null,
    supports_oauth: true,
    supports_multi_channel: true,
  },
]

function renderApp(initialEntry = '/') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<NewRunPage />} />
            <Route path="/projects" element={<ProjectsPage />} />
            <Route path="/projects/:projectId/runs" element={<ProjectRunsPage />} />
            <Route path="/projects/:projectId/channels" element={<ProjectChannelsPage />} />
            <Route path="/projects/:projectId/settings" element={<ProjectSettingsPage />} />
            <Route path="/runs" element={<RunsPage />} />
            <Route path="/runs/:runId" element={<RunDetailPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Global Project Switcher & Project Context', () => {
  beforeEach(() => {
    window.localStorage.clear()
    vi.spyOn(api, 'projects').mockResolvedValue([DEFAULT_PROJECT, GTA_PROJECT])
    vi.spyOn(api, 'project').mockImplementation(async (id) => {
      if (id === 'gta6') return GTA_PROJECT
      if (id === 'default') return DEFAULT_PROJECT
      throw new Error('Project not found')
    })
    vi.spyOn(api, 'health').mockResolvedValue(HEALTH)
    vi.spyOn(api, 'settings').mockResolvedValue(SETTINGS)
    vi.spyOn(api, 'platforms').mockResolvedValue(PLATFORMS)
    vi.spyOn(api, 'runs').mockResolvedValue([RUN_DEFAULT, RUN_GTA])
    vi.spyOn(api, 'projectRuns').mockImplementation(async (id) => (id === 'gta6' ? [RUN_GTA] : [RUN_DEFAULT]))
    vi.spyOn(api, 'projectChannels').mockImplementation(async (id) => (id === 'gta6' ? [CH_GTA] : [CH_DEFAULT]))
  })

  afterEach(() => {
    vi.restoreAllMocks()
    window.localStorage.clear()
  })

  it('selects default project initially and persists to localStorage', async () => {
    renderApp('/')

    const sidebar = screen.getByRole('complementary')
    const trigger = await within(sidebar).findByRole('button', { name: /Active project: Default Project/i })
    expect(trigger).toBeInTheDocument()
    await waitFor(() => {
      expect(window.localStorage.getItem(ACTIVE_PROJECT_STORAGE_KEY)).toBe('default')
    })
  })

  it('restores active project from localStorage across refreshes', async () => {
    window.localStorage.setItem(ACTIVE_PROJECT_STORAGE_KEY, 'gta6')
    renderApp('/')

    const sidebar = screen.getByRole('complementary')
    expect(await within(sidebar).findByRole('button', { name: /Active project: GTA 6/i })).toBeInTheDocument()
    expect(screen.getByText(/New run · GTA 6/i)).toBeInTheDocument()
    expect(window.localStorage.getItem(ACTIVE_PROJECT_STORAGE_KEY)).toBe('gta6')
  })

  it('falls back safely when stored localStorage project ID does not exist', async () => {
    window.localStorage.setItem(ACTIVE_PROJECT_STORAGE_KEY, 'deleted-project')
    renderApp('/')

    const sidebar = screen.getByRole('complementary')
    expect(await within(sidebar).findByRole('button', { name: /Active project: Default Project/i })).toBeInTheDocument()
    await waitFor(() => {
      expect(window.localStorage.getItem(ACTIVE_PROJECT_STORAGE_KEY)).toBe('default')
    })
  })

  it('removes Target project selector from New Run and submits runs under activeProjectId', async () => {
    const user = userEvent.setup()
    window.localStorage.setItem(ACTIVE_PROJECT_STORAGE_KEY, 'gta6')
    const createProjectRunsSpy = vi.spyOn(api, 'createProjectRuns').mockResolvedValue([RUN_GTA])
    vi.spyOn(api, 'run').mockResolvedValue({
      ...RUN_GTA,
      source_duration: 60,
      stages: [],
      clips: [],
      posts: [],
    })

    renderApp('/')

    const sidebar = screen.getByRole('complementary')
    await within(sidebar).findByRole('button', { name: /Active project: GTA 6/i })
    expect(screen.queryByLabelText(/Target project/i)).not.toBeInTheDocument()

    await user.type(screen.getByLabelText('Video links'), 'https://www.youtube.com/watch?v=dQw4w9WgXcQ')
    await user.click(screen.getByRole('button', { name: /Find clips/i }))

    await waitFor(() => {
      expect(createProjectRunsSpy).toHaveBeenCalledWith(
        'gta6',
        ['https://www.youtube.com/watch?v=dQw4w9WgXcQ'],
        expect.objectContaining({ clip_count: 3 }),
      )
    })
  })

  it('switches projects via sidebar switcher and immediately updates Runs, Channels, and Project Settings', async () => {
    const user = userEvent.setup()
    const updateProjectSpy = vi.spyOn(api, 'updateProject').mockResolvedValue({ ...GTA_PROJECT, name: 'GTA VI' })

    renderApp('/projects/default/runs')

    const main = screen.getByRole('main')
    const sidebar = screen.getByRole('complementary')
    await within(main).findByText('Default Video')
    expect(within(main).queryByText('GTA 6 Trailer')).not.toBeInTheDocument()

    // Switch project to GTA 6 using the sidebar switcher
    const switcher = within(sidebar).getByRole('button', { name: /Active project: Default Project/i })
    await user.click(switcher)
    const listbox = within(sidebar).getByRole('listbox', { name: 'Projects' })
    await user.click(within(listbox).getByRole('option', { name: /GTA 6/i }))

    expect(window.localStorage.getItem(ACTIVE_PROJECT_STORAGE_KEY)).toBe('gta6')
    await within(main).findByText('GTA 6 Trailer')
    expect(within(main).queryByText('Default Video')).not.toBeInTheDocument()

    // Navigate to Channels via sidebar: shows only GTA 6 channels
    await user.click(within(sidebar).getByRole('link', { name: 'Channels' }))
    await within(main).findByText('GTA 6 Shorts')
    expect(within(main).queryByText('Default Channel')).not.toBeInTheDocument()

    // Navigate to Project Settings via sidebar: operates on GTA 6
    await user.click(within(sidebar).getByRole('link', { name: 'Project settings' }))
    const nameInput = await within(main).findByLabelText('Project name')
    expect(nameInput).toHaveValue('GTA 6')
    await user.clear(nameInput)
    await user.type(nameInput, 'GTA VI')
    await user.click(within(main).getByRole('button', { name: 'Save changes' }))

    await waitFor(() => {
      expect(updateProjectSpy).toHaveBeenCalledWith('gta6', { name: 'GTA VI', description: 'GTA 6 clips' })
    })
  })

  it('keeps ALL RUNS cross-project and global Settings independent', async () => {
    const user = userEvent.setup()
    window.localStorage.setItem(ACTIVE_PROJECT_STORAGE_KEY, 'gta6')
    renderApp('/runs')

    const main = screen.getByRole('main')
    const sidebar = screen.getByRole('complementary')
    await within(main).findByText('Default Video')
    expect(within(main).getByText('GTA 6 Trailer')).toBeInTheDocument()

    await user.click(within(sidebar).getByRole('link', { name: 'Settings' }))
    await within(main).findByText('Your keys stay on this machine')
    expect(within(main).getByRole('heading', { name: 'Settings' })).toBeInTheDocument()
  })

  it('resolves RunDetail project from backend without mutating activeProjectId', async () => {
    window.localStorage.setItem(ACTIVE_PROJECT_STORAGE_KEY, 'gta6')
    const defaultRunDetail: RunDetail = {
      ...RUN_DEFAULT,
      source_duration: 120,
      stages: [],
      clips: [],
      posts: [],
    }
    vi.spyOn(api, 'run').mockResolvedValue(defaultRunDetail)

    renderApp('/runs/run-def')

    const main = screen.getByRole('main')
    const sidebar = screen.getByRole('complementary')
    await within(main).findByRole('heading', { name: 'Default Video' })
    expect(within(main).getByRole('link', { name: 'Default Project' })).toHaveAttribute('href', '/projects/default/runs')
    // Global active project remains GTA 6
    expect(within(sidebar).getByRole('button', { name: /Active project: GTA 6/i })).toBeInTheDocument()
    expect(window.localStorage.getItem(ACTIVE_PROJECT_STORAGE_KEY)).toBe('gta6')
  })

  it('handles empty projects and creates a new project from the switcher', async () => {
    const user = userEvent.setup()
    let list: Project[] = []
    vi.spyOn(api, 'projects').mockImplementation(async () => list)
    vi.spyOn(api, 'createProject').mockImplementation(async ({ name }) => {
      const created = { ...GTA_PROJECT, id: 'new-p', name, slug: 'new-p' }
      list = [created]
      return created
    })

    renderApp('/')

    const sidebar = screen.getByRole('complementary')
    await screen.findByText(/Create a project first/i)
    const newBtn = within(sidebar).getByRole('button', { name: /New project/i })
    await user.click(newBtn)
    await user.type(within(sidebar).getByLabelText('New project name'), 'Brand X')
    await user.click(within(sidebar).getByRole('button', { name: 'Create' }))

    await within(sidebar).findByRole('button', { name: /Active project: Brand X/i })
    expect(window.localStorage.getItem(ACTIVE_PROJECT_STORAGE_KEY)).toBe('new-p')
  })
})
