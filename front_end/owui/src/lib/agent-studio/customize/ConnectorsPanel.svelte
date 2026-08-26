<script lang="ts">
	// Plugins — the storefront for external tools & data. Everything here speaks MCP;
	// this surface is the human-facing directory over the EXISTING endpoints:
	//   GET  /api/owui/mcp/templates    — installable catalog + link-out directory
	//                                     (`plugins` + `sections`; see mcp_catalog.py)
	//   GET  /api/owui/mcp/connections  — the user's saved connections (+ CRUD)
	//   GET  /api/owui/mcp/registry     — the live MCP registry (Community browse)
	// One-click connect writes a connection row; a connector that needs a key
	// collects it in the Setup block and posts it under `credentials`, which the
	// backend seals with the house Fernet cipher and unseals only when the
	// sandbox container starts (plugins/mcp/credentials.py). BYO and registry
	// connectors can add arbitrary environment variables the same way, so a
	// vendor the catalog has never heard of works like a first-class one.
	// Adding a registry/custom connector reuses the SAME connect flow — nothing
	// auto-connects. Connecting ≠ live in OpenClaw: the honesty banner links the
	// explicit, flag-gated sync. Replaces the old dense grid + McpShop embed with
	// the marketplace card design + a click-through detail panel.
	import { getContext, onMount, createEventDispatcher } from 'svelte';
	import { page } from '$app/stores';
	import { fly, fade } from 'svelte/transition';
	import { toast } from 'svelte-sonner';
	import ConnectorLogo from './ConnectorLogo.svelte';

	export let mode: 'full' | 'dock' = 'full';
	export let token = '';

	const i18n: any = getContext('i18n');

	let templates: any[] = [];
	// The storefront: `plugins` = installable connectors + link-out directory entries,
	// `sections` = their display order. Both come from the same /templates call, which
	// still returns `templates` for the connect flow — see mcp_catalog.py.
	let plugins: any[] = [];
	let sections: any[] = [];
	let conns: any[] = [];
	let loaded = false;
	// failed fetch ≠ empty result — a dead backend must not render as an empty
	// catalog or "0 connected" (null from the loaders below = request failed)
	let templatesError = false;
	let connsError = false;

	let query = '';
	let view: 'directory' | 'community' = 'directory';
	let statusFilter: 'all' | 'connected' | 'not' = 'all';
	let createOpen = false;
	// Sections start open (a directory you have to unfold is a directory you don't read).
	let collapsed: Record<string, boolean> = {};

	// detail slide-over — a template (catalog / custom / registry-derived) + form
	let selected: any = null;
	let fieldValues: Record<string, string> = {};
	// Secret values for the open connector — posted once, never read back.
	let credValues: Record<string, string> = {};
	// Free-form environment for BYO / registry connectors the catalog does not
	// describe. `secret` decides whether the value is sealed or stored plain.
	let extraVars: { key: string; value: string; secret: boolean }[] = [];
	let customName = '';
	let customTransport = 'sse';
	let attaching = false;
	let busyConnId: string | null = null;

	const authHeaders = (): Record<string, string> => ({ authorization: `Bearer ${token}` });

	const loadTemplates = async () => {
		const r = await fetch('/api/owui/mcp/templates', { headers: authHeaders() })
			.then((x) => (x.ok ? x.json() : null))
			.catch(() => null);
		templatesError = r === null;
		templates = r?.templates ?? [];
		plugins = r?.plugins ?? [];
		sections = r?.sections ?? [];
	};
	const loadConns = async () => {
		const r = await fetch('/api/owui/mcp/connections', { headers: authHeaders() })
			.then((x) => (x.ok ? x.json() : null))
			.catch(() => null);
		connsError = r === null;
		conns = r?.items ?? [];
	};

	onMount(async () => {
		if (!token) token = localStorage.getItem('token') || '';
		await Promise.all([loadTemplates(), loadConns(), previewSync()]);
		loaded = true;
	});

	// Attaches upsert on the template name, so name is the join key.
	const connFor = (t: any) => conns.find((c) => c.name === (t?.connName ?? t?.name)) ?? null;

	// ── the directory ─────────────────────────────────────────────────────────
	// Three connect stories, decided by the backend (mcp_catalog.py):
	//   install      — Harvis runs the server itself; Connect works here and now.
	//   remote_oauth — a vendor-hosted MCP endpoint. Connect saves the URL; the
	//                  Authorize button then runs the OAuth 2.1 + PKCE sign-in and
	//                  stores the token. Two steps because only the second one can
	//                  send you to the vendor, and only you can sign in there.
	//   external     — no MCP server; a directory entry that links to the vendor.
	// Missing `connect` is treated as install so BYO/registry entries keep Connect.
	const connectMode = (t: any): string => t?.connect ?? 'install';
	const canConnect = (t: any) => connectMode(t) !== 'external';
	const isDirectoryOnly = (t: any) => !canConnect(t);
	const isRemote = (t: any) => connectMode(t) === 'remote_oauth';

	// Tool names are indicative only: the real list comes from `tools/list` on connect.
	// Installable entries carry {name, desc}; directory entries carry bare strings.
	const toolName = (x: any) => (typeof x === 'string' ? x : x?.name ?? '');
	const toolDesc = (x: any) => (typeof x === 'string' ? '' : x?.desc ?? '');

	// `query` and `conns` are read INSIDE this statement on purpose — routing them
	// through a helper would hide them from Svelte's dependency tracking and leave
	// the list stale after a search keystroke or a connect.
	$: q = query.trim().toLowerCase();
	$: visiblePlugins = plugins.filter((t) => {
		const hay = `${t.name} ${t.blurb ?? t.description ?? ''} ${t.vendor ?? ''}`.toLowerCase();
		if (q && !hay.includes(q)) return false;
		if (statusFilter === 'all') return true;
		const connected = !!conns.find((c) => c.name === (t.connName ?? t.name));
		return statusFilter === 'connected' ? connected : !connected;
	});
	// A connection whose name matches no catalog entry — anything added through
	// "Add → custom server", or attached under a name you chose. Without this it
	// would vanish from the list the moment it was created, and the Connected
	// filter would read empty while the sync banner counted it.
	$: orphanConns = conns
		.filter((c) => !plugins.some((p) => (p.connName ?? p.name) === c.name))
		.map((c) => ({
			id: `conn:${c.id}`,
			name: c.name,
			connName: c.name,
			blurb: c.command ?? c.url ?? '',
			// Not shown anywhere — ConnectorLogo reads the host out of it to find a mark
			// for a connector that has no catalog entry and therefore no `brand`.
			url: c.url ?? '',
			section: 'yours',
			// It exists, so Connect is meaningless — the detail panel offers Turn on/off.
			connect: 'install',
			transport: c.transport
		}))
		.filter((t) => {
			if (q && !`${t.name} ${t.blurb}`.toLowerCase().includes(q)) return false;
			return statusFilter !== 'not';
		});

	// Section order comes from the server; empty sections drop out entirely.
	// "Your connectors" is prepended because it's the one section about *your* state.
	$: directorySections = [
		{ id: 'yours', label: 'Your connectors', items: orphanConns },
		...sections.map((s) => ({ ...s, items: visiblePlugins.filter((p) => p.section === s.id) }))
	].filter((s) => s.items.length);
	$: directoryCount = visiblePlugins.length + orphanConns.length;

	// In Settings the directory reads as a list of navigable rows (one per
	// category) rather than an unfolded grid, so sections start folded there.
	// Guarded by a one-shot flag — this assigns `collapsed`, which the sections
	// themselves read, and an unguarded version would fight the user's clicks.
	let dockCollapseInit = false;
	$: if (mode === 'dock' && loaded && !dockCollapseInit && directorySections.length) {
		collapsed = Object.fromEntries(directorySections.map((s) => [s.id, true]));
		dockCollapseInit = true;
	}

	$: customTemplates = templates.filter((t) => t.category === 'custom');
	$: attachedEnabled = conns.filter((c) => c.enabled).length;

	// The Plugins/Skills switch is a page-level control: only show it on the full-page
	// Connectors route, not when this panel is embedded in Settings or Customize.
	$: showTabs = ($page?.url?.pathname ?? '').startsWith('/harvis/agent-studio/mcp-shop');

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
	const credsFor = (t: any) => t?.credentials ?? [];
	const fieldsReady = (t: any) =>
		requiredFields(t).every((f: any) => (fieldValues[f.key] ?? '').trim()) &&
		credsFor(t).every((c: any) => (credValues[c.key] ?? '').trim());
	const isCustom = (t: any) => t?.category === 'custom' || t?.__registry;

	const buildBody = (t: any) => {
		// A hosted connector carries its own endpoint — there is nothing to fill in,
		// which is why its card goes straight from Connect to Authorize.
		if (isRemote(t)) {
			return {
				name: t.connName ?? t.name,
				transport: t.transport ?? 'streamable-http',
				url: t.mcp_url,
				auth_method: 'oauth'
			};
		}
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
		// Secrets are sealed server-side; anything left unmarked is plain config.
		const credentials: Record<string, string> = {};
		const env: Record<string, string> = {};
		for (const c of credsFor(t)) {
			const v = (credValues[c.key] ?? '').trim();
			if (v) credentials[c.key] = v;
		}
		for (const row of extraVars) {
			const k = row.key.trim();
			const v = row.value.trim();
			if (!k || !v) continue;
			if (row.secret) credentials[k] = v;
			else env[k] = v;
		}
		if (Object.keys(env).length) body.env = env;
		if (Object.keys(credentials).length) body.credentials = credentials;
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
					? $i18n.t('"{{name}}" connected — key stored encrypted.', { name: savedName })
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
	// ── does it actually work? ────────────────────────────────────────────────
	// Saved ≠ reachable. Probe connects for real and lists tools, so the panel can
	// report what the server said rather than what the row claims.
	let probeResult: any = null;
	let probing = false;
	let authorizing = false;

	const probeConn = async (c: any) => {
		if (probing) return;
		probing = true;
		probeResult = await fetch(`/api/owui/mcp/connections/${c.id}/probe`, {
			method: 'POST',
			headers: authHeaders()
		})
			.then((x) => x.json())
			.catch((e) => ({ ok: false, error: `${e}` }));
		probing = false;
		await loadConns();
	};

	// The vendor's sign-in happens in a popup we do not control, so we watch the
	// row instead of the window: `authorized` flips server-side when the callback
	// lands. Polling the state we care about beats trusting a cross-origin window.
	const waitForAuthorization = async (id: string) => {
		for (let i = 0; i < 150; i++) {
			await new Promise((r) => setTimeout(r, 2000));
			await loadConns();
			if (conns.find((c) => `${c.id}` === `${id}`)?.authorized) return true;
			if (!authorizing) return false;
		}
		return false;
	};

	const authorizeConn = async (c: any) => {
		if (authorizing) return;
		authorizing = true;
		probeResult = null;
		const r = await fetch(`/api/owui/mcp/connections/${c.id}/authorize`, {
			method: 'POST',
			headers: authHeaders()
		})
			.then(async (x) => ({ ok: x.ok, body: await x.json().catch(() => null) }))
			.catch(() => ({ ok: false, body: null }));
		if (!r.ok || !r.body?.authorize_url) {
			authorizing = false;
			toast.error(r.body?.detail ?? $i18n.t('Could not start authorization.'));
			return;
		}
		window.open(r.body.authorize_url, 'harvis-mcp-auth', 'width=520,height=720');
		const ok = await waitForAuthorization(c.id);
		authorizing = false;
		if (ok) {
			toast.success($i18n.t('"{{name}}" authorized.', { name: c.name }));
			await probeConn(c);
			dispatchChanged();
		}
	};

	const deauthorizeConn = async (c: any) => {
		busyConnId = c.id;
		await fetch(`/api/owui/mcp/connections/${c.id}/authorize`, {
			method: 'DELETE',
			headers: authHeaders()
		}).catch(() => {});
		busyConnId = null;
		probeResult = null;
		await loadConns();
	};

	const dispatch = createEventDispatcher();
	const dispatchChanged = () => dispatch('changed');

	// ── Engine sync ───────────────────────────────────────────────────────────
	// Saved in Harvis ≠ live in an engine. The dry-run preview is fetched on mount
	// so this panel can tell the truth BEFORE offering a control: applying is
	// server-gated (HARVIS_OPENCLAW_SYNC) and 403s when the flag is off, so the
	// Apply button is not rendered at all in that case — a button that can only
	// ever error is the same defect as a Connect button that cannot connect.
	// The engine rows come from the backend, which knows that OpenClaw is the only
	// engine with a write target today (see _engine_targets in mcp_wizard.py).
	let syncPreview: any = null;
	let previewing = false;
	let syncOpen = false;
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
	$: syncEngines = (syncPreview?.engines ?? []) as any[];
	$: syncReady = syncEngines.filter((e) => e.status === 'ready').length;
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
		probeResult = null;
		fieldValues = {};
		credValues = {};
		extraVars = [];
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
		credValues = {};
		extraVars = [];
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
		credValues = {};
		extraVars = [];
		customName = it.name || '';
		customTransport = it.transport || 'sse';
	};
	const closeDetail = () => {
		selected = null;
		probeResult = null;
		authorizing = false;
	};

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
	$: selNeedsConfig = selected
		? (selected.fields ?? []).some((f) => f.required) ||
			(selected.credentials ?? []).length > 0 ||
			isCustom(selected)
		: false;
	// Reads credValues / extraVars directly so Svelte tracks them — a helper call
	// would leave Connect disabled after typing a key.
	$: selReqOk = selected
		? (selected.fields ?? []).filter((f) => f.required).every((f) => (fieldValues[f.key] ?? '').trim()) &&
			(selected.credentials ?? []).every((c) => (credValues[c.key] ?? '').trim()) &&
			extraVars.every((r) => !r.key.trim() || !!r.value.trim())
		: false;
	$: selReady = selected ? (isCustom(selected) ? !!customName.trim() && selReqOk : selReqOk) : false;
