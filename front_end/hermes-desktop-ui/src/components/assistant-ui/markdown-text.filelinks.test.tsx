import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { $previewTabs } from '@/store/preview'

import { MarkdownTextContent } from './markdown-text'

// Regression for #82140: a plain filesystem href in assistant markdown
// (`[report](/home/user/report.md)`) rendered as a bare dead anchor —
// file:// is blocked in the renderer, and on a remote gateway the path
// isn't on this disk at all. Such links must route through the preview
// pipeline (PreviewAttachment → normalizeOrLocalPreviewTarget), which
// resolves the path at VIEW time against the session's backend: local
// connections read the file directly, remote connections fetch it over the
// authenticated /api/fs bridge. Media-extension paths keep their inline
// player instead.
describe('MarkdownLink filesystem hrefs', () => {
  afterEach(cleanup)

  it('routes an absolute file path link through the preview attachment', async () => {
    render(<MarkdownTextContent isRunning={false} text="Wrote it: [report](/home/user/report.md)" />)

    // PreviewAttachment paints the filename + an Open preview button —
    // that's the view-time door, not a dead <a>.
    await screen.findByText('report.md')
    expect(screen.getByRole('button', { name: 'Open preview' })).toBeTruthy()
    expect(document.querySelector('a[href="/home/user/report.md"]')).toBeNull()
  })

  it('routes file:// and ~/ links the same way', async () => {
    render(
      <MarkdownTextContent isRunning={false} text={'See [notes](file:///srv/data/notes.txt) and [todo](~/todo.md)'} />
    )

    await screen.findByText('notes.txt')
    await screen.findByText('todo.md')
    expect(screen.getAllByRole('button', { name: 'Open preview' })).toHaveLength(2)
  })

  it('renders a media player for a media-extension path link', async () => {
    const { container } = render(<MarkdownTextContent isRunning={false} text="[clip](/tmp/demo.mp4)" />)

    await waitFor(() => expect(container.querySelector('video')).not.toBeNull())
    expect(container.querySelector('a[href="/tmp/demo.mp4"]')).toBeNull()
  })

  it('leaves anchors and relative links out of the preview pipeline', () => {
    render(
      <MarkdownTextContent
        isRunning={false}
        text={'[frag](#section-2) and [rel](docs/guide.md) and [site](https://example.com)'}
      />
    )

    // Fragment anchors survive untouched; relative links are NOT rewritten
    // (they keep Streamdown's pre-existing handling) — neither gains a
    // preview affordance.
    expect(screen.queryByRole('button', { name: 'Open preview' })).toBeNull()
    expect(document.querySelector('a[href="#section-2"]')).not.toBeNull()
  })
})

describe('paths the model names', () => {
  beforeEach(() => $previewTabs.set([]))
  afterEach(cleanup)

  it('opens a path written as inline code in the side panel', async () => {
    render(<MarkdownTextContent isRunning={false} text="The fix is in `/srv/app/src/main.ts:42`." />)

    fireEvent.click(await screen.findByRole('button', { name: 'Open preview: /srv/app/src/main.ts' }))

    await waitFor(() => expect($previewTabs.get().map(tab => tab.target.path)).toEqual(['/srv/app/src/main.ts']))
  })

  it('leaves commands, words and server routes as plain code', async () => {
    render(<MarkdownTextContent isRunning={false} text="Run `npm test`, call `useState`, or hit `/api/chat`." />)

    await screen.findByText('npm test')
    expect(screen.queryAllByRole('button')).toHaveLength(0)
  })

  it('keeps a server route link a plain link instead of a broken file card', async () => {
    render(<MarkdownTextContent isRunning={false} text="Send it to [the chat route](/api/chat)." />)

    await screen.findByText('the chat route')
    expect(screen.queryByRole('button', { name: 'Open preview' })).toBeNull()
  })

  it('names a made file after its link text, not the route', async () => {
    render(<MarkdownTextContent isRunning={false} text="Here it is: [House Cats.pdf](/api/v1/files/f1/content)" />)

    await screen.findByText('House Cats.pdf')
    expect(screen.queryByText('content')).toBeNull()
    expect(screen.getByRole('button', { name: 'Open preview' })).toBeTruthy()
  })
})
