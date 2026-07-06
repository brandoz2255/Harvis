<script lang="ts">
	// Adaptive Space — ONE session workspace. All UX lives in AdaptiveSpaceShell;
	// the active space is ?s=<id> on this same route (in-place transitions, no
	// page stacking). /harvis/adaptive/[id] renders the same shell for deep links.
	import { getContext } from 'svelte';
	import { WEBUI_NAME } from '$lib/stores';
	import AdaptiveSpaceShell from '$lib/agent-studio/adaptive/AdaptiveSpaceShell.svelte';

	const i18n: any = getContext('i18n');
</script>

<svelte:head>
	<title>{$i18n.t('Adaptive Space')} • {$WEBUI_NAME}</title>
</svelte:head>

<AdaptiveSpaceShell />
