export type RunStatus = 'queued' | 'running' | 'completed' | 'failed'
export type StageStatus = 'pending' | 'running' | 'done' | 'failed'
export type AspectRatio = '9:16' | '4:5' | '1:1'
export type CaptionStyle = 'bold' | 'highlight' | 'minimal'
export type PublishMode = 'queue' | 'now' | 'schedule' | 'draft'

export interface ClipOptions {
  clip_count: number
  min_seconds: number
  max_seconds: number
  aspect_ratio: AspectRatio
  captions: boolean
  caption_style: CaptionStyle
  face_tracking: boolean
  broll: boolean
  language: string
  instructions: string
  model: string | null
}

export interface Project {
  id: string
  name: string
  slug: string
  description: string | null
  owner_id: string | null
  is_default: boolean
  run_count: number
  channel_count: number
  created_at: string
  updated_at: string
}

export type ChannelStatus = 'connected' | 'expired' | 'reauthorization_required' | 'disconnected' | 'error'

export interface PlatformDescriptor {
  id: string
  name: string
  description: string
  status: 'available' | 'coming_soon'
  configured: boolean
  config_error: string | null
  supports_oauth: boolean
  supports_multi_channel: boolean
}

export interface ConnectedChannel {
  id: string
  project_id: string
  platform: string
  external_account_id: string | null
  external_channel_id: string
  display_name: string
  handle: string | null
  avatar_url: string | null
  status: ChannelStatus
  status_message: string | null
  metadata: Record<string, unknown>
  last_connected_at: string | null
  created_at: string
  updated_at: string
}

export interface PendingChannelCandidate {
  external_channel_id: string
  external_account_id: string | null
  display_name: string
  handle: string | null
  avatar_url: string | null
  metadata: Record<string, unknown>
}

export interface PendingChannelSelection {
  selection_id: string
  project_id: string
  platform: string
  channels: PendingChannelCandidate[]
}

export interface Run {
  id: string
  project_id: string
  project_name?: string
  source: string
  title: string | null
  status: RunStatus
  current_stage: string | null
  error: string | null
  options: ClipOptions
  created_at: string
  updated_at: string
  clip_count?: number
}

export interface Stage {
  name: string
  label: string
  status: StageStatus
  error?: string | null
  started_at?: string | null
  finished_at?: string | null
}

export interface Clip {
  id: string
  run_id: string
  rank: number
  start_seconds: number
  end_seconds: number
  duration_seconds: number | null
  title: string
  post_title: string
  caption: string
  hashtags: string[]
  rationale: string
  score: number | null
  transcript: string
  status: 'ready' | 'failed'
  error: string | null
  filename: string | null
  video_url: string
  poster_url: string
  download_url: string
}

export interface Post {
  id: string
  clip_id: string
  channel_id: string
  channel_name: string | null
  service: string | null
  mode: PublishMode
  scheduled_at: string | null
  status: 'sent_to_buffer' | 'failed'
  error: string | null
  created_at: string
}

export interface RunDetail extends Run {
  source_duration: number | null
  stages: Stage[]
  clips: Clip[]
  posts: Post[]
}

export interface Setting {
  key: string
  value: string
  is_set: boolean
  secret: boolean
  source: 'app' | 'env' | 'default'
  env: string
  description: string
}

export interface Check {
  name: string
  label: string
  ok: boolean
  required: boolean
  detail: string
}

export interface Health {
  version: string
  checks: Check[]
  queue: { queued: number; running: number }
  worker: boolean
}

export interface Model {
  id: string
  name: string
  context_length: number | null
  prompt_price_per_million: number | null
  completion_price_per_million: number | null
}

export interface ProviderInfo {
  id: string
  name: string
}

export interface TestConnectionRequest {
  provider?: string
  api_key?: string
  base_url?: string
  model?: string
}

export interface TestConnectionResult {
  ok: boolean
  provider: string
  model: string
  message: string
}

export interface Channel {
  id: string
  name: string
  service: string
  avatar: string
}

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: init?.body instanceof FormData ? init.headers : { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') message = body.detail
      else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join('; ')
    } catch {
      /* not JSON */
    }
    throw new ApiError(message)
  }
  return response.json() as Promise<T>
}

