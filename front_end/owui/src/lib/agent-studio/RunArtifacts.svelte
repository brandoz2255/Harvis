<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { getRunArtifacts, getArtifact, type ArtifactMeta } from '$lib/apis/agent-runs';

	const i18n: any = getContext('i18n');

	// The run whose artifacts (diff / changed-files) to show. `done` flips true when
	// the run finishes → reload so the just-written diff appears.
	export let wsId = '';
	export let done = false;

	let artifacts: ArtifactMeta[] = [];
	let diffContent = '';
	let changedFiles = '';
	let loaded = false;
	let open = true;

	const load = async () => {
		if (!wsId) return;
		artifacts = await getRunArtifacts(wsId);
		const diff = artifacts.find((a) => a.artifact_type === 'diff');
		const cf = artifacts.find((a) => a.artifact_type === 'changed_files');
		diffContent = diff ? (await getArtifact(diff.id))?.content || '' : '';
		changedFiles = cf ? (await getArtifact(cf.id))?.content || '' : '';
		loaded = true;
	};

	onMount(load);

	// Reload when the run transitions to done (artifacts get written at completion).
	let wasDone = false;
	$: if (wsId && done && !wasDone) {
		wasDone = true;
		load();
	}

	$: fileList = changedFiles.split('\n').map((s) => s.trim()).filter(Boolean);
	$: hasDiff = !!diffContent && diffContent.trim() && diffContent.trim() !== '(no changes)';

	const lineClass = (l: string): string => {
		if (l.startsWith('+') && !l.startsWith('+++')) return 'text-green-600 dark:text-green-400';
		if (l.startsWith('-') && !l.startsWith('---')) return 'text-red-500';
		if (l.startsWith('@@')) return 'text-blue-500';
		if (l.startsWith('diff ') || l.startsWith('new file') || l.startsWith('deleted'))
			return 'text-gray-400';
		return 'text-gray-600 dark:text-gray-300';
	};
</script>

{#if loaded && (hasDiff || fileList.length)}
	<div class="rounded-xl border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-900 overflow-hidden mt-2">
		<button class="w-full flex items-center gap-2 px-3 py-2 text-left" on:click={() => (open = !open)}>
			<svg
				class="size-4 text-gray-400 transition-transform {open ? 'rotate-90' : ''}"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2"
				stroke-linecap="round"
				stroke-linejoin="round"><path d="M9 18l6-6-6-6" /></svg
			>
			<span class="text-sm font-medium text-gray-800 dark:text-gray-100">{$i18n.t('Changes')}</span>
			<span class="text-[11px] text-gray-400"
				>{fileList.length}
				{fileList.length === 1 ? $i18n.t('file') : $i18n.t('files')}</span
			>
		</button>
		{#if open}
			<div class="px-3 pb-3">
				{#if fileList.length}
					<div class="flex flex-wrap gap-1 mb-2">
						{#each fileList as f}
							<span
								class="text-[11px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 font-mono"
								>{f}</span
							>
						{/each}
					</div>
				{/if}
				{#if hasDiff}
					<div
						class="text-[11px] leading-relaxed overflow-auto bg-gray-50 dark:bg-gray-850 rounded-lg p-2.5 max-h-96 font-mono"
					>
						{#each diffContent.split('\n') as ln}
							<div class="whitespace-pre {lineClass(ln)}">{ln || ' '}</div>
						{/each}
					</div>
				{:else}
					<div class="text-[11px] text-gray-400">{$i18n.t('No file changes.')}</div>
				{/if}
			</div>
		{/if}
	</div>
{/if}
