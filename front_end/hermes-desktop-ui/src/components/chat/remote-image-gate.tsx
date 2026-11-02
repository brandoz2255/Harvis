import { type ReactNode, useEffect, useState } from 'react'

/**
 * Hostname of an image that would leave this app to fetch, or null when it
 * would not: data:, blob:, relative and same-origin sources load as before.
 * Model output can embed `![](https://host/p?d=<secret>)`, and an <img> that
 * loads on render sends that request with no click — so remote ones wait.
 */
export function remoteImageHost(src: string): null | string {
  if (typeof window === 'undefined') {
    return null
  }

  try {
    const url = new URL(src, window.location.href)

    if (url.protocol !== 'http:' && url.protocol !== 'https:') {
      return null
    }

    return url.origin === window.location.origin ? null : url.hostname || null
  } catch {
    return null
  }
}

/** Renders `children` (the real <img>, <audio> or <video>) only for safe
 *  sources, or once the user has clicked to load this exact remote file. */
export function RemoteImageGate({
  children,
  kind = 'image',
  src
}: {
  children: ReactNode
  kind?: 'audio' | 'image' | 'video'
  src: string
}) {
  const host = remoteImageHost(src)
  const [approved, setApproved] = useState(false)

  useEffect(() => setApproved(false), [src])

  if (host === null || approved) {
    return <>{children}</>
  }

  return (
    <button
      className="my-2 block max-w-full rounded-lg border border-border px-3 py-2 text-left text-sm text-muted-foreground hover:text-foreground"
      data-slot="aui_remote-image-gate"
      onClick={() => setApproved(true)}
      type="button"
    >
      Load {kind} from <span className="font-medium text-foreground">{host}</span>
    </button>
  )
}
