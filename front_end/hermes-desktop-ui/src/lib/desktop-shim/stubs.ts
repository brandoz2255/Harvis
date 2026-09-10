// Benign stand-ins for the OS-level members of `window.hermesDesktop`.
//
// The contract, from the Phase 1 handoff: a stub RESOLVES to a harmless value
// and never throws, and every `on*` listener hands back a no-op disposer so the
// caller's cleanup path stays honest. A stub that throws takes a React subtree
// down with it; a stub that returns nothing useful just makes one control inert.
//
// Only the 68 NON-OPTIONAL members belong here. The ~60 optional ones are left
// genuinely `undefined` on purpose — the app already feature-detects those with
// `hermesDesktop?.x`, and filling them in would tell it a capability exists that
// the browser cannot deliver.

import { gatewayWsUrl } from './api'

/** A listener registration that never fires. Returns the disposer callers expect. */
export const noopListener = () => () => {}

const ok = async () => ({ ok: true })
const notOk = async () => ({ ok: false })

export const connection = async () => ({
  baseUrl: location.origin,
  // Harvis authenticates by cookie; there is no bearer token to hand back.
  token: '',
  wsUrl: gatewayWsUrl(),
  isFullscreen: false,
  nativeOverlayWidth: 0,
  logs: [] as string[],
  mode: 'remote' as const,
  authMode: 'token' as const,
  source: 'env' as const,
})

export const bootstrapState = async () => ({
  // `active: false` is what keeps desktop-install-overlay.tsx off the screen.
  // The browser build has nothing to bootstrap — the backend is already up.
  active: false,
  manifest: null,
  stages: {},
  error: null,
  log: [],
  startedAt: null,
  completedAt: null,
  setupChoice: null,
  unsupportedPlatform: null,
})

export const bootProgress = async () => ({
  error: null,
  fakeMode: false,
  message: '',
  phase: 'ready',
  progress: 1,
  running: false,
  timestamp: Date.now(),
})

export const version = async () => ({
  appVersion: (import.meta as any).env?.VITE_HERMES_UI_VERSION ?? 'harvis-web',
  electronVersion: '',
  nodeVersion: '',
  platform: 'web',
  hermesRoot: '',
})

/** Members with no browser equivalent, grouped by what they'd have touched. */
export const stubs = {
  // ── Connection / profiles ────────────────────────────────────────────────
  getConnection: connection,
  revalidateConnection: connection,
  touchBackend: ok,
  getProfileRoutes: async () => [],
  getConnectionConfig: async () => ({}),
  saveConnectionConfig: async () => ({}),
  applyConnectionConfig: async () => ({}),
  testConnectionConfig: async () => ({ ok: false, error: 'not available in the browser build' }),
  probeConnectionConfig: async () => ({ ok: false, error: 'not available in the browser build' }),
  oauthLoginConnectionConfig: notOk,
  oauthLogoutConnectionConfig: notOk,
  getSecretStorageEncryption: async () => ({ enabled: false }),
  setSecretStorageEncryption: async () => ({ enabled: false }),
  sshConfigHosts: async () => [],
  sshResolveHost: async () => null,
  connections: {
    list: async () => ({ connections: [], primaryId: null }),
    save: notOk,
    remove: notOk,
    setPrimary: notOk,
    test: async () => ({ ok: false, error: 'not available in the browser build' }),
  },
  cloud: {
    status: async () => ({ signedIn: false }),
    login: notOk,
    logout: ok,
    discover: async () => ({ agents: [] }),
    agentSignIn: notOk,
  },
  profile: {
    get: async () => ({ name: null }),
    remember: async () => ({ name: null }),
    set: async () => ({ name: null }),
  },

  // ── Windows the browser cannot open ──────────────────────────────────────
  openSessionWindow: notOk,
  openSessionInTerminal: notOk,
  openWindow: notOk,
  openBrowserWindow: notOk,
  onBrowserPopoutClosed: noopListener,
  claimAmbientCue: async () => false,

  // ── Filesystem ───────────────────────────────────────────────────────────
  readFileDataUrl: async () => null,
  readFileText: async () => null,
  readDir: async () => [],
  selectPaths: async () => [],
  getPathForFile: () => '',
  sanitizeWorkspaceCwd: async (cwd?: string) => cwd ?? '',
  saveImageFromUrl: notOk,
  saveImageBuffer: notOk,
  saveClipboardImage: notOk,
  revealLogs: ok,
  getRecentLogs: async () => [],

  // ── Preview file watching ────────────────────────────────────────────────
  normalizePreviewTarget: async (target?: unknown) => target ?? null,
  watchPreviewFile: notOk,
  stopPreviewFileWatch: ok,
  onPreviewFileChanged: noopListener,

  // ── PTY ──────────────────────────────────────────────────────────────────
  terminal: {
    start: async () => ({ id: '', pid: 0 }),
    write: async () => false,
    resize: async () => false,
    dispose: async () => false,
    cwd: async () => null,
    onData: noopListener,
    onExit: noopListener,
  },

  // ── Bootstrap / lifecycle ────────────────────────────────────────────────
  getBootstrapState: bootstrapState,
  getBootProgress: bootProgress,
  continueBootstrapLocal: ok,
  resetBootstrap: ok,
  repairBootstrap: ok,
  cancelBootstrap: async () => ({ ok: true, cancelled: false }),
  onBootstrapEvent: noopListener,
  onBootProgress: noopListener,
  onBackendExit: noopListener,

  // ── App shell ────────────────────────────────────────────────────────────
  getVersion: version,
  updates: {
    check: async () => ({ available: false }),
    apply: notOk,
    getBranch: async () => ({ branch: '' }),
    setBranch: async () => ({ branch: '' }),
    onProgress: noopListener,
  },
  uninstall: {
    summary: async () => ({}),
    run: notOk,
  },
  findInPage: async () => ({ matches: 0 }),
  stopFindInPage: ok,
  onFoundInPage: noopListener,
  onOpenFindBarRequested: noopListener,
  requestMicrophoneAccess: async () => {
    // The browser asks on its own when getUserMedia runs; nothing to pre-grant.
    return true
  },
  fetchLinkTitle: async () => null,

  // ── Overlays that need a second native window ────────────────────────────
  petOverlay: {
    open: notOk,
    close: ok,
    setBounds: () => {},
    setIgnoreMouse: () => {},
    setFocusable: () => {},
    pushState: () => {},
    control: () => {},
    onState: noopListener,
    onControl: noopListener,
  },
  quickEntry: {
    getSettings: async () => ({ enabled: false, registered: false, shortcut: '' }),
    setSettings: async () => ({ enabled: false, registered: false, shortcut: '' }),
    submit: () => {},
    dismiss: () => {},
  },
}
