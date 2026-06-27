<script lang="ts">
	// Integrations — a local-first, developer-focused catalog for the plug-and-play agent
	// stack: Applications (coding engines), Services (connections), and Integration Packs
	// (recipes). Ollama-style: command-first rows, distinct colored brand tiles, copyable
	// setup (never executed). Harvis CLI is featured at the top as a "Coming soon" hero.
	// Models live in the data model but are not rendered this pass.
	import { getContext, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';
	import { WEBUI_NAME, chatId, models } from '$lib/stores';
	import { copyToClipboard } from '$lib/utils';

	import {
		CATALOG,
		CATEGORY_LABEL,
		PREFERABLE_CAPABILITIES,
		mergeLiveStatus,
		filterCatalog,
		applyTemplate,
		type IntegrationCategory,
		type IntegrationDefinition,
		type LiveStatus
	} from '$lib/integrations/catalog';
	import {
		CAPABILITY_LABEL,
		SURFACE_LABEL,
		type IntegrationCapability,
		type HarvisSurface
	} from '$lib/integrations/capabilities';
	import { getIntegrationsStatus } from '$lib/apis/integrations';
	import {
		getCapabilityRegistry,
		saveCapabilityPreference,
		saveDefaultModel
	} from '$lib/integrations/registry';
	import IntegrationCard from '$lib/integrations/IntegrationCard.svelte';
	import IntegrationRow from '$lib/integrations/IntegrationRow.svelte';
	import IntegrationDetailModal from '$lib/integrations/IntegrationDetailModal.svelte';
	import BrandGlyph from '$lib/integrations/BrandGlyph.svelte';

	const i18n: any = getContext('i18n');
	const backToChat = () => goto($chatId ? `/c/${$chatId}` : '/');

	let live: LiveStatus | null = null;
	let q = '';
	let scanning = false;

	type Tab = 'all' | IntegrationCategory;
	const TABS: { key: Tab; label: string }[] = [
		{ key: 'all', label: 'All' },
		{ key: 'application', label: CATEGORY_LABEL.application },
		{ key: 'service', label: CATEGORY_LABEL.service },
		{ key: 'pack', label: CATEGORY_LABEL.pack }
	];
	let tab: Tab = 'all';

	const CATEGORY_ORDER: IntegrationCategory[] = ['application', 'service', 'pack'];

	// Harvis CLI is a hardcoded hero (not a catalog entry) — its capability metadata lives here.
	const HARVIS_CLI_PROVIDES: IntegrationCapability[] = ['local_execution_bridge'];
	const HARVIS_CLI_USED_BY: HarvisSurface[] = ['code', 'agent_studio', 'automations'];

	$: merged = mergeLiveStatus(CATALOG, live);
	$: visible = filterCatalog(merged, q);
	$: recommended = visible.filter((d) => d.recommended);
	$: shownCategories = tab === 'all' ? CATEGORY_ORDER : ([tab] as IntegrationCategory[]);
	$: byCat = (cat: IntegrationCategory) => visible.filter((d) => d.category === cat);

	// detail modal
	let showDetail = false;
	let detailDef: IntegrationDefinition | null = null;
	const openModal = (id: string) => {
		detailDef = merged.find((d) => d.id === id) ?? null;
		showDetail = !!detailDef;
	};
	$: if (showDetail && detailDef) detailDef = merged.find((d) => d.id === detailDef.id) ?? detailDef;

	const scan = async () => {
		scanning = true;
		live = await getIntegrationsStatus(localStorage.token);
		scanning = false;
	};

	// Default model (Phase C2) — pre-fills new Chat & Code sessions.
	let defaultModel = '';
	$: modelOptions = ($models ?? []).filter((m) => !(m?.info?.meta?.hidden ?? false));
	const onDefaultModelChange = async () => {
		const r = await saveDefaultModel(defaultModel || null);
		toast.success(r.synced ? $i18n.t('Default model saved') : $i18n.t('Saved locally'));
	};

	// One registry fetch on mount: hydrate the default-model picker + cache it to
	// localStorage (primes Chat/Code pre-fill), and one-time soft-sync any local-only
	// preferences up to the server (Phase A wrote local-only). No DB migration.
	const initFromRegistry = async () => {
		try {
			const reg = await getCapabilityRegistry(localStorage.token);
			if (!reg) return;
			defaultModel = reg.default_model || '';
			try {
				if (reg.default_model) {
					localStorage.setItem('harvis.integrations.default_model', reg.default_model);
				}
			} catch (_) {}
			if (!reg.preferences || Object.keys(reg.preferences).length === 0) {
				for (const c of PREFERABLE_CAPABILITIES) {
					const v = localStorage.getItem(`harvis.integrations.preferences.${c}`);
					if (v) await saveCapabilityPreference(c, v);
				}
			}
		} catch (_) {}
	};

	onMount(() => {
		scan();
		initFromRegistry();
	});

	const handleAction = async (e: CustomEvent) => {
		const { def, action } = e.detail as { def: IntegrationDefinition; action: any };
		if (action.kind === 'copy' && action.command) {
			const cmd = applyTemplate(def.commands?.[action.command], def.model?.preferred);
			if (cmd && (await copyToClipboard(cmd))) toast.success($i18n.t('Copied to clipboard'));
		} else if (action.kind === 'save_preference') {
			let allSynced = true;
			for (const c of def.provides ?? []) {
				if (PREFERABLE_CAPABILITIES.includes(c)) {
					const r = await saveCapabilityPreference(c, def.id); // localStorage-first + server sync
					if (!r.synced) allSynced = false;
				}
			}
			toast.success(
				allSynced
					? $i18n.t('Saved {{name}} as a preferred provider (applied later)', { name: def.name })
					: $i18n.t('Saved {{name}} locally (applied later)', { name: def.name })
			);
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
	<div class="max-w-5xl mx-auto px-5 py-6 space-y-6">
		<!-- header -->
		<header>
			<button class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200" on:click={backToChat}>
				← {$i18n.t('Back to chat')}
			</button>
			<div class="flex items-start justify-between gap-3 mt-2">
				<div>
					<h1 class="text-2xl font-semibold text-gray-800 dark:text-gray-100">{$i18n.t('Integrations')}</h1>
					<p class="text-sm text-gray-500 mt-1">
						{$i18n.t('Connect apps, models, services, and tools to Harvis.')}
					</p>
				</div>
				<button
					class="shrink-0 text-xs px-3 py-1.5 rounded-lg border border-gray-200 dark:border-white/10 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/5 transition disabled:opacity-50"
					on:click={scan}
					disabled={scanning}
				>
					{scanning ? $i18n.t('Scanning…') : $i18n.t('Rescan')}
				</button>
			</div>
		</header>

		<!-- Default model (Phase C2) — pre-fills new Chat & Code sessions -->
		<div
			class="flex flex-col sm:flex-row sm:items-center gap-2 rounded-xl border border-gray-100 dark:border-white/8 bg-gray-50/50 dark:bg-[#0f1626] px-4 py-3"
		>
			<label
				for="harvis-default-model"
				class="text-sm font-medium text-gray-700 dark:text-gray-200 shrink-0"
			>
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
			<span class="text-[11px] text-gray-400 sm:ml-auto"
				>{$i18n.t('Pre-fills new Chat & Code sessions')}</span
			>
		</div>

		<!-- Harvis CLI — featured hero (coming soon) -->
		<section
			class="relative overflow-hidden rounded-2xl border border-blue-500/25 bg-gradient-to-br from-blue-600/15 via-blue-500/5 to-transparent p-5 sm:p-6"
		>
			<div class="absolute -right-10 -top-10 size-40 rounded-full bg-blue-500/10 blur-3xl pointer-events-none"></div>
			<div class="relative flex flex-col sm:flex-row sm:items-center gap-4">
				<span
					class="shrink-0 size-14 flex items-center justify-center rounded-2xl bg-blue-500/15 border border-blue-500/30 text-blue-500 dark:text-blue-300"
				>
					<BrandGlyph name="harvis" className="size-8" />
				</span>
				<div class="min-w-0 flex-1">
					<div class="flex items-center gap-2 flex-wrap">
						<h2 class="text-lg font-semibold text-gray-900 dark:text-white">{$i18n.t('Harvis CLI')}</h2>
						<span
							class="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-600 dark:text-blue-300 border border-blue-500/30"
							>{$i18n.t('Coming soon')}</span
						>
					</div>
					<p class="text-sm text-gray-600 dark:text-gray-300/90 mt-1 max-w-2xl">
						{$i18n.t(
							'Run Harvis against local folders using your machine, shell, git, and existing credentials — without exposing your entire filesystem to the web container.'
						)}
					</p>
					<div
						class="mt-3 inline-flex items-center gap-2 rounded-lg border border-blue-500/20 bg-[#0a0e18]/60 px-3 py-1.5 font-mono text-[11px] text-blue-300/80"
					>
						<span class="text-blue-400">$</span> harvis run "review this repo"
					</div>
					<div class="flex flex-wrap items-center gap-x-2 gap-y-1 mt-2.5">
						{#each HARVIS_CLI_PROVIDES as c}
							<span class="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-600 dark:text-blue-300 border border-blue-500/15">{CAPABILITY_LABEL[c]}</span>
						{/each}
						<span class="text-[10px] text-gray-400">Used by {HARVIS_CLI_USED_BY.map((s) => SURFACE_LABEL[s]).join(', ')}</span>
					</div>
				</div>
				<button
					type="button"
					disabled
					class="shrink-0 self-start sm:self-center text-xs px-3 py-1.5 rounded-lg border border-blue-500/30 text-blue-500/70 dark:text-blue-300/60 bg-blue-500/5 cursor-not-allowed"
				>
					{$i18n.t('Coming soon')}
				</button>
			</div>
		</section>

		<!-- search + tabs -->
		<div class="flex flex-col sm:flex-row sm:items-center gap-3">
			<input
				bind:value={q}
				type="text"
				placeholder={$i18n.t('Search integrations…')}
				class="w-full sm:max-w-xs text-sm rounded-lg border border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-[#0c111d] px-3 py-1.5 text-gray-700 dark:text-gray-200 outline-none focus:border-blue-500/40"
			/>
			<div class="flex flex-wrap gap-1.5">
				{#each TABS as t}
					<button
						class="text-xs px-3 py-1.5 rounded-full transition {tab === t.key
							? 'bg-blue-600 text-white'
							: 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-white/5'}"
						on:click={() => (tab = t.key)}
					>
						{$i18n.t(t.label)}
					</button>
				{/each}
			</div>
		</div>

		<!-- recommended (only on All, no active search) — compact card strip -->
		{#if tab === 'all' && !q.trim() && recommended.length}
			<section class="space-y-2.5">
				<h2 class="text-sm font-semibold text-gray-700 dark:text-gray-200">{$i18n.t('Recommended')}</h2>
				<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
					{#each recommended as def (def.id)}
						<IntegrationCard {def} on:open={(e) => openModal(e.detail)} on:action={handleAction} />
					{/each}
				</div>
			</section>
		{/if}

		<!-- category sections — Ollama-style list rows -->
		{#each shownCategories as cat (cat)}
			{#if byCat(cat).length}
				<section class="space-y-2.5">
					<h2 class="text-sm font-semibold text-gray-700 dark:text-gray-200">{$i18n.t(CATEGORY_LABEL[cat])}</h2>
					<div
						class="rounded-xl border border-gray-100 dark:border-white/8 bg-gray-50/50 dark:bg-[#0f1626] divide-y divide-gray-100 dark:divide-white/6 overflow-hidden"
					>
						{#each byCat(cat) as def (def.id)}
							<IntegrationRow {def} on:open={(e) => openModal(e.detail)} on:action={handleAction} />
						{/each}
					</div>
				</section>
			{/if}
		{/each}

		{#if !visible.length}
			<div class="text-center text-sm text-gray-400 py-12">{$i18n.t('No integrations match your search.')}</div>
		{/if}
	</div>
</div>

<IntegrationDetailModal bind:show={showDetail} def={detailDef} on:action={handleAction} />
