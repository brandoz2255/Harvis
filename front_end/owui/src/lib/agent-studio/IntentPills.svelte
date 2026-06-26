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
			key: 'research',
			label: 'Research',
			hint: 'Enable research mode, then start a chat.',
			run: () => {
				researchEnabled.set(true);
				go('/');
			}
		},
		{
			key: 'code',
			label: 'Code',
			hint: 'Open the Build workspace — repos, diffs, and code review.',
			run: () => go('/harvis/vibecode')
		},
		{
			key: 'automate',
			label: 'Automate',
			hint: 'Schedule recurring tasks and background workflows.',
			run: () => go('/harvis/automations')
		}
		// Chat-only presets (Analyze / Decode / Summarize) intentionally dropped —
		// Quick Start keeps only agent-surface launchers, not main-chat prompt prefills.
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
