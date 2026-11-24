import type { ReactNode } from 'react'
import type { ChannelStatus } from '../api'
import { cn } from './ui'

export interface PlatformVisual {
  label: string
  icon: ReactNode
}

function YouTubeIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="currentColor" aria-hidden="true">
      <path d="M23.5 6.2a3.01 3.01 0 0 0-2.12-2.13C19.5 3.56 12 3.56 12 3.56s-7.5 0-9.38.51A3.01 3.01 0 0 0 .5 6.2 31.4 31.4 0 0 0 0 12a31.4 31.4 0 0 0 .5 5.8 3.01 3.01 0 0 0 2.12 2.13c1.88.51 9.38.51 9.38.51s7.5 0 9.38-.51a3.01 3.01 0 0 0 2.12-2.13A31.4 31.4 0 0 0 24 12a31.4 31.4 0 0 0-.5-5.8ZM9.6 15.6V8.4l6.24 3.6-6.24 3.6Z" />
    </svg>
  )
}

function GenericPlatformIcon({ letter }: { letter: string }) {
  return (
    <span className="font-mono text-xs font-bold uppercase" aria-hidden="true">
      {letter}
    </span>
  )
}

export const PLATFORM_UI_REGISTRY: Record<string, PlatformVisual> = {
  youtube: {
    label: 'YouTube',
    icon: <YouTubeIcon className="h-4 w-4 text-ink" />,
  },
  tiktok: {
    label: 'TikTok',
    icon: <GenericPlatformIcon letter="TT" />,
  },
  instagram: {
    label: 'Instagram',
    icon: <GenericPlatformIcon letter="IG" />,
  },
  facebook: {
    label: 'Facebook',
    icon: <GenericPlatformIcon letter="FB" />,
  },
  x: {
    label: 'X',
    icon: <GenericPlatformIcon letter="X" />,
  },
}

export function getPlatformVisual(platformId: string): PlatformVisual {
  return (
    PLATFORM_UI_REGISTRY[platformId.toLowerCase()] ?? {
      label: platformId,
      icon: <GenericPlatformIcon letter={platformId.slice(0, 2)} />,
    }
  )
}

const CHANNEL_STATUS_META: Record<ChannelStatus, { label: string; style: string; dot: string }> = {
  connected: { label: 'Connected', style: 'bg-ink text-white', dot: 'bg-acid' },
  expired: { label: 'Expired', style: 'bg-sunk text-warn', dot: 'bg-warn' },
  reauthorization_required: { label: 'Reconnect required', style: 'bg-bad-soft text-bad', dot: 'bg-bad' },
  disconnected: { label: 'Disconnected', style: 'bg-sunk text-muted', dot: 'bg-faint' },
  error: { label: 'Error', style: 'bg-bad-soft text-bad', dot: 'bg-bad' },
}

export function ChannelStatusChip({ status }: { status: ChannelStatus }) {
  const meta = CHANNEL_STATUS_META[status] ?? CHANNEL_STATUS_META.error
  return (
    <span className={cn('label px-sm inline-flex h-6 items-center gap-1.5 px-2 !text-[10px]', meta.style)}>
      <span className={cn('h-1.5 w-1.5', meta.dot)} />
      {meta.label}
    </span>
  )
}

