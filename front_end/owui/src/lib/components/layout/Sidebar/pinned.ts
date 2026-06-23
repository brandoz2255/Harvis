// Single source of truth for the default pinned sidebar items. Imported by both
// Sidebar.svelte (which renders the pins) and Sidebar/UserMenu.svelte (the pin-toggle
// menu), so the rendered defaults and the pin-state checkmarks can never diverge.
//
// 'vibecode' and 'open-notebook' are intentionally NOT default-pinned: the
// Chat / Notebook / Code mode pill at the top of the sidebar already owns those
// entry points (same hrefs), so pinning them too would be a duplicate door. They
// remain in getMenuItemMeta / isMenuItemVisible, so a user can still pin them by hand.
export const DEFAULT_PINNED_ITEMS = ['agent-studio', 'artifacts', 'workspace'];
