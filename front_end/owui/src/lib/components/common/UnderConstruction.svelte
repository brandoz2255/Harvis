<script lang="ts">
	import { getContext } from 'svelte';
	const i18n: any = getContext('i18n');

	// An honest "this isn't finished" marker. Deliberately does NOT block the surface:
	// the work underneath still runs, so it stays usable while it's being built out.
	// `variant="page"` = a full centred panel for a surface that is mostly a shell;
	// `variant="banner"` (default) = a strip above working content.
	export let variant: 'banner' | 'page' = 'banner';
	export let title = '';
	export let note = '';
</script>

{#if variant === 'page'}
	<div class="w-full h-full flex items-center justify-center p-6">
		<div
			class="max-w-md w-full rounded-2xl border border-amber-200 dark:border-amber-900/60 bg-amber-50 dark:bg-amber-950/20 px-5 py-6 text-center"
		>
			<svg
				class="size-7 mx-auto mb-3 text-amber-600 dark:text-amber-400"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="1.6"
				stroke-linecap="round"
				stroke-linejoin="round"
				aria-hidden="true"
			>
				<path d="M12 9v4M12 17h.01" />
				<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
			</svg>
			<div class="text-sm font-semibold text-amber-900 dark:text-amber-200">
				{title || $i18n.t('Under construction')}
			</div>
			<p class="mt-1.5 text-xs text-amber-800/80 dark:text-amber-200/70 leading-relaxed">
				{note ||
					$i18n.t(
						'This area is still being built. What you see here is incomplete and may change or not work yet.'
					)}
			</p>
		</div>
	</div>
{:else}
	<div
		class="flex items-start gap-2.5 rounded-xl border border-amber-200 dark:border-amber-900/60 bg-amber-50 dark:bg-amber-950/20 px-3 py-2.5"
		role="note"
	>
		<svg
			class="size-4 mt-px shrink-0 text-amber-600 dark:text-amber-400"
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			stroke-width="1.8"
			stroke-linecap="round"
			stroke-linejoin="round"
			aria-hidden="true"
		>
			<path d="M12 9v4M12 17h.01" />
			<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
		</svg>
		<div class="min-w-0">
			<div class="text-xs font-medium text-amber-900 dark:text-amber-200">
				{title || $i18n.t('Under construction')}
			</div>
			<p class="text-[11px] text-amber-800/80 dark:text-amber-200/70 leading-relaxed">
				{note ||
					$i18n.t('This area is still being built — expect rough edges and changes.')}
			</p>
		</div>
	</div>
{/if}
