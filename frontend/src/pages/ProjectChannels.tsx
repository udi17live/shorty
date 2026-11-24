import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, RefreshCw, Trash2, Unlink } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { toast } from 'sonner'
import { api, type ConnectedChannel, type PlatformDescriptor } from '../api'
import { ChannelStatusChip, getPlatformVisual } from '../components/PlatformRegistry'
import { ProjectHeader } from '../components/ProjectHeader'
import { Button, Eyebrow, Panel, cn } from '../components/ui'
import { useProjectOptional } from '../context/ProjectContext'

const OAUTH_ERROR_MESSAGES: Record<string, string> = {
  state_missing: 'Missing OAuth verification state. Please try connecting again.',
  state_mismatch: 'Security verification failed. Please start the connection from Shortyy.',
  state_reused: 'This authorization link has already been used. Please try connecting again.',
  state_expired: 'Your authorization session expired. Please try connecting again.',
  unauthorized: 'You are not authorized to connect this channel.',
  invalid_project: 'The target project could not be found.',
  oauth_denied: 'Google authorization was not granted.',
  invalid_code: 'Missing authorization code from Google.',
  exchange_failed: 'Could not complete authorization with Google. Please try again.',
  discovery_failed: 'Connected to Google, but YouTube channel details could not be loaded.',
  no_channel: 'No YouTube channel was found on that Google account.',
  provider_unavailable: 'Google / YouTube is temporarily unavailable. Please try again.',
  not_configured: 'YouTube OAuth is not configured on this server yet.',
  server_error: 'A server configuration error prevented completing the connection.',
}

