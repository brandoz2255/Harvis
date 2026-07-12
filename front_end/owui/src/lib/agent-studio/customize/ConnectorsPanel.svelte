<script lang="ts">
	// Connectors panel — the human-facing "Connectors" surface over the EXISTING
	// MCP endpoints (/api/owui/mcp/*; the protocol IS MCP — only the vocabulary
	// changes). Extracted from Customize.svelte's "MCP Connections" section so
	// the Settings modal, the Customize page and the mcp-shop surface share one
	// implementation: McpShop directory (primary) + guided wizard + quick-add +
	// the saved connections list.
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import McpWizard from './McpWizard.svelte';
	import McpShop from './McpShop.svelte';
	import ConnectorLogo from './ConnectorLogo.svelte';

	export let token = '';

	const i18n: any = getContext('i18n');

	// Guided setup (wizard) — the quick-add form below stays for power users.
	let showMcpWizard = false;

	let conns: any[] = [];
	let templates: any[] = [];

	// Claude-style manage view state: status filter pills + a query handle into
	// the embedded McpShop (Popular/table "Connect" drives the shop's search —
	// the shop's existing connect flow does the actual connecting, no dup wizard).
	let filter: 'all' | 'connected' | 'not' = 'all';
	let shopQuery = '';
	let shopEl: HTMLElement | null = null;
	let showConnForm = false;
	let cName = '';
	let cTransport = 'stdio';
	let cCommand = '';
	let cUrl = '';
	let savingConn = false;

	const loadConns = async () => {
		const r = await fetch('/api/owui/mcp/connections', {
			headers: { authorization: `Bearer ${token}` }
		})
			.then((x) => (x.ok ? x.json() : { items: [] }))
			.catch(() => ({ items: [] }));
		conns = r?.items ?? [];
	};
	const loadTemplates = async () => {
		const r = await fetch('/api/owui/mcp/templates', {
			headers: { authorization: `Bearer ${token}` }
		})
			.then((x) => (x.ok ? x.json() : null))
			.catch(() => null);
		templates = r?.templates ?? [];
	};

	const POPULAR_IDS = ['github', 'slack', 'notion'];
	$: popular = POPULAR_IDS.map((id) => templates.find((t) => t.id === id)).filter(Boolean);

	// Merged table rows: saved connections + catalog templates not yet connected
	// (shop attaches upsert on the template name, so name is the join key).
	// BYO custom tiles stay in the shop below — they aren't "a connector" yet.
	$: tableRows = [
		...conns.map((c) => ({
			kind: 'conn' as const,
			key: `c-${c.id}`,
			name: c.name,
			transport: c.transport,
			logoId: templates.find((t) => t.name === c.name)?.id ?? (c.name || '').toLowerCase(),
			conn: c,
			tpl: null as any
		})),
		...templates
			.filter((t) => t.category !== 'custom' && !conns.some((c) => c.name === t.name))
			.map((t) => ({
				kind: 'tpl' as const,
				key: `t-${t.id}`,
				name: t.name,
				transport: t.transport,
				logoId: t.id,
				conn: null as any,
				tpl: t
			}))
	];
	$: visibleRows =
		filter === 'all'
			? tableRows
			: tableRows.filter((r) => (filter === 'connected' ? r.kind === 'conn' : r.kind === 'tpl'));

	// "Connect" (Popular row / table) → drive the embedded shop's search to that
	// template and scroll there; the shop's existing card flow takes over.
	const connectTemplate = (t: any) => {
		shopQuery = t?.name ?? '';
		setTimeout(() => shopEl?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50);
	};

	const badgeClass = (transport: string) =>
		transport === 'stdio'
			? 'bg-gray-100 dark:bg-gray-850 text-gray-500 dark:text-gray-400'
			: 'bg-blue-50 dark:bg-blue-950/50 text-blue-600 dark:text-blue-400';
	const saveConn = async () => {
		if (!cName.trim() || savingConn) return;
		savingConn = true;
		const body: any = { name: cName.trim(), transport: cTransport };
		if (cTransport === 'stdio') body.command = cCommand.trim();
		else body.url = cUrl.trim();
		const res = await fetch('/api/owui/mcp/connections', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json', authorization: `Bearer ${token}` },
			body: JSON.stringify(body)
		})
			.then(async (x) => {
				if (!x.ok) throw (await x.json())?.detail ?? 'Failed';
				return x.json();
			})
			.catch((e) => {
				toast.error(`${e}`);
				return null;
			});
		savingConn = false;
		if (res) {
			cName = cCommand = cUrl = '';
			cTransport = 'stdio';
			showConnForm = false;
			await loadConns();
		}
	};
	const toggleConn = async (id: string) => {
		await fetch(`/api/owui/mcp/connections/${id}/toggle`, {
			method: 'POST',
			headers: { authorization: `Bearer ${token}` }
		}).catch(() => {});
		await loadConns();
	};
	const removeConn = async (id: string) => {
		await fetch(`/api/owui/mcp/connections/${id}`, {
			method: 'DELETE',
			headers: { authorization: `Bearer ${token}` }
		}).catch(() => {});
		conns = conns.filter((c) => c.id !== id);
	};

	onMount(async () => {
		if (!token) token = localStorage.getItem('token') || '';
		loadConns();
		loadTemplates();
	});
