<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { fetchLibrary, openReportInNewTab, type ResearchLibraryItem } from '$lib/apis/research';
	import {
		dockedResearchId,
		researchDockView,
		researchDockQuery,
		workspaceControlsTab,
		showControls,
		showArtifacts,
		artifactCode,
		artifactContents
	} from '$lib/stores';
	import Search from '$lib/components/icons/Search.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	const i18n: any = getContext('i18n');

	// The current chat (passed from ChatControls). When absent (full-page surface)
	// we show the whole research library instead of session-scoped items.
	export let history: any = null;

	const token = () => localStorage.token;

	let library: ResearchLibraryItem[] = [];
	let loading = true;

	const loadLibrary = async () => {
		loading = true;
		try {
			const res = await fetchLibrary(token());
			library = res?.research ?? [];
		} catch (_) {
			library = [];
		}
		loading = false;
	};
	onMount(loadLibrary);

	const decode = (s: string) =>
		(s || '')
			.replace(/&amp;/g, '&')
			.replace(/&quot;/g, '"')
			.replace(/&#39;/g, "'")
			.replace(/&lt;/g, '<')
			.replace(/&gt;/g, '>');

	// Research ids that actually appear in THIS chat (the per-session scope).
	$: researchMarkers = (() => {
		const out: { id: string; query: string }[] = [];
		const seen = new Set<string>();
		const msgs = history?.messages ? Object.values(history.messages) : [];
		for (const m of msgs as any[]) {
			const c = typeof m?.content === 'string' ? m.content : '';
			if (!c.includes('research_run')) continue;
			const re = /<details\b[^>]*\btype="research_run"[^>]*>/g;
			let mm: RegExpExecArray | null;
			while ((mm = re.exec(c)) !== null) {
				const tag = mm[0];
				const idm = /researchid="([^"]+)"/.exec(tag);
				const qm = /query="([^"]*)"/.exec(tag);
				if (idm && !seen.has(idm[1])) {
					seen.add(idm[1]);
					out.push({ id: idm[1], query: qm ? decode(qm[1]) : '' });
				}
			}
		}
		return out;
	})();

	$: libById = new Map(library.map((x) => [x.id, x]));

	// Reports: session-scoped (chat markers, enriched by library) or whole library on full page.
	$: reports = history
		? researchMarkers.map((mk) => {
				const lib = libById.get(mk.id);
				return {
					id: mk.id,
					query: lib?.query || mk.query || 'Research',
					source_count: lib?.source_count ?? null,
					status: lib?.status ?? 'done'
				};
			})
		: library.map((lib) => ({
				id: lib.id,
				query: lib.query || 'Research',
				source_count: lib.source_count,
				status: lib.status
			}));

	// Code / HTML / SVG artifacts produced in this chat (already aggregated by OWUI).
	$: artifacts = (($artifactContents ?? []) as Array<{ type: string; content: string }>).map(
		(a, i) => ({
			idx: i,
			content: a.content,
			label:
				a.type === 'iframe'
					? $i18n.t('Web page')
					: a.type === 'svg'
						? $i18n.t('SVG image')
						: $i18n.t('Code artifact')
		})
	);

	$: isEmpty = reports.length === 0 && artifacts.length === 0;

	const openReport = (id: string, query: string) => {
		if (!history) {
			// Full-page surface — no right-rail dock here, so open the report directly.
			openReportInNewTab(token(), id);
			return;
		}
		dockedResearchId.set(id);
		researchDockQuery.set(query);
		researchDockView.set('report');
		workspaceControlsTab.set('research');
		showControls.set(true);
	};

	const openArtifact = (content: string) => {
		artifactCode.set(content);
		showArtifacts.set(true);
		showControls.set(true);
	};
</script>

<div class="h-full overflow-y-auto px-3 pt-1 pb-4 text-sm">
	<div class="flex items-center justify-between mb-2">
		<div class="font-medium text-gray-700 dark:text-gray-200">{$i18n.t('Artifacts')}</div>
		<button
			class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
			on:click={loadLibrary}>{$i18n.t('Refresh')}</button
		>
	</div>

	{#if loading && isEmpty}
		<div class="flex items-center gap-2 text-xs text-gray-400 mt-4">
			<Spinner className="size-4" />
			{$i18n.t('Loading artifacts…')}
		</div>
	{:else if isEmpty}
		<div class="mt-6 text-center text-xs text-gray-400 leading-relaxed px-2">
			{history ? $i18n.t('No artifacts in this session yet.') : $i18n.t('No artifacts yet.')}<br />
			{$i18n.t('Research reports and things you create will collect here.')}
		</div>
	{:else}
		{#if reports.length}
			<div class="text-[11px] uppercase tracking-wide text-gray-400 mb-1.5 mt-1">
				{$i18n.t('Research reports')}
			</div>
			<div class="space-y-1.5 mb-4">
				{#each reports as r (r.id)}
					<button
						class="flex items-center gap-3 w-full text-left rounded-xl border border-gray-100 dark:border-gray-850 hover:border-amber-500/40 hover:bg-amber-500/5 px-3 py-2.5 transition"
						on:click={() => openReport(r.id, r.query)}
					>
						<div
							class="size-8 rounded-lg bg-amber-500/10 flex items-center justify-center shrink-0"
						>
							<Search className="size-4 text-amber-500" />
						</div>
						<div class="min-w-0 flex-1">
							<div class="text-sm font-medium text-gray-800 dark:text-gray-100 truncate">
								{r.query}
							</div>
							<div class="text-[11px] text-gray-400">
								{#if r.source_count != null}{r.source_count} {$i18n.t('sources')} · {/if}{$i18n.t(
									'Document'
								)}
							</div>
						</div>
						<svg
							class="size-4 text-gray-400 shrink-0"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"><path d="M9 18l6-6-6-6" /></svg
						>
					</button>
				{/each}
			</div>
		{/if}

		{#if artifacts.length}
			<div class="text-[11px] uppercase tracking-wide text-gray-400 mb-1.5">
				{$i18n.t('Generated artifacts')}
			</div>
			<div class="space-y-1.5">
				{#each artifacts as a (a.idx)}
					<button
						class="flex items-center gap-3 w-full text-left rounded-xl border border-gray-100 dark:border-gray-850 hover:border-gray-300 dark:hover:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-850/50 px-3 py-2.5 transition"
						on:click={() => openArtifact(a.content)}
					>
						<div
							class="size-8 rounded-lg bg-gray-100 dark:bg-gray-800 flex items-center justify-center shrink-0"
						>
							<svg
								class="size-4 text-gray-500 dark:text-gray-300"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="2"
								stroke-linecap="round"
								stroke-linejoin="round"
								><path d="M16 18l6-6-6-6" /><path d="M8 6l-6 6 6 6" /></svg
							>
						</div>
						<div class="min-w-0 flex-1">
							<div class="text-sm font-medium text-gray-800 dark:text-gray-100 truncate">
								{a.label}
							</div>
							<div class="text-[11px] text-gray-400">{$i18n.t('Open in viewer')}</div>
						</div>
						<svg
							class="size-4 text-gray-400 shrink-0"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"><path d="M9 18l6-6-6-6" /></svg
						>
					</button>
				{/each}
			</div>
		{/if}
	{/if}
</div>