function formatConnectedDate(iso: string | null): string {
  if (!iso) return '–'
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

export function ProjectChannelsPage() {
  const { projectId: paramProjectId } = useParams()
  const projectCtx = useProjectOptional()
  const projectId = paramProjectId || projectCtx?.activeProjectId || ''
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()

  const oauthStatus = searchParams.get('oauth_status')
  const oauthPlatform = searchParams.get('platform') ?? 'youtube'
  const oauthReason = searchParams.get('reason') ?? ''
  const selectionId = searchParams.get('selection') ?? ''

  const [banner, setBanner] = useState<{ tone: 'ok' | 'info' | 'bad'; message: string } | null>(null)
  const [connectingPlatform, setConnectingPlatform] = useState<string | null>(null)
  const [selectedExternalIds, setSelectedExternalIds] = useState<string[]>([])
  const prevProjectIdRef = useRef(projectId)

  useEffect(() => {
    if (prevProjectIdRef.current !== projectId) {
      prevProjectIdRef.current = projectId
      setSelectedExternalIds([])
      setConnectingPlatform(null)
      setBanner(null)
    }
  }, [projectId])

  const project = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.project(projectId),
    enabled: !!projectId,
  })
  const platforms = useQuery({ queryKey: ['platforms'], queryFn: api.platforms })
  const channels = useQuery({
    queryKey: ['project-channels', projectId],
    queryFn: () => api.projectChannels(projectId),
    enabled: !!projectId,
  })
  const pendingSelection = useQuery({
    queryKey: ['pending-selection', projectId, oauthPlatform, selectionId],
    queryFn: () => api.pendingChannelSelection(projectId, oauthPlatform, selectionId),
    enabled: oauthStatus === 'select' && !!selectionId && !!projectId,
  })

  useEffect(() => {
    if (!oauthStatus) return
    if (oauthStatus === 'connected') {
      const label = getPlatformVisual(oauthPlatform).label
      const msg = `${label} connected successfully`
      setBanner({ tone: 'ok', message: msg })
      toast.success(msg)
      queryClient.invalidateQueries({ queryKey: ['project-channels', projectId] })
      queryClient.invalidateQueries({ queryKey: ['project', projectId] })
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      setSearchParams({}, { replace: true })
    } else if (oauthStatus === 'cancelled') {
      const label = getPlatformVisual(oauthPlatform).label
      setBanner({ tone: 'info', message: `${label} connection cancelled.` })
      setSearchParams({}, { replace: true })
    } else if (oauthStatus === 'error') {
      const msg = OAUTH_ERROR_MESSAGES[oauthReason] ?? 'Could not connect channel. Please try again.'
      setBanner({ tone: 'bad', message: msg })
      toast.error(msg)
      setSearchParams({}, { replace: true })
    }
  }, [oauthStatus, oauthPlatform, oauthReason, projectId, queryClient, setSearchParams])

  const connect = useMutation({
    mutationFn: async (platformId: string) => {
      setConnectingPlatform(platformId)
      return api.connectChannel(projectId, platformId)
    },
    onSuccess: (res) => {
      window.location.assign(res.authorization_url)
    },
    onError: (err) => {
      setConnectingPlatform(null)
      setBanner({ tone: 'bad', message: err.message })
      toast.error(err.message)
    },
  })

  const completeSelection = useMutation({
    mutationFn: () =>
      api.completeChannelSelection(projectId, oauthPlatform, {
        selection_id: selectionId,
        external_channel_ids: selectedExternalIds,
      }),
    onSuccess: (connected) => {
      queryClient.invalidateQueries({ queryKey: ['project-channels', projectId] })
      queryClient.invalidateQueries({ queryKey: ['project', projectId] })
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      const msg =
        connected.length === 1
          ? 'YouTube connected successfully'
          : `${connected.length} YouTube channels connected successfully`
      setBanner({ tone: 'ok', message: msg })
      toast.success(msg)
      setSelectedExternalIds([])
      setSearchParams({}, { replace: true })
    },
    onError: (err) => {
      toast.error(err.message)
    },
  })

  const disconnect = useMutation({
    mutationFn: (channelId: string) => api.disconnectChannel(projectId, channelId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project-channels', projectId] })
      queryClient.invalidateQueries({ queryKey: ['project', projectId] })
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      toast.success('Channel disconnected from project')
    },
    onError: (err) => toast.error(err.message),
  })

  const remove = useMutation({
    mutationFn: (channelId: string) => api.removeChannel(projectId, channelId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project-channels', projectId] })
      queryClient.invalidateQueries({ queryKey: ['project', projectId] })
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      toast.success('Channel removed')
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

  const channelList = channels.data ?? []

  return (
    <div className="flex flex-col gap-8">
      <ProjectHeader project={project.data} />

      {banner && (
        <Panel
          role="status"
          className={cn(
            'flex items-center justify-between gap-4 border-l-4 px-5 py-4 text-sm',
            banner.tone === 'ok' && 'border-l-ok bg-surface text-ink',
            banner.tone === 'info' && 'border-l-ink bg-surface text-body',
            banner.tone === 'bad' && 'border-l-bad bg-bad-soft text-bad',
          )}
        >
          <div className="flex items-center gap-3">
            {banner.tone === 'ok' ? (
              <CheckCircle2 className="h-4 w-4 shrink-0 text-ok" />
            ) : (
              <AlertTriangle className="h-4 w-4 shrink-0" />
            )}
            <span>{banner.message}</span>
          </div>
          <button
            type="button"
            className="label cursor-pointer text-muted hover:text-ink"
            onClick={() => setBanner(null)}
          >
            Dismiss
          </button>
        </Panel>
      )}

      {oauthStatus === 'select' && selectionId && (
        <Panel className="border-l-4 border-l-acid p-6">
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1">
              <Eyebrow>Choose YouTube channel</Eyebrow>
              <h2 className="display text-2xl">Select which channel to connect</h2>
              <p className="text-sm text-muted">
                Multiple YouTube channels are available on this Google account. Select the channel(s) to connect to{' '}
                {project.data.name}.
              </p>
            </div>

            {pendingSelection.isLoading ? (
              <p className="text-sm text-muted">Loading available channels…</p>
            ) : pendingSelection.error ? (
              <p className="text-sm text-bad">{pendingSelection.error.message}</p>
            ) : (
              <>
                <div className="grid gap-3 sm:grid-cols-2">
                  {(pendingSelection.data?.channels ?? []).map((cand) => {
                    const checked = selectedExternalIds.includes(cand.external_channel_id)
                    return (
                      <button
                        key={cand.external_channel_id}
                        type="button"
                        aria-pressed={checked}
                        onClick={() =>
                          setSelectedExternalIds((prev) =>
                            checked
                              ? prev.filter((id) => id !== cand.external_channel_id)
                              : [...prev, cand.external_channel_id],
                          )
                        }
                        className={cn(
                          'flex cursor-pointer items-center gap-3 border p-3.5 text-left transition-colors',
                          checked ? 'border-ink bg-paper' : 'border-line bg-surface hover:border-line-strong',
                        )}
                      >
                        <ChannelAvatar url={cand.avatar_url} name={cand.display_name} />
                        <div className="min-w-0 flex-1">
                          <p className="truncate font-semibold">{cand.display_name}</p>
                          {cand.handle && <p className="font-mono text-xs text-muted">{cand.handle}</p>}
                        </div>
                        <span className={cn('h-3.5 w-3.5 border', checked ? 'border-ink bg-acid' : 'border-line-strong')} />
                      </button>
                    )
                  })}
                </div>
                <div className="flex justify-end gap-2">
                  <Button variant="ghost" onClick={() => setSearchParams({}, { replace: true })}>
                    Cancel
                  </Button>
                  <Button
                    variant="acid"
                    disabled={selectedExternalIds.length === 0}
                    loading={completeSelection.isPending}
                    onClick={() => completeSelection.mutate()}
                  >
                    Connect selected
                  </Button>
                </div>
              </>
            )}
          </div>
        </Panel>
      )}

      <section className="flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <Eyebrow>Connected channels</Eyebrow>
          <span className="label text-faint">{channelList.length} total</span>
        </div>

        {channels.isLoading ? (
          <Panel className="p-6 text-sm text-muted">Loading connected channels…</Panel>
        ) : channelList.length === 0 ? (
          <Panel className="p-6 text-sm text-muted">
            No channels connected to {project.data.name} yet. Connect a platform below to get started.
          </Panel>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {channelList.map((ch) => (
              <ConnectedChannelCard
                key={ch.id}
                channel={ch}
                reconnecting={connectingPlatform === ch.platform && connect.isPending}
                disconnecting={disconnect.isPending && disconnect.variables === ch.id}
                removing={remove.isPending && remove.variables === ch.id}
                onReconnect={() => connect.mutate(ch.platform)}
                onDisconnect={() => {
                  if (confirm(`Disconnect "${ch.display_name}" from ${project.data.name}?`)) {
                    disconnect.mutate(ch.id)
                  }
                }}
                onRemove={() => remove.mutate(ch.id)}
              />
            ))}
          </div>
        )}
      </section>

      <section className="flex flex-col gap-4">
        <Eyebrow>Connect a platform</Eyebrow>
        {platforms.isLoading ? (
          <Panel className="p-6 text-sm text-muted">Loading platforms…</Panel>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {(platforms.data ?? []).map((platform) => (
              <PlatformCard
                key={platform.id}
                platform={platform}
                connecting={connectingPlatform === platform.id && connect.isPending}
                onConnect={() => connect.mutate(platform.id)}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function ChannelAvatar({ url, name }: { url: string | null; name: string }) {
  if (url) {
    return <img src={url} alt={name} className="px-sm h-11 w-11 shrink-0 border border-line object-cover" />
  }
  return (
    <span className="px-sm flex h-11 w-11 shrink-0 items-center justify-center border border-line bg-sunk font-mono text-sm font-semibold text-ink">
      {name.slice(0, 2).toUpperCase()}
    </span>
  )
}

function ConnectedChannelCard({
  channel,
  reconnecting,
  disconnecting,
  removing,
  onReconnect,
  onDisconnect,
  onRemove,
}: {
  channel: ConnectedChannel
  reconnecting: boolean
  disconnecting: boolean
  removing: boolean
  onReconnect: () => void
  onDisconnect: () => void
  onRemove: () => void
}) {
  const visual = getPlatformVisual(channel.platform)
  const needsReconnect =
    channel.status === 'reauthorization_required' ||
    channel.status === 'disconnected' ||
    channel.status === 'expired' ||
    channel.status === 'error'

  return (
    <Panel className="flex flex-col justify-between gap-5 p-5">
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between gap-2">
          <span className="label inline-flex items-center gap-2 text-ink">
            {visual.icon}
            {visual.label}
          </span>
          <ChannelStatusChip status={channel.status} />
        </div>

        <div className="flex items-center gap-3.5">
          <ChannelAvatar url={channel.avatar_url} name={channel.display_name} />
          <div className="min-w-0 flex-1">
            <p className="truncate text-base font-semibold tracking-tight">{channel.display_name}</p>
            {channel.handle && <p className="truncate font-mono text-xs text-muted">{channel.handle}</p>}
          </div>
        </div>

        {channel.status_message && (
          <p className="border-l-2 border-bad/50 bg-bad-soft px-3 py-2 text-xs leading-relaxed text-bad">
            {channel.status_message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-3 border-t border-line pt-4">
        <div className="label flex items-center justify-between text-faint">
          <span>Connected</span>
          <span>{formatConnectedDate(channel.last_connected_at)}</span>
        </div>

        <div className="flex gap-2">
          {needsReconnect && (
            <Button variant="ink" size="sm" className="flex-1" loading={reconnecting} onClick={onReconnect}>
              <RefreshCw className="h-3.5 w-3.5" /> Reconnect
            </Button>
          )}
          {channel.status !== 'disconnected' ? (
            <Button
              variant="line"
              size="sm"
              className={needsReconnect ? '' : 'w-full'}
              loading={disconnecting}
              onClick={onDisconnect}
            >
              <Unlink className="h-3.5 w-3.5" /> Disconnect
            </Button>
          ) : (
            <Button variant="danger" size="sm" loading={removing} onClick={onRemove} aria-label={`Remove ${channel.display_name}`}>
              <Trash2 className="h-3.5 w-3.5" /> Remove
            </Button>
          )}
        </div>
      </div>
    </Panel>
  )
}

function PlatformCard({
  platform,
  connecting,
  onConnect,
}: {
  platform: PlatformDescriptor
  connecting: boolean
  onConnect: () => void
}) {
  const visual = getPlatformVisual(platform.id)
  const available = platform.status === 'available'

  return (
    <Panel className={cn('flex flex-col justify-between gap-5 p-5', !available && 'bg-paper/60')}>
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <span className="inline-flex items-center gap-2 font-semibold">
            {visual.icon}
            {platform.name}
          </span>
          {!available && (
            <span className="label px-sm bg-sunk px-2 py-0.5 !text-[10px] text-muted">Coming soon</span>
          )}
        </div>
        <p className="text-[13px] leading-relaxed text-muted">
          {available ? platform.description : 'Coming soon'}
        </p>
        {available && !platform.configured && platform.config_error && (
          <p className="text-xs leading-relaxed text-warn">{platform.config_error}</p>
        )}
      </div>

      <div className="flex justify-end border-t border-line pt-4">
        {available ? (
          <Button
            variant="acid"
            size="sm"
            loading={connecting}
            disabled={!platform.configured}
            onClick={onConnect}
          >
            {connecting ? `Connecting ${platform.name}…` : 'Connect'}
          </Button>
        ) : (
          <Button variant="line" size="sm" disabled>
            Coming soon
          </Button>
        )}
      </div>
    </Panel>
  )
}

