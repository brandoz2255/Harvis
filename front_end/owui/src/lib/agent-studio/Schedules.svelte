<script lang="ts">
	// Schedules = the MAIN-CHAT lens over the one cron store (Automations.svelte
	// is the single implementation; this thin wrapper just pins context='chat').
	// A fired Schedule runs its prompt through a chat completion and posts the
	// reply into an owui chat — no workspace run.
	import Automations from './Automations.svelte';

	export let mode: 'full' | 'dock' = 'full';
	export let embed = false;
</script>

<Automations {mode} {embed} context="chat" />
