<script lang="ts">
	// Adaptive Space's slot now holds CAD Studio (Gate 6, 2026-08-03).
	//
	// The old "coming soon" placeholder is gone: the HUD it was holding a space for
	// was never user-ready, and CAD is the thing that is. Rather than let two URLs
	// render the same workspace, this one redirects — `/harvis/cad` is canonical.
	//
	// The Adaptive Space components (AdaptiveSpaceShell, RepoRunnerSurface and the
	// rest of lib/agent-studio/adaptive/) are NOT deleted. Nothing imports them, so
	// they cost nothing at runtime, and keeping them means "rebuild it later" is a
	// revival rather than a rewrite. Bringing it back is: mount the shell here instead
	// of redirecting, and restore the sidebar link in components/layout/Sidebar.svelte.
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	onMount(() => {
		goto('/harvis/cad', { replaceState: true });
	});
</script>
