<script lang="ts">
	// Knowledge = the unified "all things knowledge" hub:
	//   1. Deep Research hero (ask a complex question → a full cited report) — wired to
	//      the Harvis `/api/research/*` deep-research backend.
	//   2. Neural Map — the live sessions/runs graph (embedded GlobalMap).
	//   3. Sources — everything Harvis treats as knowledge: Notebooks, Projects
	//      (folders), GitHub repos, and Memory.
	import { getContext, onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { marked } from 'marked';
	import DOMPurify from 'dompurify';
	import { WEBUI_NAME, chatId } from '$lib/stores';
	import GlobalMap from '$lib/agent-studio/GlobalMap.svelte';
	import { listNotebooks, type Notebook } from '$lib/apis/notebooks';
	import { getFolders } from '$lib/apis/folders';
	import { getMemories, type MemoryEntry } from '$lib/apis/memory';
	import { listUserGithubRepos } from '$lib/apis/agent-runs';
	import {
		getKnowledgeBases,
		deleteKnowledgeById,
		createKbFromRepo,
		getKbStatus
	} from '$lib/apis/knowledge';
	import {
		startResearch,
		streamResearch,
		peekResult,
		cancelResearch,
		fetchLibrary,
		openReportInNewTab,
		type ResearchLibraryItem
	} from '$lib/apis/research';

	const i18n: any = getContext('i18n');
	const backToChat = () => goto($chatId ? `/c/${$chatId}` : '/');

	let token = '';

	const rel = (iso?: string | number) => {
		if (iso == null) return '';
		const t = typeof iso === 'number' ? iso * (iso < 1e12 ? 1000 : 1) : Date.parse(iso);
		if (isNaN(t)) return '';
		const s = Math.max(1, Math.floor((Date.now() - t) / 1000));
		if (s < 60) return $i18n.t('just now');
		const m = Math.floor(s / 60);
		if (m < 60) return $i18n.t('{{n}}m ago', { n: m });
		const h = Math.floor(m / 60);
		if (h < 24) return $i18n.t('{{n}}h ago', { n: h });
		const d = Math.floor(h / 24);
		if (d < 7) return $i18n.t('{{n}}d ago', { n: d });
		return $i18n.t('{{n}}w ago', { n: Math.floor(d / 7) });
	};

	// ─── Deep Research ──────────────────────────────────────────────────────────
	let query = '';
	let researching = false;
	let researchError = '';
	let phase = '';
	let round = 0;
	let sourcesFound = 0;
	let resultHtml = '';
	let researchSources: { title?: string; url?: string }[] = [];
	let currentSession = '';
	let abortCtl: AbortController | null = null;
	let library: ResearchLibraryItem[] = [];

	// Research depth — real: maps to the backend's max_rounds + max_time.
	const DEPTHS = [
		{ label: 'Fast', hint: '1 round · quick', rounds: 1, time: 120 },
		{ label: 'Balanced', hint: '2 rounds · default', rounds: 2, time: 300 },
		{ label: 'Thorough', hint: '4 rounds · deep', rounds: 4, time: 600 }
	];
	let depth = DEPTHS[1];
	let showDepth = false;

	// A pool of starter prompts; a fresh random 4 are shown on each page load.
	const EXAMPLE_POOL = [
		{ t: 'Compare options', q: 'Compare the leading local LLM inference runtimes in 2026 by speed, hardware needs, and ease of use.' },
		{ t: 'Evaluate a decision', q: 'Renting vs. buying a home across major US regions — analyze price-to-rent ratios, mortgage rates, and recent trends.' },
		{ t: 'Survey a field', q: 'Summarize the current state of retrieval-augmented generation: techniques, tradeoffs, and benchmarks.' },
		{ t: 'Track a trend', q: 'What changed in open-source AI agents over the last year, and where is the field heading?' },
		{ t: 'Compare frameworks', q: 'Compare the top web frameworks in 2026 by performance, ecosystem, learning curve, and hiring demand.' },
		{ t: 'Evaluate healthcare', q: 'Compare healthcare access, outcomes, and costs across major developed countries.' },
		{ t: 'Market analysis', q: 'Analyze the electric vehicle market in 2026: leading makers, battery tech, pricing, and adoption barriers.' },
		{ t: 'Science explainer', q: 'Explain recent advances in fusion energy and how close commercial reactors realistically are.' },
		{ t: 'Food culture', q: 'Analyze restaurant and grocery trends to see which cuisines are growing fastest and why.' },
		{ t: 'Climate impacts', q: 'Analyze recent climate, energy, and emissions data to identify the most significant 2026 shifts.' },
		{ t: 'Tooling deep-dive', q: 'Compare vector databases for production RAG: performance, scaling, cost, and operational tradeoffs.' },
		{ t: 'Career & skills', q: 'Which skills and certifications most improve software engineering salaries in 2026, with evidence?' },
		{ t: 'Security survey', q: 'Survey the most exploited software vulnerability classes in the last year and the best defenses.' },
		{ t: 'Concept comparison', q: 'Compare index funds and actively managed funds by historical returns, fees, and risk profiles.' }
	];

	const _shuffle = <T>(arr: T[]): T[] => {
		const a = [...arr];
		for (let i = a.length - 1; i > 0; i--) {
			const j = Math.floor(Math.random() * (i + 1));
			[a[i], a[j]] = [a[j], a[i]];
		}
		return a;
	};
	const examples = _shuffle(EXAMPLE_POOL).slice(0, 4);

	const PHASE_LABEL: Record<string, string> = {
		probing: 'Probing',
		planning: 'Planning',
		searching: 'Searching the web',
		reading: 'Reading sources',
		analyzing: 'Analyzing',
		writing: 'Writing the report',
		complete: 'Done'
	};

	const loadLibrary = async () => {
		try {
			const r = await fetchLibrary(token);
			library = (r?.research ?? []).filter((x) => !x.archived).slice(0, 6);
		} catch {
			library = [];
		}
	};

	const runResearch = async () => {
		const q = query.trim();
		if (!q || researching) return;
		researching = true;
		researchError = '';
		resultHtml = '';
		researchSources = [];
		phase = 'Starting';
		round = 0;
		sourcesFound = 0;
		currentSession = '';
		abortCtl = new AbortController();
		try {
			const { session_id } = await startResearch(token, {
				query: q,
				max_rounds: depth.rounds,
				max_time: depth.time
			});
			currentSession = session_id;
			await streamResearch(
				token,
				session_id,
				(e) => {
					if (e?.phase) phase = PHASE_LABEL[e.phase] ?? e.phase;
					if (typeof e?.round === 'number') round = e.round;
					if (typeof e?.total_sources === 'number') sourcesFound = e.total_sources;
					if (e?.error) researchError = String(e.error);
				},
				abortCtl.signal
			);
			if (!researchError) {
				try {
					const { result, sources } = await peekResult(token, session_id);
					resultHtml = DOMPurify.sanitize(marked.parse(result || '') as string);
					researchSources = Array.isArray(sources) ? sources : [];
				} catch {
					researchError = 'The report finished but could not be loaded — try Open full report.';
				}
			}
			await loadLibrary();
		} catch (e: any) {
			if (e?.name !== 'AbortError') researchError = e?.detail || e?.message || 'Research failed — try again.';
		}
		researching = false;
	};

	const stopResearch = () => {
		abortCtl?.abort();
		if (currentSession) cancelResearch(token, currentSession).catch(() => {});
		researching = false;
	};

	const onComposerKey = (e: KeyboardEvent) => {
		if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
			e.preventDefault();
			runResearch();
		}
	};

	const openReport = (id: string) => openReportInNewTab(token, id);

	// ─── Sources ────────────────────────────────────────────────────────────────
	let recentNotebooks: Notebook[] = [];
	let folders: { id: string; name?: string }[] = [];
	let repos: { full_name?: string; name?: string; html_url?: string }[] = [];
	let memories: MemoryEntry[] = [];

	const openNotebook = (id: string) => goto(`/harvis/notebooks?onb=/notebooks/${id}`);

	// ─── Knowledge bases (K3: GitHub repo → searchable RAG, attachable to chats) ──
	let kbs: any[] = [];
	let showAddRepo = false;
	let repoInput = '';
	let branchInput = 'main';
	let addingRepo = false;
	let addError = '';
	const pollers: Record<string, any> = {};

	const loadKbs = async () => {
		try {
			const r = await getKnowledgeBases(token);
			kbs = ((r as any)?.items ?? r ?? []) as any[];
		} catch {
			kbs = [];
		}
	};

	const pollKb = (id: string) => {
		if (pollers[id]) return;
		let n = 0;
		let misses = 0;
		pollers[id] = setInterval(async () => {
			n += 1;
			const s: any = await getKbStatus(token, id);
			if (s) {
				misses = 0;
				kbs = kbs.map((k) =>
					k.id === id
						? { ...k, status: s.status, meta: { ...(k.meta ?? {}), ...(s.meta ?? {}), error: s.error } }
						: k
				);
			} else {
				misses += 1;
			}
			// Bail-out must run even when the status endpoint fails (s === null),
			// otherwise the interval spins forever and the card lies "Ingesting…".
			// 3 consecutive misses (~9s) means the endpoint is down, not slow — bail
			// fast instead of claiming progress for the full cap; one good read resets.
			const done = s?.status === 'ready' || s?.status === 'error';
			if (done || n > 100 || misses >= 3) {
				clearInterval(pollers[id]);
				delete pollers[id];
				if (!done) {
					kbs = kbs.map((k) =>
						k.id === id && k.status !== 'ready' && k.status !== 'error'
							? { ...k, status: 'unknown' }
							: k
					);
				}
			}
		}, 3000);
	};

	const retryKbStatus = (id: string) => {
		kbs = kbs.map((k) => (k.id === id && k.status === 'unknown' ? { ...k, status: 'indexing' } : k));
		pollKb(id);
	};

	const addRepo = async () => {
		const raw = repoInput.trim();
		if (!raw || addingRepo) return;
		addingRepo = true;
		addError = '';
		const parts = raw
			.replace(/^https?:\/\/github\.com\//i, '')
			.replace(/\.git$/i, '')
			.split('/')
			.filter(Boolean);
		const owner = parts[0] ?? '';
		const repo = parts[1] ?? '';
		if (!owner || !repo) {
			addError = $i18n.t('Enter a public repo as owner/repo or a GitHub URL.');
			addingRepo = false;
			return;
		}
		try {
			const res: any = await createKbFromRepo(token, owner, repo, branchInput.trim() || 'main');
			repoInput = '';
			showAddRepo = false;
			await loadKbs();
			if (res?.id) pollKb(res.id);
		} catch (e: any) {
			addError = e?.detail || e?.message || String(e) || $i18n.t('Could not add repository.');
		}
		addingRepo = false;
	};

	const removeKb = async (id: string) => {
		try {
			await deleteKnowledgeById(token, id);
		} catch {
			/* ignore */
		}
		if (pollers[id]) {
			clearInterval(pollers[id]);
			delete pollers[id];
		}
		kbs = kbs.filter((k) => k.id !== id);
	};

	onMount(async () => {
		token = localStorage.getItem('token') || '';
		listNotebooks()
			.then((nbs) => {
				recentNotebooks = (nbs ?? [])
					.slice()
					.sort((a, b) => Date.parse(b.updated_at ?? '0') - Date.parse(a.updated_at ?? '0'))
					.slice(0, 5);
			})
			.catch(() => {});
		getFolders(token).then((f) => (folders = f ?? [])).catch(() => {});
		listUserGithubRepos().then((r) => (repos = r ?? [])).catch(() => {});
		getMemories(token).then((m) => (memories = m ?? [])).catch(() => {});
		loadLibrary();
		loadKbs().then(() => {
			for (const k of kbs) {
				if (k.status && k.status !== 'ready' && k.status !== 'error') pollKb(k.id);
			}
		});
	});

	onDestroy(() => {
		abortCtl?.abort();
		for (const id of Object.keys(pollers)) clearInterval(pollers[id]);
	});
</script>

<svelte:head>
	<title>{$i18n.t('Knowledge')} • {$WEBUI_NAME}</title>
</svelte:head>

<svelte:window on:click={() => (showDepth = false)} />

<div class="w-full h-full overflow-y-auto">
	<div class="max-w-5xl mx-auto px-5 py-6 space-y-6">
		<!-- Header -->
		<header>
			<button
				class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
				on:click={backToChat}>← {$i18n.t('Back to chat')}</button
			>
			<h1 class="text-2xl font-semibold text-gray-800 dark:text-gray-100 mt-2">
				{$i18n.t('Knowledge')}
			</h1>
			<p class="text-sm text-gray-500 mt-1">
				{$i18n.t('Research, notebooks, sources, and memory — everything you know, in one place.')}
			</p>
		</header>

		<!-- Deep Research hero -->
		<section
			class="rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-5"
		>
			<div class="flex items-center gap-2 mb-1">
				<svg
					class="size-5 text-blue-500"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="1.8"
					stroke-linecap="round"
					stroke-linejoin="round"
				>
					<circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" />
				</svg>
				<h2 class="text-lg font-semibold text-gray-800 dark:text-gray-100">
					{$i18n.t('Deep Research')}
				</h2>
			</div>
			<p class="text-sm text-gray-500 mb-3">
				{$i18n.t('Ask a complex question. Get a full report, with sources.')}
			</p>

			<!-- Composer -->
			<div
				class="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 px-3.5 pt-3 pb-2"
			>
				<textarea
					bind:value={query}
					on:keydown={onComposerKey}
					rows="2"
					placeholder={$i18n.t('Get a detailed report')}
					class="w-full resize-none bg-transparent text-sm text-gray-800 dark:text-gray-100 placeholder-gray-400 outline-none px-0.5 py-1"
				/>
				<!-- Toolbar -->
				<div class="flex items-center gap-2 mt-1">
					<!-- Deep research (active mode) -->
					<span
						class="inline-flex items-center gap-1.5 rounded-lg bg-blue-500/10 text-blue-600 dark:text-blue-400 pl-2 pr-2.5 py-1 text-xs font-medium"
					>
						<svg
							class="size-3.5"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="1.8"
							stroke-linecap="round"
							stroke-linejoin="round"
							><circle cx="11" cy="11" r="7" /><path d="M21 21l-3.5-3.5M11 8v6M8 11h6" /></svg
						>
						{$i18n.t('Deep research')}
					</span>

					<!-- Depth (real: max_rounds + max_time) -->
					<div class="relative">
						<button
							on:click|stopPropagation={() => (showDepth = !showDepth)}
							class="inline-flex items-center gap-1 rounded-lg border border-gray-200 dark:border-gray-800 hover:bg-gray-100 dark:hover:bg-gray-850 px-2.5 py-1 text-xs text-gray-600 dark:text-gray-300 transition"
						>
							<svg
								class="size-3.5"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.8"
								stroke-linecap="round"
								stroke-linejoin="round"
								><path
									d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"
								/></svg
							>
							{depth.label}
							<svg class="size-3 opacity-60" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m18 15-6-6-6 6" /></svg>
						</button>
						{#if showDepth}
							<div
								class="absolute left-0 bottom-full mb-1.5 w-48 rounded-xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-900 shadow-lg p-1 z-30"
							>
								{#each DEPTHS as d}
									<button
										on:click|stopPropagation={() => {
											depth = d;
											showDepth = false;
										}}
										class="w-full text-left rounded-lg px-2.5 py-1.5 hover:bg-gray-100 dark:hover:bg-gray-850 transition {depth.label ===
										d.label
											? 'text-blue-600 dark:text-blue-400'
											: 'text-gray-700 dark:text-gray-200'}"
									>
										<div class="text-xs font-medium">{d.label}</div>
										<div class="text-[10px] text-gray-400">{d.hint}</div>
									</button>
								{/each}
							</div>
						{/if}
					</div>

					<div class="flex-1"></div>

					<!-- Send / Stop -->
					{#if researching}
						<button
							on:click={stopResearch}
							title={$i18n.t('Stop')}
							class="size-8 rounded-full bg-gray-200 dark:bg-gray-800 text-gray-600 dark:text-gray-300 flex items-center justify-center hover:bg-gray-300 dark:hover:bg-gray-700 transition"
						>
							<svg class="size-3.5" viewBox="0 0 24 24" fill="currentColor"
								><rect x="6" y="6" width="12" height="12" rx="2" /></svg
							>
						</button>
					{:else}
						<button
							on:click={runResearch}
							disabled={!query.trim()}
							title={$i18n.t('Research')}
							class="size-8 rounded-full bg-blue-600 text-white flex items-center justify-center hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition"
						>
							<svg
								class="size-4"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="2"
								stroke-linecap="round"
								stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7" /></svg
							>
						</button>
					{/if}
				</div>
			</div>

			<!-- Examples (idle only) -->
			{#if !researching && !resultHtml && !researchError}
				<div class="mt-3 space-y-1">
					{#each examples as ex}
						<button
							type="button"
							on:click={() => (query = ex.q)}
							class="w-full flex items-center gap-2 text-left rounded-lg px-2 py-1.5 hover:bg-gray-100 dark:hover:bg-gray-850 transition group"
						>
							<svg
								class="size-3.5 text-gray-400 shrink-0"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.8"
								stroke-linecap="round"
								stroke-linejoin="round"><path d="M7 17 17 7M7 7h10v10" /></svg
							>
							<span class="text-xs font-medium text-gray-700 dark:text-gray-200 shrink-0">{ex.t}</span>
							<span class="text-xs text-gray-400 truncate">{ex.q}</span>
						</button>
					{/each}
				</div>
			{/if}

			<!-- Progress -->
			{#if researching}
				<div class="mt-4 flex items-center gap-3 text-sm text-gray-600 dark:text-gray-300">
					<svg class="size-4 animate-spin text-blue-500" viewBox="0 0 24 24" fill="none">
						<circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2.5" opacity="0.25" />
						<path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" />
					</svg>
					<span>{phase || $i18n.t('Researching')}…</span>
					{#if round}<span class="text-xs text-gray-400">{$i18n.t('round {{n}}', { n: round })}</span>{/if}
					{#if sourcesFound}<span class="text-xs text-gray-400">· {$i18n.t('{{n}} sources', { n: sourcesFound })}</span>{/if}
				</div>
			{/if}

			<!-- Error -->
			{#if researchError && !researching}
				<div class="mt-3 text-sm text-red-500">{researchError}</div>
			{/if}

			<!-- Result -->
			{#if resultHtml && !researching}
				<div class="mt-4 border-t border-gray-100 dark:border-gray-850 pt-4">
					<div class="flex items-center justify-between mb-2">
						<div class="text-sm font-medium text-gray-800 dark:text-gray-100">{$i18n.t('Report')}</div>
						{#if currentSession}
							<button
								on:click={() => openReport(currentSession)}
								class="text-xs text-blue-600 dark:text-blue-400 hover:underline"
								>{$i18n.t('Open full report')} →</button
							>
						{/if}
					</div>
					<div class="prose prose-sm dark:prose-invert max-w-none text-gray-700 dark:text-gray-200">
						{@html resultHtml}
					</div>
					{#if researchSources.length}
						<div class="mt-4">
							<div class="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-1.5">
								{$i18n.t('Sources')}
							</div>
							<div class="flex flex-col gap-1">
								{#each researchSources as s, i}
									<a
										href={s.url}
										target="_blank"
										rel="noreferrer"
										class="text-xs text-gray-600 dark:text-gray-300 hover:text-blue-600 dark:hover:text-blue-400 truncate"
										>{i + 1}. {s.title || s.url}</a
									>
								{/each}
							</div>
						</div>
					{/if}
				</div>
			{/if}

			<!-- Recent reports (idle) -->
			{#if !researching && !resultHtml && library.length}
				<div class="mt-4 border-t border-gray-100 dark:border-gray-850 pt-3">
					<div class="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-1">
						{$i18n.t('Recent research')}
					</div>
					<div class="divide-y divide-gray-100 dark:divide-gray-850">
						{#each library as r (r.id)}
							<button
								type="button"
								on:click={() => openReport(r.id)}
								class="w-full flex items-center justify-between gap-3 py-2 text-left group"
							>
								<span
									class="truncate text-sm text-gray-700 dark:text-gray-200 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition"
									>{r.query}</span
								>
								<span class="text-xs text-gray-400 shrink-0"
									>{r.source_count} {$i18n.t('sources')} · {rel(r.completed_at)}</span
								>
							</button>
						{/each}
					</div>
				</div>
			{/if}
		</section>

		<!-- Neural Map -->
		<section
			class="rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-4"
		>
			<div class="flex items-center justify-between mb-3">
				<div class="text-sm font-medium text-gray-800 dark:text-gray-100">{$i18n.t('Neural Map')}</div>
				<a
					href="/harvis/agent-studio/global-map"
					class="text-xs text-blue-600 dark:text-blue-400 hover:underline">{$i18n.t('View full')}</a
				>
			</div>
			<div
				class="h-80 rounded-xl overflow-hidden border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-950"
			>
				<GlobalMap embedded mode="full" />
			</div>
		</section>

		<!-- Knowledge bases (K3: GitHub repo → searchable RAG, attachable to chats) -->
		<section
			class="rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-5"
		>
			<div class="flex items-center justify-between gap-2 mb-1">
				<div class="flex items-center gap-2 min-w-0">
					<svg
						class="size-5 text-blue-500 shrink-0"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="1.8"
						stroke-linecap="round"
						stroke-linejoin="round"
					>
						<ellipse cx="12" cy="5" rx="9" ry="3" /><path d="M3 5v14a9 3 0 0 0 18 0V5" /><path
							d="M3 12a9 3 0 0 0 18 0"
						/>
					</svg>
					<h2 class="text-lg font-semibold text-gray-800 dark:text-gray-100 truncate">
						{$i18n.t('Knowledge bases')}
					</h2>
				</div>
				<button
					on:click={() => {
						showAddRepo = !showAddRepo;
						addError = '';
					}}
					class="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 text-white px-3 py-1.5 text-xs font-medium hover:bg-blue-700 transition shrink-0"
				>
					<svg
						class="size-3.5"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2.2"
						stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg
					>
					{$i18n.t('Add from GitHub')}
				</button>
			</div>
			<p class="text-sm text-gray-500 mb-3">
				{$i18n.t(
					'Ingest a public GitHub repo into a searchable knowledge base, then attach it in any chat (＋ → Attach Knowledge) to ground answers in that code.'
				)}
			</p>

			{#if showAddRepo}
				<div
					class="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 p-3 mb-3"
				>
					<div class="flex flex-col sm:flex-row gap-2">
						<input
							bind:value={repoInput}
							on:keydown={(e) => e.key === 'Enter' && addRepo()}
							placeholder={$i18n.t('owner/repo or GitHub URL')}
							class="flex-1 rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent px-3 py-1.5 text-sm text-gray-800 dark:text-gray-100 placeholder-gray-400 outline-none focus:border-blue-500"
						/>
						<input
							bind:value={branchInput}
							placeholder={$i18n.t('branch')}
							class="w-full sm:w-28 rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent px-3 py-1.5 text-sm text-gray-800 dark:text-gray-100 placeholder-gray-400 outline-none focus:border-blue-500"
						/>
						<button
							on:click={addRepo}
							disabled={addingRepo || !repoInput.trim()}
							class="rounded-lg bg-blue-600 text-white px-4 py-1.5 text-sm font-medium hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition shrink-0"
						>
							{addingRepo ? $i18n.t('Adding…') : $i18n.t('Add')}
						</button>
					</div>
					{#if addError}<div class="text-xs text-red-500 mt-2">{addError}</div>{/if}
					<div class="text-[11px] text-gray-400 mt-2">
						{$i18n.t(
							'Public repos only. Ingestion (clone → chunk → embed) runs in the background — large repos take a minute.'
						)}
					</div>
				</div>
			{/if}

			{#if kbs.length}
				<div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
					{#each kbs as k (k.id)}
						<div
							class="group rounded-xl border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-950 px-3 py-2.5 flex items-center gap-2.5"
						>
							<svg class="size-4 text-gray-400 shrink-0" viewBox="0 0 24 24" fill="currentColor"
								><path
									d="M12 2C6.48 2 2 6.48 2 12c0 4.42 2.87 8.17 6.84 9.5.5.08.66-.22.66-.48v-1.7c-2.78.6-3.37-1.34-3.37-1.34-.45-1.16-1.1-1.47-1.1-1.47-.9-.62.07-.6.07-.6 1 .07 1.53 1.03 1.53 1.03.89 1.52 2.34 1.08 2.91.83.09-.65.35-1.09.63-1.34-2.22-.25-4.55-1.11-4.55-4.94 0-1.09.39-1.99 1.03-2.69-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.02a9.6 9.6 0 0 1 5 0c1.91-1.29 2.75-1.02 2.75-1.02.55 1.38.2 2.4.1 2.65.64.7 1.03 1.6 1.03 2.69 0 3.84-2.34 4.69-4.57 4.94.36.31.68.92.68 1.85v2.74c0 .27.16.57.67.48A10 10 0 0 0 22 12c0-5.52-4.48-10-10-10z"
								/></svg
							>
							<div class="min-w-0 flex-1">
								<div class="truncate text-sm font-medium text-gray-800 dark:text-gray-100">
									{k.name}
								</div>
								<div class="flex items-center gap-2 mt-0.5 min-w-0">
									{#if k.status === 'ready'}
										<span class="text-[11px] text-green-600 dark:text-green-400 shrink-0">● {$i18n.t('Ready')}</span>
										{#if k.meta?.chunk_count}
											<span class="text-[11px] text-gray-400 truncate"
												>{k.meta.chunk_count} {$i18n.t('chunks')} · {k.meta.file_count}
												{$i18n.t('files')}</span
											>
										{/if}
									{:else if k.status === 'error'}
										<span class="text-[11px] text-red-500 shrink-0">● {$i18n.t('Failed')}</span>
										{#if k.meta?.error}<span class="text-[11px] text-gray-400 truncate">{k.meta.error}</span>{/if}
									{:else if k.status === 'unknown'}
										<span class="text-[11px] text-gray-500 dark:text-gray-400 shrink-0">● {$i18n.t('Status unknown')}</span>
										<button
											on:click={() => retryKbStatus(k.id)}
											class="text-[11px] text-blue-600 dark:text-blue-400 hover:underline shrink-0"
										>
											{$i18n.t('Retry')}
										</button>
									{:else}
										<span class="inline-flex items-center gap-1 text-[11px] text-amber-500 shrink-0">
											<svg class="size-3 animate-spin" viewBox="0 0 24 24" fill="none"
												><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="3" opacity="0.25" /><path
													d="M21 12a9 9 0 0 0-9-9"
													stroke="currentColor"
													stroke-width="3"
													stroke-linecap="round"
												/></svg
											>
											{$i18n.t('Ingesting…')}
										</span>
									{/if}
								</div>
							</div>
							<button
								on:click={() => removeKb(k.id)}
								title={$i18n.t('Delete')}
								class="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 transition shrink-0"
							>
								<svg
									class="size-4"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="1.8"
									stroke-linecap="round"
									stroke-linejoin="round"
									><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m2 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" /></svg
								>
							</button>
						</div>
					{/each}
				</div>
			{:else if !showAddRepo}
				<div class="text-xs text-gray-500 py-2">
					{$i18n.t('No knowledge bases yet. Add a GitHub repo to get started.')}
				</div>
			{/if}
		</section>

		<!-- Sources grid -->
		<section class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
			<!-- Notebooks -->
			<div
				class="rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-4 flex flex-col"
			>
				<div class="flex items-center justify-between mb-2">
					<div class="text-sm font-medium text-gray-800 dark:text-gray-100">{$i18n.t('Notebooks')}</div>
					<a href="/harvis/notebooks" class="text-xs text-blue-600 dark:text-blue-400 hover:underline"
						>{$i18n.t('All')}</a
					>
				</div>
				{#if recentNotebooks.length}
					<div class="divide-y divide-gray-100 dark:divide-gray-850 flex-1">
						{#each recentNotebooks as nb (nb.id)}
							<button
								type="button"
								on:click={() => openNotebook(nb.id)}
								class="w-full flex items-center gap-2 py-1.5 text-left group min-w-0"
							>
								<span class="text-sm shrink-0">{nb.emoji || '📓'}</span>
								<span
									class="truncate text-xs text-gray-700 dark:text-gray-200 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition"
									>{nb.title || $i18n.t('Untitled')}</span
								>
							</button>
						{/each}
					</div>
				{:else}
					<div class="text-xs text-gray-500 flex-1 py-2">{$i18n.t('No notebooks yet.')}</div>
				{/if}
			</div>

			<!-- Projects (folders) — informational; projects are managed in the chat sidebar -->
			<div
				class="rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-4 flex flex-col"
			>
				<div class="flex items-center justify-between mb-2">
					<div class="text-sm font-medium text-gray-800 dark:text-gray-100">{$i18n.t('Projects')}</div>
					<span class="text-xs text-gray-400">{folders.length}</span>
				</div>
				{#if folders.length}
					<div class="flex flex-col gap-1 flex-1">
						{#each folders.slice(0, 5) as f (f.id)}
							<div class="flex items-center gap-2 min-w-0">
								<svg
									class="size-3.5 text-gray-400 shrink-0"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="1.8"
									stroke-linecap="round"
									stroke-linejoin="round"
									><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" /></svg
								>
								<span class="truncate text-xs text-gray-700 dark:text-gray-200">{f.name || $i18n.t('Untitled')}</span>
							</div>
						{/each}
					</div>
				{:else}
					<div class="text-xs text-gray-500 flex-1 py-2">
						{$i18n.t('Group chats into projects with shared context.')}
					</div>
				{/if}
			</div>

			<!-- GitHub -->
			<div
				class="rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-4 flex flex-col"
			>
				<div class="flex items-center justify-between mb-2">
					<div class="text-sm font-medium text-gray-800 dark:text-gray-100 flex items-center gap-1.5">
						<svg class="size-4" viewBox="0 0 24 24" fill="currentColor"
							><path
								d="M12 2C6.48 2 2 6.48 2 12c0 4.42 2.87 8.17 6.84 9.5.5.08.66-.22.66-.48v-1.7c-2.78.6-3.37-1.34-3.37-1.34-.45-1.16-1.1-1.47-1.1-1.47-.9-.62.07-.6.07-.6 1 .07 1.53 1.03 1.53 1.03.89 1.52 2.34 1.08 2.91.83.09-.65.35-1.09.63-1.34-2.22-.25-4.55-1.11-4.55-4.94 0-1.09.39-1.99 1.03-2.69-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.02a9.6 9.6 0 0 1 5 0c1.91-1.29 2.75-1.02 2.75-1.02.55 1.38.2 2.4.1 2.65.64.7 1.03 1.6 1.03 2.69 0 3.84-2.34 4.69-4.57 4.94.36.31.68.92.68 1.85v2.74c0 .27.16.57.67.48A10 10 0 0 0 22 12c0-5.52-4.48-10-10-10z"
							/></svg
						>
						{$i18n.t('GitHub')}
					</div>
					{#if repos.length}<span class="text-xs text-gray-400">{repos.length}</span>{/if}
				</div>
				{#if repos.length}
					<div class="flex flex-col gap-1 flex-1">
						{#each repos.slice(0, 5) as r}
							<a
								href={r.html_url}
								target="_blank"
								rel="noreferrer"
								class="truncate text-xs text-gray-700 dark:text-gray-200 hover:text-blue-600 dark:hover:text-blue-400"
								>{r.full_name || r.name}</a
							>
						{/each}
					</div>
				{:else}
					<div class="flex-1 flex flex-col">
						<div class="text-xs text-gray-500 flex-1 py-2">
							{$i18n.t('Connect repositories to read and code against them.')}
						</div>
						<a
							href="/harvis/vibecode"
							class="text-xs text-blue-600 dark:text-blue-400 hover:underline self-start"
							>{$i18n.t('Connect GitHub')} →</a
						>
					</div>
				{/if}
			</div>

			<!-- Memory -->
			<a
				href="/harvis/agent-studio/brain"
				class="group rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-4 flex flex-col hover:border-blue-500/40 transition"
			>
				<div class="flex items-center justify-between mb-2">
					<div class="text-sm font-medium text-gray-800 dark:text-gray-100">{$i18n.t('Memory')}</div>
					<span class="text-xs text-gray-400">{memories.length}</span>
				</div>
				{#if memories.length}
					<div class="flex flex-col gap-1 flex-1">
						{#each memories.slice(0, 4) as m}
							<div class="truncate text-xs text-gray-700 dark:text-gray-200">• {m.content}</div>
						{/each}
					</div>
				{:else}
					<div class="text-xs text-gray-500 flex-1 py-2">
						{$i18n.t('Your saved insights and preferences.')}
					</div>
				{/if}
				<span class="text-xs text-blue-600 dark:text-blue-400 mt-2 group-hover:underline self-start"
					>{$i18n.t('View')}</span
				>
			</a>
		</section>
	</div>
</div>
