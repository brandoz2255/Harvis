# Island rendering: trusted in-page mount

The island the Harvis app shows (src/mods/island-host.tsx) renders in the app's own React tree via src/island/mount.js — same origin, same process. There is no iframe, no postMessage listener and no cross-context channel, so the opaque-origin WindowProxy risk (a navigated frame keeping its proxy and receiving wildcard messages) does not apply: there is nothing to navigate and nothing to spoof. Browser tests assert that spoofed `island:*` messages change nothing and that the page holds no island iframe and no `window.__island*` global.

That is what makes private data safe here: the signed-in account's bots and its own game-art files reach the island by direct method calls on the mounted app, keyed by account id — an account switch disposes the old island (loop, listeners, art blob URLs, DOM) before the new one mounts, and art is stored per account in IndexedDB.

Isolation rules the mount keeps:

- Scoped: every DOM lookup and style sits under the caller's container (`.hi-root`); the island sets no window globals and reads no app state.
- Keys and pointer input apply only while the host marks the island interactive (Explore open), so typing in chat never reaches it.
- dispose() is total: rAF cancelled, window/document listeners removed, custom art source disposed, container emptied. Unit tests and browser tests cover account switch, sign-out and in-flight art loads.
- Game files never leave the browser: the stardew engine fetches nothing (src/mods/island-assets.test.ts enforces it).

The standalone demo page (public/island/, from src/island/main.js) still exists for the landing link; it shows demo characters only and accepts messages solely from its `?host=` origin. The app no longer embeds it.

## Mod frames and navigation

Approved mods still render in the nested sandbox (`public/mod-sandbox-proxy.html`). The domain allowlist in the manifest CSP covers fetch, XHR and WebSocket only, not navigation: CSP has no `navigate-to`, so a mod can send its own frame to another URL and the request carries whatever the mod put in it. Two things narrow that. `form-action 'none'` closes the form route. The proxy treats any `load` of the mod frame after the first as a navigation, removes the frame and reports `ui/error` to the host, so a mod cannot keep running (or keep showing a foreign page inside the app) after it leaves. The first navigation request itself is not preventable from the page, which is why mods stay behind per-mod approval.
