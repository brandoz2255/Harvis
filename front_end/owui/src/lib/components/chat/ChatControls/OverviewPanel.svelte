<script lang="ts">
	import ViewPanel from './ViewPanel.svelte';
</script>

<!-- Overview = the process rail: ONE dense column of this chat's background tasks
     (Running + Finished N). Each row expands IN PLACE to the run's detail (folded
     phases → per-agent table, Table⇄Graph) — no separate docked surface, no page.
     The ChatControls 'overview' content wrapper provides the scroll + padding. -->
<div class="space-y-2">
	<ViewPanel />
</div>
