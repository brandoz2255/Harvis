<script lang="ts">
	// Old Adaptive Space deep links land on CAD Studio's project list, not on a CAD
	// project: an adaptive space id is not a `cad_projects` id, and quietly opening
	// "some part" for a link that named a different thing would be worse than landing
	// one level up.
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	onMount(() => {
		goto('/harvis/cad', { replaceState: true });
	});
</script>
