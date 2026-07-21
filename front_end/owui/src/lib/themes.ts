// Harvis theme registry — the single source of truth for the theme changer.
//
// A theme is a TOKEN MAP, not a stylesheet (see DESIGN.md → Theming). Each theme picks a
// base Tailwind mode (`dark`|`light`) and a set of CSS-variable overrides — the surface
// `--color-gray-*` ramp, the `--color-blue-*` accent, and an optional `--theme-font-body`.
// Components never change; switching a theme just rewrites these variables. Adding a theme =
// adding an entry here, then mirroring its FOUC-critical values in `src/app.html`'s inline
// loader (which runs before this module and paints the first frame). Keep the two in sync.

export type ThemeGroup = 'system' | 'dark' | 'light';

export interface ThemeDef {
	id: string; // persisted to localStorage.theme
	label: string;
	icon: string;
	base: 'dark' | 'light'; // Tailwind mode class ('system' is resolved at runtime)
	vars?: Record<string, string>; // CSS custom-property overrides
	font?: string; // optional --theme-font-body value (e.g. a serif reading face)
	metaColor: string; // <meta name="theme-color">
	group: ThemeGroup;
	eggOnly?: boolean; // gated behind enable_easter_eggs
}

// Every CSS var any theme may touch — cleared on each switch so nothing leaks between themes.
export const MANAGED_VARS = [
	'--color-gray-50', '--color-gray-100', '--color-gray-200', '--color-gray-300',
	'--color-gray-400', '--color-gray-500', '--color-gray-600', '--color-gray-700',
	'--color-gray-800', '--color-gray-850', '--color-gray-900', '--color-gray-950',
	'--color-blue-400', '--color-blue-500', '--color-blue-600', '--color-blue-700',
	'--theme-font-body'
];

export const THEMES: ThemeDef[] = [
	{ id: 'system', label: 'System', icon: '🖥️', base: 'dark', metaColor: '#00030b', group: 'system' },

	// ── Dark ──
	// Midnight = the tailwind.css @theme near-black blue-charcoal ramp itself (no overrides).
	// This is Harvis's default identity; leaving vars empty also fixes the old bug where
	// re-selecting "Dark" neutralised the ramp to #171717.
	{ id: 'dark', label: 'Midnight', icon: '🌑', base: 'dark', metaColor: '#00030b', group: 'dark' },
	{
		id: 'harvis-dark', label: 'Slate', icon: '🤖', base: 'dark', group: 'dark', metaColor: '#0e111a',
		vars: { '--color-gray-800': '#1a1f2e', '--color-gray-850': '#141823', '--color-gray-900': '#0e111a', '--color-gray-950': '#090b12' }
	},
	{
		id: 'oled-dark', label: 'OLED', icon: '🌃', base: 'dark', group: 'dark', metaColor: '#000000',
		vars: { '--color-gray-800': '#101010', '--color-gray-850': '#050505', '--color-gray-900': '#000000', '--color-gray-950': '#000000' }
	},

	// ── Light ──
	{ id: 'light', label: 'Light', icon: '☀️', base: 'light', metaColor: '#ffffff', group: 'light' },
	{
		// Airy — cool light-gray canvas + soft indigo accent (Ref 1 · MetricFlow). White cards
		// come from components' bg-white in light mode; the pastel KPI treatment is per-page.
		id: 'airy', label: 'Airy', icon: '🌤️', base: 'light', group: 'light', metaColor: '#f4f6f8',
		vars: {
			'--color-gray-50': '#f4f6f8', '--color-gray-100': '#eef1f5', '--color-gray-200': '#e3e8ee',
			'--color-blue-400': '#8b8ef7', '--color-blue-500': '#6d70f0', '--color-blue-600': '#5457e6', '--color-blue-700': '#4143c9'
		}
	},
	{
		// Warm — cream paper + coral accent + serif reading font (Ref 2 · Claude.ai). Overrides
		// the dark-end grays too because in light mode those tokens are the TEXT color.
		id: 'warm', label: 'Warm', icon: '📜', base: 'light', group: 'light', metaColor: '#f5f1e8',
		font: "'InstrumentSerif', Georgia, 'Times New Roman', serif",
		vars: {
			'--color-gray-50': '#f5f1e8', '--color-gray-100': '#efe9dc', '--color-gray-200': '#e6ddcc',
			'--color-gray-700': '#3a352c', '--color-gray-800': '#2b2a26', '--color-gray-900': '#211f1b',
			'--color-blue-400': '#e89f86', '--color-blue-500': '#df8365', '--color-blue-600': '#d0684a', '--color-blue-700': '#b5543a'
		}
	},

	{ id: 'her', label: 'Her', icon: '🌷', base: 'light', metaColor: '#983724', group: 'light', eggOnly: true }
];

export const getTheme = (id: string): ThemeDef | undefined => THEMES.find((t) => t.id === id);

/** Resolve the concrete Tailwind base for an id (handles 'system' + unknown ids). */
export const resolveBase = (id: string): 'dark' | 'light' => {
	if (id === 'system' || !getTheme(id)) {
		return typeof window !== 'undefined' &&
			window.matchMedia('(prefers-color-scheme: dark)').matches
			? 'dark'
			: 'light';
	}
	return (getTheme(id) as ThemeDef).base;
};

/**
 * Apply a theme by id: clear managed vars, set the base mode class + a `theme-<id>` marker +
 * `data-theme`, write the var/font overrides, and sync `<meta theme-color>`. Idempotent; the
 * single runtime entry point used by the settings picker and the desktop `theme:update` event.
 */
export const applyThemeById = (id: string): void => {
	if (typeof document === 'undefined') return;
	const el = document.documentElement;
	const def = getTheme(id);
	const base = resolveBase(id);

	// 1) clear anything a previous theme set, so nothing leaks
	for (const v of MANAGED_VARS) el.style.removeProperty(v);

	// 2) base mode class + markers (drop the old base + any theme-* marker first)
	['dark', 'light', 'her'].forEach((c) => el.classList.remove(c));
	Array.from(el.classList)
		.filter((c) => c.startsWith('theme-'))
		.forEach((c) => el.classList.remove(c));
	el.classList.add(base);
	if (id === 'her') el.classList.add('her');
	el.classList.add(`theme-${def ? def.id : 'dark'}`);
	el.dataset.theme = id;

	// 3) var + font overrides
	if (def?.vars) for (const [k, val] of Object.entries(def.vars)) el.style.setProperty(k, val);
	if (def?.font) el.style.setProperty('--theme-font-body', def.font);

	// 4) meta theme-color
	const meta = document.querySelector('meta[name="theme-color"]');
	if (meta) {
		const color =
			id === 'system' ? (base === 'dark' ? '#00030b' : '#ffffff') : (def?.metaColor ?? '#00030b');
		meta.setAttribute('content', color);
	}
};
