<script lang="ts">
	import { dockedRunId } from '$lib/stores';
	import RunWorkspace from '$lib/agent-studio/RunWorkspace.svelte';
	import ViewPanel from './ViewPanel.svelte';
</script>

<!-- Overview = the docked run's live workspace (Processes + Map + Changes) on
     top, then the all-runs Progress / Recent lists. The ChatControls 'overview'
     content wrapper provides the scroll + padding. -->
<div class="space-y-2">
	{#if $dockedRunId}
		<RunWorkspace wsId={$dockedRunId} />
	{/if}
	<ViewPanel />
</div>
