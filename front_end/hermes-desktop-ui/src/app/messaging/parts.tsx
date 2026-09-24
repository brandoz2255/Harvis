import type * as React from 'react'

import { StatusDot, type StatusTone } from '@/components/status-dot'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Tip } from '@/components/ui/tooltip'
import type { MessagingEnvVarInfo, MessagingPlatformInfo, PairingUser } from '@/hermes'
import { type Translations, useI18n } from '@/i18n'
import { ExternalLink, Trash2 } from '@/lib/icons'
import { cn } from '@/lib/utils'

import { CREDENTIAL_CONTROL_CLASS } from '../settings/credential-key-ui'
import { ListRow } from '../settings/primitives'

import { PlatformAvatar } from './platform-icon'

export type EditMap = Record<string, Record<string, string>>

export const PILL_TONE: Record<StatusTone, string> = {
  good: 'bg-primary/10 text-primary',
  muted: 'bg-muted text-muted-foreground',
  warn: 'bg-amber-500/10 text-amber-600 dark:text-amber-300',
  bad: 'bg-destructive/10 text-destructive'
}

// States the Harvis backend reports that the shared locale files do not name.
const HARVIS_STATES: Record<string, string> = { error: 'Error', unsupported: 'Not supported yet' }

export const stateLabel = (state: null | string | undefined, m: Translations['messaging']) =>
  state ? m.states[state] || HARVIS_STATES[state] || state.replace(/_/g, ' ') : m.unknown

export function stateTone({ enabled, state, supported }: MessagingPlatformInfo): StatusTone {
  if (supported === false || !enabled) {
    return 'muted'
  }

  if (state === 'connected') {
    return 'good'
  }

  if (state === 'fatal' || state === 'startup_failed' || state === 'error' || state === 'gateway_stopped') {
    return 'bad'
  }

  return 'warn'
}

export const trimEdits = (edits: Record<string, string>): Record<string, string> =>
  Object.fromEntries(
    Object.entries(edits)
      .map(([k, v]) => [k, v.trim()])
      .filter(([, v]) => v)
  )

/** Stable row identity: a user id is only unique within its platform. */
export const pairingKey = (user: PairingUser) => `${user.platform}:${user.user_id}`

export const pairingLabel = (user: PairingUser) => user.user_name || user.user_id

/** Group pairing rows by platform id so a detail pane can slice its own. */
export function byPlatform(rows: PairingUser[]): Record<string, PairingUser[]> {
  const grouped: Record<string, PairingUser[]> = {}

  for (const row of rows) {
    ;(grouped[row.platform] ||= []).push(row)
  }

  return grouped
}

const FIELD_COPY: Record<string, { advanced?: boolean }> = {
  TELEGRAM_PROXY: { advanced: true },
  DISCORD_REPLY_TO_MODE: { advanced: true },
  DISCORD_ALLOW_ALL_USERS: { advanced: true },
  DISCORD_HOME_CHANNEL: { advanced: true },
  DISCORD_HOME_CHANNEL_NAME: { advanced: true },
  BLUEBUBBLES_ALLOW_ALL_USERS: { advanced: true },
  MATTERMOST_ALLOW_ALL_USERS: { advanced: true },
  MATTERMOST_HOME_CHANNEL: { advanced: true },
  QQ_ALLOW_ALL_USERS: { advanced: true },
  QQBOT_HOME_CHANNEL: { advanced: true },
  QQBOT_HOME_CHANNEL_NAME: { advanced: true },
  WHATSAPP_ENABLED: { advanced: true },
  WHATSAPP_MODE: { advanced: true }
}

// Harvis never lets an unknown sender through: without an allowlist they get a
// pairing code instead. The shared locale copy says otherwise, so it loses here.
const ALLOWLIST_HELP =
  'Comma-separated IDs that can chat with Harvis as you. Anyone else is sent a pairing code that you approve on this page.'

export function fieldCopy(field: MessagingEnvVarInfo, m: Translations['messaging']) {
  const copy = FIELD_COPY[field.key] || {}
  const localized = m.fieldCopy[field.key] || {}
  const allowlist = field.key.endsWith('_ALLOWED_USERS')

  return {
    label: localized.label || field.prompt || field.key,
    help: allowlist ? ALLOWLIST_HELP : localized.help || field.description,
    placeholder: localized.placeholder || field.prompt,
    advanced: Boolean(copy.advanced || field.advanced)
  }
}

