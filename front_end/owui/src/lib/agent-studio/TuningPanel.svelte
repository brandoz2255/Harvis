<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { models } from '$lib/stores';
	import Controls from '$lib/components/chat/Controls/Controls.svelte';

	const i18n: any = getContext('i18n');
	export let mode: 'full' | 'dock' = 'full';

	// The agent's default behaviour — the SAME Controls component used in the chat
	// right rail (relocate, don't rebuild). OWUI's facade stubs user-settings, so
	// these defaults persist to localStorage (durable per-browser). Wiring them
	// into actual run behaviour is a follow-up.
	const TUNING_KEY = 'harvis.tuning.defaults';
	let params: Record<string, any> = {};
	let seeded = false;
	let saveTimer: ReturnType<typeof setTimeout>;

	onMount(() => {
		try {
			const stored = JSON.parse(localStorage.getItem(TUNING_KEY) || 'null');
			if (stored && typeof stored === 'object') params = stored;
		} catch (e) {
			console.error('tuning seed', e);
		}
		seeded = true;
	});

	$: if (seeded && params) {
		clearTimeout(saveTimer);
		saveTimer = setTimeout(() => {
			try {
				localStorage.setItem(TUNING_KEY, JSON.stringify(params));
			} catch (e) {
				console.error('tuning save', e);
			}
		}, 400);
	}
</script>

<div class={mode === 'full' ? 'p-4 w-full h-full overflow-y-auto' : ''}>
	<div class="mb-2 text-xs text-gray-400">
		{$i18n.t('Default behaviour for the agent (saved on this device).')}
	</div>
	{#if seeded}
		<Controls embed={true} models={$models} chatFiles={[]} bind:params />
	{/if}
</div>
