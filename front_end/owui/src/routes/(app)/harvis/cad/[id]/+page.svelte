<script lang="ts">
	// A deep link to one part. The id is passed straight to the workspace, which asks
	// `/api/cad/projects/{id}` for it — a project the caller does not own 404s there,
	// so a guessed id in the URL reveals nothing.
	import { page } from '$app/stores';
	import CadWorkspace from '$lib/cad/CadWorkspace.svelte';

	$: projectId = $page.params.id ?? '';
</script>

<CadWorkspace {projectId} />
