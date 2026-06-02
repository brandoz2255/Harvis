<script lang="ts">
	import { getContext } from 'svelte';
	import { page } from '$app/stores';
	import { WEBUI_NAME } from '$lib/stores';
	import WorkspaceActivity from '$lib/components/chat/WorkspaceActivity.svelte';
	import WorkspaceRunCard from '$lib/components/chat/Messages/WorkspaceRunCard.svelte';

	const i18n: any = getContext('i18n');

	// Optional ?ws=<id> focuses a specific run (the card streams/replays it).
	$: wsId = $page.url.searchParams.get('ws');
</script>

<svelte:head>
	<title>{$i18n.t('Agent Studio')} • {$WEBUI_NAME}</title>
</svelte:head>

<div class="w-full h-full overflow-y-auto">
	<div class="max-w-3xl mx-auto px-4 py-6">
		<h1 class="text-xl font-medium text-gray-800 dark:text-gray-100">{$i18n.t('Agent Studio')}</h1>
		<p class="text-sm text-gray-500 mt-1 mb-5">
			{$i18n.t('Your agent workspace runs — live and recent.')}
		</p>

		{#if wsId}
			{#key wsId}
				<WorkspaceRunCard
					attributes={{ workspaceid: wsId, tasklabel: $i18n.t('Workspace run') }}
					className="w-full mb-6"
				/>
			{/key}
		{/if}

		<WorkspaceActivity />
	</div>
</div>