</script>

<div class="w-full">
	<div class="flex items-center justify-between gap-2 mb-1">
		<div class="flex items-center gap-2">
			<svg class="size-5 text-blue-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 2v6m6-6v6M5 8h14a2 2 0 0 1 2 2v2a7 7 0 0 1-7 7h-4a7 7 0 0 1-7-7v-2a2 2 0 0 1 2-2zM12 19v3" /></svg>
			<h2 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{$i18n.t('Connectors')}</h2>
		</div>
		<div class="flex items-center gap-1.5">
			<!-- Demoted to secondary — the directory grid below is the primary path. -->
			<button
				on:click={() => (showMcpWizard = !showMcpWizard)}
				class="inline-flex items-center gap-1.5 rounded-full border border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300 px-3 py-1.5 text-xs font-medium hover:bg-gray-100 dark:hover:bg-gray-850 transition"
			>
				<svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v3m6.4-.4-2.1 2.1M21 12h-3m.4 6.4-2.1-2.1M12 18v3m-6.4-.4 2.1-2.1M3 12h3m-.4-6.4 2.1 2.1" /></svg>
				{$i18n.t('Guided setup')}
			</button>
			<button
				on:click={() => (showConnForm = !showConnForm)}
				class="inline-flex items-center gap-1.5 rounded-full border border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300 px-3 py-1.5 text-xs font-medium hover:bg-gray-100 dark:hover:bg-gray-850 transition"
			>
				<svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg>
				{$i18n.t('Quick add')}
			</button>
		</div>
	</div>
	<p class="text-sm text-gray-500 mb-3">{$i18n.t('Connect apps and data sources to give your agents more tools. Connectors speak MCP (Model Context Protocol) under the hood.')}</p>

	<!-- status filter pills (Claude-style manage view) -->
	<div class="flex flex-wrap gap-1.5 mb-3" role="group" aria-label={$i18n.t('Filter connectors')}>
		{#each [{ id: 'all', label: $i18n.t('All') }, { id: 'connected', label: $i18n.t('Connected') }, { id: 'not', label: $i18n.t('Not connected') }] as f (f.id)}
			<button
				type="button"
				aria-pressed={filter === f.id}
				on:click={() => (filter = f.id as any)}
				class="px-3 py-1.5 rounded-full text-xs font-medium border transition {filter === f.id
					? 'border-blue-500 bg-blue-50 dark:bg-blue-950/50 text-blue-600 dark:text-blue-400'
					: 'border-gray-200 dark:border-gray-800 text-gray-500 dark:text-gray-400 hover:border-gray-300 dark:hover:border-gray-700'}"
				>{f.label}</button
			>
		{/each}
	</div>

	<!-- POPULAR — three well-known connectors, one click into the shop's connect flow -->
	{#if popular.length}
		<div class="mb-3">
			<div class="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-1.5">{$i18n.t('Popular')}</div>
			<div class="grid grid-cols-1 sm:grid-cols-3 gap-2">
				{#each popular as t (t.id)}
					{@const connected = conns.some((c) => c.name === t.name)}
					<div class="rounded-xl border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-950 px-3 py-2.5 flex items-center gap-2.5">
						<div class="shrink-0 grid place-items-center size-8 rounded-lg bg-gray-100 dark:bg-gray-800/70 border border-gray-200/70 dark:border-gray-700/60">
							<ConnectorLogo id={t.id} size="size-4" />
						</div>
						<div class="min-w-0 flex-1 text-sm font-medium text-gray-800 dark:text-gray-100 truncate">{t.name}</div>
						{#if connected}
							<span class="shrink-0 inline-flex items-center gap-1 text-xs font-medium text-green-600 dark:text-green-400">
								<svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 13 4 4L19 7" /></svg>
								{$i18n.t('Connected')}
							</span>
						{:else}
							<button
								type="button"
								on:click={() => connectTemplate(t)}
								class="shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium bg-blue-600 text-white hover:bg-blue-700 transition"
								>{$i18n.t('Connect')}</button
							>
						{/if}
					</div>
				{/each}
			</div>
		</div>
	{/if}

	<!-- main table: saved connections + catalog templates not yet connected -->
	<div class="rounded-xl border border-gray-100 dark:border-gray-850 overflow-hidden mb-3">
		<div class="overflow-x-auto">
			<table class="w-full text-sm">
				<thead>
					<tr class="text-left text-[11px] uppercase tracking-wide text-gray-400 border-b border-gray-100 dark:border-gray-850 bg-gray-50/60 dark:bg-gray-900/40">
						<th class="px-3 py-2 font-semibold">{$i18n.t('Connector')}</th>
						<th class="px-3 py-2 font-semibold">{$i18n.t('Type')}</th>
						<th class="px-3 py-2 font-semibold">{$i18n.t('Status')}</th>
					</tr>
				</thead>
				<tbody>
					{#each visibleRows as row (row.key)}
						<tr class="group border-b border-gray-50 dark:border-gray-900 last:border-0">
							<td class="px-3 py-2">
								<div class="flex items-center gap-2.5 min-w-0">
									<div class="shrink-0 grid place-items-center size-7 rounded-lg bg-gray-100 dark:bg-gray-800/70 border border-gray-200/70 dark:border-gray-700/60">
										<ConnectorLogo id={row.logoId} size="size-4" />
									</div>
									<span class="truncate font-medium text-gray-800 dark:text-gray-100">{row.name}</span>
								</div>
							</td>
							<td class="px-3 py-2 whitespace-nowrap">
								<span class="text-[10px] font-mono px-1.5 py-0.5 rounded border border-gray-200 dark:border-gray-800 text-gray-400 mr-1" title={$i18n.t('Model Context Protocol')}>MCP</span>
								<span class="text-[10px] font-mono px-1.5 py-0.5 rounded {badgeClass(row.transport)}">{row.transport}</span>
							</td>
							<td class="px-3 py-2 whitespace-nowrap">
								{#if row.conn}
									<div class="flex items-center gap-2">
										{#if row.conn.enabled}
											<span class="inline-flex items-center gap-1 text-xs font-medium text-green-600 dark:text-green-400">
												<svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 13 4 4L19 7" /></svg>
												{$i18n.t('Connected')}
											</span>
											<button
												type="button"
												on:click={() => toggleConn(row.conn.id)}
												class="text-[11px] text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition"
												>{$i18n.t('Turn off')}</button
											>
										{:else}
											<span class="text-xs font-medium text-gray-400">{$i18n.t('Off')}</span>
											<button
												type="button"
												on:click={() => toggleConn(row.conn.id)}
												class="text-[11px] text-blue-600 dark:text-blue-400 hover:underline transition"
												>{$i18n.t('Turn on')}</button
											>
										{/if}
										<button
											type="button"
											on:click={() => removeConn(row.conn.id)}
											title={$i18n.t('Delete')}
											class="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 transition"
										>
											<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m2 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" /></svg>
										</button>
									</div>
								{:else}
									<button
										type="button"
										on:click={() => connectTemplate(row.tpl)}
										class="px-2.5 py-1 rounded-lg text-xs font-medium border border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-850 transition"
										>{$i18n.t('Connect')}</button
									>
								{/if}
							</td>
						</tr>
					{:else}
						<tr>
							<td colspan="3" class="px-3 py-4 text-center text-xs text-gray-500">
								{filter === 'connected' ? $i18n.t('No connectors yet.') : $i18n.t('Nothing here.')}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</div>

	{#if showMcpWizard}
		<div class="mb-3">
			<McpWizard
				{token}
				on:saved={() => {
					showMcpWizard = false;
					loadConns();
				}}
				on:close={() => (showMcpWizard = false)}
			/>
		</div>
	{/if}

	{#if showConnForm}
		<div class="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 p-3 mb-3 space-y-2">
			<div class="flex gap-2">
				<input bind:value={cName} placeholder={$i18n.t('Connector name')} class="flex-1 rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent px-3 py-1.5 text-sm outline-none focus:border-blue-500" />
				<select bind:value={cTransport} class="rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent dark:bg-gray-950 px-3 py-1.5 text-sm outline-none focus:border-blue-500">
					<option value="stdio">stdio</option>
					<option value="sse">sse</option>
					<option value="streamable-http">streamable-http</option>
				</select>
			</div>
			{#if cTransport === 'stdio'}
				<input bind:value={cCommand} placeholder={$i18n.t('Command, e.g. npx -y @modelcontextprotocol/server-filesystem /path')} class="w-full rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent px-3 py-1.5 text-sm outline-none focus:border-blue-500 font-mono" />
			{:else}
				<input bind:value={cUrl} placeholder={$i18n.t('Server URL, e.g. https://host/sse')} class="w-full rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent px-3 py-1.5 text-sm outline-none focus:border-blue-500 font-mono" />
			{/if}
			<div class="flex justify-end gap-2">
				<button on:click={() => (showConnForm = false)} class="rounded-lg px-3 py-1.5 text-sm text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-850">{$i18n.t('Cancel')}</button>
				<button on:click={saveConn} disabled={savingConn || !cName.trim()} class="rounded-lg bg-blue-600 text-white px-4 py-1.5 text-sm font-medium hover:bg-blue-700 disabled:opacity-40">{savingConn ? $i18n.t('Saving…') : $i18n.t('Add')}</button>
			</div>
		</div>
	{/if}

	<!-- Browse section — the connector directory grid stays embedded here; the
	     Popular/table "Connect" buttons drive its search via bind:query.
	     on:changed keeps the manage table above in sync. -->
	{#if token}
		<div class="mt-1" bind:this={shopEl}>
			<div class="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-1.5">{$i18n.t('Browse connectors')}</div>
			<McpShop {token} bind:query={shopQuery} on:changed={loadConns} />
		</div>
	{/if}
</div>
