/**
 * The window an MCP OAuth consent screen opens in.
 *
 * Browsers only allow `window.open` inside the click that asked for it. The OAuth
 * start request takes seconds (server discovery, registration), so opening the
 * authorization URL after it would be blocked as an unrequested popup. The fix is
 * to open the window synchronously, blank, and point it at the URL once it
 * arrives. The desktop (Electron) build has no such rule and hands the URL to the
 * system browser instead.
 *
 * Completion is NOT reported through the popup: the flow is polled server-side
 * (`completeMcpDesktopOAuth`), so the popup is closed by the callback page, by the
 * person, or by `close()` here. The popup's `opener` is cut so the vendor's
 * consent page cannot reach back into Harvis.
 */

import { type CompleteOptions, completeMcpDesktopOAuth, type McpOAuthFlow } from './mcp-dashboard-oauth'

export interface OAuthWindow {
  /** Show the consent screen. Falls back to a new tab if the popup was blocked. */
  open: (url: string) => Promise<void>
  /** Close the popup if it is still open. Safe to call twice. */
  close: () => void
}

const POPUP_NAME = 'harvis-mcp-oauth'
const POPUP_FEATURES = 'popup,width=560,height=780'

export function prepareOAuthWindow(): OAuthWindow {
  const desktop = typeof window === 'undefined' ? undefined : window.hermesDesktop
  const inBrowserTab = Boolean((desktop as { webShell?: boolean } | undefined)?.webShell)
  let popup: Window | null = null

  if (inBrowserTab) {
    try {
      popup = window.open('about:blank', POPUP_NAME, POPUP_FEATURES)

      if (popup) {
        popup.opener = null
      }
    } catch {
      popup = null
    }
  }

  return {
    async open(url) {
      if (popup && !popup.closed) {
        popup.location.href = url

        return
      }

      await window.hermesDesktop.openExternal(url)
    },
    close() {
      try {
        if (popup && !popup.closed) {
          popup.close()
        }
      } catch {
        // already gone
      }
    }
  }
}

/**
 * Run a whole MCP OAuth flow: open the popup inside the caller's click, start the
 * flow, show the consent screen, poll to completion, and always close the popup.
 * Call it directly from the click handler, before any `await`.
 */
export async function connectMcpWithPopup(options: Omit<CompleteOptions, 'openExternal'>): Promise<McpOAuthFlow> {
  const win = prepareOAuthWindow()

  try {
    return await completeMcpDesktopOAuth({ ...options, openExternal: url => win.open(url) })
  } finally {
    win.close()
  }
}
