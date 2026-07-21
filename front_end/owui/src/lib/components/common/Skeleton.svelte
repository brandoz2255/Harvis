<script lang="ts">
	// Shared skeleton bar — the primitive behind content-shaped loading placeholders
	// (generalized from Sidebar/ChatItemSkeleton). Compose bars inside a container
	// that mirrors the REAL layout being loaded, and put aria-busy="true" +
	// aria-hidden="true" on that container — each bar is purely decorative.
	// The shimmer sweeps a gray-token gradient (theme-aware: airy/warm/harvis-dark
	// re-tint via --color-gray-*); prefers-reduced-motion drops the sweep and
	// leaves the static tint in place.
	export let width = '100%';
	export let height = '0.75rem';
	export let rounded = 'rounded-md';
	export let delay = 0; // ms — stagger rows so a list reads as a cascade
	export let className = '';
</script>

<div
	class="skeleton-bar relative overflow-hidden bg-gray-100 dark:bg-gray-850 {rounded} {className}"
	style="width: {width}; height: {height}; --skeleton-delay: {delay}ms;"
></div>

<style>
	.skeleton-bar::after {
		content: '';
		position: absolute;
		inset: 0;
		transform: translateX(-100%);
		background: linear-gradient(90deg, transparent, var(--color-gray-50, transparent), transparent);
		animation: skeleton-shimmer 1.6s ease-in-out var(--skeleton-delay, 0ms) infinite;
	}
	:global(html.dark) .skeleton-bar::after {
		background: linear-gradient(90deg, transparent, var(--color-gray-800, transparent), transparent);
	}
	@media (prefers-reduced-motion: reduce) {
		.skeleton-bar::after {
			display: none;
		}
	}
	@keyframes skeleton-shimmer {
		100% {
			transform: translateX(100%);
		}
	}
</style>
