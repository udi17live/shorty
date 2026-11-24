import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, type ConnectedChannel, type PlatformDescriptor, type Project } from '../api'
import { ProjectChannelsPage } from '../pages/ProjectChannels'

const PROJECT: Project = {
  id: 'proj1',
  name: 'GTA 6',
  slug: 'gta-6',
  description: 'GTA 6 brand',
  owner_id: null,
  is_default: false,
  run_count: 2,
  channel_count: 1,
  created_at: '2026-11-25T00:00:00Z',
  updated_at: '2026-11-25T00:00:00Z',
}

const PLATFORMS: PlatformDescriptor[] = [
  {
    id: 'youtube',
    name: 'YouTube',
    description: 'Connect your YouTube channel via Google OAuth 2.0',
    status: 'available',
    configured: true,
    config_error: null,
    supports_oauth: true,
    supports_multi_channel: true,
  },
  {
    id: 'tiktok',
    name: 'TikTok',
    description: 'Connect your TikTok account',
    status: 'coming_soon',
    configured: false,
    config_error: null,
    supports_oauth: false,
    supports_multi_channel: false,
  },
]

const CHANNEL: ConnectedChannel = {
  id: 'ch1',
  project_id: 'proj1',
  platform: 'youtube',
  external_account_id: null,
  external_channel_id: 'UC_GTA6',
  display_name: 'GTA 6 Shorts',
  handle: '@gta6shorts',
  avatar_url: 'https://example.com/avatar.jpg',
  status: 'connected',
  status_message: null,
  metadata: {},
  last_connected_at: '2026-11-25T00:00:00Z',
  created_at: '2026-11-25T00:00:00Z',
  updated_at: '2026-11-25T00:00:00Z',
}

function renderChannels(initialEntry = '/projects/proj1/channels') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/projects/:projectId/channels" element={<ProjectChannelsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ProjectChannelsPage', () => {
  beforeEach(() => {
    vi.spyOn(api, 'project').mockResolvedValue(PROJECT)
    vi.spyOn(api, 'platforms').mockResolvedValue(PLATFORMS)
    vi.spyOn(api, 'projectChannels').mockResolvedValue([])
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders platform cards and initiates YouTube OAuth redirect with loading state', async () => {
    const user = userEvent.setup()
    let resolveConnect!: (v: { authorization_url: string }) => void
    const connectSpy = vi.spyOn(api, 'connectChannel').mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveConnect = resolve
        }),
    )

    const assignMock = vi.fn()
    Object.defineProperty(window, 'location', {
      value: { ...window.location, assign: assignMock },
      writable: true,
    })

    renderChannels()

    await screen.findByText('GTA 6')
    expect(screen.getByText('YouTube')).toBeInTheDocument()
    expect(screen.getByText('TikTok')).toBeInTheDocument()
    const comingSoonButtons = screen.getAllByRole('button', { name: 'Coming soon' })
    expect(comingSoonButtons[0]).toBeDisabled()

    const connectBtn = screen.getByRole('button', { name: 'Connect' })
    await user.click(connectBtn)

    expect(connectSpy).toHaveBeenCalledWith('proj1', 'youtube')
    expect(screen.getByRole('button', { name: /Connecting YouTube/i })).toBeInTheDocument()

    resolveConnect({ authorization_url: 'https://accounts.google.com/o/oauth2/v2/auth?state=abc' })
    await waitFor(() => {
      expect(assignMock).toHaveBeenCalledWith('https://accounts.google.com/o/oauth2/v2/auth?state=abc')
    })
  })

  it('displays connected channel after callback and supports disconnect', async () => {
    const user = userEvent.setup()
    let channelsState: ConnectedChannel[] = [CHANNEL]
    vi.spyOn(api, 'projectChannels').mockImplementation(async () => channelsState)
    const disconnectSpy = vi.spyOn(api, 'disconnectChannel').mockImplementation(async () => {
      const updated = { ...CHANNEL, status: 'disconnected' as const }
      channelsState = [updated]
      return updated
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    renderChannels('/projects/proj1/channels?oauth_status=connected&platform=youtube&channel=ch1')

    await screen.findByText('YouTube connected successfully')
    expect(screen.getByText('GTA 6 Shorts')).toBeInTheDocument()
    expect(screen.getByText('@gta6shorts')).toBeInTheDocument()
    expect(screen.getAllByText('Connected').length).toBeGreaterThanOrEqual(1)

    await user.click(screen.getByRole('button', { name: /Disconnect/i }))
    expect(disconnectSpy).toHaveBeenCalledWith('proj1', 'ch1')
    await screen.findByText('Disconnected')
  })

  it('displays error banner when connect initiation fails', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'connectChannel').mockRejectedValue(new Error('Google OAuth is not configured'))
    renderChannels()

    await screen.findByText('GTA 6')
    await user.click(screen.getByRole('button', { name: 'Connect' }))
    await screen.findByText('Google OAuth is not configured')
  })

  it('handles OAuth cancelled and error callback states cleanly', async () => {
    renderChannels('/projects/proj1/channels?oauth_status=cancelled&platform=youtube')
    await screen.findByText('YouTube connection cancelled.')

    renderChannels('/projects/proj1/channels?oauth_status=error&platform=youtube&reason=no_channel')
    await screen.findByText('No YouTube channel was found on that Google account.')
  })

  it('handles multi-channel selection after OAuth callback', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'pendingChannelSelection').mockResolvedValue({
      selection_id: 'sel1',
      project_id: 'proj1',
      platform: 'youtube',
      channels: [
        {
          external_channel_id: 'UC_1',
          external_account_id: null,
          display_name: 'Channel One',
          handle: '@one',
          avatar_url: null,
          metadata: {},
        },
        {
          external_channel_id: 'UC_2',
          external_account_id: null,
          display_name: 'Channel Two',
          handle: '@two',
          avatar_url: null,
          metadata: {},
        },
      ],
    })
    const completeSpy = vi.spyOn(api, 'completeChannelSelection').mockResolvedValue([CHANNEL])

    renderChannels('/projects/proj1/channels?oauth_status=select&platform=youtube&selection=sel1')

    await screen.findByText('Select which channel to connect')
    await user.click(screen.getByRole('button', { name: /Channel One/i }))
    await user.click(screen.getByRole('button', { name: 'Connect selected' }))

    await waitFor(() => {
      expect(completeSpy).toHaveBeenCalledWith('proj1', 'youtube', {
        selection_id: 'sel1',
        external_channel_ids: ['UC_1'],
      })
    })
  })
})
