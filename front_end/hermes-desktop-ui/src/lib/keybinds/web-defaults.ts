// Harvis serves this renderer as a web page, not an Electron app. A browser
// keeps some chords for itself and never hands them to a page: Ctrl/⌘+N, +T,
// +W, +Shift+N, +Shift+T, +Shift+W, Ctrl+Tab and Ctrl+PgUp/PgDn open, close or
// switch *browser* tabs and windows. A hint that says "Ctrl+N" there names a
// key that opens a browser window instead of a new chat, so on the web those
// actions ship with Alt chords the page does receive.

// Set by `lib/desktop-shim`, which only installs when Electron's bridge is absent.
export const IS_WEB_SHELL =
  typeof window !== 'undefined' &&
  (window as { hermesDesktop?: { webShell?: boolean } }).hermesDesktop?.webShell === true

const SESSION_SLOTS = Object.fromEntries(
  Array.from({ length: 9 }, (_, i) => [`session.slot.${i + 1}`, [`alt+shift+${i + 1}`]])
)

export const WEB_DEFAULTS: Readonly<Record<string, readonly string[]>> = {
  'session.new': ['alt+n'],
  'session.newTab': ['alt+t'],
  // A page can't open a second app window; the browser's own Ctrl+N does that.
  'session.newWindow': [],
  'session.next': ['alt+]'],
  'session.prev': ['alt+['],
  // Alt+digit switches browser tabs on Linux, so slots take Alt+Shift.
  ...SESSION_SLOTS,
  'view.closeTab': ['alt+w'],
  'view.reopenTab': ['alt+shift+t'],
  'view.closeTerminal': ['alt+shift+w']
}

/** Defaults with the browser-reserved chords swapped out. */
export function webSafeDefaults(id: string, defaults: readonly string[]): readonly string[] {
  return WEB_DEFAULTS[id] ?? defaults
}

/** Whether `combo` is one of the Alt replacements, which fire from inputs like the Ctrl chords they replace. */
export function isWebReplacement(actionId: string, combo: string): boolean {
  return WEB_DEFAULTS[actionId]?.includes(combo) ?? false
}
