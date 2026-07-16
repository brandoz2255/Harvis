<script lang="ts">
	// Adaptive Space is HIDDEN for the deployment cut (2026-07-12) — deep-link
	// shares redirect to the /harvis/adaptive placeholder. To bring it back,
	// restore the <AdaptiveSpaceShell initialSpaceId={…} /> mount below.
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	onMount(() => {
		goto('/harvis/adaptive', { replaceState: true });
	});
</script>
