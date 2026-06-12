<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { getMemories, addMemory, clearMemories, type MemoryEntry } from '$lib/apis/memory';

	const i18n: any = getContext('i18n');

	let loading = true;
	let saving = false;
	let entries: MemoryEntry[] = [];
	let draft = '';

	const token = () => localStorage.token;

	const load = async () => {
		loading = true;
		try {
			entries = await getMemories(token());
		} catch (e) {
			console.error('memory load', e);
			entries = [];
		}
		loading = false;
	};

	const add = async () => {
		const content = draft.trim();
		if (!content) return;
		saving = true;
		try {
			await addMemory(token(), content, 'manual');
			draft = '';
			toast.success($i18n.t('Memory added'));
			await load();
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			saving = false;
		}
	};

	const clearAll = async () => {
		if (!entries.length) return;
		if (!confirm($i18n.t('Clear all memories? This cannot be undone.'))) return;
		try {
			const r = await clearMemories(token());
			toast.success($i18n.t('Cleared {{n}} memories', { n: r?.deleted ?? 0 }));
			await load();
		} catch (e) {
			toast.error(`${e}`);
		}
	};

	const onKeydown = (e: KeyboardEvent) => {
		if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
			e.preventDefault();
			add();
		}
	};

	onMount(load);
</script>

<div class="text-sm">
	<div class="flex items-start gap-2 mb-3">
		<textarea
			bind:value={draft}
			on:keydown={onKeydown}
			rows="2"
			placeholder={$i18n.t('Add a memory the agent should remember…  (⌘/Ctrl+Enter)')}
			class="flex-1 rounded-lg py-2 px-3 text-sm bg-gray-50 dark:bg-gray-850 outline-none resize-none"
		></textarea>
		<button
			type="button"
			class="text-xs px-3 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white transition disabled:opacity-50 shrink-0"
			on:click={add}
			disabled={saving || !draft.trim()}>{saving ? $i18n.t('Adding…') : $i18n.t('Add')}</button
		>
	</div>

	{#if loading}
		<div class="text-gray-500 text-xs py-2">{$i18n.t('Loading…')}</div>
	{:else if entries.length === 0}
		<div class="text-gray-500 text-xs py-2">{$i18n.t('No memories yet.')}</div>
	{:else}
		<div class="flex items-center justify-between mb-1.5">
			<div class="text-xs font-medium text-gray-500">
				{entries.length}
				{entries.length === 1 ? $i18n.t('memory') : $i18n.t('memories')}
			</div>
			<button
				type="button"
				class="text-xs text-red-600 hover:bg-red-50 dark:hover:bg-red-950 px-2 py-1 rounded-lg transition"
				on:click={clearAll}>{$i18n.t('Clear all')}</button
			>
		</div>
		<div class="space-y-1.5 max-h-72 overflow-y-auto pr-1">
			{#each entries as e, i (i)}
				<div
					class="rounded-lg border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 px-3 py-2"
				>
					<div class="text-gray-700 dark:text-gray-200 whitespace-pre-wrap break-words">
						{e.content}
					</div>
					<div
						class="mt-1 flex items-center gap-2 text-[10px] uppercase tracking-wide text-gray-400"
					>
						<span>{e.source}</span>
						{#if e.created_at}<span>· {new Date(e.created_at).toLocaleString()}</span>{/if}
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>
