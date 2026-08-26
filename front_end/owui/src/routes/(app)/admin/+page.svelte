<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';

	import { config } from '$lib/stores';

	onMount(() => {
		// Admin > Users is unbacked in the Harvis facade (/api/v1/users/,
		// /api/v1/groups/* all 404), so /admin lands on Evaluations instead
		// unless the flag turns the pane back on.
		goto($config?.features?.enable_admin_users ? '/admin/users' : '/admin/evaluations');
	});
</script>
