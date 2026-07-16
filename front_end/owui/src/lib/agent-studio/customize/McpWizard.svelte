<script lang="ts">
	// Guided MCP connection wizard (Phase 5): template → config → credentials →
	// permission preview → connection test → save. Saves through the EXISTING
	// /api/owui/mcp/connections endpoint (mcp_servers table) — no new storage.
	// Credential hard gate: fields flagged secret are never collected; the step
	// shows "credential storage pending review" instead. No secrets touch
	// localStorage and none are echoed back by any GET.
	import { createEventDispatcher, getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	export let token = '';

	const i18n: any = getContext('i18n');
	const dispatch = createEventDispatcher();

	const STEPS = ['Template', 'Configure', 'Credentials', 'Permissions', 'Test', 'Save'];
	let step = 0;

	let templates: any[] = [];
	let template: any = null;
	let name = '';
	let transport = 'stdio';
	let fieldValues: Record<string, string> = {};

	let testing = false;
	let testResult: any = null;
	let saving = false;

	onMount(async () => {
		const r = await fetch('/api/owui/mcp/templates', {
			headers: { authorization: `Bearer ${token}` }
		})
			.then((x) => (x.ok ? x.json() : null))
			.catch(() => null);
		templates = r?.templates ?? [];
	});

	const pickTemplate = (t: any) => {
		template = t;
		transport = t.transport ?? 'stdio';
		name = name || t.name;
		fieldValues = {};
		testResult = null;
		step = 1;
	};

	$: command =
		template?.command_template != null
			? (template.fields ?? []).reduce(
					(acc: string, f: any) => acc.replaceAll(`{${f.key}}`, (fieldValues[f.key] ?? '').trim()),
					template.command_template
				)
			: '';
	$: url = template?.command_template == null ? (fieldValues['url'] ?? '').trim() : '';
	$: configValid =
		!!name.trim() &&
		(template?.fields ?? []).every((f: any) => !f.required || (fieldValues[f.key] ?? '').trim());
	$: pendingCreds = (template?.credentials ?? []).filter((c: any) => c.secret);

	const runTest = async () => {
		testing = true;
		testResult = null;
		testResult = await fetch('/api/owui/mcp/test', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json', authorization: `Bearer ${token}` },
			body: JSON.stringify({ url: url || null, transport })
		})
			.then(async (x) => {
				const j = await x.json().catch(() => null);
				if (!x.ok) return { ok: false, testable: true, detail: j?.detail ?? 'Test failed.' };
				return j;
			})
			.catch(() => ({ ok: false, testable: true, detail: 'Test request failed.' }));
		testing = false;
	};

	const save = async () => {
		if (saving || !configValid) return;
		saving = true;
		const body: any = { name: name.trim(), transport };
		if (transport === 'stdio') body.command = command;
		else body.url = url;
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
		saving = false;
		if (res) {
			toast.success($i18n.t('Connection "{{name}}" saved.', { name: name.trim() }));
			dispatch('saved');
		}
	};
</script>

