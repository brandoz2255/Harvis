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
	import { WEBUI_NAME, chatId, models } from '$lib/stores';
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
		type NormStatus,
		type GroupKey,
		type EngineReadiness
	} from '$lib/integrations/status';
	import ControlCard from '$lib/integrations/ControlCard.svelte';
	import IntegrationDetailModal from '$lib/integrations/IntegrationDetailModal.svelte';

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
		return ek && engineReadiness[ek]?.ready ? { ...d, status: 'ready' as const } : d;
	});
	$: searched = filterCatalog(merged, q);
	$: counts = statusCounts(searched, engineReadiness);
	$: cardsInGroup = (g: GroupKey) => searched.filter((d) => groupOf(d) === g);
	$: flatCards = isGroupFilter(filter)
		? cardsInGroup(filter)
		: isStatusFilter(filter)
			? searched.filter((d) => !isPack(d) && normalizeStatus(d, engineReadiness) === filter)
			: [];

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
	<title>{$i18n.t('Integrations')} • {$WEBUI_NAME}</title>
</svelte:head>

<div class="w-full h-full overflow-y-auto">
	<div class="max-w-5xl mx-auto px-5 py-6 space-y-5">
		<!-- header -->
		<header>
			<button class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200" on:click={backToChat}>
				← {$i18n.t('Back to chat')}
			</button>
			<div class="flex items-end justify-between gap-3 mt-2 flex-wrap">
				<div>
					<h1 class="text-2xl font-semibold text-gray-800 dark:text-gray-100">{$i18n.t('Integrations')}</h1>
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
				</div>
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

		<!-- group filter tabs + search -->
		<div class="flex flex-col sm:flex-row sm:items-center gap-3">
			<div class="flex flex-wrap gap-1.5">
				{#each GROUP_TABS as g}
					<button
						class="text-xs px-3 py-1.5 rounded-full transition {filter === g
							? 'bg-blue-600 text-white'
							: 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-white/5'}"
						on:click={() => (filter = filter === g ? 'all' : g)}>{$i18n.t(GROUP_LABEL[g])}</button
					>
				{/each}
			</div>
			<input
				bind:value={q}
				type="text"
				placeholder={$i18n.t('Search…')}
				class="w-full sm:max-w-[14rem] sm:ml-auto text-sm rounded-lg border border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-[#0c111d] px-3 py-1.5 text-gray-700 dark:text-gray-200 outline-none focus:border-blue-500/40"
			/>
		</div>

		<!-- default model — what Chat/Code use unless overridden -->
		<div
			class="flex flex-col sm:flex-row sm:items-center gap-2 rounded-xl border border-gray-100 dark:border-white/8 bg-gray-50/50 dark:bg-[#0f1626] px-4 py-2.5"
		>
			<label for="harvis-default-model" class="text-sm font-medium text-gray-700 dark:text-gray-200 shrink-0">
				{$i18n.t('Default model')}
			</label>
			<select
				id="harvis-default-model"
				bind:value={defaultModel}
				on:change={onDefaultModelChange}
				class="text-sm rounded-lg border border-gray-200 dark:border-white/10 bg-white dark:bg-[#0a0e18] px-2.5 py-1.5 text-gray-700 dark:text-gray-200 outline-none focus:border-blue-500/40 sm:max-w-xs"
			>
				<option value="">{$i18n.t('Not set')}</option>
				{#each modelOptions as m (m.id)}
					<option value={m.id}>{m.name ?? m.id}</option>
				{/each}
			</select>
			<span class="text-[11px] text-gray-400 sm:ml-auto">{$i18n.t('Pre-fills new Chat & Code sessions')}</span>
		</div>

		<!-- body -->
		{#if filter === 'all'}
			{#each GROUP_ORDER as g (g)}
				{#if cardsInGroup(g).length}
					<section class="space-y-2">
						<h2 class="text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
							{$i18n.t(GROUP_LABEL[g])}
						</h2>
						<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
							{#each cardsInGroup(g) as def (def.id)}
								<ControlCard {def} {engineReadiness} {prefs} on:open={(e) => openModal(e.detail)} on:setDefault={(e) => setAsDefault(e.detail)} />
							{/each}
						</div>
					</section>
				{/if}
			{/each}
		{:else}
			<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
				{#each flatCards as def (def.id)}
					<ControlCard {def} {engineReadiness} {prefs} on:open={(e) => openModal(e.detail)} on:setDefault={(e) => setAsDefault(e.detail)} />
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
