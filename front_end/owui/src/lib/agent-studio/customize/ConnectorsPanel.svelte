<script lang="ts">
	// Connectors — the calm capability marketplace for external tools & data
	// (Gmail-style connectors that work across Harvis and its agents). Connectors
	// speak MCP (Model Context Protocol) under the hood; this surface is the human
	// -facing directory over the EXISTING endpoints:
	//   GET  /api/owui/mcp/templates    — curated catalog (Anthropic & Partners)
	//   GET  /api/owui/mcp/connections  — the user's saved connections (+ CRUD)
	//   GET  /api/owui/mcp/registry     — the live MCP registry (Community browse)
	// One-click connect writes a connection row; needs_secret connectors connect
	// "limited" (the pending_review credential gate stands — no key is collected).
	// Adding a registry/custom connector reuses the SAME connect flow — nothing
	// auto-connects. Connecting ≠ live in OpenClaw: the honesty banner links the
	// explicit, flag-gated sync. Replaces the old dense grid + McpShop embed with
	// the marketplace card design + a click-through detail panel.
	import { getContext, onMount, createEventDispatcher } from 'svelte';
	import { fly, fade } from 'svelte/transition';
	import { toast } from 'svelte-sonner';
	import ConnectorLogo from './ConnectorLogo.svelte';

	export let mode: 'full' | 'dock' = 'full';
	export let token = '';

	const i18n: any = getContext('i18n');

	let templates: any[] = [];
	let conns: any[] = [];
	let loaded = false;

	let query = '';
	let view: 'partners' | 'community' = 'partners';
	let statusFilter: 'all' | 'connected' | 'not' = 'all';
	let createOpen = false;

	// detail slide-over — a template (catalog / custom / registry-derived) + form
	let selected: any = null;
	let fieldValues: Record<string, string> = {};
	let customName = '';
	let customTransport = 'sse';
	let attaching = false;
	let busyConnId: string | null = null;

	const authHeaders = (): Record<string, string> => ({ authorization: `Bearer ${token}` });

	const loadTemplates = async () => {
		const r = await fetch('/api/owui/mcp/templates', { headers: authHeaders() })
			.then((x) => (x.ok ? x.json() : null))
			.catch(() => null);
		templates = r?.templates ?? [];
	};
	const loadConns = async () => {
		const r = await fetch('/api/owui/mcp/connections', { headers: authHeaders() })
			.then((x) => (x.ok ? x.json() : { items: [] }))
			.catch(() => ({ items: [] }));
		conns = r?.items ?? [];
	};

	onMount(async () => {
		if (!token) token = localStorage.getItem('token') || '';
		await Promise.all([loadTemplates(), loadConns()]);
		loaded = true;
	});

	// Attaches upsert on the template name, so name is the join key.
	const connFor = (t: any) => conns.find((c) => c.name === (t?.connName ?? t?.name)) ?? null;

	const matches = (name: string, desc: string) => {
		const q = query.trim().toLowerCase();
		return !q || `${name} ${desc}`.toLowerCase().includes(q);
	};

	// ── curated catalog (Anthropic & Partners) ────────────────────────────────
	const isPartner = (t: any) =>
		(t.publisher === 'reference' || t.publisher === 'partner') && t.category !== 'custom';
	const POPULAR_IDS = ['github', 'slack', 'notion'];
	$: popular = POPULAR_IDS.map((id) => templates.find((t) => t.id === id)).filter(Boolean);
	$: partnerCards = templates.filter(
		(t) => isPartner(t) && matches(t.name, t.blurb ?? t.description ?? '')
	);
	$: visiblePartners = partnerCards.filter((t) => {
		if (statusFilter === 'all') return true;
		const connected = !!connFor(t);
		return statusFilter === 'connected' ? connected : !connected;
	});
	$: customTemplates = templates.filter((t) => t.category === 'custom');
	$: attachedEnabled = conns.filter((c) => c.enabled).length;

	// ── live MCP registry (Community browse) ──────────────────────────────────
	let registryItems: any[] = [];
	let registryError = false;
	let registryLoading = false;
	let registryTimer: ReturnType<typeof setTimeout> | null = null;
	let registrySeq = 0;
	let registryLoadedOnce = false;

	const fetchRegistry = async (q: string) => {
		const seq = ++registrySeq;
		registryLoading = true;
		const r = await fetch(`/api/owui/mcp/registry?q=${encodeURIComponent(q)}&limit=18`, {
			headers: authHeaders()
		})
			.then((x) => (x.ok ? x.json() : null))
			.catch(() => null);
		if (seq !== registrySeq) return;
		registryLoading = false;
		registryLoadedOnce = true;
		registryItems = r?.items ?? [];
		registryError = !r || !!r?.error;
	};
	// debounce lives in a plain fn so the reactive block only depends on inputs
	const scheduleRegistry = (v: string, raw: string) => {
		if (v !== 'community') return;
		if (registryTimer) clearTimeout(registryTimer);
		const q = raw.trim();
		registryTimer = setTimeout(() => fetchRegistry(q), q ? 300 : 0);
	};
	$: scheduleRegistry(view, query);

	// ── connect / disconnect ──────────────────────────────────────────────────
	const requiredFields = (t: any) => (t?.fields ?? []).filter((f: any) => f.required);
	const fieldsReady = (t: any) =>
		requiredFields(t).every((f: any) => (fieldValues[f.key] ?? '').trim());
	const isCustom = (t: any) => t?.category === 'custom' || t?.__registry;

	const buildBody = (t: any) => {
		const transport = t.__registry
			? t.transport || 'sse'
			: t.category === 'custom' && t.id === 'custom-url'
				? customTransport
				: (t.transport ?? 'stdio');
		const name = (isCustom(t) ? customName.trim() : t.name) || t.name;
		const body: any = { name, transport };
		if (t.command_template != null) {
			body.command = (t.fields ?? []).reduce(
				(acc: string, f: any) => acc.replaceAll(`{${f.key}}`, (fieldValues[f.key] ?? '').trim()),
				t.command_template
			);
		} else {
			body.url = (fieldValues['url'] ?? '').trim();
		}
		return body;
	};

	const attach = async (t: any) => {
		if (attaching) return;
		attaching = true;
		const savedName = (isCustom(t) ? customName.trim() : t.name) || t.name;
		const res = await fetch('/api/owui/mcp/connections', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json', ...authHeaders() },
			body: JSON.stringify(buildBody(t))
		})
			.then(async (x) => {
				if (!x.ok) throw (await x.json())?.detail ?? 'Failed';
				return x.json();
			})
			.catch((e) => {
				toast.error(`${e}`);
				return null;
			});
		attaching = false;
		if (res) {
			toast.success(
				t.needs_secret
					? $i18n.t('"{{name}}" connected (limited — no credentials stored).', { name: savedName })
					: $i18n.t('"{{name}}" connected.', { name: savedName })
			);
			await loadConns();
			// reflect connected state in the open panel
			if (selected) selected = { ...selected, connName: savedName };
			dispatchChanged();
		}
	};
	const toggle = async (c: any) => {
		busyConnId = c.id;
		await fetch(`/api/owui/mcp/connections/${c.id}/toggle`, { method: 'POST', headers: authHeaders() }).catch(() => {});
		busyConnId = null;
		await loadConns();
		dispatchChanged();
	};
	const detach = async (c: any) => {
		busyConnId = c.id;
		await fetch(`/api/owui/mcp/connections/${c.id}`, { method: 'DELETE', headers: authHeaders() }).catch(() => {});
		busyConnId = null;
		await loadConns();
		dispatchChanged();
	};
	const dispatch = createEventDispatcher();
	const dispatchChanged = () => dispatch('changed');

	// ── OpenClaw sync honesty banner ──────────────────────────────────────────
	let syncPreview: any = null;
	let previewing = false;
	let applying = false;
	let applyNote = '';
	let applyError = '';
	const previewSync = async () => {
		previewing = true;
		syncPreview = await fetch('/api/owui/openclaw/sync/preview', { headers: authHeaders() })
			.then((x) => (x.ok ? x.json() : null))
			.catch(() => null);
		previewing = false;
	};
	const applySync = async () => {
		if (applying) return;
		applying = true;
		applyNote = applyError = '';
		const r = await fetch('/api/owui/openclaw/sync/apply', { method: 'POST', headers: authHeaders() })
			.then(async (x) => ({ ok: x.ok, body: await x.json().catch(() => null) }))
			.catch(() => ({ ok: false, body: null }));
		applying = false;
		if (r.ok) applyNote = r.body?.note ?? $i18n.t('Applied.');
		else applyError = r.body?.detail ?? $i18n.t('Apply failed.');
	};

	// ── open / close detail ────────────────────────────────────────────────────
	const openDetail = (t: any) => {
		selected = { ...t, connName: t.name };
		fieldValues = {};
		customName = '';
		customTransport = t.id === 'custom-url' ? (t.transports?.[0] ?? 'sse') : 'sse';
	};
	const openCustom = () => {
		createOpen = false;
		const t = customTemplates.find((x) => x.id === 'custom-url') ?? customTemplates[0];
		if (!t) {
			toast.error($i18n.t('Custom connector template unavailable.'));
			return;
		}
		selected = { ...t };
		fieldValues = {};
		customName = '';
		customTransport = t.transports?.[0] ?? 'sse';
	};
	const openRegistry = (it: any) => {
		// Reuse the BYO custom flow prefilled from the registry entry — no
		// auto-connect, no package execution; the user still confirms.
		const base = customTemplates.find((x) => (it.url ? x.id === 'custom-url' : x.id === 'custom-stdio'));
		selected = {
			...(base ?? {}),
			__registry: true,
			name: it.name,
			description: it.description,
			transport: it.transport || (it.url ? 'sse' : 'stdio'),
			id: base?.id ?? (it.url ? 'custom-url' : 'custom-stdio')
		};
		fieldValues = it.url ? { url: it.url } : {};
		customName = it.name || '';
		customTransport = it.transport || 'sse';
	};
	const closeDetail = () => (selected = null);

	const enterCommunity = () => {
		view = 'community';
		if (!registryLoadedOnce && !registryLoading) fetchRegistry(query.trim());
	};

	// selected-panel derived state — reference `conns`, `fieldValues`, `customName`
	// DIRECTLY so Svelte tracks them (helper-function reads aren't tracked, which
	// left the panel stale after connect/disconnect and kept Connect disabled).
	$: selConn = selected
		? conns.find((c) => c.name === (selected.connName ?? selected.name)) ?? null
		: null;
	$: selNeedsConfig = selected ? ((selected.fields ?? []).some((f) => f.required) || isCustom(selected)) : false;
	$: selReqOk = selected
		? (selected.fields ?? []).filter((f) => f.required).every((f) => (fieldValues[f.key] ?? '').trim())
		: false;
	$: selReady = selected ? (isCustom(selected) ? !!customName.trim() && selReqOk : selReqOk) : false;
