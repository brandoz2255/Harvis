<script lang="ts">
	// Adaptive Space is HIDDEN for the deployment cut (2026-07-12). The feature (the
	// JARVIS-style HUD + surface router) is built but its action/fabrication "run"
	// capability was never turned on, so it's not user-ready. This route shows a
	// "coming soon" placeholder instead of mounting the shell. To bring it back:
	//   1. re-import + mount <AdaptiveSpaceShell /> below (component is untouched)
	//   2. restore the sidebar nav link in components/layout/Sidebar.svelte
	import { getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { WEBUI_NAME } from '$lib/stores';

	const i18n: any = getContext('i18n');
</script>

<svelte:head>
	<title>{$i18n.t('Adaptive Space')} • {$WEBUI_NAME}</title>
</svelte:head>

<div class="w-full h-full min-h-dvh flex items-center justify-center px-6 bg-gray-50 dark:bg-gray-950">
	<div class="max-w-md text-center">
		<div class="mx-auto mb-5 size-14 grid place-items-center rounded-2xl bg-gray-100 dark:bg-gray-900 border border-gray-200 dark:border-gray-800 text-gray-400">
			<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" class="size-7">
				<path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1" /><circle cx="12" cy="12" r="3.2" />
			</svg>
		</div>
		<h1 class="text-xl font-semibold text-gray-900 dark:text-gray-50">{$i18n.t('Adaptive Space')}</h1>
		<p class="mt-2 text-sm text-gray-500 leading-relaxed">
			{$i18n.t('Not available yet — Adaptive Space is still in development. Check back in a future release.')}
		</p>
		<button
			type="button"
			on:click={() => goto('/')}
			class="mt-6 inline-flex items-center gap-1.5 rounded-full border border-gray-200 dark:border-gray-700 px-4 py-1.5 text-sm font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-850 transition"
		>
			<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M12 19l-7-7 7-7" /></svg>
			{$i18n.t('Back to chat')}
		</button>
	</div>
</div>
