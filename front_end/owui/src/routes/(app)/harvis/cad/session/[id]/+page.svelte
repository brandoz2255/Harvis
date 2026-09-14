<script lang="ts">
	// A CAD session opened by a chat request. The id is a session, not a project — the
	// project it shows is resolved server-side, and a session the caller does not own
	// 404s there, so a guessed id in the URL reveals nothing.
	import { page } from '$app/stores';
	import CadSessionWorkspace from '$lib/cad/CadSessionWorkspace.svelte';

	$: sessionId = $page.params.id ?? '';
</script>

<CadSessionWorkspace {sessionId} />
