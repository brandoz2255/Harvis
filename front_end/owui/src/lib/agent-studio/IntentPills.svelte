<script lang="ts">
	import { getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { researchEnabled } from '$lib/stores';

	const i18n: any = getContext('i18n');

	// v1: intent pills are routers / prompt-presets, NOT new features. Deep
	// per-feature wiring (research backend, hash/decode skill routing) is P4.
	type Intent = { key: string; label: string; hint: string; run: () => void };

	const go = (path: string) => goto(path);

	const intents: Intent[] = [
		{
			key: 'auto',
			label: 'Auto',
			hint: 'Start a normal chat — Harvis auto-detects the task.',
			run: () => go('/')
		},
		{
			key: 'hash',
			label: 'Hash',
			hint: 'Prefill a hash-cracking prompt — paste your hash, then send.',
			run: () =>
				go(
					`/?q=${encodeURIComponent(
						'Crack this hash — identify the algorithm and use the hash-cracking skill:\n'
					)}&submit=false`
				)
		},
		{
			key: 'decode',
			label: 'Decode',
			hint: 'Prefill a decode prompt — paste your encoded text, then send.',
			run: () =>
				go(
					`/?q=${encodeURIComponent(
						'Decode this — identify the encoding (base64 / hex / url / rot13 / …) and decode it:\n'
					)}&submit=false`
				)
		},
		{
			key: 'research',
			label: 'Research',
			hint: 'Enable research mode, then start a chat.',
			run: () => {
				researchEnabled.set(true);
				go('/');
			}
		}
		// Vibecode intent intentionally omitted — the Vibe Code workspace is parked;
		// general/advanced AI use leads the hub. Re-add when Vibecode is revived.
	];
</script>

<div class="flex flex-wrap items-center gap-2">
	{#each intents as intent (intent.key)}
		<button
			type="button"
			class="text-sm px-3.5 py-1.5 rounded-full border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900 text-gray-700 dark:text-gray-200 hover:border-blue-500 hover:text-blue-600 dark:hover:text-blue-400 transition"
			title={$i18n.t(intent.hint)}
			on:click={intent.run}
		>
			{$i18n.t(intent.label)}
		</button>
	{/each}
</div>
