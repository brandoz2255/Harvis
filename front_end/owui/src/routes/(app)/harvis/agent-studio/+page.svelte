<script lang="ts">
	import { getContext } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { WEBUI_NAME, chatId } from '$lib/stores';
	import WorkspaceActivity from '$lib/components/chat/WorkspaceActivity.svelte';
	import IntentPills from '$lib/agent-studio/IntentPills.svelte';
	import Brain from '$lib/agent-studio/Brain.svelte';
	import { surfaces } from '$lib/agent-studio/surfaces';
	import Map from '$lib/components/icons/Map.svelte';
	import ChartBar from '$lib/components/icons/ChartBar.svelte';
	import Bolt from '$lib/components/icons/Bolt.svelte';

	const i18n: any = getContext('i18n');

	const surfaceIcon: Record<string, any> = {
		'global-map': Map,
		'model-comparison': ChartBar,
		activity: Bolt
	};

	// A run id in ?ws= is the OLD deep-link shape — redirect to the dedicated run
	// view (the canonical run page). Preserves every old link; back button stays
	// clean via replaceState.
	$: wsId = $page.url.searchParams.get('ws');
	$: if (wsId) goto(`/harvis/agent-studio/run/${wsId}`, { replaceState: true });

	// One-click hop back to the last-viewed chat (the sidebar pin handles chat→studio).
	const backToChat = () => goto($chatId ? `/c/${$chatId}` : '/');

	// Full-page surface links (Brain + Tuning already live on this page;
	// Neural Map ('global-map') is nested under Brain → all excluded).
	const surfaceLinks = surfaces.filter(
		(s) => s.modes.includes('full') && !['brain', 'tuning', 'global-map'].includes(s.key)
	);
</script>

<svelte:head>
	<title>{$i18n.t('Agent Studio')} • {$WEBUI_NAME}</title>
</svelte:head>

<div class="w-full h-full overflow-y-auto">
	<div class="max-w-3xl mx-auto px-4 py-6 space-y-8">
		<!-- Band 1 — header + intent pills -->
		<header>
			<button
				class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 mb-2"
				on:click={backToChat}>← {$i18n.t('Back to chat')}</button
			>
			<h1 class="text-xl font-medium text-gray-800 dark:text-gray-100">
				{$i18n.t('Agent Studio')}
			</h1>
			<p class="text-sm text-gray-500 mt-1 mb-4">
				{$i18n.t('Configure your agent, then start a task or watch it run.')}
			</p>
			<IntentPills />
			<nav class="mt-3 flex flex-wrap items-center gap-1">
				{#each surfaceLinks as s (s.key)}
					<a
						href={`/harvis/agent-studio/${s.key}`}
						class="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg text-gray-500 hover:text-blue-600 dark:hover:text-blue-400 hover:bg-gray-100 dark:hover:bg-gray-850 transition"
					>
						<svelte:component this={surfaceIcon[s.key]} className="size-3.5" />
						{$i18n.t(s.label)}
					</a>
				{/each}
			</nav>
		</header>

		<!-- Band 2 — Brain config (OpenClaw · Skills · Memory) -->
		<section>
			<h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
				{$i18n.t('Brain')}
			</h2>
			<Brain />
		</section>

		<!-- Band 3 — run logs -->
		<section>
			<h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
				{$i18n.t('Runs')}
			</h2>
			<WorkspaceActivity />
		</section>
	</div>
</div>
