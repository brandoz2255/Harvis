import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { DisclosureCaret } from '@/components/ui/disclosure-caret'
import { ErrorBanner } from '@/components/ui/error-state'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import type { MessagingPlatformInfo, PairingUser } from '@/hermes'
import { useI18n } from '@/i18n'
import { openExternalLink } from '@/lib/external-link'
import { Copy, ExternalLink, Save, Send } from '@/lib/icons'
import { cn } from '@/lib/utils'

import { ListRow } from '../settings/primitives'

import {
  CAPTION_CLASS,
  fieldCopy,
  introCopy,
  MessagingField,
  pairingKey,
  pairingLabel,
  SectionTitle,
  SetupPill,
  StatePill,
  stateLabel,
  stateTone
} from './parts'
import { PlatformAvatar } from './platform-icon'

export interface TestResult {
  message: string
  ok: boolean
  platformId: string
}

export function PlatformDetail({
  approved,
  approving,
  edits,
  onApprove,
  onClear,
  onDismiss,
  onEdit,
  onRevoke,
  pending,
  platform,
  saving,
  testResult
}: {
  approved: PairingUser[]
  approving: null | string
  edits: Record<string, string>
  onApprove: (user: PairingUser) => void
  onClear: (key: string) => void
  onDismiss: (user: PairingUser) => void
  onEdit: (key: string, value: string) => void
  onRevoke: (user: PairingUser) => void
  pending: PairingUser[]
  platform: MessagingPlatformInfo
  saving: string | null
  testResult: TestResult | null
}) {
  const { t } = useI18n()
  const m = t.messaging
  const [showAdvanced, setShowAdvanced] = useState(false)

  const requiredFields = platform.env_vars.filter(field => field.required)
  const optionalFields = platform.env_vars.filter(field => !field.required && !fieldCopy(field, m).advanced)
  const advancedFields = platform.env_vars.filter(field => !field.required && fieldCopy(field, m).advanced)
  const hiddenCount = advancedFields.length
  const unsupported = platform.supported === false

  const fields = (list: typeof requiredFields) =>
    list.map(field => (
      <MessagingField edits={edits} field={field} key={field.key} onClear={onClear} onEdit={onEdit} saving={saving} />
    ))

  return (
    <>
      <header className="flex items-start gap-3">
        <PlatformAvatar platformId={platform.id} platformName={platform.name} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="min-w-0 truncate text-[0.9375rem] font-semibold tracking-tight">{platform.name}</h3>
            <StatePill tone={stateTone(platform)}>{stateLabel(platform.state, m)}</StatePill>
            {platform.display && <span className="text-xs text-muted-foreground">as {platform.display}</span>}
            {!unsupported && !platform.configured && <SetupPill>{m.needsSetup}</SetupPill>}
          </div>
          <p className={cn('mt-1', CAPTION_CLASS)}>{platform.description}</p>
          <PlatformHint platform={platform} />
        </div>
      </header>

      {platform.error_message &&
        (unsupported ? (
          <p className={cn('rounded-xl bg-muted px-3 py-2', CAPTION_CLASS)}>{platform.error_message}</p>
        ) : (
          <ErrorBanner>{platform.error_message}</ErrorBanner>
        ))}

      {testResult && testResult.platformId === platform.id && (
        <p
          className={cn('text-xs', testResult.ok ? 'text-primary' : 'text-destructive')}
          data-testid="messaging-test-result"
          role="status"
        >
          {testResult.message}
        </p>
      )}

      {/* Pending pairing requests. Rendered only when someone is actually
          waiting — an empty-state card here would be permanent chrome on a
          page that is usually about credentials, not approvals. */}
      {pending.length > 0 && (
        <section>
          <SectionTitle>{m.pendingRequests(pending.length)}</SectionTitle>
          <p className={cn('mt-1', CAPTION_CLASS)}>
            These people messaged your bot and were sent a pairing code. Approve only codes you recognise: an approved
            sender chats with Harvis as you.
          </p>
          <div className="mt-1 grid gap-1">
            {pending.map(user => {
              const busy = approving === pairingKey(user)
              const waited = typeof user.age_minutes === 'number' ? m.waitingSince(user.age_minutes) : null

              return (
                <ListRow
                  action={
                    <div className="flex items-center gap-1">
                      <Button
                        disabled={busy || !user.request_id}
                        onClick={() => onApprove(user)}
                        size="sm"
                        variant="secondary"
                      >
                        {busy ? m.approving : m.approve}
                      </Button>
                      <Button
                        disabled={busy || !user.request_id}
                        onClick={() => onDismiss(user)}
                        size="sm"
                        variant="ghost"
                      >
                        Dismiss
                      </Button>
                    </div>
                  }
                  description={[
                    user.request_id ? `code ${user.request_id}` : null,
                    user.user_name ? user.user_id : null,
                    waited
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                  key={pairingKey(user)}
                  title={pairingLabel(user)}
                />
              )
            })}
          </div>
        </section>
      )}

      {approved.length > 0 && (
        <section>
          <SectionTitle>{m.approvedUsers(approved.length)}</SectionTitle>
          <div className="mt-1 grid gap-1">
            {approved.map(user => (
              <ListRow
                action={
                  <Button
                    aria-label={m.revokeAria(pairingLabel(user))}
                    onClick={() => onRevoke(user)}
                    size="sm"
                    variant="ghost"
                  >
                    {m.revoke}
                  </Button>
                }
                description={user.user_name ? user.user_id : undefined}
                key={pairingKey(user)}
                title={pairingLabel(user)}
              />
            ))}
          </div>
        </section>
      )}

      <section>
        <SectionTitle>{m.getCredentials}</SectionTitle>
        <p className={cn('mt-1', CAPTION_CLASS)}>{introCopy(platform, m)}</p>
        {platform.docs_url && (
          <div className="mt-3">
            <Button asChild size="sm" variant="textStrong">
              <a
                href={platform.docs_url}
                onClick={event => {
                  // Route through the validated external opener instead of
                  // letting Electron resolve the anchor: an empty/relative
                  // href resolves to the app's own index.html file path.
                  event.preventDefault()
                  openExternalLink(platform.docs_url)
                }}
                rel="noreferrer"
                target="_blank"
              >
                {m.openSetupGuide}
                <ExternalLink className="size-3.5" />
              </a>
            </Button>
          </div>
        )}
      </section>

      <WebhookBox platform={platform} />

      <section>
        <SectionTitle>{m.required}</SectionTitle>
        <div className="mt-3 grid gap-1">
          {requiredFields.length > 0 ? fields(requiredFields) : <p className={CAPTION_CLASS}>{m.noTokenNeeded}</p>}
        </div>
      </section>

      {optionalFields.length > 0 && (
        <section>
          <SectionTitle>{m.recommended}</SectionTitle>
          <div className="mt-3 grid gap-1">{fields(optionalFields)}</div>
        </section>
      )}

      {hiddenCount > 0 && (
        <section>
          <button
            className="flex w-full items-center justify-between gap-2 py-0.5 text-left text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground transition-colors hover:text-foreground"
            onClick={() => setShowAdvanced(value => !value)}
            type="button"
          >
            <span>{m.advanced(hiddenCount)}</span>
            <DisclosureCaret open={showAdvanced} size="0.875rem" />
          </button>
          {showAdvanced && <div className="mt-3 grid gap-1">{fields(advancedFields)}</div>}
        </section>
      )}
    </>
  )
}

/** Webhook platforms: the public URL to register, or why there is none yet. */
function WebhookBox({ platform }: { platform: MessagingPlatformInfo }) {
  if (!platform.webhook_url && !platform.webhook_note) {
    return null
  }

  const url = platform.webhook_url

  return (
    <section>
      <SectionTitle>Webhook</SectionTitle>
      {url ? (
        <>
          <p className={cn('mt-1', CAPTION_CLASS)}>
            Register this callback URL with your verify token in the provider's dashboard and subscribe to messages.
          </p>
          <div className="mt-2 flex items-center gap-2">
            <Input aria-label="Webhook URL" className="font-mono text-xs" readOnly value={url} />
            <Button
              aria-label="Copy webhook URL"
              className="size-8 shrink-0"
              onClick={() => void navigator.clipboard?.writeText(url).catch(() => undefined)}
              variant="ghost"
            >
              <Copy className="size-3.5" />
            </Button>
          </div>
        </>
      ) : (
        <p className={cn('mt-1', CAPTION_CLASS)}>{platform.webhook_note}</p>
      )}
    </section>
  )
}

export function PlatformActionBar({
  hasEdits,
  onSave,
  onTest,
  onToggle,
  platform,
  saving
}: {
  hasEdits: boolean
  onSave: () => void
  onTest: () => void
  onToggle: (enabled: boolean) => void
  platform: MessagingPlatformInfo
  saving: string | null
}) {
  const { t } = useI18n()
  const m = t.messaging
  const isSavingEnv = saving === `env:${platform.id}`
  const testing = saving === `test:${platform.id}`
  const unsupported = platform.supported === false

  return (
    <>
      <Switch
        aria-label={platform.enabled ? m.disableAria(platform.name) : m.enableAria(platform.name)}
        checked={platform.enabled}
        disabled={unsupported || saving === `enabled:${platform.id}`}
        onCheckedChange={onToggle}
        size="xs"
      />

      <div className="ml-auto flex items-center gap-2">
        {hasEdits && <span className="text-xs text-muted-foreground">{m.unsavedChanges}</span>}
        {!unsupported && (
          <Button
            disabled={!platform.can_test || testing}
            onClick={onTest}
            size="sm"
            title={
              platform.can_test
                ? 'Send a short message to the last chat that wrote to the bot, or the first allowed user'
                : 'Available once the platform is connected and knows a chat to reply to'
            }
            variant="secondary"
          >
            <Send />
            {testing ? 'Sending...' : 'Send test message'}
          </Button>
        )}
        <Button disabled={!hasEdits || isSavingEnv} onClick={onSave} size="sm">
          <Save />
          {isSavingEnv ? m.saving : m.saveChanges}
        </Button>
      </div>
    </>
  )
}

/** One line on what happens next, only when there is something to do. */
function PlatformHint({ platform }: { platform: MessagingPlatformInfo }) {
  let hint: null | string = null

  if (platform.supported === false || !platform.enabled) {
    hint = null
  } else if (platform.state === 'connecting') {
    hint = 'Saved. The messaging gateway picks this up within a few seconds.'
  } else if (platform.state === 'connected' && !platform.can_test && !platform.runs_on_harvis) {
    hint = 'Connected. Message the bot once (or add yourself to the allowed users) to enable the test button.'
  } else if (platform.state === 'connected') {
    hint = 'Connected. Message the bot from your app to chat with Harvis.'
  }

  return hint ? <p className="mt-2 text-xs leading-5 text-muted-foreground">{hint}</p> : null
}
