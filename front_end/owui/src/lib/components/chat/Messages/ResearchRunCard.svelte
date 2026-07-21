<script lang="ts">
	import { getContext, onDestroy, onMount } from 'svelte';
	import { streamResearch, peekResult, openReportInNewTab } from '$lib/apis/research';
	import {
		dockedResearchId,
		researchDockView,
		researchDockQuery,
		workspaceControlsTab,
		showControls
	} from '$lib/stores';
	import Markdown from '$lib/components/chat/Messages/Markdown.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	const i18n: any = getContext('i18n');

	// Rendered from a <details type="research_run" researchid=… query=…> marker.
	export let id = '';
	export let attributes: Record<string, string> = {};

	$: researchId = attributes?.researchid ?? '';
	$: query = attributes?.query ?? '';

	const token = () => localStorage.token;

	let phase = 'planning';
	let status: 'running' | 'done' | 'error' | 'cancelled' = 'running';
	let sources: { url: string }[] = [];
	let report = '';
	let errMsg = '';
	let elapsed = 0;
	let controller: AbortController | null = null;
	let timer: any = null;
	let started = false;

	const PHASE_LABEL: Record<string, string> = {
		probing: 'Checking model…',
		planning: 'Research plan created',
		searching: 'Gathering sources…',
		reading: 'Reading sources…',
		analyzing: 'Analyzing findings…',
		writing: 'Writing the report…'
	};

	// group accumulated source URLs by domain → [{domain, count}], biggest first
	$: domains = (() => {
		const counts: Record<string, number> = {};
		for (const s of sources) {
			try {
				const h = new URL(s.url).hostname.replace(/^www\./, '');
				counts[h] = (counts[h] ?? 0) + 1;
			} catch (_) {
				/* ignore */
			}
		}
		return Object.entries(counts)
			.map(([domain, count]) => ({ domain, count }))
			.sort((a, b) => b.count - a.count);
	})();
	$: maxCount = domains.reduce((m, d) => Math.max(m, d.count), 1);
	$: totalSources = sources.length;

	const loadReport = async () => {
		try {
			const res = await peekResult(token(), researchId);
			report = res?.result ?? '';
			if (res?.sources?.length) sources = res.sources;
		} catch (_) {
			/* result may have been consumed/cleared */
		}
	};

	const consume = async () => {
		controller = new AbortController();
		try {
			await streamResearch(
				token(),
				researchId,
				(ev) => {
					if (ev?.phase && PHASE_LABEL[ev.phase]) phase = ev.phase;
					if (Array.isArray(ev?.sources)) sources = ev.sources;
					if (ev?.phase === 'error' || ev?.error) {
						errMsg = ev?.message || ev?.error || 'Research failed';
						status = 'error';
					}
					if (ev?.status === 'cancelled') status = 'cancelled';
					if (ev?.final || ev?.status === 'done') status = 'done';
				},
				controller.signal
			);
		} catch (e: any) {
			if (e?.name !== 'AbortError' && status === 'running') {
				// stream unreachable (e.g. reload after completion) — try the saved result
				await loadReport();
				if (report) status = 'done';
				else {
					errMsg = `${e}`;
					status = 'error';
				}
			}
		}
		if (status === 'done' && !report) await loadReport();
	};

	// Unified cockpit palette (see runFormat.ts): done=emerald · error=red ·
	// cancelled=gray (inert) · running=blue-pulse. amber = "needs YOU" only —
	// a research that is merely running must not read as awaiting the user.
	const statusDot = () => {
		if (status === 'done') return 'bg-emerald-500';
		if (status === 'error') return 'bg-red-500';
		if (status === 'cancelled') return 'bg-gray-400 dark:bg-gray-600';
		return 'bg-blue-500 animate-pulse';
	};

	// Short preview for the chat — the full report lives in the docked panel.
	$: summary = (() => {
		const body = (report || '').replace(/^---[\s\S]*?---\s*/, '').trim(); // drop stats header
		const txt = body.replace(/[#*`>]/g, '').replace(/\n{2,}/g, '\n').trim();
		return txt.length > 320 ? txt.slice(0, 320).trim() + '…' : txt;
	})();

	// Open the research overview/report in the right-rail dock.
	const dock = (view: 'overview' | 'report') => {
		dockedResearchId.set(researchId);
		researchDockQuery.set(query);
		researchDockView.set(view);
		workspaceControlsTab.set('research');
		showControls.set(true);
	};

	onMount(() => {
		if (started || !researchId) return;
		started = true;
		timer = setInterval(() => {
			if (status === 'running') elapsed += 1;
		}, 1000);
		consume();
	});

	onDestroy(() => {
		controller?.abort();
		if (timer) clearInterval(timer);
	});
</script>

<div class="w-full my-1 rounded-2xl border border-gray-100 dark:border-gray-850 overflow-hidden">
	<!-- header -->
	<div class="flex items-center gap-2 px-4 py-2.5 bg-gray-50/60 dark:bg-gray-850/40">
		<Search className="size-4 text-amber-500" />
		<span class="size-2 rounded-full shrink-0 {statusDot()}"></span>
		<span class="text-sm font-medium text-gray-800 dark:text-gray-100 truncate">
			{query || $i18n.t('Deep Research')}
		</span>
		<span class="ml-auto text-[11px] text-gray-400 tabular-nums shrink-0">
			{#if status === 'running'}{totalSources} {$i18n.t('sources')} · {elapsed}s{:else}{totalSources} {$i18n.t('sources')}{/if}
		</span>
	</div>

	<div class="px-4 py-3">
		{#if status === 'error'}
			<div class="text-xs text-red-500">{errMsg || $i18n.t('Research failed')}</div>
		{:else if status === 'done'}
			{#if summary}
				<div class="text-sm text-gray-700 dark:text-gray-200 leading-relaxed mb-3">{summary}</div>
			{/if}
			<!-- Research Report artifact — click to open it in the side panel -->
			<button
				class="flex items-center gap-3 w-full text-left rounded-xl border border-gray-100 dark:border-gray-850 hover:border-amber-500/40 hover:bg-amber-500/5 px-3 py-2.5 transition"
				on:click={() => dock('report')}
			>
				<div class="size-8 rounded-lg bg-amber-500/10 flex items-center justify-center shrink-0">
					<Search className="size-4 text-amber-500" />
				</div>
				<div class="min-w-0">
					<div class="text-sm font-medium text-gray-800 dark:text-gray-100">{$i18n.t('Research Report')}</div>
					<div class="text-[11px] text-gray-400">{totalSources} {$i18n.t('sources')} · {$i18n.t('Document')}</div>
				</div>
				<svg class="ml-auto size-4 text-gray-400 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l6-6-6-6" /></svg>
			</button>
			<div class="flex items-center gap-2 mt-2">
				<button class="text-[11px] text-gray-500 hover:text-amber-500 transition" on:click={() => dock('overview')}>{$i18n.t('Sources & overview')}</button>
				<span class="text-gray-300 dark:text-gray-700">·</span>
				<button class="text-[11px] text-gray-500 hover:text-amber-500 transition" on:click={() => openReportInNewTab(token(), researchId)}>{$i18n.t('Open full report')}</button>
			</div>
		{:else}
			<!-- running: phase + live sources-by-domain (the Claude-style panel, inline) -->
			<div class="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-300 mb-2">
				<Spinner className="size-3.5" />
				{$i18n.t(PHASE_LABEL[phase] ?? 'Researching…')}
			</div>
			{#if domains.length}
				<div class="space-y-1">
					{#each domains as d (d.domain)}
						<div class="flex items-center gap-2 text-[11px]">
							<span class="text-gray-700 dark:text-gray-200 truncate w-40 shrink-0">{d.domain}</span>
							<div class="flex-1 h-1.5 rounded-full bg-gray-100 dark:bg-gray-800 overflow-hidden">
								<div class="h-full bg-amber-500/60 rounded-full" style="width: {(d.count / maxCount) * 100}%"></div>
							</div>
							<span class="text-gray-400 tabular-nums shrink-0 w-16 text-right">
								{d.count} {d.count === 1 ? $i18n.t('source') : $i18n.t('sources')}
							</span>
						</div>
					{/each}
				</div>
			{:else}
				<div class="text-[11px] text-gray-400">{$i18n.t('Searching the web…')}</div>
			{/if}
		{/if}
	</div>
</div>
