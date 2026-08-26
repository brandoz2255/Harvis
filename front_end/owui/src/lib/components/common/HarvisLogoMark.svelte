<script lang="ts">
	// Static Harvis robot mark for app chrome (sidebar corner, collapsed rail).
	// Inlined rather than <img src="/static/harvis-logo.svg"> so it can read the
	// theme's accent vars — CSS custom properties cannot cross into an <img>-loaded
	// SVG document. Colors mirror HarvisMascot.svelte: accent = --color-blue-400,
	// body = the blue ramp, face screen = the gray ramp (so it re-hues per theme:
	// cyan in Midnight, indigo in Airy, coral in Warm).
	//
	// NOTE: the gradient/filter ids are namespaced `harvisMark*` on purpose —
	// HarvisMascot.svelte uses `harvisGlow`/`harvisBodyGradient`/`harvisScreenGradient`,
	// and duplicate ids on the same page cross-wire the paint servers.
	export let className = 'size-6';
</script>

<svg
	xmlns="http://www.w3.org/2000/svg"
	viewBox="0 0 60 70"
	fill="none"
	class={className}
	aria-hidden="true"
>
	<defs>
		<filter id="harvisMarkGlow" x="-50%" y="-50%" width="200%" height="200%">
			<feGaussianBlur stdDeviation="1.5" result="coloredBlur" />
			<feMerge>
				<feMergeNode in="coloredBlur" />
				<feMergeNode in="SourceGraphic" />
			</feMerge>
		</filter>
		<linearGradient id="harvisMarkBody" x1="0%" y1="0%" x2="0%" y2="100%">
			<stop offset="0%" stop-color="var(--color-blue-500)" />
			<stop offset="100%" stop-color="var(--color-blue-700)" />
		</linearGradient>
		<linearGradient id="harvisMarkScreen" x1="0%" y1="0%" x2="0%" y2="100%">
			<stop offset="0%" stop-color="var(--color-gray-800)" />
			<stop offset="100%" stop-color="var(--color-gray-950)" />
		</linearGradient>
	</defs>

	<g>
		<line
			x1="20"
			y1="8"
			x2="16"
			y2="0"
			stroke="var(--harvis-mark-accent)"
			stroke-width="2"
			stroke-linecap="round"
		/>
		<circle cx="16" cy="2" r="3" fill="var(--harvis-mark-accent)" filter="url(#harvisMarkGlow)" />
		<line
			x1="40"
			y1="8"
			x2="44"
			y2="0"
			stroke="var(--harvis-mark-accent)"
			stroke-width="2"
			stroke-linecap="round"
		/>
		<circle cx="44" cy="2" r="3" fill="var(--harvis-mark-accent)" filter="url(#harvisMarkGlow)" />

		<rect x="12" y="8" width="36" height="30" rx="6" fill="url(#harvisMarkBody)" />
		<rect x="16" y="12" width="28" height="22" rx="3" fill="url(#harvisMarkScreen)" />

		<path
			d="M21 21 Q24 17 27 21"
			stroke="var(--harvis-mark-accent)"
			stroke-width="2.5"
			stroke-linecap="round"
			fill="none"
			filter="url(#harvisMarkGlow)"
		/>
		<path
			d="M33 21 Q36 17 39 21"
			stroke="var(--harvis-mark-accent)"
			stroke-width="2.5"
			stroke-linecap="round"
			fill="none"
			filter="url(#harvisMarkGlow)"
		/>
		<path
			d="M24 28 Q30 33 36 28"
			stroke="var(--harvis-mark-accent)"
			stroke-width="2"
			stroke-linecap="round"
			fill="none"
			filter="url(#harvisMarkGlow)"
		/>

		<rect x="14" y="38" width="10" height="28" rx="3" fill="url(#harvisMarkBody)" />
		<rect x="36" y="38" width="10" height="28" rx="3" fill="url(#harvisMarkBody)" />
		<rect x="14" y="48" width="32" height="8" rx="2" fill="url(#harvisMarkBody)" />

		<rect x="4" y="42" width="6" height="14" rx="3" fill="var(--harvis-mark-accent)" />
		<rect x="50" y="42" width="6" height="14" rx="3" fill="var(--harvis-mark-accent)" />
	</g>
</svg>