<div class="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 p-3 mb-3">
	<!-- stepper header -->
	<div class="flex items-center justify-between mb-3">
		<div class="flex items-center gap-1 overflow-x-auto">
			{#each STEPS as s, i}
				<button
					on:click={() => {
						if (i < step) step = i;
					}}
					class="shrink-0 flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium transition {i === step
						? 'bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900'
						: i < step
							? 'text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-850'
							: 'text-gray-400'}"
				>
					<span class="font-mono">{i + 1}</span>
					{$i18n.t(s)}
				</button>
				{#if i < STEPS.length - 1}
					<span class="shrink-0 text-gray-300 dark:text-gray-700 text-[10px]">›</span>
				{/if}
			{/each}
		</div>
		<button on:click={() => dispatch('close')} title={$i18n.t('Close')} class="shrink-0 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition">
			<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18" /></svg>
		</button>
	</div>

	{#if step === 0}
		<!-- 1 · template picker -->
		<div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
			{#each templates as t (t.id)}
				<button
					on:click={() => pickTemplate(t)}
					class="text-left rounded-xl border px-3 py-2.5 transition {template?.id === t.id
						? 'border-gray-400 dark:border-gray-500'
						: 'border-gray-100 dark:border-gray-850 hover:border-gray-300 dark:hover:border-gray-700'}"
				>
					<div class="text-sm font-medium text-gray-800 dark:text-gray-100">{t.name}</div>
					<div class="text-xs text-gray-500 mt-0.5">{t.description}</div>
					<div class="text-[10px] text-gray-400 mt-1 font-mono">{t.transport}</div>
				</button>
			{:else}
				<div class="text-xs text-gray-500 py-1">{$i18n.t('Loading templates…')}</div>
			{/each}
		</div>
	{:else if step === 1}
		<!-- 2 · config form -->
		<div class="space-y-2">
			<input
				bind:value={name}
				placeholder={$i18n.t('Connection name')}
				class="w-full rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent px-3 py-1.5 text-sm outline-none focus:border-gray-400 dark:focus:border-gray-500"
			/>
			{#if (template?.transports ?? []).length > 1}
				<select
					bind:value={transport}
					class="w-full rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent dark:bg-gray-950 px-3 py-1.5 text-sm outline-none focus:border-gray-400 dark:focus:border-gray-500"
				>
					{#each template.transports as tr}
						<option value={tr}>{tr}</option>
					{/each}
				</select>
			{/if}
			{#each template?.fields ?? [] as f (f.key)}
				<div>
					<label class="text-xs text-gray-500" for={`mcpw-${f.key}`}>{f.label}{f.required ? ' *' : ''}</label>
					<input
						id={`mcpw-${f.key}`}
						bind:value={fieldValues[f.key]}
						placeholder={f.placeholder ?? ''}
						class="w-full rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent px-3 py-1.5 text-sm outline-none focus:border-gray-400 dark:focus:border-gray-500 font-mono"
					/>
					{#if f.help}<div class="text-[11px] text-gray-400 mt-0.5">{f.help}</div>{/if}
				</div>
			{/each}
			{#if transport === 'stdio' && command}
				<div class="rounded-lg bg-gray-50 dark:bg-gray-900 border border-gray-100 dark:border-gray-850 px-3 py-2">
					<div class="text-[10px] uppercase tracking-wide text-gray-400 mb-0.5">{$i18n.t('Command preview')}</div>
					<code class="text-xs font-mono text-gray-700 dark:text-gray-300 break-all">{command}</code>
				</div>
			{/if}
		</div>
	{:else if step === 2}
		<!-- 3 · credentials (hard gate: no new secret storage) -->
		{#if pendingCreds.length}
			<div class="space-y-2">
				{#each pendingCreds as c (c.key)}
					<div class="rounded-lg border border-amber-200 dark:border-amber-900 bg-amber-50 dark:bg-amber-950/40 px-3 py-2.5">
						<div class="flex items-center gap-2">
							<svg class="size-4 text-amber-500 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></svg>
							<span class="text-sm font-medium text-amber-700 dark:text-amber-300">{c.label} <code class="text-[11px] font-mono">({c.key})</code></span>
						</div>
						<p class="text-xs text-amber-700/80 dark:text-amber-300/80 mt-1">
							{$i18n.t(
								'Credential storage for this template is pending review — Harvis will not store this secret yet. The connection is saved without it and the tool will be limited until credential support lands.'
							)}
						</p>
					</div>
				{/each}
			</div>
		{:else}
			<div class="text-sm text-gray-500 py-2">{$i18n.t('This template needs no credentials.')}</div>
		{/if}
	{:else if step === 3}
		<!-- 4 · permission preview -->
		{#if (template?.tools ?? []).length}
			<p class="text-xs text-gray-500 mb-2">{$i18n.t('Tools this server exposes to your agents:')}</p>
			<div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
				{#each template.tools as t (t.name)}
					<div class="rounded-xl border border-gray-100 dark:border-gray-850 px-3 py-2">
						<code class="text-xs font-mono text-gray-700 dark:text-gray-300">{t.name}</code>
						<div class="text-xs text-gray-500 mt-0.5">{t.desc}</div>
					</div>
				{/each}
			</div>
		{:else}
			<div class="text-sm text-gray-500 py-2">
				{template?.tools_note ?? $i18n.t('Tools are discovered from the server at connect time.')}
			</div>
		{/if}
	{:else if step === 4}
		<!-- 5 · connection test -->
		{#if transport === 'stdio'}
			<div class="text-sm text-gray-500 py-2">
				{$i18n.t('stdio servers run as a local process — there is no network handshake to test. You can save it directly.')}
			</div>
		{:else}
			<div class="flex items-center gap-2 mb-2">
				<button
					on:click={runTest}
					disabled={testing || !url}
					class="rounded-lg bg-gray-900 text-white hover:bg-gray-800 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white px-4 py-1.5 text-sm font-medium disabled:opacity-40"
					>{testing ? $i18n.t('Testing…') : $i18n.t('Run connection test')}</button
				>
				<code class="text-xs font-mono text-gray-500 truncate">{url}</code>
			</div>
			{#if testResult}
				<div class="rounded-lg border px-3 py-2 text-sm {testResult.ok
					? 'border-green-200 dark:border-green-900 text-green-700 dark:text-green-400'
					: 'border-red-200 dark:border-red-900 text-red-600 dark:text-red-400'}">
					{testResult.ok ? '✓' : '✕'}
					{testResult.detail}
					{#if testResult.status}<span class="text-xs opacity-70">(HTTP {testResult.status}{testResult.latency_ms != null ? ` · ${testResult.latency_ms}ms` : ''})</span>{/if}
				</div>
			{/if}
			<p class="text-[11px] text-gray-400 mt-2">
				{$i18n.t('Private, loopback and link-local addresses are blocked server-side.')}
			</p>
		{/if}
	{:else}
		<!-- 6 · review + save -->
		<div class="rounded-lg bg-gray-50 dark:bg-gray-900 border border-gray-100 dark:border-gray-850 px-3 py-2.5 space-y-1 text-sm">
			<div><span class="text-gray-400 text-xs">{$i18n.t('Name')}:</span> <span class="text-gray-800 dark:text-gray-100">{name}</span></div>
			<div><span class="text-gray-400 text-xs">{$i18n.t('Transport')}:</span> <code class="text-xs font-mono">{transport}</code></div>
			{#if transport === 'stdio'}
				<div><span class="text-gray-400 text-xs">{$i18n.t('Command')}:</span> <code class="text-xs font-mono break-all">{command}</code></div>
			{:else}
				<div><span class="text-gray-400 text-xs">URL:</span> <code class="text-xs font-mono break-all">{url}</code></div>
			{/if}
			{#if pendingCreds.length}
				<div class="text-xs text-amber-600 dark:text-amber-400">{$i18n.t('Saved without credentials (pending review).')}</div>
			{/if}
		</div>
		<p class="text-[11px] text-gray-400 mt-2">
			{$i18n.t('After saving you can enable, disable or remove it from the connections list.')}
		</p>
	{/if}

	<!-- footer nav -->
	{#if step > 0}
		<div class="flex justify-between items-center mt-3">
			<button
				on:click={() => (step = Math.max(0, step - 1))}
				class="rounded-lg px-3 py-1.5 text-sm text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-850"
				>{$i18n.t('Back')}</button
			>
			{#if step < STEPS.length - 1}
				<button
					on:click={() => (step = step + 1)}
					disabled={step === 1 && !configValid}
					class="rounded-lg bg-gray-900 text-white hover:bg-gray-800 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white px-4 py-1.5 text-sm font-medium disabled:opacity-40"
					>{$i18n.t('Continue')}</button
				>
			{:else}
				<button
					on:click={save}
					disabled={saving || !configValid}
					class="rounded-lg bg-gray-900 text-white hover:bg-gray-800 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white px-4 py-1.5 text-sm font-medium disabled:opacity-40"
					>{saving ? $i18n.t('Saving…') : $i18n.t('Save connection')}</button
				>
			{/if}
		</div>
	{/if}
</div>
