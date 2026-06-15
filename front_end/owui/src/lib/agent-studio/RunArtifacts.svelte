<script lang="ts">
	import { getContext, onMount, createEventDispatcher } from 'svelte';
	import { getRunArtifacts, getArtifact, type ArtifactMeta } from '$lib/apis/agent-runs';
	import ArtifactPreview from './ArtifactPreview.svelte';

	const i18n: any = getContext('i18n');
	const dispatch = createEventDispatcher();

	// The run whose artifacts (diff / changed-files / file) to show. `done` flips
	// true when the run finishes → reload so the just-written artifacts appear.
	export let wsId = '';
	export let done = false;
	// Which cards to render: 'all' (full run page), 'preview' (Artifacts tab),
	// 'changes' (Overview workspace). Lets the dock split preview vs diffs.
	export let mode: 'all' | 'preview' | 'changes' = 'all';
	// `bare` drops this component's own card chrome (border + collapse header) and
	// renders just the body — for when a parent RailCard supplies the chrome.
	export let bare = false;
	// `fill` (with bare) makes the preview take the full available height — the
	// Artifacts tab renders the preview full-bleed as THE artifact.
	export let fill = false;

	let artifacts: ArtifactMeta[] = [];
	// One block per sub-agent (multi-agent orchestrate runs produce N diffs).
	let diffs: { label: string; content: string }[] = [];
	let changedFiles = '';
	let loaded = false;
	let open = true;
	// Primary file to render as a live preview (above the diffs).
	let primary: { name: string; content: string } | null = null;
	let previewOpen = true;

	// index.html / any .html (largest if several) > largest file overall.
	const pickPrimary = (files: { name: string; content: string }[]) => {
		const nonEmpty = files.filter((f) => f.content && f.content.trim());
		if (!nonEmpty.length) return null;
		const html = nonEmpty.filter((f) => /\.html?$/i.test(f.name));
		const pool = html.length ? html : nonEmpty;
		return pool.reduce((a, b) => (b.content.length > a.content.length ? b : a));
	};

	const hasContent = (c: string) => !!c && c.trim() && c.trim() !== '(no changes)';

	const load = async () => {
		if (!wsId) return;
		artifacts = await getRunArtifacts(wsId);
		const diffMetas = artifacts.filter((a) => a.artifact_type === 'diff');
		const cf = artifacts.find((a) => a.artifact_type === 'changed_files');
		diffs = await Promise.all(
			diffMetas.map(async (d) => ({
				label: d.path || $i18n.t('Changes'),
				content: (await getArtifact(d.id))?.content || ''
			}))
		);
		changedFiles = cf ? (await getArtifact(cf.id))?.content || '' : '';
		// Full file contents → pick the primary one to preview.
		const fileMetas = artifacts.filter((a) => a.artifact_type === 'file');
		const files = await Promise.all(
			fileMetas.map(async (a) => ({
				name: a.path || 'file',
				content: (await getArtifact(a.id))?.content || ''
			}))
		);
		primary = pickPrimary(files);
		loaded = true;
		// Tell parents what's available so they can show/hide their cards.
		const fl = changedFiles.split('\n').map((s) => s.trim()).filter(Boolean);
		dispatch('loaded', {
			hasPreview: !!primary,
			hasChanges: diffs.some((d) => hasContent(d.content)) || fl.length > 0,
			primary
		});
	};

	onMount(load);

	// Reload when the run transitions to done (artifacts get written at completion).
	let wasDone = false;
	$: if (wsId && done && !wasDone) {
		wasDone = true;
		load();
	}

	$: fileList = changedFiles.split('\n').map((s) => s.trim()).filter(Boolean);
	$: anyDiff = diffs.some((d) => hasContent(d.content));

	const lineClass = (l: string): string => {
		if (l.startsWith('+') && !l.startsWith('+++')) return 'text-green-600 dark:text-green-400';
		if (l.startsWith('-') && !l.startsWith('---')) return 'text-red-500';
		if (l.startsWith('@@')) return 'text-blue-500';
		if (l.startsWith('diff ') || l.startsWith('new file') || l.startsWith('deleted'))
			return 'text-gray-400';
		return 'text-gray-600 dark:text-gray-300';
	};
</script>

<!-- Preview card (rendered for mode 'all' | 'preview'). -->
{#if mode !== 'changes' && loaded && primary}
	<div
		class={bare
			? fill
				? 'h-full flex flex-col min-h-0'
				: ''
			: 'rounded-xl border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-900 overflow-hidden mt-2'}
	>
		{#if !bare}
			<button
				class="w-full flex items-center gap-2 px-3 py-2 text-left"
				on:click={() => (previewOpen = !previewOpen)}
			>
				<svg
					class="size-4 text-gray-400 transition-transform {previewOpen ? 'rotate-90' : ''}"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"><path d="M9 18l6-6-6-6" /></svg
				>
				<span class="text-sm font-medium text-gray-800 dark:text-gray-100">{$i18n.t('Preview')}</span>
				<span class="text-[11px] text-gray-400 font-mono truncate">{primary.name}</span>
			</button>
		{/if}
		{#if bare || previewOpen}
			<div class={bare ? (fill ? 'flex-1 min-h-0 flex flex-col' : '') : 'px-3 pb-3'}>
				{#if bare}
					<div class="text-[11px] text-gray-400 font-mono truncate mb-1.5 {fill ? 'shrink-0' : ''}">
						{primary.name}
					</div>
				{/if}
				{#if fill}
					<div class="flex-1 min-h-0">
						<ArtifactPreview name={primary.name} content={primary.content} {fill} />
					</div>
				{:else}
					<ArtifactPreview name={primary.name} content={primary.content} />
				{/if}
			</div>
		{/if}
	</div>
{/if}

<!-- Changes card (rendered for mode 'all' | 'changes'). -->
{#if mode !== 'preview' && loaded && (anyDiff || fileList.length)}
	<div
		class={bare
			? ''
			: 'rounded-xl border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-900 overflow-hidden mt-2'}
	>
		{#if !bare}
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
					{fileList.length === 1 ? $i18n.t('file') : $i18n.t('files')}{#if diffs.length > 1}
						· {diffs.length} {$i18n.t('agents')}{/if}</span
				>
			</button>
		{/if}
		{#if bare || open}
			<div class={bare ? '' : 'px-3 pb-3'}>
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
				<!-- One diff block per sub-agent. -->
				<div class="space-y-2">
					{#each diffs as d}
						<div>
							{#if diffs.length > 1}
								<div class="text-[11px] font-medium text-gray-500 dark:text-gray-400 mb-1 truncate">
									{d.label}
								</div>
							{/if}
							{#if hasContent(d.content)}
								<div
									class="text-[11px] leading-relaxed overflow-auto bg-gray-50 dark:bg-gray-850 rounded-lg p-2.5 max-h-96 font-mono"
								>
									{#each d.content.split('\n') as ln}
										<div class="whitespace-pre {lineClass(ln)}">{ln || ' '}</div>
									{/each}
								</div>
							{:else}
								<div class="text-[11px] text-gray-400">{$i18n.t('No file changes.')}</div>
							{/if}
						</div>
					{/each}
				</div>
			</div>
		{/if}
	</div>
{/if}
