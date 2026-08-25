<script lang="ts">
	// Integrations — a compact, real-time control panel for the plug-and-play agent stack.
	// Top: a live summary bar (status counts) → group/status filters → grouped sections of
	// COMPACT cards (face = icon · name · purpose · ONE normalized status · Manage · default).
	// All the detail (capabilities, runtime, source, security, setup, connection) lives in the
	// details drawer (IntegrationDetailModal). State is kept live by polling every 7s while the
	// tab is visible + an instant refetch after every action.
	import { getContext, onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';
	import { WEBUI_NAME, chatId, models, showSidebar } from '$lib/stores';
	import { copyToClipboard } from '$lib/utils';

	import {
		CATALOG,
		PREFERABLE_CAPABILITIES,
		mergeLiveStatus,
		filterCatalog,
		applyTemplate,
		type IntegrationDefinition,
		type LiveStatus
	} from '$lib/integrations/catalog';
	import { getIntegrationsStatus } from '$lib/apis/integrations';
	import {
		getCapabilityRegistry,
		saveCapabilityPreference,
		saveDefaultModel
	} from '$lib/integrations/registry';
	import {
		NORM_META,
		normalizeStatus,
		statusCounts,
		groupOf,
		isPack,
		preferableCaps,
		GROUP_ORDER,
		GROUP_LABEL,
		SECTION_ORDER,
		SECTION_LABEL,
		SECTION_HINT,
		sectionOf,
		type SectionKey,
		type NormStatus,
		type GroupKey,
		type EngineReadiness
	} from '$lib/integrations/status';
	import ControlCard from '$lib/integrations/ControlCard.svelte';
	import IntegrationDetailModal from '$lib/integrations/IntegrationDetailModal.svelte';
	import IntegrationLogs from '$lib/integrations/IntegrationLogs.svelte';
	import FreeKeysGuide from '$lib/integrations/FreeKeysGuide.svelte';
	import FeaturedProviderCard from '$lib/integrations/FeaturedProviderCard.svelte';

	const i18n: any = getContext('i18n');
	const backToChat = () => goto($chatId ? `/c/${$chatId}` : '/');

	// ── live state ──────────────────────────────────────────────────────────────────────
	let live: LiveStatus | null = null;
	let engineReadiness: EngineReadiness = {};
	let prefs: Record<string, string> = {};
	let defaultModel = '';
	let checking = false;
	let q = '';

	// filter: 'all' | a normalized status (from the summary chips) | a purpose group (from the tabs)
	type Filter = 'all' | NormStatus | GroupKey;
	let filter: Filter = 'all';
	const isStatusFilter = (f: Filter): f is NormStatus => f in NORM_META;
	const isGroupFilter = (f: Filter): f is GroupKey => GROUP_ORDER.includes(f as GroupKey);

	const GROUP_TABS: GroupKey[] = ['engines', 'models', 'repos', 'tools', 'chat'];
	const SUMMARY_ORDER: NormStatus[] = ['ready', 'connected', 'needs_setup', 'unavailable', 'disabled', 'error'];

	// Engine readiness overlays the static catalog so a verified cloud engine reads as live.
	const ENGINE_CARD_TO_READINESS: Record<string, string> = {
		'claude-code': 'claude-code',
		'codex-app': 'codex',
		opencode: 'opencode',
		'hermes-agent': 'hermes-agent'
	};
	$: merged = mergeLiveStatus(CATALOG, live).map((d) => {
		const ek = ENGINE_CARD_TO_READINESS[d.id];
		const er = ek ? engineReadiness[ek] : undefined;
		// A verified cloud credential (connected) reads as "live" even when the Build engine is off.
		return er && (er.ready || er.connected) ? { ...d, status: 'ready' as const } : d;
	});
	$: searched = filterCatalog(merged, q);
	$: counts = statusCounts(searched, engineReadiness);
	$: cardsInGroup = (g: GroupKey) => searched.filter((d) => groupOf(d) === g);
	// P6: the "all" layout renders the five named dashboard sections.
	$: cardsInSection = (s: SectionKey) => searched.filter((d) => sectionOf(d) === s);

	// A section can nominate one lead card (catalog `featured`). It renders large, first, with
	// its setup steps opened up; everything else in that section drops to a compact row. This
	// is the recommended way in, not a ranking — OpenRouter is featured because one free key
	// there reaches models from several vendors, which is the shortest path to a working chat.
	const leadOf = (list: IntegrationDefinition[]) => list.find((d) => d.featured) ?? null;
	const restOf = (list: IntegrationDefinition[]) => {
		const lead = leadOf(list);
		return lead ? list.filter((d) => d.id !== lead.id) : list;
	};

	// Collapsible sections (2026-07-29 directory layout — the chevron on each heading).
	// Everything starts open. A live search query forces every section open, so a match can
	// never hide inside a collapsed group.
	let collapsed: Record<string, boolean> = {};
	const toggleSection = (s: SectionKey) => (collapsed = { ...collapsed, [s]: !collapsed[s] });
	$: sectionOpen = (s: SectionKey) => (q.trim() ? true : !collapsed[s]);

	// P6: per-integration logs drawer.
	let showLogs = false;
	let logsDef: IntegrationDefinition | null = null;
	const openLogs = (def: IntegrationDefinition) => {
		logsDef = def;
		showLogs = true;
	};
	$: flatCards = isGroupFilter(filter)
		? cardsInGroup(filter)
		: isStatusFilter(filter)
			? searched.filter((d) => !isPack(d) && normalizeStatus(d, engineReadiness) === filter)
			: [];

	// ── free-key onboarding ─────────────────────────────────────────────────────────────
	// The one thing a fresh install is missing is a model. The guide names the vendors with a
	// real free tier and hands off to the normal connect flow; the callout below only appears
	// when the user genuinely has nowhere to send a message yet.
	let showFreeKeys = false;
	$: freeProviderCards = merged.filter((d) => d.freeTier && d.keyConsoleUrl);
	$: anyFreeConnected = freeProviderCards.some(
		(d) => normalizeStatus(d, engineReadiness) === 'connected'
	);
	// Local Ollama counts as "has a model" — someone running models on their own box doesn't
	// need to be told about cloud free tiers.
	$: localModelsReady = merged.some(
		(d) => d.id === 'ollama' && (d.status === 'ready' || d.status === 'running')
	);
	// `live` gates it so the callout can't flash during the first fetch, when everything still
	// reads as unconnected.
	$: showNoModelCallout = !!live && !anyFreeConnected && !localModelsReady;

	// ── details drawer ──────────────────────────────────────────────────────────────────
	let showDetail = false;
	let detailDef: IntegrationDefinition | null = null;
	const openModal = (id: string) => {
		detailDef = merged.find((d) => d.id === id) ?? null;
		showDetail = !!detailDef;
	};
	$: if (showDetail && detailDef) detailDef = merged.find((d) => d.id === detailDef!.id) ?? detailDef;
	// Refetch when the drawer closes (catches connect/verify/disconnect done inside it).
	let wasOpen = false;
	$: {
		if (wasOpen && !showDetail) refresh(false);
		wasOpen = showDetail;
	}

	// ── data fetch (live status + registry) ───────────────────────────────────────────────
	const refresh = async (withSpinner = true) => {
		if (withSpinner) checking = true;
		const [l, reg] = await Promise.all([
			getIntegrationsStatus(localStorage.token),
			getCapabilityRegistry(localStorage.token)
		]);
		if (l) live = l;
		if (reg) {
			engineReadiness = reg.engine_readiness || {};
			prefs = reg.preferences || {};
		}
		checking = false;
	};

	// default model — pre-fills new Chat & Code sessions (kept out of refresh() so polling
	// never clobbers an in-progress selection).
	$: modelOptions = ($models ?? []).filter((m) => !(m?.info?.meta?.hidden ?? false));
	const onDefaultModelChange = async () => {
		const r = await saveDefaultModel(defaultModel || null);
		toast.success(r.synced ? $i18n.t('Default model saved') : $i18n.t('Saved locally'));
	};

	// One-time on mount: soft-sync local-only prefs up to the server + seed defaultModel.
	const initOnce = async () => {
		try {
			const reg = await getCapabilityRegistry(localStorage.token);
			if (!reg) return;
			defaultModel = reg.default_model || '';
			if (reg.default_model) {
				try {
					localStorage.setItem('harvis.integrations.default_model', reg.default_model);
				} catch (_) {}
			}
			if (!reg.preferences || Object.keys(reg.preferences).length === 0) {
				for (const c of PREFERABLE_CAPABILITIES) {
					const v = localStorage.getItem(`harvis.integrations.preferences.${c}`);
					if (v) await saveCapabilityPreference(c, v);
				}
			}
		} catch (_) {}
	};

	// ── real-time polling (pause when the tab is hidden) ───────────────────────────────────
	let pollTimer: ReturnType<typeof setInterval> | null = null;
	const onVisibility = () => {
		if (typeof document === 'undefined') return;
		if (document.hidden) {
			if (pollTimer) clearInterval(pollTimer);
			pollTimer = null;
		} else if (!pollTimer) {
			refresh(false);
			pollTimer = setInterval(() => refresh(false), 7000);
		}
	};

	onMount(async () => {
		await initOnce();
		await refresh();
		pollTimer = setInterval(() => refresh(false), 7000);
		document.addEventListener('visibilitychange', onVisibility);
	});
	onDestroy(() => {
		if (pollTimer) clearInterval(pollTimer);
		if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisibility);
	});

	// ── actions ───────────────────────────────────────────────────────────────────────────
	const setAsDefault = async (def: IntegrationDefinition) => {
		const caps = preferableCaps(def);
		// optimistic → instant badge; refresh confirms from the server.
		const next = { ...prefs };
		for (const c of caps) next[c] = def.id;
		prefs = next;
		let synced = true;
		for (const c of caps) {
			const r = await saveCapabilityPreference(c, def.id);
			if (!r.synced) synced = false;
		}
		toast.success(
			synced
				? $i18n.t('{{name}} is now the default', { name: def.name })
				: $i18n.t('Saved {{name}} locally', { name: def.name })
		);
		refresh(false);
	};

	const handleAction = async (e: CustomEvent) => {
		const { def, action } = e.detail as { def: IntegrationDefinition; action: any };
		if (action.kind === 'copy' && action.command) {
			const cmd = applyTemplate(def.commands?.[action.command], def.model?.preferred);
			if (cmd && (await copyToClipboard(cmd))) toast.success($i18n.t('Copied to clipboard'));
		} else if (action.kind === 'save_preference') {
			await setAsDefault(def);
		} else if (action.kind === 'link' && action.href) {
			goto(action.href);
		} else if (action.kind === 'detail') {
			openModal(def.id);
		}
	};
