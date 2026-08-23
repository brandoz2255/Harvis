<script lang="ts">
	// Guided MCP connection wizard (Phase 5): template → config → credentials →
	// permission preview → connection test → save. Saves through the EXISTING
	// /api/owui/mcp/connections endpoint (mcp_servers table) — no new storage.
	// Secrets are collected on the Credentials step and posted once under
	// `credentials`; the backend seals them with the house Fernet cipher before
	// they reach the mcp_servers row and unseals them only when the sandbox
	// container is spawned. Nothing here touches localStorage, and a GET returns
	// a fixed mask rather than the value. Any server can be given extra
	// environment variables by hand, so a vendor the catalog has never heard of
	// works the same way as GitHub or Slack.
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
	// Secret values, held in component state until save and never read back.
	let credValues: Record<string, string> = {};
	// Free-form environment for a server the catalog does not describe — this is
	// what keeps the wizard vendor-agnostic instead of a fixed list.
	let extraVars: { key: string; value: string; secret: boolean }[] = [];

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
		credValues = {};
		extraVars = [];
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
	$: creds = template?.credentials ?? [];
	$: missingCreds = creds.filter((c: any) => !(credValues[c.key] ?? '').trim());
	$: storedSecretKeys = [
		...creds.filter((c: any) => (credValues[c.key] ?? '').trim()).map((c: any) => c.key),
		...extraVars.filter((r) => r.secret && r.key.trim() && r.value.trim()).map((r) => r.key.trim())
	];

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
		// Secret values go in `credentials` (sealed server-side); anything the user
		// marked non-secret is plain configuration and goes in `env`.
		const credentials: Record<string, string> = {};
		const env: Record<string, string> = {};
		for (const c of creds) {
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
					class="shrink-0 flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium transition {i === step
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
		<!-- 3 · credentials -->
		<div class="space-y-2">
			{#each creds as c (c.key)}
				<label class="block">
					<span class="block text-xs font-medium text-gray-600 dark:text-gray-300 mb-1">
						{c.label} <code class="text-[11px] font-mono text-gray-400">{c.key}</code>
					</span>
					<input
						type="password"
						autocomplete="new-password"
						spellcheck="false"
						bind:value={credValues[c.key]}
						placeholder={$i18n.t('Paste the value')}
						class="w-full rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-3 py-1.5 text-sm font-mono outline-none focus:border-gray-400 dark:focus:border-gray-600"
					/>
				</label>
			{/each}

			{#each extraVars as row, i}
				<div class="flex items-center gap-2">
					<input
						bind:value={row.key}
						placeholder="ENV_NAME"
						spellcheck="false"
						class="w-2/5 rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-3 py-1.5 text-sm font-mono outline-none focus:border-gray-400 dark:focus:border-gray-600"
					/>
					<input
						type={row.secret ? 'password' : 'text'}
						autocomplete="new-password"
						spellcheck="false"
						bind:value={row.value}
						placeholder={$i18n.t('Value')}
						class="flex-1 rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-3 py-1.5 text-sm font-mono outline-none focus:border-gray-400 dark:focus:border-gray-600"
					/>
					<label class="flex items-center gap-1 text-[11px] text-gray-500 shrink-0" title={$i18n.t('Encrypt this value at rest')}>
						<input type="checkbox" bind:checked={row.secret} class="accent-gray-700" />
						{$i18n.t('Secret')}
					</label>
					<button
						on:click={() => (extraVars = extraVars.filter((_, j) => j !== i))}
						title={$i18n.t('Remove')}
						class="shrink-0 text-gray-400 hover:text-red-500 transition"
					>
						<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18" /></svg>
					</button>
				</div>
			{/each}

			<button
				on:click={() => (extraVars = [...extraVars, { key: '', value: '', secret: true }])}
				class="rounded-lg border border-dashed border-gray-300 dark:border-gray-700 px-3 py-1.5 text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 hover:border-gray-400 dark:hover:border-gray-600 transition"
				>+ {$i18n.t('Add environment variable')}</button
			>

			<p class="text-[11px] text-gray-400">
				{creds.length || extraVars.length
					? $i18n.t(
							'Values marked secret are encrypted before storage and only decrypted when the server starts. They are never shown again — editing this connection later keeps the stored value unless you type a new one.'
						)
					: $i18n.t(
							'This template needs no credentials. Add environment variables here if your server expects any.'
						)}
			</p>
		</div>
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
			{#if storedSecretKeys.length}
				<div>
					<span class="text-gray-400 text-xs">{$i18n.t('Secrets stored')}:</span>
					<code class="text-xs font-mono">{storedSecretKeys.join(', ')}</code>
				</div>
			{/if}
			{#if missingCreds.length}
				<div class="text-xs text-amber-600 dark:text-amber-400">
					{$i18n.t('Saving without')}
					<code class="text-[11px] font-mono">{missingCreds.map((c) => c.key).join(', ')}</code>
					— {$i18n.t('the server may refuse to start.')}
				</div>
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