</script>

<div class="w-full {mode === 'full' ? 'max-w-3xl mx-auto' : ''}">
	<!-- top bar: title + quick actions -->
	<div class="flex items-start justify-between gap-2 mb-1">
		<div>
			<h1 class="text-2xl font-semibold text-gray-900 dark:text-gray-50">{$i18n.t('Connectors')}</h1>
			<p class="text-sm text-gray-500 mt-1">{$i18n.t('Connect Harvis to your favorite tools and data. Connectors work across Harvis and its agents.')}</p>
		</div>
		<div class="flex items-center gap-1 shrink-0">
			<button type="button" on:click={() => { loadTemplates(); loadConns(); if (view === 'community') fetchRegistry(query.trim()); }} title={$i18n.t('Refresh')} class="size-8 grid place-items-center rounded-lg text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-850 transition">
				<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.6-6.4M21 3v6h-6" /></svg>
			</button>
			<div class="relative">
				<button type="button" on:click={() => (createOpen = !createOpen)} class="inline-flex items-center gap-1 rounded-lg border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-200 px-3 h-8 text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-850 transition">
					{$i18n.t('Add')}
					<svg class="size-3.5 opacity-70" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6" /></svg>
				</button>
				{#if createOpen}
					<button type="button" class="fixed inset-0 z-40 cursor-default" on:click={() => (createOpen = false)} tabindex="-1" aria-hidden="true"></button>
					<div class="absolute right-0 top-9 z-50 w-52 rounded-xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-900 shadow-lg p-1" transition:fly={{ y: -6, duration: 120 }}>
						<button type="button" on:click={openCustom} class="w-full text-left px-3 py-1.5 rounded-lg text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-850 transition">{$i18n.t('Add custom connector')}</button>
						<button type="button" on:click={() => { createOpen = false; enterCommunity(); }} class="w-full text-left px-3 py-1.5 rounded-lg text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-850 transition">{$i18n.t('Browse the MCP registry')}</button>
					</div>
				{/if}
			</div>
		</div>
	</div>

	<!-- search -->
	<div class="relative mt-4 mb-4">
		<svg class="size-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
		<input
			bind:value={query}
			placeholder={$i18n.t('Search connectors…')}
			aria-label={$i18n.t('Search connectors')}
			class="w-full h-11 rounded-full border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 pl-10 pr-4 text-sm outline-none focus:border-gray-400 dark:focus:border-gray-600 transition"
		/>
	</div>

	<!-- view segmented control + status filter -->
	<div class="flex items-center justify-between gap-2 mb-4">
		<div class="inline-flex items-center rounded-full bg-gray-100 dark:bg-gray-850 p-0.5 text-sm">
			<button type="button" on:click={() => (view = 'partners')} class="px-3.5 py-1.5 rounded-full font-medium transition {view === 'partners' ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-50 shadow-sm' : 'text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200'}">{$i18n.t('Anthropic & Partners')}</button>
			<button type="button" on:click={enterCommunity} class="px-3.5 py-1.5 rounded-full font-medium transition {view === 'community' ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-50 shadow-sm' : 'text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200'}">{$i18n.t('Community')}</button>
		</div>
		{#if view === 'partners'}
			<div class="inline-flex items-center rounded-full bg-gray-100 dark:bg-gray-850 p-0.5 text-xs" role="group" aria-label={$i18n.t('Filter connectors')}>
				{#each [{ id: 'all', label: $i18n.t('All') }, { id: 'connected', label: $i18n.t('Connected') }, { id: 'not', label: $i18n.t('Not connected') }] as f (f.id)}
					<button type="button" aria-pressed={statusFilter === f.id} on:click={() => (statusFilter = f.id)} class="px-2.5 py-1 rounded-full font-medium transition {statusFilter === f.id ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-50 shadow-sm' : 'text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200'}">{f.label}</button>
				{/each}
			</div>
		{/if}
	</div>

	<!-- honesty banner: attached ≠ live in OpenClaw -->
	{#if attachedEnabled > 0}
		<div class="rounded-xl border border-amber-200 dark:border-amber-900 bg-amber-50 dark:bg-amber-950/40 px-3 py-2.5 mb-4">
			<div class="flex flex-wrap items-center gap-2">
				<svg class="size-4 text-amber-500 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /></svg>
				<span class="text-xs font-medium text-amber-700 dark:text-amber-300 flex-1 min-w-[12rem]">{$i18n.t('{{count}} connector(s) connected — not yet live in OpenClaw.', { count: attachedEnabled })}</span>
				<button type="button" on:click={previewSync} disabled={previewing} class="min-h-[32px] px-3 rounded-lg text-xs font-medium border border-amber-300 dark:border-amber-800 text-amber-700 dark:text-amber-300 hover:bg-amber-100 dark:hover:bg-amber-900/40 disabled:opacity-40 transition">{previewing ? $i18n.t('Previewing…') : $i18n.t('Preview sync')}</button>
				<button type="button" on:click={applySync} disabled={applying} title={$i18n.t('Writes the previewed config to the OpenClaw mounts. Server-gated by HARVIS_OPENCLAW_SYNC.')} class="min-h-[32px] px-3 rounded-lg text-xs font-medium bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-40 transition">{applying ? $i18n.t('Applying…') : $i18n.t('Apply')}</button>
			</div>
			{#if syncPreview}
				<div class="mt-2 text-[11px] text-amber-800 dark:text-amber-200">{$i18n.t('Dry run — {{count}} connection(s) would be written to {{file}} (sync flag {{state}}).', { count: syncPreview?.mcp?.count ?? 0, file: syncPreview?.mcp?.target_file ?? 'openclaw.json', state: syncPreview?.enabled ? 'ON' : 'OFF' })}</div>
			{/if}
			{#if applyNote}<div class="mt-2 text-[11px] text-green-700 dark:text-green-400">✓ {applyNote}</div>{/if}
			{#if applyError}<div class="mt-2 text-[11px] text-red-600 dark:text-red-400">✕ {applyError}</div>{/if}
		</div>
	{/if}

	{#if view === 'partners'}
		<!-- POPULAR row -->
		{#if popular.length && !query.trim()}
			<div class="mb-5">
				<div class="text-[11px] font-semibold uppercase tracking-wide text-gray-400 mb-2">{$i18n.t('Popular')}</div>
				<div class="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
					{#each popular as t (t.id)}
						{@const conn = connFor(t)}
						<button type="button" on:click={() => openDetail(t)} class="flex items-center gap-2.5 rounded-2xl border border-gray-200/80 dark:border-gray-800 bg-white dark:bg-gray-900 px-3 py-2.5 text-left hover:border-gray-300 dark:hover:border-gray-700 transition">
							<div class="shrink-0 size-8 grid place-items-center rounded-lg bg-gray-50 dark:bg-gray-800/70 border border-gray-200/70 dark:border-gray-700/60"><ConnectorLogo id={t.id} size="size-5" /></div>
							<div class="min-w-0 flex-1 text-sm font-medium text-gray-900 dark:text-gray-100 truncate">{t.name}</div>
							{#if conn}
								<svg class="size-4 text-emerald-500 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m5 13 4 4L19 7" /></svg>
							{:else}
								<svg class="size-4 text-gray-400 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg>
							{/if}
						</button>
					{/each}
				</div>
			</div>
		{/if}

		<!-- curated card grid -->
		<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
			{#each visiblePartners as t (t.id)}
				{@const conn = connFor(t)}
				<button type="button" on:click={() => openDetail(t)} class="text-left rounded-2xl border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-950 p-3.5 hover:border-gray-300 dark:hover:border-gray-700 transition flex flex-col gap-2">
					<div class="flex items-start gap-2.5">
						<div class="shrink-0 size-9 grid place-items-center rounded-lg bg-gray-50 dark:bg-gray-800/70 border border-gray-200/70 dark:border-gray-700/60"><ConnectorLogo id={t.id} size="size-5" /></div>
						<div class="min-w-0 flex-1">
							<div class="flex items-center gap-1.5">
								<span class="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">{t.name}</span>
								<span class="shrink-0 text-[9px] font-mono px-1 py-0.5 rounded bg-gray-100 dark:bg-gray-850 text-gray-400" title={$i18n.t('Model Context Protocol')}>MCP</span>
							</div>
							<div class="text-xs text-gray-500 mt-0.5 line-clamp-2">{t.blurb ?? t.description}</div>
						</div>
						{#if conn}
							<span class="shrink-0 inline-flex items-center gap-1 text-[11px] font-medium {conn.enabled ? 'text-emerald-500' : 'text-gray-400'}"><span class="size-1.5 rounded-full {conn.enabled ? 'bg-emerald-500' : 'bg-gray-400'}"></span>{conn.enabled ? $i18n.t('On') : $i18n.t('Off')}</span>
						{:else}
							<span class="shrink-0 size-7 grid place-items-center rounded-lg text-gray-400 border border-gray-200 dark:border-gray-700"><svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg></span>
						{/if}
					</div>
					{#if t.needs_secret}
						<div class="flex items-center gap-1.5 text-[11px] text-amber-600 dark:text-amber-400">
							<svg class="size-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></svg>
							{$i18n.t('Needs an API key — connects limited.')}
						</div>
					{/if}
				</button>
			{:else}
				<div class="col-span-full text-sm text-gray-500 py-8 text-center">{loaded ? $i18n.t('No connectors match your search.') : $i18n.t('Loading catalog…')}</div>
			{/each}
		</div>
	{:else}
		<!-- Community = live MCP registry browse -->
		<div class="text-[11px] font-semibold uppercase tracking-wide text-gray-400 mb-2">{$i18n.t('From the MCP registry')}</div>
		{#if registryLoading && !registryItems.length}
			<div class="text-sm text-gray-500 py-6 text-center">{$i18n.t('Searching the MCP registry…')}</div>
		{:else if registryItems.length}
			<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
				{#each registryItems as it, ri (`${it.id}::${ri}`)}
					<button type="button" on:click={() => openRegistry(it)} class="text-left rounded-2xl border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-950 p-3.5 hover:border-gray-300 dark:hover:border-gray-700 transition flex flex-col gap-2">
						<div class="flex items-start gap-2.5">
							<div class="shrink-0 size-9 grid place-items-center rounded-lg bg-gray-50 dark:bg-gray-800/70 border border-gray-200/70 dark:border-gray-700/60"><ConnectorLogo id={'custom-url'} size="size-5" /></div>
							<div class="min-w-0 flex-1">
								<div class="flex items-center gap-1.5">
									<span class="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">{it.name}</span>
									<span class="shrink-0 text-[10px] px-1.5 py-0.5 rounded-full bg-gray-100 dark:bg-gray-850 text-gray-500">{$i18n.t('Community')}</span>
								</div>
								<div class="text-xs text-gray-500 mt-0.5 line-clamp-2">{it.description}</div>
							</div>
							<span class="shrink-0 size-7 grid place-items-center rounded-lg text-gray-400 border border-gray-200 dark:border-gray-700"><svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg></span>
						</div>
						<span class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-850 text-gray-400 self-start">{it.transport}</span>
					</button>
				{/each}
			</div>
		{:else if registryError}
			<div class="text-sm text-gray-400 py-6 text-center">{$i18n.t('MCP registry unreachable — check back shortly.')}</div>
		{:else}
			<div class="text-sm text-gray-400 py-6 text-center">{registryLoadedOnce ? $i18n.t('No registry matches for this search.') : $i18n.t('Loading the registry…')}</div>
		{/if}
	{/if}
</div>

<!-- ── detail slide-over ──────────────────────────────────────────────────── -->
{#if selected}
	<button type="button" class="fixed inset-0 z-40 bg-black/40 cursor-default" on:click={closeDetail} transition:fade={{ duration: 150 }} aria-label={$i18n.t('Close')}></button>
	<aside class="fixed right-0 top-0 z-50 h-full w-full sm:w-[420px] bg-white dark:bg-gray-950 border-l border-gray-200 dark:border-gray-800 shadow-2xl overflow-y-auto" transition:fly={{ x: 420, duration: 200 }}>
		<div class="p-5">
			<div class="flex items-start gap-3">
				<div class="shrink-0 size-12 grid place-items-center rounded-xl bg-gray-50 dark:bg-gray-800/70 border border-gray-200/70 dark:border-gray-700/60"><ConnectorLogo id={selected.id} size="size-6" /></div>
				<div class="min-w-0 flex-1">
					<div class="text-lg font-semibold text-gray-900 dark:text-gray-50">{selected.name}</div>
					<div class="text-sm text-gray-500">{selected.description ?? selected.blurb ?? ''}</div>
				</div>
				<button type="button" on:click={closeDetail} aria-label={$i18n.t('Close')} class="shrink-0 size-8 grid place-items-center rounded-lg text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-850 transition"><svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18" /></svg></button>
			</div>

			<!-- status + primary action -->
			<div class="mt-4 flex items-center gap-2">
				{#if selConn}
					<span class="inline-flex items-center gap-1.5 text-xs font-medium {selConn.enabled ? 'text-emerald-500' : 'text-gray-400'}"><span class="size-1.5 rounded-full {selConn.enabled ? 'bg-emerald-500' : 'bg-gray-400'}"></span>{selConn.enabled ? $i18n.t('Connected · On') : $i18n.t('Connected · Off')}</span>
				{:else}
					<span class="inline-flex items-center gap-1.5 text-xs font-medium text-gray-400"><span class="size-1.5 rounded-full bg-gray-300 dark:bg-gray-600"></span>{$i18n.t('Not connected')}</span>
				{/if}
				<div class="flex-1"></div>
				{#if selConn}
					<button type="button" on:click={() => toggle(selConn)} disabled={busyConnId === selConn.id} class="h-8 px-3 rounded-full text-xs font-medium border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-850 disabled:opacity-40 transition">{selConn.enabled ? $i18n.t('Turn off') : $i18n.t('Turn on')}</button>
				{:else}
					<button type="button" on:click={() => attach(selected)} disabled={attaching || (selNeedsConfig && !selReady)} class="h-8 px-4 rounded-full text-xs font-medium bg-gray-900 text-white hover:bg-gray-800 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white disabled:opacity-40 transition">{attaching ? $i18n.t('Connecting…') : selected.needs_secret ? $i18n.t('Connect (limited)') : selNeedsConfig ? $i18n.t('Connect') : $i18n.t('Connect')}</button>
				{/if}
			</div>

			<div class="mt-5 space-y-4 text-sm">
				{#if selected.needs_secret}
					<div class="rounded-lg border border-amber-200 dark:border-amber-900 bg-amber-50 dark:bg-amber-950/40 px-3 py-2 text-[12px] text-amber-700 dark:text-amber-300">{$i18n.t('This connector needs an API key. Harvis connects it limited and does not store the key yet (pending review).')}</div>
				{/if}

				<!-- inline config (custom BYO + templates with required fields) -->
				{#if !selConn && selNeedsConfig}
					<div class="space-y-2">
						<div class="text-[11px] font-semibold uppercase tracking-wide text-gray-400">{$i18n.t('Setup')}</div>
						{#if isCustom(selected)}
							<input bind:value={customName} placeholder={$i18n.t('Connector name')} class="w-full rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent px-3 py-2 text-sm outline-none focus:border-gray-400 dark:focus:border-gray-600" />
						{/if}
						{#if isCustom(selected) && selected.id === 'custom-url' && (selected.transports?.length ?? 0) > 1}
							<select bind:value={customTransport} class="w-full rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent dark:bg-gray-950 px-3 py-2 text-sm outline-none focus:border-gray-400 dark:focus:border-gray-600">
								{#each selected.transports as tr}<option value={tr}>{tr}</option>{/each}
							</select>
						{/if}
						{#each selected.fields ?? [] as f (f.key)}
							<div>
								<label class="text-[11px] text-gray-500" for={`conn-${selected.id}-${f.key}`}>{f.label}{f.required ? ' *' : ''}</label>
								<input id={`conn-${selected.id}-${f.key}`} bind:value={fieldValues[f.key]} placeholder={f.placeholder ?? ''} class="w-full rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent px-3 py-2 text-sm outline-none focus:border-gray-400 dark:focus:border-gray-600 font-mono" />
								{#if f.help}<div class="text-[10px] text-gray-400 mt-0.5">{f.help}</div>{/if}
							</div>
						{/each}
					</div>
				{/if}

				{#if (selected.tools ?? []).length}
					<div>
						<div class="text-[11px] font-semibold uppercase tracking-wide text-gray-400 mb-1.5">{$i18n.t('Capabilities')}</div>
						<div class="flex flex-wrap gap-1.5">
							{#each selected.tools as tool}<span class="text-xs px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-850 text-gray-600 dark:text-gray-300" title={tool.desc}>{tool.name}</span>{/each}
						</div>
					</div>
				{:else if selected.tools_note}
					<div class="text-[12px] text-gray-500">{selected.tools_note}</div>
				{/if}

				<div class="grid grid-cols-2 gap-3">
					<div>
						<div class="text-[11px] font-semibold uppercase tracking-wide text-gray-400 mb-1">{$i18n.t('Transport')}</div>
						<div class="text-gray-700 dark:text-gray-200 text-[13px] font-mono">{selConn?.transport ?? selected.transport}</div>
					</div>
					<div>
						<div class="text-[11px] font-semibold uppercase tracking-wide text-gray-400 mb-1">{$i18n.t('Protocol')}</div>
						<div class="text-gray-700 dark:text-gray-200 text-[13px]">{$i18n.t('MCP (Model Context Protocol)')}</div>
					</div>
				</div>

				<div class="text-[11px] text-gray-400">{$i18n.t('Connecting saves a connection. It goes live for agents after an explicit OpenClaw sync (see the banner).')}</div>

				{#if selConn}
					<div class="flex pt-1">
						<div class="flex-1"></div>
						<button type="button" on:click={() => detach(selConn)} disabled={busyConnId === selConn.id} class="h-8 px-3 rounded-lg text-xs font-medium text-red-500 hover:bg-red-50 dark:hover:bg-red-950/40 disabled:opacity-40 transition">{$i18n.t('Disconnect')}</button>
					</div>
				{/if}
			</div>
		</div>
	</aside>
{/if}
