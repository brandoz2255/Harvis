<script lang="ts">
	import { getContext } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { showSidebar, WEBUI_NAME } from '$lib/stores';
	import { surfaceByKey } from '$lib/agent-studio/surfaces';
	import UnderConstruction from '$lib/components/common/UnderConstruction.svelte';

	const i18n: any = getContext('i18n');

	$: surface = surfaceByKey($page.params.surface);

	// "Go back just as I came in" — return to wherever you entered from; fall back to
	// the Agent Studio hub on a cold deep-link. Every sub-surface gets this exit.
	const back = () => {
		if (typeof window !== 'undefined' && window.history.length > 1) window.history.back();
		else goto('/harvis/agent-studio');
	};
</script>

<svelte:head>
	<title>{surface ? $i18n.t(surface.label) : $i18n.t('Agent Studio')} • {$WEBUI_NAME}</title>
</svelte:head>

<!-- Sit in the app shell's content column (right of the fixed sidebar), like the chat route. -->
<div
	class="w-full h-full flex flex-col {$showSidebar
		? 'md:max-w-[calc(100%-var(--sidebar-width))]'
		: ''}"
>
	<!-- Consistent back bar so every sub-surface is enter/exit symmetric. -->
	<div class="shrink-0 px-5 pt-4 pb-2.5 border-b border-gray-100 dark:border-gray-850">
		<button
			class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition"
			on:click={back}>← {$i18n.t('Back')}</button
		>
		{#if surface}
			<div class="text-sm font-semibold text-gray-800 dark:text-gray-100 mt-1 flex items-center gap-2">
				{$i18n.t(surface.label)}
				{#if surface.underConstruction}
					<span
						class="text-[10px] px-1.5 py-0.5 rounded-full border border-amber-300 dark:border-amber-800 text-amber-700 dark:text-amber-400"
						>{$i18n.t('WIP')}</span
					>
				{/if}
			</div>
		{/if}
	</div>

	<div class="flex-1 min-h-0 overflow-y-auto">
		{#if surface?.underConstruction}
			<!-- Honest marker, deliberately non-blocking: the surface underneath still runs. -->
			<div class="px-5 pt-4">
				<UnderConstruction />
			</div>
		{/if}
		{#if surface}
			{#key surface.key}
				<svelte:component this={surface.component} mode="full" />
			{/key}
		{:else}
			<div class="w-full h-full flex items-center justify-center text-sm text-gray-400">
				{$i18n.t('Surface not found')}
			</div>
		{/if}
	</div>
</div>