export const api = {
  health: () => request<Health>('/api/health'),
  settings: () => request<Setting[]>('/api/settings'),
  saveSettings: (values: Record<string, string | null>) =>
    request<Setting[]>('/api/settings', { method: 'PUT', body: JSON.stringify({ values }) }),
  models: (provider?: string) =>
    request<Model[]>(provider ? `/api/models?provider=${encodeURIComponent(provider)}` : '/api/models'),
  providers: () => request<ProviderInfo[]>('/api/providers'),
  testConnection: (body?: TestConnectionRequest) =>
    request<TestConnectionResult>('/api/settings/test-connection', {
      method: 'POST',
      body: JSON.stringify(body ?? {}),
    }),
  projects: () => request<Project[]>('/api/projects'),
  project: (id: string) => request<Project>(`/api/projects/${id}`),
  createProject: (body: { name: string; description?: string | null }) =>
    request<Project>('/api/projects', { method: 'POST', body: JSON.stringify(body) }),
  updateProject: (id: string, body: { name?: string; description?: string | null }) =>
    request<Project>(`/api/projects/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteProject: (id: string) => request<{ deleted: string }>(`/api/projects/${id}`, { method: 'DELETE' }),
  projectRuns: (projectId: string) => request<Run[]>(`/api/projects/${projectId}/runs`),
  createProjectRuns: (projectId: string, sources: string[], options: ClipOptions) =>
    request<Run[]>(`/api/projects/${projectId}/runs`, {
      method: 'POST',
      body: JSON.stringify({ sources, options }),
    }),
  platforms: () => request<PlatformDescriptor[]>('/api/platforms'),
  projectChannels: (projectId: string) => request<ConnectedChannel[]>(`/api/projects/${projectId}/channels`),
  connectChannel: (projectId: string, platform: string) =>
    request<{ authorization_url: string }>(`/api/projects/${projectId}/channels/connect/${platform}`, {
      method: 'POST',
    }),
  pendingChannelSelection: (projectId: string, platform: string, selectionId: string) =>
    request<PendingChannelSelection>(
      `/api/projects/${projectId}/channels/connect/${platform}/pending/${encodeURIComponent(selectionId)}`,
    ),
  completeChannelSelection: (
    projectId: string,
    platform: string,
    body: { selection_id: string; external_channel_ids: string[] },
  ) =>
    request<ConnectedChannel[]>(`/api/projects/${projectId}/channels/connect/${platform}/complete`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  disconnectChannel: (projectId: string, channelId: string) =>
    request<ConnectedChannel>(`/api/projects/${projectId}/channels/${channelId}/disconnect`, {
      method: 'POST',
    }),
  removeChannel: (projectId: string, channelId: string) =>
    request<{ deleted: string }>(`/api/projects/${projectId}/channels/${channelId}`, { method: 'DELETE' }),
  runs: (projectId?: string) =>
    request<Run[]>(projectId ? `/api/runs?project_id=${encodeURIComponent(projectId)}` : '/api/runs'),
  run: (id: string) => request<RunDetail>(`/api/runs/${id}`),
  createRuns: (sources: string[], options: ClipOptions, projectId?: string | null) =>
    request<Run[]>('/api/runs', {
      method: 'POST',
      body: JSON.stringify({ sources, options, ...(projectId ? { project_id: projectId } : {}) }),
    }),
  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<{ source: string; name: string }>('/api/uploads', { method: 'POST', body: form })
  },
  retry: (id: string, fromStage?: string) =>
    request<RunDetail>(`/api/runs/${id}/retry`, {
      method: 'POST',
      body: JSON.stringify({ from_stage: fromStage ?? null }),
    }),
  deleteRun: (id: string) => request<{ deleted: string }>(`/api/runs/${id}`, { method: 'DELETE' }),
  channels: () => request<Channel[]>('/api/buffer/channels'),
  organizations: () => request<{ id: string; name: string }[]>('/api/buffer/organizations'),
  publish: (
    clipId: string,
    body: { channel_ids: string[]; mode: PublishMode; scheduled_at?: string | null; text?: string; title?: string },
  ) => request<Post[]>(`/api/clips/${clipId}/publish`, { method: 'POST', body: JSON.stringify(body) }),
}

export const DEFAULT_OPTIONS: ClipOptions = {
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
}
