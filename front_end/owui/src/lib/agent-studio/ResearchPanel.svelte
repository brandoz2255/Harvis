<script lang="ts">
	import { getContext, onDestroy } from 'svelte';
	import { streamResearch, peekResult, openReportInNewTab } from '$lib/apis/research';
	import { researchDockView, researchDockQuery } from '$lib/stores';
	import Markdown from '$lib/components/chat/Messages/Markdown.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	const i18n: any = getContext('i18n');

	// The docked research overview/report — opened from a ResearchRunCard's buttons.
	export let researchId = '';
	export let mode: 'full' | 'dock' = 'dock';

	const token = () => localStorage.token;

	let activeId = '';
	let phase = 'planning';
	let status: 'running' | 'done' | 'error' = 'running';
	let sources: { url: string }[] = [];
	let queries: string[] = [];
	let report = '';
	let controller: AbortController | null = null;

	const PHASE_LABEL: Record<string, string> = {
		probing: 'Checking model…',
		planning: 'Research plan created',
		searching: 'Gathering sources…',
		reading: 'Reading sources…',
		analyzing: 'Analyzing findings…',
		writing: 'Writing the report…'
	};

	$: domains = (() => {
		const c: Record<string, number> = {};
		for (const s of sources) {
			try {
				const h = new URL(s.url).hostname.replace(/^www\./, '');
				c[h] = (c[h] ?? 0) + 1;
			} catch (_) {
				/* ignore */
			}
		}
		return Object.entries(c)
			.map(([domain, count]) => ({ domain, count }))
			.sort((a, b) => b.count - a.count);
	})();
	$: maxCount = domains.reduce((m, d) => Math.max(m, d.count), 1);

	const loadReport = async () => {
		try {
			const r = await peekResult(token(), activeId);
			report = r?.result ?? '';
			if (r?.sources?.length) sources = r.sources;
		} catch (_) {
			/* result may be consumed/unavailable */
		}
	};

	const start = (id: string) => {
		controller?.abort();
		activeId = id;
		phase = 'planning';
		status = 'running';
		sources = [];
		queries = [];
		report = '';
		if (!id) return;
		controller = new AbortController();
		(async () => {
			try {
				await streamResearch(
					token(),
					id,
					(ev) => {
						if (ev?.phase && PHASE_LABEL[ev.phase]) phase = ev.phase;
						if (Array.isArray(ev?.sources)) sources = ev.sources;
						if (Array.isArray(ev?.queries)) queries = ev.queries;
						if (ev?.phase === 'error' || ev?.error) status = 'error';
						if (ev?.final || ev?.status === 'done') status = 'done';
					},
					controller.signal
				);
			} catch (_) {
				/* stream ended / already done */
			}
			if (status !== 'error') status = 'done';
			await loadReport();
		})();
	};
	$: if (researchId !== activeId) start(researchId);

	onDestroy(() => controller?.abort());
</script>

<div class="w-full h-full flex flex-col {mode === 'full' ? 'max-w-3xl mx-auto px-4 py-4' : 'px-1 py-2'}">
	<div class="flex items-center gap-2 mb-2 shrink-0">
		<Search className="size-4 text-amber-500" />
		<div class="text-sm font-medium text-gray-800 dark:text-gray-100 truncate">
			{$researchDockQuery || $i18n.t('Deep Research')}
		</div>
	</div>

	<!-- Report / Overview toggle (the two corresponding buttons) -->
	<div class="flex gap-1 mb-2 shrink-0 text-xs">
		<button
			class="px-2.5 py-1 rounded-lg border transition {$researchDockView === 'overview'
				? 'border-amber-500/50 bg-amber-500/10 text-amber-600 dark:text-amber-300'
				: 'border-gray-200 dark:border-gray-800 text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-800/50'}"
			on:click={() => researchDockView.set('overview')}>{$i18n.t('Overview')}</button
		>
		<button
			class="px-2.5 py-1 rounded-lg border transition {$researchDockView === 'report'
				? 'border-amber-500/50 bg-amber-500/10 text-amber-600 dark:text-amber-300'
				: 'border-gray-200 dark:border-gray-800 text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-800/50'}"
			on:click={() => researchDockView.set('report')}>{$i18n.t('Report')}</button
		>
	</div>

	<div class="flex-1 min-h-0 overflow-y-auto -mx-1 px-1">
		{#if $researchDockView === 'report'}
			{#if report}
				<div class="markdown-prose markdown-prose-sm text-sm text-gray-700 dark:text-gray-200">
					<Markdown id={`research-dock-${activeId}`} content={report} />
				</div>
				<button
					class="mt-3 inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-lg bg-amber-500 hover:bg-amber-600 text-white transition"
					on:click={() => openReportInNewTab(token(), activeId)}
				>
					{$i18n.t('Open full report')}
				</button>
			{:else if status === 'running'}
				<div class="flex items-center gap-2 text-xs text-gray-400">
					<Spinner className="size-4" />
					{$i18n.t('The report will appear here when research completes…')}
				</div>
			{:else}
				<div class="text-xs text-gray-400">{$i18n.t('No report available.')}</div>
			{/if}
		{:else}
			<!-- Overview: plan → gathered N sources → sources-by-domain → searches run -->
			<div class="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-300 mb-2">
				{#if status === 'running'}
					<Spinner className="size-3.5" />
				{:else}
					<span class="size-2 rounded-full bg-blue-500"></span>
				{/if}
				{status === 'done'
					? $i18n.t('Research report is ready')
					: $i18n.t(PHASE_LABEL[phase] ?? 'Researching…')}
			</div>

			<div class="text-[11px] text-gray-500 mb-1">
				{$i18n.t('Gathered {{n}} sources', { n: sources.length })}
			</div>
			<div class="space-y-1 mb-3">
				{#each domains as d (d.domain)}
					<div class="flex items-center gap-2 text-[11px]">
						<span class="text-gray-700 dark:text-gray-200 truncate w-40 shrink-0">{d.domain}</span>
						<div class="flex-1 h-1.5 rounded-full bg-gray-100 dark:bg-gray-800 overflow-hidden">
							<div class="h-full bg-amber-500/60 rounded-full" style="width: {(d.count / maxCount) * 100}%"></div>
						</div>
						<span class="text-gray-400 tabular-nums shrink-0 w-10 text-right">{d.count}</span>
					</div>
				{/each}
			</div>

			{#if queries.length}
				<div class="text-[11px] text-gray-500 mb-1">{$i18n.t('Searches run')}</div>
				<div class="space-y-1">
					{#each queries as q}
						<div class="flex items-center gap-1.5 text-[11px] text-gray-600 dark:text-gray-300">
							<Search className="size-3 text-gray-400 shrink-0" />
							<span class="truncate">{q}</span>
						</div>
					{/each}
				</div>
			{/if}
		{/if}
	</div>
</div>
