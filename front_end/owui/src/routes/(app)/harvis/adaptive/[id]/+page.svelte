<script lang="ts">
	// Direct/share URL for a saved space — renders the SAME shell as
	// /harvis/adaptive (no separate page experience), seeded with the id.
	import { getContext } from 'svelte';
	import { page } from '$app/stores';
	import { WEBUI_NAME } from '$lib/stores';
	import AdaptiveSpaceShell from '$lib/agent-studio/adaptive/AdaptiveSpaceShell.svelte';

	const i18n: any = getContext('i18n');
</script>

<svelte:head>
	<title>{$i18n.t('Adaptive Space')} • {$WEBUI_NAME}</title>
</svelte:head>

{#key $page.params.id}
	<AdaptiveSpaceShell initialSpaceId={$page.params.id} />
{/key}