const PLATFORM_INTRO: Record<string, string> = {
  telegram:
    'In Telegram, talk to @BotFather, run /newbot, and copy the token it gives you. Then grab your numeric user ID from @userinfobot.',
  discord:
    'Open the Discord Developer Portal, create an application, add a Bot, then copy its token. Invite the bot to your server with the right scopes.',
  slack:
    'Create a Slack app, enable Socket Mode, install it to your workspace, then copy the bot token and app-level token.',
  mattermost:
    'On your Mattermost server, create a bot account or personal access token, then paste the server URL and token here.',
  matrix: 'Sign in to your homeserver with the bot account, then copy the access token, user ID, and homeserver URL.',
  signal:
    'Run signal-cli as a daemon with its HTTP endpoint, then point Harvis at the URL and the linked phone number.',
  bluebubbles:
    'Run BlueBubbles Server on a Mac with iMessage, expose its API, then point Harvis at the URL with the server password.',
  homeassistant:
    'In Home Assistant, open your profile and create a long-lived access token. Paste it here along with your HA URL.',
  email:
    'Use a dedicated mailbox. For Gmail/Workspace, create an app password and use imap.gmail.com / smtp.gmail.com.',
  sms: 'Get your Twilio Account SID and Auth Token from the Twilio console, plus a phone number that can send SMS.'
}

/** The backend's own setup hint wins: it describes what Harvis actually runs. */
export const introCopy = (platform: MessagingPlatformInfo, m: Translations['messaging']) =>
  platform.setup_hint || m.platformIntro[platform.id] || PLATFORM_INTRO[platform.id] || platform.description

export function PlatformRow({
  active,
  onSelect,
  pendingCount,
  platform
}: {
  active: boolean
  onSelect: () => void
  pendingCount: number
  platform: MessagingPlatformInfo
}) {
  const { t } = useI18n()
  const unsupported = platform.supported === false

  return (
    <button
      className={cn(
        'row-hover flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:text-foreground',
        active ? 'bg-(--ui-row-active-background) text-foreground' : 'text-(--ui-text-secondary)',
        unsupported && !active && 'opacity-55'
      )}
      onClick={onSelect}
      title={unsupported ? `${platform.name}: not supported by Harvis yet` : undefined}
      type="button"
    >
      <PlatformAvatar platformId={platform.id} platformName={platform.name} />
      <span className="flex min-w-0 flex-1 items-center justify-between gap-2">
        <span className="truncate text-[length:var(--conversation-text-font-size)] font-normal">{platform.name}</span>
        <span className="flex shrink-0 items-center gap-1.5">
          {/* Someone is waiting to be let in — the only way this page tells
              you so before you open the platform. */}
          {pendingCount > 0 && (
            <span
              aria-label={t.messaging.pendingAria(pendingCount)}
              className={cn(
                'inline-flex min-w-4 items-center justify-center rounded-full px-1 text-[0.66rem] font-medium tabular-nums',
                PILL_TONE.warn
              )}
            >
              {pendingCount}
            </span>
          )}
          <StatusDot tone={stateTone(platform)} />
        </span>
      </span>
    </button>
  )
}

export function MessagingField({
  edits,
  field,
  onClear,
  onEdit,
  saving
}: {
  edits: Record<string, string>
  field: MessagingEnvVarInfo
  onClear: (key: string) => void
  onEdit: (key: string, value: string) => void
  saving: string | null
}) {
  const { t } = useI18n()
  const m = t.messaging
  const copy = fieldCopy(field, m)
  const fieldId = `messaging-field-${field.key}`

  return (
    <ListRow
      action={
        <div className="flex items-center gap-2">
          <Input
            className={CREDENTIAL_CONTROL_CLASS}
            id={fieldId}
            onChange={event => onEdit(field.key, event.target.value)}
            placeholder={field.is_set ? field.redacted_value || m.replaceValue : copy.placeholder}
            type={field.is_password ? 'password' : 'text'}
            value={edits[field.key] || ''}
          />
          {field.url && (
            <Tip label={m.openDocs}>
              <Button asChild className="size-8 shrink-0" variant="ghost">
                <a href={field.url} rel="noreferrer" target="_blank">
                  <ExternalLink className="size-3.5" />
                </a>
              </Button>
            </Tip>
          )}
          {field.is_set && (
            <Tip label={m.clearField(field.key)}>
              <Button
                className="size-8 shrink-0"
                disabled={saving === `clear:${field.key}`}
                onClick={() => onClear(field.key)}
                variant="ghost"
              >
                <Trash2 className="size-3.5" />
              </Button>
            </Tip>
          )}
        </div>
      }
      description={copy.help}
      title={
        <span className="flex flex-wrap items-center gap-2">
          <label htmlFor={fieldId}>{copy.label}</label>
          {field.is_set && <span className="text-[0.66rem] font-medium text-primary">{m.saved}</span>}
        </span>
      }
    />
  )
}

export function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h4 className="text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground">{children}</h4>
}

export const CAPTION_CLASS =
  'text-[length:var(--conversation-caption-font-size)] leading-(--conversation-caption-line-height) text-(--ui-text-tertiary)'

export function StatePill({ children, tone }: { children: string; tone: StatusTone }) {
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center gap-1.5 rounded-full px-2 py-0.5 text-[0.66rem] font-medium',
        PILL_TONE[tone]
      )}
    >
      <StatusDot tone={tone} />
      {children}
    </span>
  )
}

export function SetupPill({ children }: { children: string }) {
  return (
    <span
      className={cn('inline-flex items-center rounded-full px-2 py-0.5 text-[0.66rem] font-medium', PILL_TONE.muted)}
    >
      {children}
    </span>
  )
}
