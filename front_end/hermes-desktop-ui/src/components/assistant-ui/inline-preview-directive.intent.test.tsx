import { act, cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const submit = vi.hoisted(() => vi.fn(() => true))

vi.mock('@/app/chat/composer/focus', () => ({ requestComposerSubmit: submit }))
vi.mock('@/lib/desktop-fs', () => ({
  readDesktopFileText: vi.fn(async () => ({ binary: false, text: '<html><body><button>go</button></body></html>' }))
}))
vi.mock('@/lib/local-preview', () => ({ localPreviewTarget: (file: string) => ({ path: file }) }))
vi.mock('@/lib/artifact-bridge', () => ({
  useArtifactBridge: () => undefined,
  withArtifactBridge: (doc: string) => doc
}))

import { InlinePreviewDirective, WIDGET_INTENT_LABEL } from './inline-preview-directive'

const setActivation = (isActive: boolean) =>
  Object.defineProperty(navigator, 'userActivation', { configurable: true, value: { isActive } })

async function mountWidget() {
  const view = render(
    <div data-composer-surface-id="surface-a" data-composer-target="tile:a">
      <InlinePreviewDirective attrs={{ file: '/w/a.html' }} streaming={false} />
    </div>
  )

  const frame = await view.findByTitle('/w/a.html')
  const token = /var t="([^"]+)"/.exec(frame.getAttribute('srcdoc') ?? '')?.[1] ?? ''

  const send = (prompt: string, source: Window | null = (frame as HTMLIFrameElement).contentWindow) =>
    act(() => {
      window.dispatchEvent(
        new MessageEvent('message', {
          data: { prompt, token, type: 'hermes-inline-preview-intent' },
          source
        })
      )
    })

  return { frame, send }
}

describe('widget intents', () => {
  beforeEach(() => {
    submit.mockClear()
    setActivation(true)
  })

  afterEach(cleanup)

  it('sends a labelled, visible turn into the widget own chat surface', async () => {
    const { send } = await mountWidget()

    send('get-price eth')

    expect(submit).toHaveBeenCalledTimes(1)
    expect(submit).toHaveBeenCalledWith(`${WIDGET_INTENT_LABEL}get-price eth`, {
      surfaceId: 'surface-a',
      target: 'tile:a'
    })
  })

  it('drops an intent with no user activation', async () => {
    setActivation(false)

    const { send } = await mountWidget()

    send('hello')

    expect(submit).not.toHaveBeenCalled()
  })

  it('drops an intent that does not come from its own frame', async () => {
    const { send } = await mountWidget()

    send('hello', window)

    expect(submit).not.toHaveBeenCalled()
  })

  it('stops after a few intents per mount', async () => {
    const now = vi.spyOn(Date, 'now')
    const { send } = await mountWidget()

    for (let i = 0; i < 8; i += 1) {
      now.mockReturnValue(1_000_000 + i * 2_000)
      send(`go ${i}`)
    }

    now.mockRestore()
    expect(submit).toHaveBeenCalledTimes(5)
  })
})