</script>

<svelte:head>
	<title>{$i18n.t('Engines')} • {$WEBUI_NAME}</title>
</svelte:head>

<div
	class="w-full h-full overflow-y-auto {$showSidebar
		? 'md:max-w-[calc(100%-var(--sidebar-width))]'
		: ''}"
>
	<div class="max-w-5xl mx-auto px-5 py-6 space-y-5">
		<!-- header -->
		<header>
			<button class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200" on:click={backToChat}>
				← {$i18n.t('Back to chat')}
			</button>
			<div class="flex items-end justify-between gap-3 mt-2 flex-wrap">
				<div>
					<h1 class="text-2xl font-semibold text-gray-800 dark:text-gray-100">{$i18n.t('Engines')}</h1>
					<p class="text-sm text-gray-500 mt-0.5">
						{$i18n.t('What Harvis can use — and what it uses by default.')}
					</p>
				</div>
				<div class="flex items-center gap-3">
					<!-- live indicator -->
					<span class="inline-flex items-center gap-1.5 text-[11px] text-gray-400">
						<span
							class="size-1.5 rounded-full {checking ? 'bg-blue-500 animate-pulse' : 'bg-green-500'}"
						></span>
						{checking ? $i18n.t('Checking…') : $i18n.t('Live')}
					</span>
					<button
						class="text-xs px-2.5 py-1 rounded-lg border border-gray-200 dark:border-white/10 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/5 transition disabled:opacity-50"
						on:click={() => refresh()}
						disabled={checking}
					>
						{$i18n.t('Refresh')}
					</button>
					<button
						class="text-xs px-2.5 py-1 rounded-lg border border-blue-500/30 text-blue-600 dark:text-blue-300 hover:bg-blue-500/10 transition"
						on:click={() => (showFreeKeys = true)}
					>
						{$i18n.t('Get free API keys')}
					</button>
				</div>
			</div>

			<!-- page-level search: the primary way to find something in a long directory -->
			<div class="relative mt-4">
				<svg
					class="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-gray-400 pointer-events-none"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
					aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg
				>
				<input
					bind:value={q}
					type="text"
					placeholder={$i18n.t('Search engines and connectors')}
					aria-label={$i18n.t('Search engines and connectors')}
					class="w-full text-sm rounded-xl border border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-[#0c111d] pl-9 pr-9 py-2.5 text-gray-700 dark:text-gray-200 placeholder:text-gray-400 outline-none focus:border-blue-500/40"
				/>
				{#if q}
					<button
						class="absolute right-2.5 top-1/2 -translate-y-1/2 p-1 rounded-lg text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition"
						title={$i18n.t('Clear')}
						aria-label={$i18n.t('Clear')}
						on:click={() => (q = '')}
					>
						<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="size-4"><path d="M18 6 6 18M6 6l12 12" /></svg>
					</button>
				{/if}
			</div>
		</header>

		<!-- summary bar: status counts (click to filter) -->
		<div class="flex flex-wrap items-center gap-1.5">
			<button
				class="text-xs px-2.5 py-1 rounded-lg border transition {filter === 'all'
					? 'border-blue-500/40 bg-blue-500/10 text-blue-600 dark:text-blue-300'
					: 'border-gray-100 dark:border-gray-850 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-850'}"
				on:click={() => (filter = 'all')}>{$i18n.t('All')}</button
			>
			{#each SUMMARY_ORDER as s}
				{#if counts[s] > 0}
					<button
						class="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-lg border transition {filter === s
							? 'border-gray-300 dark:border-gray-700 bg-gray-50 dark:bg-gray-850'
							: 'border-gray-100 dark:border-gray-850 hover:bg-gray-50 dark:hover:bg-gray-850'}"
						on:click={() => (filter = filter === s ? 'all' : s)}
					>
						<span class="size-1.5 rounded-full {NORM_META[s].dot}"></span>
						<span class="text-gray-600 dark:text-gray-300">{NORM_META[s].label}</span>
						<span class="font-semibold {NORM_META[s].text}">{counts[s]}</span>
					</button>
				{/if}
			{/each}
		</div>

		<!-- group filter tabs (search lives in the header now) -->
		<div class="flex flex-wrap gap-1.5">
			{#each GROUP_TABS as g}
				<button
					class="text-xs px-3 py-1.5 rounded-lg transition {filter === g
						? 'bg-blue-600 text-white'
						: 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-white/5'}"
					on:click={() => (filter = filter === g ? 'all' : g)}>{$i18n.t(GROUP_LABEL[g])}</button
				>
			{/each}
		</div>

		<!-- No model anywhere: the one state where a new user is genuinely stuck. Says what's
		     missing and offers the shortest path out of it. Disappears the moment anything
		     connects, so it can never nag someone who already has a working setup. -->
		{#if showNoModelCallout}
			<div
				class="rounded-xl border border-blue-500/25 bg-blue-500/5 px-4 py-3.5 flex flex-col sm:flex-row sm:items-center gap-3"
			>
				<div class="min-w-0 flex-1">
					<p class="text-sm font-medium text-gray-800 dark:text-gray-100">
						{$i18n.t('No model provider connected yet')}
					</p>
					<p class="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
						{$i18n.t(
							'Harvis needs somewhere to send a message. Several providers publish a free tier — one API key is enough to start chatting, with no GPU and no card.'
						)}
					</p>
				</div>
				<button
					class="shrink-0 text-xs px-3 py-1.5 rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition"
					on:click={() => (showFreeKeys = true)}
				>
					{$i18n.t('Get free API keys')}
				</button>
			</div>
		{/if}

		<!-- body — P6 sections, 2026-07-29 directory layout: collapsible heading + two columns -->
		{#if filter === 'all'}
			{#each SECTION_ORDER as s (s)}
				{#if cardsInSection(s).length || s === 'ssh_remote'}
					<section>
						<button
							type="button"
							class="group w-full flex items-center gap-2 text-left py-1.5 outline-none"
							aria-expanded={sectionOpen(s)}
							on:click={() => toggleSection(s)}
						>
							<div class="min-w-0">
								<h2 class="text-base font-semibold text-gray-800 dark:text-gray-100">
									{$i18n.t(SECTION_LABEL[s])}
								</h2>
								<p class="text-xs text-gray-400 dark:text-gray-500">{$i18n.t(SECTION_HINT[s])}</p>
							</div>
							<svg
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="2"
								stroke-linecap="round"
								stroke-linejoin="round"
								class="size-4 shrink-0 text-gray-400 group-hover:text-gray-600 dark:group-hover:text-gray-300 transition-transform {sectionOpen(
									s
								)
									? 'rotate-0'
									: '-rotate-90'}"
								aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg
							>
						</button>
						{#if sectionOpen(s)}
						{#if cardsInSection(s).length}
							{@const lead = leadOf(cardsInSection(s))}
							{#if lead}
								<div class="mt-1 mb-2">
									<FeaturedProviderCard def={lead} {engineReadiness} on:open={(e) => openModal(e.detail)} />
								</div>
							{/if}
							<div class="grid grid-cols-1 md:grid-cols-2 gap-x-4 mt-0.5">
								{#each restOf(cardsInSection(s)) as def (def.id)}
									<ControlCard {def} {engineReadiness} {prefs} compact={!!lead} on:open={(e) => openModal(e.detail)} on:setDefault={(e) => setAsDefault(e.detail)} on:logs={(e) => openLogs(e.detail)} />
								{/each}
							</div>
						{:else if s === 'ssh_remote'}
							<!-- SSH ships scaffold-only (HARVIS_SSH_ENABLED off) — placeholder, no functionality -->
							<div class="rounded-xl border border-dashed border-gray-200 dark:border-gray-800 px-4 py-3 flex items-center gap-3">
								<svg class="size-4 text-gray-400 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2" /><path d="m6 8 3 2.5L6 13M11 13h5" /></svg>
								<div class="min-w-0">
									<div class="text-sm text-gray-600 dark:text-gray-300">{$i18n.t('SSH remote workspaces')}</div>
									<div class="text-[11px] text-gray-400">{$i18n.t('Coming soon — pending security review. Connection manager, folder mounts, and remote terminal are gated behind explicit approval.')}</div>
								</div>
							</div>
						{/if}
						{/if}
					</section>
				{/if}
			{/each}
		{:else}
			{@const flatLead = leadOf(flatCards)}
			{#if flatLead}
				<FeaturedProviderCard def={flatLead} {engineReadiness} on:open={(e) => openModal(e.detail)} />
			{/if}
			<div class="grid grid-cols-1 md:grid-cols-2 gap-x-4">
				{#each restOf(flatCards) as def (def.id)}
					<ControlCard {def} {engineReadiness} {prefs} compact={!!flatLead} on:open={(e) => openModal(e.detail)} on:setDefault={(e) => setAsDefault(e.detail)} on:logs={(e) => openLogs(e.detail)} />
				{/each}
			</div>
			{#if !flatCards.length}
				<div class="text-center text-sm text-gray-400 py-12">{$i18n.t('Nothing here.')}</div>
			{/if}
		{/if}
	</div>
</div>

<IntegrationDetailModal
	bind:show={showDetail}
	def={detailDef}
	on:action={handleAction}
	on:changed={() => refresh(false)}
/>

<!-- P6: read-only recent-activity drawer -->
<IntegrationLogs bind:show={showLogs} integrationId={logsDef?.id ?? ''} name={logsDef?.name ?? ''} />

<!-- Free-key onboarding. Hands off to the SAME detail modal as every other connect, so the
     credential is only ever typed into ConnectionPanel — the guide never touches a key. -->
<FreeKeysGuide
	bind:show={showFreeKeys}
	{merged}
	{engineReadiness}
	on:connect={(e) => openModal(e.detail)}
/>
