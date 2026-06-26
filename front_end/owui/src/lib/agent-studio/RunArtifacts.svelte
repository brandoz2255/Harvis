<script lang="ts">
	import { getContext, onMount, createEventDispatcher } from 'svelte';
	import {
		getRunArtifacts,
		getArtifact,
		getRunRepo,
		createPrForRun,
		type ArtifactMeta,
		type RunRepo
	} from '$lib/apis/agent-runs';
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
	// When set, keep ONLY the diff produced by this sub-agent (the Workflow Inspector's
	// per-agent session). The diff's label is "{agent_label} · {branch}", so we match the
	// first segment exactly against the agent's label. Unset ⇒ all agents' diffs (default).
	export let agentLabel: string | null = null;

	let artifacts: ArtifactMeta[] = [];
	// One block per sub-agent (multi-agent orchestrate runs produce N diffs).
	let diffs: { id: string; label: string; content: string }[] = [];
	let changedFiles = '';
	let loaded = false;
	let open = true;
	// Primary file to render as a live preview (above the diffs).
	let primary: { name: string; content: string } | null = null;
	let previewOpen = true;
	// Attached-repo Create-PR (HUMAN-only): gated on the run having a GitHub-backed
	// attached repo + a real diff. The confirm + click is the only trigger.
	let runRepo: RunRepo | null = null;
	let prOpenFor: string | null = null; // artifact id whose PR confirm is open
	let prTitle = '';
	let prBusy = false;
	let prError = '';
	let prResult: { pr_url?: string; pr_number?: number } | null = null;
	let prResultFor: string | null = null;

	const startPr = (id: string) => {
		prOpenFor = id;
		prError = '';
		prResult = null;
		prTitle = '';
	};
	const doCreatePr = async (id: string) => {
		prBusy = true;
		prError = '';
		try {
			prResult = await createPrForRun(wsId, { artifact_id: id, title: prTitle || undefined });
			prResultFor = id;
			prOpenFor = null;
		} catch (e: any) {
			prError = String(e?.message ?? e);
		} finally {
			prBusy = false;
		}
	};

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
		runRepo = await getRunRepo(wsId); // null unless the run attached a repo
		const diffMetas = artifacts.filter((a) => a.artifact_type === 'diff');
		const cf = artifacts.find((a) => a.artifact_type === 'changed_files');
		diffs = await Promise.all(
			diffMetas.map(async (d) => ({
				id: d.id,
				label: d.path || $i18n.t('Changes'),
				content: (await getArtifact(d.id))?.content || ''
			}))
		);
		changedFiles = cf ? (await getArtifact(cf.id))?.content || '' : '';
		// Per-agent session (agentLabel set): keep only this agent's diff and drop the
		// aggregate changed-files chips (the agent's own diff is its source of truth).
		if (agentLabel) {
			diffs = diffs.filter((d) => (d.label.split(' · ')[0] || '').trim() === agentLabel);
			changedFiles = '';
		}
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

	// +N/−M counts for a diff (real git diff or difflib) — the per-repo/per-agent stat.
	const diffStats = (content: string): { add: number; del: number } => {
		let add = 0;
		let del = 0;
		for (const l of (content || '').split('\n')) {
			if (l.startsWith('+') && !l.startsWith('+++')) add++;
			else if (l.startsWith('-') && !l.startsWith('---')) del++;
		}
		return { add, del };
	};

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
						{@const st = diffStats(d.content)}
						<div>
							<!-- Per-diff header (per-repo / per-agent): label · +N −M, like the Claude Code diff rows. -->
							<div class="flex items-center gap-2 mb-1">
								<span class="text-[11px] font-medium text-gray-600 dark:text-gray-300 truncate">{d.label}</span>
								{#if runRepo}
									<span class="text-[10px] text-gray-400 font-mono shrink-0 truncate">{runRepo.name}{runRepo.branch ? ` · ${runRepo.branch}` : ''}</span>
								{/if}
								{#if hasContent(d.content)}
									<span class="text-[11px] font-mono shrink-0 whitespace-nowrap"
										><span class="text-green-600 dark:text-green-400">+{st.add}</span>
										<span class="text-red-500">−{st.del}</span></span
										>
								{/if}
								{#if hasContent(d.content) && runRepo?.has_github}
									<button
										type="button"
										class="ml-auto shrink-0 text-[11px] px-2 py-0.5 rounded-md border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition"
										on:click={() => startPr(d.id)}
									>
										{$i18n.t('Create PR')}
									</button>
								{/if}
							</div>
							{#if prOpenFor === d.id}
								<div class="mb-2 rounded-lg border border-gray-200 dark:border-gray-700 p-2 space-y-1.5">
									<input
										class="w-full text-xs rounded-md bg-gray-50 dark:bg-gray-800 border-0 px-2 py-1.5 text-gray-700 dark:text-gray-200 outline-none"
										placeholder={$i18n.t('PR title (optional)')}
										bind:value={prTitle}
									/>
									<div class="flex items-center gap-1.5 flex-wrap">
										<button
											type="button"
											class="text-[11px] px-2.5 py-1 rounded-md bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50 transition"
											disabled={prBusy}
											on:click={() => doCreatePr(d.id)}
										>
											{prBusy ? $i18n.t('Opening…') : $i18n.t('Open pull request')}
										</button>
										<button
											type="button"
											class="text-[11px] px-2 py-1 rounded-md text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800 transition"
											on:click={() => (prOpenFor = null)}
										>
											{$i18n.t('Cancel')}
										</button>
										<span class="text-[10px] text-gray-400">{$i18n.t('Pushes a branch + opens a PR — refuses main/master.')}</span>
									</div>
									{#if prError}
										<div class="text-[11px] text-red-500">{prError}</div>
									{/if}
								</div>
							{/if}
							{#if prResultFor === d.id && prResult?.pr_url}
								<a
									href={prResult.pr_url}
									target="_blank"
									rel="noopener noreferrer"
									class="inline-block mb-2 text-[11px] text-blue-500 hover:underline"
								>{$i18n.t('Pull request opened')} #{prResult.pr_number} →</a>
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
