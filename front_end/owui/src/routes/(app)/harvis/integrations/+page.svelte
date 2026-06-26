<script lang="ts">
	// Integrations — bridged from the UI prototype. A plug-and-play config center:
	// runtimes, model routers, code engines, and local tools surfaced as cards so
	// they don't clutter the main UI. Status is indicative of the deployment's
	// core services; actions route to the real config (Settings / Library).
	import { getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { WEBUI_NAME, chatId, showSettings } from '$lib/stores';

	const i18n: any = getContext('i18n');
	const backToChat = () => goto($chatId ? `/c/${$chatId}` : '/');

	type State = 'connected' | 'available' | 'add';
	const integrations: {
		title: string;
		type: string;
		desc: string;
		state: State;
		action?: 'manage' | 'connect' | 'add';
	}[] = [
		{
			title: 'OpenClaw',
			type: 'Agent runtime',
			desc: 'Executes multi-step tool-calling tasks in an isolated workspace pod.',
			state: 'connected',
			action: 'manage'
		},
		{
			title: 'Hermes',
			type: 'Model router',
			desc: 'Routes each request across local and cloud models automatically.',
			state: 'connected',
			action: 'manage'
		},
		{
			title: 'Ollama',
			type: 'Local models',
			desc: 'Serves local LLMs for chat, agents, and embeddings.',
			state: 'connected',
			action: 'manage'
		},
		{
			title: 'Discord',
			type: 'Messaging bot',
			desc: 'The same Harvis agent, reachable from a Discord channel.',
			state: 'connected'
		},
		{
			title: 'GitHub',
			type: 'Repos & PRs',
			desc: 'Clone repositories, review diffs, and open pull requests from Vibe Code.',
			state: 'available',
			action: 'connect'
		},
		{
			title: 'Custom Tool',
			type: 'Plugin bridge',
			desc: 'Add your own tool or MCP server to the agent toolset.',
			state: 'add',
			action: 'add'
		}
	];

	const actionLabel = { manage: 'Manage', connect: 'Connect', add: 'Add tool' } as const;

	const onAction = (it: (typeof integrations)[number]) => {
		if (it.action === 'manage') showSettings.set(true);
		else if (it.action === 'connect') goto('/harvis/vibecode');
		else if (it.action === 'add') goto('/workspace/tools');
	};
</script>

<svelte:head>
	<title>{$i18n.t('Integrations')} • {$WEBUI_NAME}</title>
</svelte:head>

<div class="w-full h-full overflow-y-auto">
	<div class="max-w-5xl mx-auto px-5 py-6 space-y-8">
		<header>
			<button
				class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
				on:click={backToChat}>← {$i18n.t('Back to chat')}</button
			>
			<h1 class="text-2xl font-semibold text-gray-800 dark:text-gray-100 mt-2">
				{$i18n.t('Integrations')}
			</h1>
			<p class="text-sm text-gray-500 mt-1">
				{$i18n.t(
					'Plug in runtimes, model routers, code engines, and local tools without cluttering the main UI.'
				)}
			</p>
		</header>

		<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
			{#each integrations as it}
				<div
					class="flex flex-col rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-4"
				>
					<div class="flex items-start justify-between gap-2">
						<div class="text-sm font-medium text-gray-800 dark:text-gray-100">{it.title}</div>
						{#if it.state === 'connected'}
							<span
								class="inline-flex items-center gap-1 shrink-0 text-[11px] font-medium text-green-600 dark:text-green-400"
							>
								<span class="size-1.5 rounded-full bg-green-500"></span>{$i18n.t('Connected')}
							</span>
						{:else if it.state === 'available'}
							<span class="shrink-0 text-[11px] font-medium text-gray-400">{$i18n.t('Available')}</span>
						{:else}
							<span class="shrink-0 text-[11px] font-medium text-blue-500">{$i18n.t('Add')}</span>
						{/if}
					</div>
					<div class="text-[11px] uppercase tracking-wide text-gray-400 mt-0.5">{it.type}</div>
					<div class="text-xs text-gray-500 leading-relaxed mt-2 flex-1">{$i18n.t(it.desc)}</div>
					{#if it.action}
						<button
							class="mt-3 self-start text-xs font-medium text-blue-600 dark:text-blue-400 hover:underline"
							on:click={() => onAction(it)}
						>
							{$i18n.t(actionLabel[it.action])}
						</button>
					{/if}
				</div>
			{/each}
		</div>
	</div>
</div>