</script>

<div class="w-full {mode === 'full' ? 'max-w-4xl mx-auto' : ''}">
	<!-- Plugins | Skills — the two halves of "what your agents can do". Page-level, so
	     it only appears on the full-page route (see showTabs). -->
	{#if showTabs}
		<div class="flex justify-center mb-5">
			<div class="inline-flex items-center rounded-lg bg-gray-100 dark:bg-gray-850 p-0.5 text-sm">
				<span class="px-4 py-1.5 rounded-lg font-medium bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-50 shadow-sm" aria-current="page">{$i18n.t('Plugins')}</span>
				<a href="/harvis/agent-studio/skills" class="px-4 py-1.5 rounded-lg font-medium text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200 transition">{$i18n.t('Skills')}</a>
			</div>
		</div>
	{/if}

	<!-- top bar: title + search + quick actions -->
	<div class="flex flex-wrap items-start justify-between gap-3 mb-1">
		<div class="min-w-[15rem] flex-1">
			<h1 class="{mode === 'full' ? 'text-2xl' : 'text-lg'} font-semibold text-gray-900 dark:text-gray-50">{mode === 'full' ? $i18n.t('Plugins') : $i18n.t('Connectors')}</h1>
			<p class="text-sm text-gray-500 mt-1">{mode === 'full' ? $i18n.t('Work with Harvis across your favorite tools. Plugins speak MCP, and work across Harvis and its agents.') : $i18n.t('Manage the tools and data your agents can reach.')}</p>
		</div>
		<div class="flex items-center gap-1 shrink-0">
			<div class="relative">
				<svg class="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
				<input
					bind:value={query}
					placeholder={$i18n.t('Search plugins')}
					aria-label={$i18n.t('Search plugins')}
					class="w-52 sm:w-60 h-9 rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 pl-9 pr-3 text-sm outline-none focus:border-gray-400 dark:focus:border-gray-600 transition"
				/>
			</div>
			<button type="button" on:click={() => { loadTemplates(); loadConns(); if (view === 'community') fetchRegistry(query.trim()); }} title={$i18n.t('Refresh')} class="size-8 grid place-items-center rounded-lg text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-850 transition">
				<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.6-6.4M21 3v6h-6" /></svg>
			</button>
			<!-- Settings renders these two as rows at the bottom of the list instead —
			     a dropdown inside a settings pane is one layer of chrome too many. -->
			<div class="relative" class:hidden={mode !== 'full'}>
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

	<!-- view segmented control + status filter (full page only — in Settings the
	     registry is reached from a row, and the status filter is noise) -->
	<div class="flex items-center justify-between gap-2 mt-5 mb-4" class:hidden={mode !== 'full'}>
		<div class="inline-flex items-center rounded-lg bg-gray-100 dark:bg-gray-850 p-0.5 text-sm">
			<button type="button" on:click={() => (view = 'directory')} class="px-3.5 py-1.5 rounded-lg font-medium transition {view === 'directory' ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-50 shadow-sm' : 'text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200'}">{$i18n.t('Directory')}</button>
			<button type="button" on:click={enterCommunity} class="px-3.5 py-1.5 rounded-lg font-medium transition {view === 'community' ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-50 shadow-sm' : 'text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200'}">{$i18n.t('MCP registry')}</button>
		</div>
		{#if view === 'directory'}
			<div class="inline-flex items-center rounded-lg bg-gray-100 dark:bg-gray-850 p-0.5 text-xs" role="group" aria-label={$i18n.t('Filter connectors')}>
				{#each [{ id: 'all', label: $i18n.t('All') }, { id: 'connected', label: $i18n.t('Connected') }, { id: 'not', label: $i18n.t('Not connected') }] as f (f.id)}
					<button type="button" aria-pressed={statusFilter === f.id} on:click={() => (statusFilter = f.id)} class="px-2.5 py-1 rounded-lg font-medium transition {statusFilter === f.id ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-50 shadow-sm' : 'text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200'}">{f.label}</button>
				{/each}
			</div>
		{/if}
	</div>

	{#if mode !== 'full'}<div class="mt-5"></div>{/if}

	<!-- failed connections fetch: the connected/count state below would be a lie -->
	{#if connsError}
		<div class="rounded-xl border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-950/40 px-3 py-2.5 mb-4">
			<div class="flex flex-wrap items-center gap-2">
				<span class="text-xs font-medium text-red-600 dark:text-red-400 flex-1 min-w-[12rem]">{$i18n.t('Could not load your connections — the connected states shown may be wrong.')}</span>
				<button type="button" on:click={loadConns} class="min-h-[32px] px-3 rounded-lg text-xs font-medium border border-red-300 dark:border-red-800 text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-900/40 transition">{$i18n.t('Retry')}</button>
			</div>
		</div>
	{/if}

	<!-- Engine sync — saved in Harvis ≠ live in an engine. Neutral on purpose: this
	     is a state you act on, not a fault. Apply renders only when the server
	     actually permits it (see the script comment). -->
	{#if attachedEnabled > 0}
		<div class="rounded-xl border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900/40 px-3 py-2.5 mb-4">
			<div class="flex flex-wrap items-center gap-2">
				<svg class="size-4 text-gray-400 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3v6M15 3v6M7 9h10v4a5 5 0 0 1-10 0zM12 18v3" /></svg>
				<span class="text-xs flex-1 min-w-[13rem]">
					<span class="font-medium text-gray-700 dark:text-gray-200">{$i18n.t('Engine sync')}</span>
					<span class="text-gray-500 dark:text-gray-400">
						— {$i18n.t('{{count}} connector(s) saved in Harvis.', { count: attachedEnabled })}
						{#if !syncPreview}
							{previewing ? $i18n.t('Checking which engines can receive them…') : $i18n.t('Engine state unavailable.')}
						{:else if syncReady}
							{$i18n.t('{{ready}} of {{total}} engines can receive them.', { ready: syncReady, total: syncEngines.length })}
						{:else}
							{$i18n.t('No engine can receive them yet.')}
						{/if}
					</span>
				</span>
				<button type="button" on:click={() => (syncOpen = !syncOpen)} aria-expanded={syncOpen} class="min-h-[32px] px-3 rounded-lg text-xs font-medium border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-850 transition">{syncOpen ? $i18n.t('Hide engines') : $i18n.t('Engines')}</button>
				{#if syncPreview?.enabled}
					<button type="button" on:click={applySync} disabled={applying} title={$i18n.t('Writes the previewed config to the OpenClaw mounts.')} class="min-h-[32px] px-3 rounded-lg text-xs font-medium bg-gray-900 text-white hover:bg-gray-800 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white disabled:opacity-40 transition">{applying ? $i18n.t('Applying…') : $i18n.t('Apply')}</button>
				{/if}
			</div>

			{#if syncOpen}
				<div class="mt-3 space-y-2">
					{#each syncEngines as e (e.id)}
						<div class="flex items-start gap-2">
							<span class="mt-1.5 size-1.5 rounded-full shrink-0 {e.status === 'ready' ? 'bg-emerald-500' : 'bg-gray-300 dark:bg-gray-600'}"></span>
							<div class="min-w-0">
								<div class="text-[12px]">
									<span class="font-medium text-gray-700 dark:text-gray-200">{e.label}</span>
									<span class="text-gray-400"> · {e.status === 'ready' ? $i18n.t('ready') : e.status === 'blocked' ? $i18n.t('turned off on this server') : $i18n.t('no publish path yet')}</span>
								</div>
								<div class="text-[11px] text-gray-500 dark:text-gray-400">{e.note}</div>
							</div>
						</div>
					{/each}
					{#if syncPreview}
						<div class="text-[11px] text-gray-400 pt-0.5">{$i18n.t('Dry run — {{count}} connection(s) would be written to {{file}}.', { count: syncPreview?.mcp?.count ?? 0, file: syncPreview?.mcp?.target_file ?? 'openclaw.json' })}</div>
					{:else if !previewing}
						<div class="text-[11px] text-gray-400">{$i18n.t('Could not reach the sync preview.')} <button type="button" class="underline hover:text-gray-600 dark:hover:text-gray-200" on:click={previewSync}>{$i18n.t('Retry')}</button></div>
					{/if}
				</div>
			{/if}

			{#if applyNote}<div class="mt-2 text-[11px] text-emerald-600 dark:text-emerald-400">{applyNote}</div>{/if}
			{#if applyError}<div class="mt-2 text-[11px] text-red-500 dark:text-red-400">{applyError}</div>{/if}
		</div>
	{/if}

	{#if view === 'directory'}
		{#if !directorySections.length}
			<div class="text-sm text-gray-500 py-8 text-center">
				{#if templatesError}
					{$i18n.t('Could not load the plugin directory.')}
					<button type="button" class="ml-1 text-blue-600 dark:text-blue-400 hover:underline" on:click={() => { loadTemplates(); loadConns(); }}>{$i18n.t('Retry')}</button>
				{:else}
					{loaded ? $i18n.t('No plugins match your search.') : $i18n.t('Loading directory…')}
				{/if}
			</div>
		{/if}

		<!-- category sections, server-ordered; each row is [logo · name · tagline · glyph] -->
		{#each directorySections as sec (sec.id)}
			<section class={mode === 'full' ? 'mb-6' : ''}>
				<button
					type="button"
					on:click={() => (collapsed = { ...collapsed, [sec.id]: !collapsed[sec.id] })}
					aria-expanded={!collapsed[sec.id]}
					class="w-full flex items-center gap-2 text-left group {mode === 'full'
						? 'py-1.5'
						: 'py-3 border-b border-gray-100 dark:border-gray-850 px-2 -mx-2 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-900/60 transition'}"
				>
					<h2 class="{mode === 'full' ? 'text-[15px]' : 'text-sm'} font-semibold text-gray-900 dark:text-gray-100">{$i18n.t(sec.label)}</h2>
					<span class="text-xs text-gray-400">{sec.items.length}</span>
					{#if mode !== 'full'}<div class="flex-1"></div>{/if}
					<svg class="size-4 text-gray-400 transition-transform {collapsed[sec.id] ? '-rotate-90' : ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6" /></svg>
				</button>
				{#if sec.blurb && !collapsed[sec.id]}
					<p class="text-xs text-gray-500 mb-2 {mode === 'full' ? '' : 'mt-2'}">{sec.blurb}</p>
				{/if}
				{#if !collapsed[sec.id]}
					<div class="grid grid-cols-1 {mode === 'full' ? 'sm:grid-cols-2' : 'pl-2'} gap-x-6">
						{#each sec.items as t (t.id)}
							{@const conn = connFor(t)}
							<button type="button" on:click={() => openDetail(t)} class="w-full text-left flex items-center gap-3 py-2.5 border-b border-gray-100 dark:border-gray-850 hover:bg-gray-50/70 dark:hover:bg-gray-900/60 rounded-lg px-2 -mx-2 transition">
								<div class="shrink-0 size-9 grid place-items-center rounded-lg bg-gray-50 dark:bg-gray-800/70 border border-gray-200/70 dark:border-gray-700/60 overflow-hidden">
									<ConnectorLogo id={t.id} brand={t.brand} name={t.name} url={t.url ?? ''} size="size-5" />
								</div>
								<div class="min-w-0 flex-1">
									<div class="text-sm font-semibold text-gray-900 dark:text-gray-100 truncate">{t.name}</div>
									<div class="text-xs text-gray-500 truncate">{t.blurb ?? t.description ?? ''}</div>
								</div>
								{#if conn}
									<span class="shrink-0 inline-flex items-center gap-1 text-[11px] font-medium {conn.enabled ? 'text-emerald-500' : 'text-gray-400'}" title={conn.enabled ? $i18n.t('Connected · On') : $i18n.t('Connected · Off')}><span class="size-1.5 rounded-full {conn.enabled ? 'bg-emerald-500' : 'bg-gray-400'}"></span>{conn.enabled ? $i18n.t('On') : $i18n.t('Off')}</span>
								{:else if canConnect(t)}
									<!-- Harvis runs this one itself, so it can genuinely be added here. -->
									<svg class="size-4 shrink-0 text-gray-300 dark:text-gray-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
								{:else}
									<!-- Directory entry: the detail panel sends you to the vendor. -->
									<svg class="size-3.5 shrink-0 text-gray-300 dark:text-gray-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 4h6v6M20 4l-8.5 8.5M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4" /></svg>
								{/if}
							</button>
						{/each}
					</div>
				{/if}
			</section>
		{/each}

		<!-- Settings: the two actions that live in the Add dropdown on the full page,
		     as rows — same destinations, no dropdown. -->
		{#if mode !== 'full'}
			<button type="button" on:click={openCustom} class="w-full flex items-center gap-3 py-3 px-2 -mx-2 rounded-lg border-b border-gray-100 dark:border-gray-850 text-left hover:bg-gray-50 dark:hover:bg-gray-900/60 transition">
				<div class="shrink-0 size-9 grid place-items-center rounded-lg bg-gray-50 dark:bg-gray-800/70 border border-gray-200/70 dark:border-gray-700/60 text-gray-400">
					<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg>
				</div>
				<div class="min-w-0 flex-1">
					<div class="text-sm font-medium text-gray-900 dark:text-gray-100">{$i18n.t('Add custom connector')}</div>
					<div class="text-xs text-gray-500 truncate">{$i18n.t('Point Harvis at an MCP server you run')}</div>
				</div>
				<svg class="size-4 shrink-0 text-gray-300 dark:text-gray-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6" /></svg>
			</button>
			<button type="button" on:click={enterCommunity} class="w-full flex items-center gap-3 py-3 px-2 -mx-2 rounded-lg border-b border-gray-100 dark:border-gray-850 text-left hover:bg-gray-50 dark:hover:bg-gray-900/60 transition">
				<div class="shrink-0 size-9 grid place-items-center rounded-lg bg-gray-50 dark:bg-gray-800/70 border border-gray-200/70 dark:border-gray-700/60 text-gray-400">
					<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
				</div>
				<div class="min-w-0 flex-1">
					<div class="text-sm font-medium text-gray-900 dark:text-gray-100">{$i18n.t('Browse the MCP registry')}</div>
					<div class="text-xs text-gray-500 truncate">{$i18n.t('Search community-published MCP servers')}</div>
				</div>
				<svg class="size-4 shrink-0 text-gray-300 dark:text-gray-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6" /></svg>
			</button>
		{/if}
	{:else}
		<!-- Settings has no segmented control, so the registry needs its own way back. -->
		{#if mode !== 'full'}
			<button type="button" on:click={() => (view = 'directory')} class="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 mb-3 transition">
				<svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6" /></svg>
				{$i18n.t('Connectors')}
			</button>
		{/if}
		<!-- Community = live MCP registry browse -->
		<div class="text-[11px] font-semibold uppercase tracking-wide text-gray-400 mb-2">{$i18n.t('From the MCP registry')}</div>
		{#if registryLoading && !registryItems.length}
			<div class="text-sm text-gray-500 py-6 text-center">{$i18n.t('Searching the MCP registry…')}</div>
		{:else if registryItems.length}
			<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
				{#each registryItems as it, ri (`${it.id}::${ri}`)}
					<button type="button" on:click={() => openRegistry(it)} class="text-left rounded-2xl border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-950 p-3.5 hover:border-gray-300 dark:hover:border-gray-700 transition flex flex-col gap-2">
						<div class="flex items-start gap-2.5">
							<div class="shrink-0 size-9 grid place-items-center rounded-lg bg-gray-50 dark:bg-gray-800/70 border border-gray-200/70 dark:border-gray-700/60"><ConnectorLogo id={''} name={it.name} url={it.url ?? ''} size="size-5" /></div>
							<div class="min-w-0 flex-1">
								<div class="flex items-center gap-1.5">
									<span class="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">{it.name}</span>
									<span class="shrink-0 text-[10px] px-1.5 py-0.5 rounded-md bg-gray-100 dark:bg-gray-850 text-gray-500">{$i18n.t('Community')}</span>
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
				<div class="shrink-0 size-12 grid place-items-center rounded-xl bg-gray-50 dark:bg-gray-800/70 border border-gray-200/70 dark:border-gray-700/60 overflow-hidden"><ConnectorLogo id={selected.id} brand={selected.brand} name={selected.name} url={selected.url ?? ''} size="size-6" /></div>
				<div class="min-w-0 flex-1">
					<div class="text-lg font-semibold text-gray-900 dark:text-gray-50">{selected.name}</div>
					<div class="text-sm text-gray-500">{selected.description ?? selected.blurb ?? ''}</div>
				</div>
				<button type="button" on:click={closeDetail} aria-label={$i18n.t('Close')} class="shrink-0 size-8 grid place-items-center rounded-lg text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-850 transition"><svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18" /></svg></button>
			</div>

			<!-- status + primary action -->
			<div class="mt-4 flex flex-wrap items-center gap-2">
				{#if isDirectoryOnly(selected)}
					<!-- No Connect button on purpose: Harvis has no MCP OAuth client yet, so a
					     button here would fail. The honest action is the vendor's own page. -->
					<span class="shrink-0 inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-medium text-gray-400"><span class="size-1.5 rounded-full bg-gray-300 dark:bg-gray-600"></span>{$i18n.t('Not available in Harvis yet')}</span>
					{#if selected.homepage}
						<a href={selected.homepage} target="_blank" rel="noopener noreferrer" class="ml-auto shrink-0 h-8 px-4 inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg text-xs font-medium bg-gray-900 text-white hover:bg-gray-800 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white transition">
							{$i18n.t('Open')} {selected.vendor ?? selected.name}
							<svg class="size-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 4h6v6M20 4l-9 9" /></svg>
						</a>
					{/if}
				{:else if selConn}
					{#if selConn.auth_method === 'oauth' && !selConn.authorized}
						<span class="shrink-0 inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-medium text-amber-500"><span class="size-1.5 rounded-full bg-amber-500"></span>{$i18n.t('Needs authorization')}</span>
					{:else}
						<span class="shrink-0 inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-medium {selConn.enabled ? 'text-emerald-500' : 'text-gray-400'}"><span class="size-1.5 rounded-full {selConn.enabled ? 'bg-emerald-500' : 'bg-gray-400'}"></span>{selConn.enabled ? $i18n.t('Connected · On') : $i18n.t('Connected · Off')}</span>
					{/if}
				{:else}
					<span class="shrink-0 inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-medium text-gray-400"><span class="size-1.5 rounded-full bg-gray-300 dark:bg-gray-600"></span>{$i18n.t('Not connected')}</span>
				{/if}
				<!-- Directory-only entries already drew their own spacer and vendor link in the
				     branch above; they must NOT fall through to Connect/Turn on. -->
				{#if !isDirectoryOnly(selected)}
					<div class="ml-auto flex flex-wrap items-center justify-end gap-2">
					{#if selConn}
						<button type="button" on:click={() => probeConn(selConn)} disabled={probing} class="shrink-0 h-8 px-3 whitespace-nowrap rounded-lg text-xs font-medium border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-850 disabled:opacity-40 transition">{probing ? $i18n.t('Testing…') : $i18n.t('Test')}</button>
						{#if selConn.auth_method === 'oauth'}
							<button type="button" on:click={() => authorizeConn(selConn)} disabled={authorizing} class="shrink-0 h-8 px-3 whitespace-nowrap rounded-lg text-xs font-medium {selConn.authorized ? 'border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-850' : 'bg-gray-900 text-white hover:bg-gray-800 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white'} disabled:opacity-40 transition">{authorizing ? $i18n.t('Waiting…') : selConn.authorized ? $i18n.t('Re-authorize') : $i18n.t('Authorize')}</button>
						{/if}
						<button type="button" on:click={() => toggle(selConn)} disabled={busyConnId === selConn.id} class="shrink-0 h-8 px-3 whitespace-nowrap rounded-lg text-xs font-medium border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-850 disabled:opacity-40 transition">{selConn.enabled ? $i18n.t('Turn off') : $i18n.t('Turn on')}</button>
					{:else}
						<button type="button" on:click={() => attach(selected)} disabled={attaching || (selNeedsConfig && !selReady)} class="shrink-0 h-8 px-4 whitespace-nowrap rounded-lg text-xs font-medium bg-gray-900 text-white hover:bg-gray-800 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white disabled:opacity-40 transition">{attaching ? $i18n.t('Connecting…') : selected.needs_secret ? $i18n.t('Add key & connect') : $i18n.t('Connect')}</button>
					{/if}
					</div>
				{/if}
			</div>

			<div class="mt-5 space-y-4 text-sm">
				{#if selected.needs_secret}
					<div class="rounded-lg border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900/40 px-3 py-2 text-[12px] text-gray-600 dark:text-gray-300">{$i18n.t('This connector needs an API key. Enter it below — it is encrypted at rest and decrypted only when the server starts.')}</div>
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
						{#each selected.credentials ?? [] as c (c.key)}
							<div>
								<label class="text-[11px] text-gray-500" for={`conn-${selected.id}-cred-${c.key}`}
									>{c.label} <code class="text-[10px] font-mono text-gray-400">{c.key}</code></label
								>
								<input
									id={`conn-${selected.id}-cred-${c.key}`}
									type="password"
									autocomplete="new-password"
									spellcheck="false"
									bind:value={credValues[c.key]}
									placeholder={$i18n.t('Paste the value')}
									class="w-full rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent px-3 py-2 text-sm outline-none focus:border-gray-400 dark:focus:border-gray-600 font-mono"
								/>
							</div>
						{/each}

						{#each extraVars as row, i}
							<div class="flex items-center gap-2">
								<input
									bind:value={row.key}
									placeholder="ENV_NAME"
									spellcheck="false"
									class="w-2/5 rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent px-3 py-2 text-sm outline-none focus:border-gray-400 dark:focus:border-gray-600 font-mono"
								/>
								<input
									type={row.secret ? 'password' : 'text'}
									autocomplete="new-password"
									spellcheck="false"
									bind:value={row.value}
									placeholder={$i18n.t('Value')}
									class="flex-1 rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent px-3 py-2 text-sm outline-none focus:border-gray-400 dark:focus:border-gray-600 font-mono"
								/>
								<label class="flex items-center gap-1 text-[11px] text-gray-500 shrink-0" title={$i18n.t('Encrypt this value at rest')}>
									<input type="checkbox" bind:checked={row.secret} class="accent-gray-700" />
									{$i18n.t('Secret')}
								</label>
								<button type="button" on:click={() => (extraVars = extraVars.filter((_, j) => j !== i))} aria-label={$i18n.t('Remove')} class="shrink-0 text-gray-400 hover:text-red-500 transition">
									<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18" /></svg>
								</button>
							</div>
						{/each}
						<button
							type="button"
							on:click={() => (extraVars = [...extraVars, { key: '', value: '', secret: true }])}
							class="rounded-lg border border-dashed border-gray-300 dark:border-gray-700 px-3 py-1.5 text-[11px] text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 hover:border-gray-400 dark:hover:border-gray-600 transition"
							>+ {$i18n.t('Add environment variable')}</button
						>
						<div class="text-[10px] text-gray-400">
							{$i18n.t('Values marked secret are encrypted before storage and never shown again.')}
						</div>
					</div>
				{/if}

				<!-- Example prompts — what you'd actually say once this is connected. -->
				{#if (selected.prompts ?? []).length}
					<div>
						<div class="text-[11px] font-semibold uppercase tracking-wide text-gray-400 mb-1.5">{$i18n.t('Try asking')}</div>
						<div class="space-y-1.5">
							{#each selected.prompts as p}
								<div class="rounded-lg border border-gray-100 dark:border-gray-850 bg-gray-50/70 dark:bg-gray-900/60 px-3 py-2 text-[12px] text-gray-600 dark:text-gray-300">“{p}”</div>
							{/each}
						</div>
					</div>
				{/if}

				{#if (selected.tools ?? []).length}
					<div>
						<!-- "Typical" is the honest word: the real list comes from the server's
						     tools/list once connected, and vendors change it without notice. -->
						<div class="text-[11px] font-semibold uppercase tracking-wide text-gray-400 mb-1.5">{$i18n.t('Typical tools')}</div>
						<div class="flex flex-wrap gap-1.5">
							{#each selected.tools as tool}<span class="text-xs px-2 py-0.5 rounded-md bg-gray-100 dark:bg-gray-850 text-gray-600 dark:text-gray-300 font-mono" title={toolDesc(tool)}>{toolName(tool)}</span>{/each}
						</div>
					</div>
				{:else if selected.tools_note}
					<div class="text-[12px] text-gray-500">{selected.tools_note}</div>
				{/if}

				{#if isDirectoryOnly(selected)}
					{#if selected.mcp_url}
						<div>
							<div class="text-[11px] font-semibold uppercase tracking-wide text-gray-400 mb-1">{$i18n.t('MCP endpoint')}</div>
							<div class="text-gray-700 dark:text-gray-200 text-[12px] font-mono break-all">{selected.mcp_url}</div>
							<div class="text-[11px] text-gray-400 mt-1">{$i18n.t('This vendor publishes a remote MCP server. Harvis cannot sign in to it yet — that needs an OAuth client, which is not built. Set it up on the vendor\'s side for now.')}</div>
						</div>
					{:else}
						<div class="text-[11px] text-gray-400">{$i18n.t('No MCP server for this one yet. It is listed so you can find the official integration.')}</div>
					{/if}
				{:else}
					<div class="grid grid-cols-2 gap-3">
						<div>
							<div class="text-[11px] font-semibold uppercase tracking-wide text-gray-400 mb-1">{$i18n.t('Transport')}</div>
							<div class="text-gray-700 dark:text-gray-200 text-[13px] font-mono">{selConn?.transport ?? selected.transport ?? '—'}</div>
						</div>
						<div>
							<div class="text-[11px] font-semibold uppercase tracking-wide text-gray-400 mb-1">{$i18n.t('Protocol')}</div>
							<div class="text-gray-700 dark:text-gray-200 text-[13px]">{$i18n.t('MCP (Model Context Protocol)')}</div>
						</div>
					</div>

					<div class="text-[11px] text-gray-400">{$i18n.t('Connecting saves a connection. It reaches an agent only after an explicit engine sync — see Engine sync on the directory.')}</div>
				{/if}

				<!-- The way out to the vendor's own page — every card has one. -->
				{#if selected.homepage || selected.docs_url}
					<div class="flex flex-wrap items-center gap-x-4 gap-y-1 pt-1 border-t border-gray-100 dark:border-gray-850">
						{#if selected.homepage}
							<a href={selected.homepage} target="_blank" rel="noopener noreferrer" class="inline-flex items-center gap-1 text-[12px] text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 transition pt-2">
								{$i18n.t('Developed by')} {selected.vendor ?? selected.name}
								<svg class="size-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 4h6v6M20 4l-9 9" /></svg>
							</a>
						{/if}
						{#if selected.docs_url}
							<a href={selected.docs_url} target="_blank" rel="noopener noreferrer" class="inline-flex items-center gap-1 text-[12px] text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 transition pt-2">
								{$i18n.t('Documentation')}
								<svg class="size-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 4h6v6M20 4l-9 9" /></svg>
							</a>
						{/if}
					</div>
					<div class="text-[11px] text-gray-400">{$i18n.t('Third-party plugins are not built or reviewed by Harvis. Check what you are granting before you connect.')}</div>
				{/if}

				{#if selConn && authorizing}
					<div class="rounded-lg border border-amber-200 dark:border-amber-900/60 bg-amber-50 dark:bg-amber-950/30 px-3 py-2 text-[12px] text-amber-700 dark:text-amber-300">{$i18n.t('Finish signing in to {{vendor}} in the window that opened. This panel updates when it completes.', { vendor: selected.vendor ?? selected.name })}</div>
				{/if}

				{#if probeResult}
					<div class="rounded-lg border px-3 py-2 text-[12px] {probeResult.ok ? 'border-emerald-200 dark:border-emerald-900/60 bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300' : 'border-red-200 dark:border-red-900/60 bg-red-50 dark:bg-red-950/30 text-red-600 dark:text-red-300'}">
						{#if probeResult.ok}
							<div class="font-medium">{$i18n.t('Working — {{count}} tool(s).', { count: probeResult.tool_count })}</div>
							{#if probeResult.tools?.length}
								<div class="mt-1 opacity-80 break-words">{probeResult.tools.join(', ')}</div>
							{/if}
						{:else}
							<div>{probeResult.error}</div>
						{/if}
					</div>
				{/if}

				{#if selConn}
					<div class="flex flex-wrap items-center gap-2 pt-1">
						{#if selConn.authorized}
							<button type="button" on:click={() => deauthorizeConn(selConn)} disabled={busyConnId === selConn.id} class="shrink-0 h-8 px-3 whitespace-nowrap rounded-lg text-xs font-medium text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-850 disabled:opacity-40 transition">{$i18n.t('Sign out')}</button>
						{/if}
						<div class="flex-1"></div>
						<button type="button" on:click={() => detach(selConn)} disabled={busyConnId === selConn.id} class="shrink-0 h-8 px-3 whitespace-nowrap rounded-lg text-xs font-medium text-red-500 hover:bg-red-50 dark:hover:bg-red-950/40 disabled:opacity-40 transition">{$i18n.t('Disconnect')}</button>
					</div>
				{/if}
			</div>
		</div>
	</aside>
{/if}
