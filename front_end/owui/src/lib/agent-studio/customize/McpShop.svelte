<script lang="ts">
	// Connectors directory (Claude-directory style) — human-facing "Connectors"
	// over the EXISTING MCP endpoints (the protocol IS MCP; only the vocabulary
	// changed): GET /api/owui/mcp/templates (catalog) + /api/owui/mcp/connections
	// CRUD (mcp_servers table). One-click connect writes a connection row;
	// connectors flagged needs_secret connect as 'limited' (the pending_review
	// credential hard gate stands — no key is ever collected or stored here).
	// Connecting does NOT make a connector live in OpenClaw: the honesty banner
	// below links the explicit, flag-gated sync preview/apply. Cards carry the
	// catalog's `publisher` tier and group under "Anthropic & Partners"
	// (reference + partner) vs "Community" (everything else) — pure client
	// grouping over the same list. Mirrors the Integrations catalog pattern
	// (search + category chips + card grid).
	import { createEventDispatcher, getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import ConnectorLogo from './ConnectorLogo.svelte';

	export let mode: 'full' | 'dock' = 'full';
	export let token = '';

	const i18n: any = getContext('i18n');
	const dispatch = createEventDispatcher();

	let templates: any[] = [];
	let categories: { id: string; label: string }[] = [];
	let conns: any[] = [];
	let loaded = false;

	// Bindable so hosts (ConnectorsPanel's Popular row) can drive the search.
	export let query = '';
	let activeCat = 'all';

	// per-card inline config (templates with required fields can't one-click)
	let expandedId: string | null = null;
	let fieldValues: Record<string, string> = {};
	let attachingId: string | null = null;
	let busyConnId: string | null = null;
	// Registry "Add" prefill — overrides the BYO card's connection name/transport
	// so the saved row keeps the registry entry's identity. Cleared on card switch.
	let prefillName: string | null = null;
	let prefillTransport: string | null = null;

	// ── live MCP registry (metadata-only; backend proxy, fail-closed) ──────
	let registryItems: any[] = [];
	let registryError = false;
	let registryLoading = false;
	let registryTimer: ReturnType<typeof setTimeout> | null = null;
	let registrySeq = 0;

	const fetchRegistry = async (q: string) => {
		const seq = ++registrySeq;
		registryLoading = true;
		const r = await fetch(`/api/owui/mcp/registry?q=${encodeURIComponent(q)}&limit=12`, {
			headers: authHeaders()
		})
			.then((x) => (x.ok ? x.json() : null))
			.catch(() => null);
		if (seq !== registrySeq) return; // stale response
		registryLoading = false;
		registryItems = r?.items ?? [];
		registryError = !r || !!r?.error;
	};

	// Debounce lives in a plain function so the $: statement only depends on
	// `query` — referencing registryTimer/registrySeq directly in a reactive
	// block would make its own writes re-trigger it (update-depth loop).
	const scheduleRegistry = (raw: string) => {
		if (registryTimer) clearTimeout(registryTimer);
		const q = raw.trim();
		if (q) {
			registryTimer = setTimeout(() => fetchRegistry(q), 350);
		} else {
			registrySeq++; // invalidate any in-flight fetch
			registryItems = [];
			registryError = false;
			registryLoading = false;
		}
	};
	$: scheduleRegistry(query);

	// "Add" from the registry → prefill the EXISTING BYO confirm flow (no
	// auto-connect, no package execution): url entries open the custom-url
	// card with the URL filled in; package-only entries open custom-stdio
	// with the connection name filled in. The user still confirms.
	const addFromRegistry = (item: any) => {
		const targetId = item.url ? 'custom-url' : 'custom-stdio';
		fieldValues = item.url ? { url: item.url } : {};
		prefillName = item.name || item.id || null;
		prefillTransport = item.url ? item.transport || null : null;
		expandedId = targetId;
		activeCat = 'all';
		query = ''; // clear the filter so the BYO card is guaranteed visible
		setTimeout(() => {
			document
				.getElementById(`mcpshop-card-${targetId}`)
				?.scrollIntoView({ behavior: 'smooth', block: 'center' });
		}, 50);
	};

	// OpenClaw sync honesty banner
	let syncPreview: any = null;
	let previewing = false;
	let applying = false;
	let applyNote = '';
	let applyError = '';

	const authHeaders = (): Record<string, string> => ({ authorization: `Bearer ${token}` });

	const loadTemplates = async () => {
		const r = await fetch('/api/owui/mcp/templates', { headers: authHeaders() })
			.then((x) => (x.ok ? x.json() : null))
			.catch(() => null);
		templates = r?.templates ?? [];
		categories = r?.categories ?? [];
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

	// Shop attaches use the template name as the connection name (upsert-keyed
	// per user), so attached state is a name match against saved connections.
	const connFor = (t: any) => conns.find((c) => c.name === t.name) ?? null;

	$: filtered = templates.filter((t) => {
		if (activeCat !== 'all' && t.category !== activeCat) return false;
		const q = query.trim().toLowerCase();
		if (!q) return true;
		return [t.name, t.blurb, t.description, t.category, ...(t.tools ?? []).map((x: any) => x.name)]
			.filter(Boolean)
			.join(' ')
			.toLowerCase()
			.includes(q);
	});
	$: attachedEnabled = conns.filter((c) => c.enabled).length;

	// Publisher tiering (Claude-directory style): reference + partner cards sit
	// under "Anthropic & Partners"; everything else (community/byo/unlabelled)
	// under "Community". Client-side grouping only — same list, same endpoints.
	const isOfficial = (t: any) => t.publisher === 'reference' || t.publisher === 'partner';
	$: publisherGroups = [
		{ id: 'official', label: 'Anthropic & Partners', items: filtered.filter(isOfficial) },
		{ id: 'community', label: 'Community', items: filtered.filter((t) => !isOfficial(t)) }
	].filter((g) => g.items.length > 0);

	const requiredFields = (t: any) => (t.fields ?? []).filter((f: any) => f.required);
	const fieldsReady = (t: any) =>
		requiredFields(t).every((f: any) => (fieldValues[f.key] ?? '').trim());

	const buildBody = (t: any) => {
		const transport = prefillTransport ?? t.transport ?? 'stdio';
		const body: any = { name: prefillName ?? t.name, transport };
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
		if (attachingId) return;
		if (expandedId !== t.id) {
			// Switching cards: drop the other card's field values AND any registry
			// prefill — otherwise an abandoned registry "Add" would rename an
			// unrelated one-click connect (buildBody reads prefillName).
			fieldValues = {};
			prefillName = null;
			prefillTransport = null;
		}
		if (requiredFields(t).length && (expandedId !== t.id || !fieldsReady(t))) {
			// needs config → open the card's inline form first
			expandedId = t.id;
			return;
		}
		attachingId = t.id;
		const savedName = prefillName ?? t.name;
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
		attachingId = null;
		if (res) {
			expandedId = null;
			fieldValues = {};
			prefillName = null;
			prefillTransport = null;
			toast.success(
				t.needs_secret
					? $i18n.t('"{{name}}" connected (limited — no credentials stored).', { name: savedName })
					: $i18n.t('"{{name}}" connected.', { name: savedName })
			);
			await loadConns();
			dispatch('changed');
		}
	};

	const toggle = async (c: any) => {
		busyConnId = c.id;
		await fetch(`/api/owui/mcp/connections/${c.id}/toggle`, {
			method: 'POST',
			headers: authHeaders()
		}).catch(() => {});
		busyConnId = null;
		await loadConns();
		dispatch('changed');
	};
	const detach = async (c: any) => {
		busyConnId = c.id;
		await fetch(`/api/owui/mcp/connections/${c.id}`, {
			method: 'DELETE',
			headers: authHeaders()
		}).catch(() => {});
		busyConnId = null;
		await loadConns();
		dispatch('changed');
	};

	const previewSync = async () => {
		previewing = true;
		syncPreview = await fetch('/api/owui/openclaw/sync/preview', { headers: authHeaders() })
			.then((x) => (x.ok ? x.json() : null))
			.catch(() => null);
		previewing = false;
	};
	// Explicit, human-triggered apply — server-side HARD gate (HARVIS_OPENCLAW_SYNC);
	// a 403 with the honest reason is surfaced verbatim. Never called automatically.
	const applySync = async () => {
		if (applying) return;
		applying = true;
		applyNote = '';
		applyError = '';
		const r = await fetch('/api/owui/openclaw/sync/apply', {
			method: 'POST',
			headers: authHeaders()
		})
			.then(async (x) => ({ ok: x.ok, body: await x.json().catch(() => null) }))
			.catch(() => ({ ok: false, body: null }));
		applying = false;
		if (r.ok) applyNote = r.body?.note ?? $i18n.t('Applied.');
		else applyError = r.body?.detail ?? $i18n.t('Apply failed.');
	};

	// Neutral badges — the transport label itself conveys the value; no
	// color-coding by transport (avoids a second, unrelated splash of color).
	const badgeClass = (_transport: string) => 'bg-gray-100 dark:bg-gray-850 text-gray-500 dark:text-gray-400';
	const focusRing =
		'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-400 dark:focus-visible:ring-gray-500 focus-visible:ring-offset-1 dark:focus-visible:ring-offset-gray-950';
</script>

<div class="w-full {mode === 'full' ? 'max-w-4xl mx-auto' : ''} space-y-3">
	<!-- search + category chips (mirrors the Integrations catalog filter) -->
	<div class="flex flex-col sm:flex-row sm:items-center gap-2">
		<div class="relative flex-1">
			<svg class="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
			<input
				bind:value={query}
				placeholder={$i18n.t('Search connectors…')}
				aria-label={$i18n.t('Search connectors')}
				class="w-full min-h-[44px] rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 pl-9 pr-3 text-sm outline-none focus:border-gray-400 dark:focus:border-gray-500 {focusRing}"
			/>
		</div>
		<div class="flex flex-wrap gap-1.5" role="group" aria-label={$i18n.t('Filter by category')}>
			{#each [{ id: 'all', label: $i18n.t('All') }, ...categories] as cat (cat.id)}
				<button
					type="button"
					aria-pressed={activeCat === cat.id}
					on:click={() => (activeCat = cat.id)}
					class="min-h-[44px] px-3 rounded-full text-xs font-medium border transition {focusRing} {activeCat === cat.id
						? 'border-gray-300 dark:border-gray-600 bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-50'
						: 'border-gray-200 dark:border-gray-800 text-gray-500 dark:text-gray-400 hover:border-gray-300 dark:hover:border-gray-700'}"
					>{$i18n.t(cat.label)}</button
				>
			{/each}
		</div>
	</div>

	<!-- honesty banner: attached ≠ live. Preview is a dry run; Apply is flag-gated. -->
	{#if attachedEnabled > 0}
		<div class="rounded-xl border border-amber-200 dark:border-amber-900 bg-amber-50 dark:bg-amber-950/40 px-3 py-2.5">
			<div class="flex flex-wrap items-center gap-2">
				<svg class="size-4 text-amber-500 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /></svg>
				<span class="text-xs font-medium text-amber-700 dark:text-amber-300 flex-1 min-w-[12rem]">
					{$i18n.t('{{count}} connector(s) connected — not yet live in OpenClaw.', { count: attachedEnabled })}
				</span>
				<button
					type="button"
					on:click={previewSync}
					disabled={previewing}
					class="min-h-[44px] px-3 rounded-lg text-xs font-medium border border-amber-300 dark:border-amber-800 text-amber-700 dark:text-amber-300 hover:bg-amber-100 dark:hover:bg-amber-900/40 disabled:opacity-40 transition {focusRing}"
					>{previewing ? $i18n.t('Previewing…') : $i18n.t('Preview sync')}</button
				>
				<button
					type="button"
					on:click={applySync}
					disabled={applying}
					title={$i18n.t('Writes the previewed config to the OpenClaw mounts. Server-gated by HARVIS_OPENCLAW_SYNC.')}
					class="min-h-[44px] px-3 rounded-lg text-xs font-medium bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-40 transition {focusRing}"
					>{applying ? $i18n.t('Applying…') : $i18n.t('Apply')}</button
				>
			</div>
			{#if syncPreview}
				<div class="mt-2 rounded-lg bg-white/60 dark:bg-gray-950/40 border border-amber-200/60 dark:border-amber-900/60 px-2.5 py-2 space-y-1">
					<div class="text-[11px] text-amber-800 dark:text-amber-200 font-medium">
						{$i18n.t('Dry run — {{count}} connection(s) would be written to {{file}} (sync flag {{state}}).', {
							count: syncPreview?.mcp?.count ?? 0,
							file: syncPreview?.mcp?.target_file ?? 'openclaw.json',
							state: syncPreview?.enabled ? 'ON' : 'OFF'
						})}
					</div>
					{#each syncPreview?.notes ?? [] as n}
						<div class="text-[11px] text-amber-700/80 dark:text-amber-300/80">· {n}</div>
					{/each}
				</div>
			{/if}
			{#if applyNote}
				<div class="mt-2 text-[11px] text-green-700 dark:text-green-400">✓ {applyNote}</div>
			{/if}
			{#if applyError}
				<div class="mt-2 text-[11px] text-red-600 dark:text-red-400">✕ {applyError}</div>
			{/if}
		</div>
	{/if}

	<!-- Publisher-tiered directory: "Anthropic & Partners" vs "Community" groups
	     over the same filtered list (client grouping only). -->
	{#each publisherGroups as g (g.id)}
	<div>
		<div class="flex items-center gap-2 mb-1.5 mt-1">
			<div class="text-xs font-semibold uppercase tracking-wide text-gray-400">{$i18n.t(g.label)}</div>
			<div class="flex-1 h-px bg-gray-100 dark:bg-gray-850" aria-hidden="true"></div>
		</div>
		<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
		{#each g.items as t (t.id)}
			{@const conn = connFor(t)}
			{@const byo = t.category === 'custom'}
			<div
				id={`mcpshop-card-${t.id}`}
				class="rounded-2xl border bg-white dark:bg-gray-950 p-3 flex flex-col gap-2 transition {byo
					? 'border-dashed border-gray-300 dark:border-gray-700'
					: 'border-gray-100 dark:border-gray-850 hover:border-gray-300 dark:hover:border-gray-700'}"
			>
				<div class="flex items-start justify-between gap-2">
					<div class="min-w-0 flex items-start gap-2.5">
						<div class="shrink-0 grid place-items-center size-9 rounded-lg bg-gray-100 dark:bg-gray-800/70 border border-gray-200/70 dark:border-gray-700/60">
							<ConnectorLogo id={t.id} />
						</div>
						<div class="min-w-0">
							<div class="text-sm font-medium text-gray-800 dark:text-gray-100 truncate">{t.name}</div>
							<div class="text-xs text-gray-500 mt-0.5 line-clamp-2">{t.blurb ?? t.description}</div>
						</div>
					</div>
					<div class="shrink-0 flex items-center gap-1">
						<!-- Protocol badge (Claude-style): the connector speaks MCP under the hood. -->
						<span class="text-[10px] font-mono px-1.5 py-0.5 rounded border border-gray-200 dark:border-gray-800 text-gray-400" title={$i18n.t('Model Context Protocol')}>MCP</span>
						<span class="text-[10px] font-mono px-1.5 py-0.5 rounded {badgeClass(t.transport)}">{t.transport}</span>
					</div>
				</div>
				{#if t.needs_secret}
					<div class="flex items-center gap-1.5 text-[11px] text-amber-600 dark:text-amber-400">
						<svg class="size-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></svg>
						{$i18n.t('Needs an API key — connects limited, no key stored (pending review).')}
					</div>
				{/if}

				{#if expandedId === t.id && !conn}
					<!-- inline config for templates with required fields (incl. BYO tiles) -->
					<div class="space-y-1.5">
						{#each t.fields ?? [] as f (f.key)}
							<div>
								<label class="text-[11px] text-gray-500" for={`mcpshop-${t.id}-${f.key}`}>{f.label}{f.required ? ' *' : ''}</label>
								<input
									id={`mcpshop-${t.id}-${f.key}`}
									bind:value={fieldValues[f.key]}
									placeholder={f.placeholder ?? ''}
									class="w-full min-h-[44px] rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent px-3 text-sm outline-none focus:border-gray-400 dark:focus:border-gray-500 font-mono {focusRing}"
								/>
								{#if f.help}<div class="text-[10px] text-gray-400 mt-0.5">{f.help}</div>{/if}
							</div>
						{/each}
					</div>
				{/if}

				<div class="mt-auto pt-1">
					{#if conn}
						<div class="flex items-center gap-1.5">
							<span class="flex-1 inline-flex items-center gap-1.5 text-xs font-medium {conn.enabled ? 'text-green-600 dark:text-green-400' : 'text-gray-400'}">
								<span class="size-1.5 rounded-full {conn.enabled ? 'bg-green-500' : 'bg-gray-400'}" aria-hidden="true"></span>
								{conn.enabled ? $i18n.t('Connected · On') : $i18n.t('Connected · Off')}
							</span>
							<button
								type="button"
								on:click={() => toggle(conn)}
								disabled={busyConnId === conn.id}
								class="min-h-[44px] px-3 rounded-lg text-xs font-medium border border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-850 disabled:opacity-40 transition {focusRing}"
								>{conn.enabled ? $i18n.t('Turn off') : $i18n.t('Turn on')}</button
							>
							<button
								type="button"
								on:click={() => detach(conn)}
								disabled={busyConnId === conn.id}
								aria-label={$i18n.t('Disconnect {{name}}', { name: t.name })}
								class="min-h-[44px] min-w-[44px] inline-flex items-center justify-center rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/40 disabled:opacity-40 transition {focusRing}"
							>
								<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m2 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" /></svg>
							</button>
						</div>
					{:else}
						<button
							type="button"
							on:click={() => attach(t)}
							disabled={attachingId === t.id || (expandedId === t.id && !fieldsReady(t))}
							class="w-full min-h-[44px] rounded-lg text-sm font-medium transition disabled:opacity-40 {focusRing} {t.needs_secret
								? 'border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300 hover:bg-amber-100 dark:hover:bg-amber-900/40'
								: 'border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 text-gray-800 dark:text-gray-100 hover:bg-gray-100 dark:hover:bg-gray-800'}"
						>
							{#if attachingId === t.id}{$i18n.t('Connecting…')}
							{:else if expandedId === t.id}{$i18n.t('Confirm connect')}
							{:else if t.needs_secret}{$i18n.t('Connect (limited)')}
							{:else if requiredFields(t).length}{$i18n.t('Configure & connect')}
							{:else}{$i18n.t('Connect')}{/if}
						</button>
					{/if}
				</div>
			</div>
		{/each}
		</div>
	</div>
	{:else}
		<div class="text-xs text-gray-500 py-3 text-center">
			{loaded ? $i18n.t('No connectors match your search.') : $i18n.t('Loading catalog…')}
		</div>
	{/each}

	<!-- Live MCP registry results (metadata-only; backend proxy is fail-closed).
	     Only rendered while a search query is active — never blocks the catalog. -->
	{#if query.trim()}
		<div>
			<div class="flex items-center gap-2 mb-1.5 mt-1">
				<div class="text-xs font-semibold uppercase tracking-wide text-gray-400">{$i18n.t('From the MCP registry')}</div>
				<div class="flex-1 h-px bg-gray-100 dark:bg-gray-850" aria-hidden="true"></div>
			</div>
			{#if registryLoading && !registryItems.length}
				<div class="text-xs text-gray-500 py-2">{$i18n.t('Searching the MCP registry…')}</div>
			{:else if registryItems.length}
				<div class="space-y-1.5">
					{#each registryItems as it, ri (`${it.id}::${ri}`)}
						<div class="rounded-xl border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-950 px-3 py-2 flex items-center gap-2.5">
							<div class="shrink-0 grid place-items-center size-8 rounded-lg bg-gray-100 dark:bg-gray-800/70 border border-gray-200/70 dark:border-gray-700/60">
								<ConnectorLogo id={'custom-url'} size="size-4" />
							</div>
							<div class="min-w-0 flex-1">
								<div class="text-sm font-medium text-gray-800 dark:text-gray-100 truncate">{it.name}</div>
								<div class="text-xs text-gray-500 truncate">{it.description}</div>
							</div>
							<span class="shrink-0 text-[10px] font-mono px-1.5 py-0.5 rounded {badgeClass(it.transport)}">{it.transport}</span>
							<button
								type="button"
								on:click={() => addFromRegistry(it)}
								class="shrink-0 min-h-[36px] px-3 rounded-lg text-xs font-medium border border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-850 transition {focusRing}"
								>{$i18n.t('Add')}</button
							>
						</div>
					{/each}
				</div>
			{:else if registryError}
				<div class="text-xs text-gray-400 py-2">
					{$i18n.t('MCP registry unreachable — showing built-in catalog only')}
				</div>
			{:else}
				<div class="text-xs text-gray-400 py-2">
					{$i18n.t('No registry matches for this search.')}
				</div>
			{/if}
		</div>
	{/if}
</div>
