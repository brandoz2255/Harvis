<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { getAllArtifacts, getArtifact, type GlobalArtifactMeta } from '$lib/apis/agent-runs';
	import ArtifactPreview from './ArtifactPreview.svelte';
	import ArtifactActions from './ArtifactActions.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	const i18n: any = getContext('i18n');

	// 'full' = the global Artifacts page (sidebar nav). 'dock' would be narrow.
	export let mode: 'full' | 'dock' = 'full';

	let items: GlobalArtifactMeta[] = [];
	let loaded = false;
	let selected: { name: string; content: string } | null = null;
	let loadingPreview = false;

	const load = async () => {
		loaded = false;
		items = await getAllArtifacts();
		loaded = true;
	};
	onMount(load);

	const open = async (it: GlobalArtifactMeta) => {
		loadingPreview = true;
		selected = { name: it.path || 'artifact', content: '' };
		const a = await getArtifact(it.id);
		selected = { name: it.path || 'artifact', content: a?.content || '' };
		loadingPreview = false;
	};

	const kindOf = (path: string | null): string => {
		const ext = (path?.split('.').pop() || '').toLowerCase();
		if (ext === 'html' || ext === 'htm') return 'HTML';
		if (ext === 'md' || ext === 'markdown') return 'MD';
		return ext ? ext.toUpperCase().slice(0, 6) : 'FILE';
	};

	const relDate = (iso: string | null): string => {
		if (!iso) return '';
		const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
		if (s < 60) return 'just now';
		if (s < 3600) return `${Math.floor(s / 60)}m ago`;
		if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
		return `${Math.floor(s / 86400)}d ago`;
	};
</script>

<div class="h-full flex flex-col min-h-0">
	{#if selected}
		<div
			class="flex items-center gap-2 px-4 py-2.5 shrink-0 border-b border-gray-100 dark:border-gray-850"
		>
			<button
				class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition shrink-0"
				on:click={() => (selected = null)}>← {$i18n.t('All artifacts')}</button
			>
			<span class="text-sm font-medium text-gray-800 dark:text-gray-100 font-mono truncate">
				{selected.name}
			</span>
			{#if !loadingPreview && selected.content}
				<div class="ml-auto shrink-0">
					<ArtifactActions name={selected.name} content={selected.content} />
				</div>
			{/if}
		</div>
		<div class="flex-1 min-h-0 p-4">
			{#if loadingPreview}
				<div class="flex items-center gap-2 text-xs text-gray-400">
					<Spinner className="size-4" />
					{$i18n.t('Loading…')}
				</div>
			{:else}
				<ArtifactPreview name={selected.name} content={selected.content} fill />
			{/if}
		</div>
	{:else}
		<div class="flex items-center justify-between px-4 py-2.5 shrink-0">
			<div class="font-medium text-gray-700 dark:text-gray-200">
				{$i18n.t('Artifacts')}
				{#if loaded}<span class="text-xs text-gray-400">({items.length})</span>{/if}
			</div>
			<button
				class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
				on:click={load}>{$i18n.t('Refresh')}</button
			>
		</div>
		<div class="flex-1 min-h-0 overflow-y-auto px-4 pb-4">
			{#if !loaded}
				<div class="flex items-center gap-2 text-xs text-gray-400 mt-4">
					<Spinner className="size-4" />
					{$i18n.t('Loading artifacts…')}
				</div>
			{:else if items.length === 0}
				<div class="mt-10 text-center text-xs text-gray-400 leading-relaxed">
					{$i18n.t('No artifacts yet.')}<br />
					{$i18n.t('Files your agents create will collect here.')}
				</div>
			{:else}
				<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
					{#each items as it (it.id)}
						<button
							class="text-left rounded-xl border border-gray-100 dark:border-gray-850 hover:border-blue-500/40 hover:bg-blue-500/5 p-3 transition flex flex-col gap-1.5 min-h-[5.5rem]"
							on:click={() => open(it)}
						>
							<div class="flex items-center gap-2 min-w-0">
								<span
									class="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400 shrink-0"
									>{kindOf(it.path)}</span
								>
								<span
									class="text-sm font-medium text-gray-800 dark:text-gray-100 font-mono truncate"
									>{it.path || 'artifact'}</span
								>
							</div>
							{#if it.task_brief}
								<div class="text-[11px] text-gray-500 dark:text-gray-400 truncate">
									{it.task_brief}
								</div>
							{/if}
							<div class="text-[10px] text-gray-400 mt-auto">{relDate(it.created_at)}</div>
						</button>
					{/each}
				</div>
			{/if}
		</div>
	{/if}
</div>
