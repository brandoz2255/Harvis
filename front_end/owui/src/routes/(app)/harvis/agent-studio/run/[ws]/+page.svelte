<script lang="ts">
	import { getContext } from 'svelte';
	import { page } from '$app/stores';
	import { WEBUI_NAME, showSidebar } from '$lib/stores';
	import RunView from '$lib/agent-studio/RunView.svelte';

	const i18n: any = getContext('i18n');

	$: wsId = $page.params.ws;
</script>

<svelte:head>
	<title>{$i18n.t('Workflow')} • {$WEBUI_NAME}</title>
</svelte:head>

<!-- Sit inside the app shell's content column (right of the fixed sidebar). -->
<div class="w-full h-full {$showSidebar ? 'md:max-w-[calc(100%-var(--sidebar-width))]' : ''}">
	{#key wsId}
		<RunView {wsId} mode="full" />
	{/key}
</div>
