<script lang="ts">
	// Custom Sub-Agents — define a specialist (Claude-Code-subagent style) the P5
	// orchestrator auto-delegates to: name + description (used for delegation) +
	// dedicated system prompt + allowed-tools allowlist + attached skills + attached
	// connectors + a (local) model. Backed by /api/owui/subagents. The main agent
	// hands a step to the sub-agent whose DESCRIPTION best matches it.
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { models } from '$lib/stores';

	export let token = '';

	const i18n: any = getContext('i18n');

	// The tools actually offered on the wire (workspace/orchestration/tools.py).
	// Empty allowlist ⇒ the sub-agent gets ALL of them; a non-empty list withholds
	// the rest at offer time (authorize_action still gates at dispatch). `finish` is
	// always available (the run loop needs it) so it isn't shown here.
	const TOOLS: { id: string; label: string; note: string }[] = [
		{ id: 'read_file', label: 'Read files', note: 'inspect workspace files' },
		{ id: 'edit_file', label: 'Write files', note: 'create files' },
		{ id: 'str_replace', label: 'Edit files', note: 'modify existing files' },
		{ id: 'exec', label: 'Run commands', note: 'sandboxed shell' }
	];

	let subagents: any[] = [];
	let skills: any[] = [];
	let conns: any[] = [];
	let loaded = false;
	let loadError = false;
	let saving = false;

	let showForm = false;
	let editingId: string | null = null;
	let fName = '';
	let fDesc = '';
	let fPrompt = '';
	let fModel = '';
	let fTools: Record<string, boolean> = {};
	let fSkills: Record<string, boolean> = {};
	let fMcps: Record<string, boolean> = {};

	const authHeaders = () => ({ authorization: `Bearer ${token}` });

	// A sub-agent may only pin a LOCAL model (cloud needs per-user creds the runner
	// can't assume). Filter the picker to non-cloud ids.
	$: localModels = ($models || []).filter(
		(m: any) => m?.id && !String(m.id).startsWith('anthropic/') && !String(m.id).startsWith('openai/')
	);
	const skillName = (id: string) => skills.find((s) => s.id === id)?.name ?? id;
	const connName = (id: string) => conns.find((c) => String(c.id) === String(id))?.name ?? id;
	const isSupported = (s: any) => s?.meta?.audit?.verdict === 'supported';

	const load = async () => {
		const [sa, sk, cn] = await Promise.all([
			fetch('/api/owui/subagents', { headers: authHeaders() })
				.then((x) => (x.ok ? x.json() : null))
				.catch(() => null),
			fetch('/api/v1/skills/', { headers: authHeaders() })
				.then((x) => (x.ok ? x.json() : []))
				.catch(() => []),
			fetch('/api/owui/mcp/connections', { headers: authHeaders() })
				.then((x) => (x.ok ? x.json() : null))
				.catch(() => null)
		]);
		// null = the request failed (backend down / non-2xx) — keep that distinct
		// from a healthy backend reporting an empty list, so a dead backend never
		// renders as "no sub-agents yet"
		loadError = sa === null;
		subagents = Array.isArray(sa?.items) ? sa.items : [];
		skills = Array.isArray(sk) ? sk : Array.isArray(sk?.items) ? sk.items : [];
		conns = Array.isArray(cn) ? cn : Array.isArray(cn?.items) ? cn.items : [];
		loaded = true;
	};

	const resetForm = () => {
		fName = fDesc = fPrompt = fModel = '';
		fTools = {};
		fSkills = {};
		fMcps = {};
		editingId = null;
		showForm = false;
	};

	const editAgent = (a: any) => {
		editingId = a.id;
		fName = a.name ?? '';
		fDesc = a.description ?? '';
		fPrompt = a.system_prompt ?? '';
		fModel = a.model ?? '';
		fTools = Object.fromEntries((a.allowed_tools ?? []).map((t: string) => [t, true]));
		fSkills = Object.fromEntries((a.skill_ids ?? []).map((s: string) => [s, true]));
		fMcps = Object.fromEntries((a.mcp_ids ?? []).map((m: string) => [String(m), true]));
		showForm = true;
	};

	const kebabOk = (n: string) => /^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/.test(n) && n.length <= 40;

	const saveAgent = async () => {
		const name = fName.trim().toLowerCase();
		if (!name || saving) return;
		if (!kebabOk(name)) {
			toast.error($i18n.t('Name must be kebab-case, e.g. "code-reviewer" (max 40 chars).'));
			return;
		}
		saving = true;
		const body = {
			name,
			description: fDesc.trim(),
			system_prompt: fPrompt,
			model: fModel,
			allowed_tools: Object.keys(fTools).filter((k) => fTools[k]),
			skill_ids: Object.keys(fSkills).filter((k) => fSkills[k]),
			mcp_ids: Object.keys(fMcps).filter((k) => fMcps[k])
		};
		const url = editingId
			? `/api/owui/subagents/${editingId}/update`
			: '/api/owui/subagents';
		const res = await fetch(url, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json', ...authHeaders() },
			body: JSON.stringify(body)
		});
		saving = false;
		if (res.ok) {
			await load();
			resetForm();
			toast.success($i18n.t('Sub-agent saved.'));
		} else {
			const j = await res.json().catch(() => ({}));
			toast.error(j?.detail || $i18n.t('Could not save sub-agent.'));
		}
	};

	const toggleAgent = async (a: any) => {
		await fetch(`/api/owui/subagents/${a.id}/toggle`, { method: 'POST', headers: authHeaders() });
		await load();
	};

	const removeAgent = async (a: any) => {
		await fetch(`/api/owui/subagents/${a.id}`, { method: 'DELETE', headers: authHeaders() });
		await load();
	};

	onMount(load);
</script>

<div class="flex items-center justify-between gap-2 mb-1">
	<div class="flex items-center gap-2">
		<svg class="size-5 text-emerald-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="7" r="3.2" /><path d="M5.5 20a6.5 6.5 0 0 1 13 0" /><path d="M18.5 8.5l1.5-1.5M20 11h1" /></svg>
		<h2 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{$i18n.t('Custom sub-agents')}</h2>
	</div>
	<button
		on:click={() => (showForm ? resetForm() : ((resetForm(), (showForm = true))))}
		class="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 text-white px-3 py-2 text-xs font-medium hover:bg-blue-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 transition"
	>
		<svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg>
		{$i18n.t('New sub-agent')}
	</button>
</div>
<p class="text-sm text-gray-500 mb-3">
	{$i18n.t(
		'Define a specialist and the orchestrator hands a step to it when the step matches its description. Each sub-agent runs with its own model, system prompt, tool allowlist and attached skills.'
	)}
</p>

{#if showForm}
	<div class="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 p-3 mb-3 space-y-3">
		<div>
			<label class="block text-xs font-medium text-gray-500 mb-1" for="sa-name">{$i18n.t('Name (kebab-case)')}</label>
			<input
				id="sa-name"
				bind:value={fName}
				placeholder="code-reviewer"
				class="w-full rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent px-3 py-2 text-sm font-mono outline-none focus:border-blue-500"
			/>
		</div>
		<div>
			<label class="block text-xs font-medium text-gray-500 mb-1" for="sa-desc">{$i18n.t('When should the orchestrator delegate to this?')}</label>
			<textarea
				id="sa-desc"
				bind:value={fDesc}
				rows="2"
				placeholder={$i18n.t('e.g. "Reviews code diffs for bugs and security issues before they land."')}
				class="w-full rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent px-3 py-2 text-sm outline-none focus:border-blue-500 resize-y"
			></textarea>
		</div>
		<div>
			<label class="block text-xs font-medium text-gray-500 mb-1" for="sa-prompt">{$i18n.t('System prompt')}</label>
			<textarea
				id="sa-prompt"
				bind:value={fPrompt}
				rows="4"
				placeholder={$i18n.t('Instructions, priorities and constraints for this sub-agent.')}
				class="w-full rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent px-3 py-2 text-sm outline-none focus:border-blue-500 resize-y"
			></textarea>
		</div>
		<div>
			<label class="block text-xs font-medium text-gray-500 mb-1" for="sa-model">{$i18n.t('Model (local only)')}</label>
			<select
				id="sa-model"
				bind:value={fModel}
				class="w-full rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent dark:bg-gray-950 px-3 py-2 text-sm outline-none focus:border-blue-500"
			>
				<option value="">{$i18n.t('Inherit the run\'s model')}</option>
				{#each localModels as m}
					<option value={m.id}>{m.name || m.id}</option>
				{/each}
			</select>
		</div>

		<div>
			<div class="text-xs font-medium text-gray-500 mb-1.5">{$i18n.t('Allowed tools')}</div>
			<div class="grid grid-cols-2 gap-1.5">
				{#each TOOLS as t (t.id)}
					<label class="flex items-center gap-2 rounded-lg border border-gray-200 dark:border-gray-800 px-2.5 py-2 text-sm cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-900">
						<input type="checkbox" bind:checked={fTools[t.id]} class="accent-blue-600 size-4" />
						<span class="text-gray-800 dark:text-gray-100">{$i18n.t(t.label)}</span>
						<span class="text-[10px] text-gray-400 ml-auto">{t.note}</span>
					</label>
				{/each}
			</div>
			<p class="text-[11px] text-gray-400 mt-1">{$i18n.t('None selected = all tools available. Selecting some withholds the rest.')}</p>
		</div>

		<div>
			<div class="text-xs font-medium text-gray-500 mb-1.5">{$i18n.t('Attached skills')}</div>
			{#if skills.length}
				<div class="space-y-1 max-h-40 overflow-y-auto pr-1">
					{#each skills as s (s.id)}
						<label class="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-900">
							<input type="checkbox" bind:checked={fSkills[s.id]} class="accent-blue-600 size-4" />
							<span class="truncate text-gray-800 dark:text-gray-100">{s.name}</span>
							{#if isSupported(s)}
								<span class="shrink-0 text-[10px] text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950 rounded px-1.5 py-0.5">{$i18n.t('supported')}</span>
							{:else}
								<span class="shrink-0 text-[10px] text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950 rounded px-1.5 py-0.5" title={$i18n.t('Not audited — it will not inject until a human marks it supported.')}>{$i18n.t('unaudited')}</span>
							{/if}
						</label>
					{/each}
				</div>
				<p class="text-[11px] text-gray-400 mt-1">{$i18n.t('Only skills with a human "supported" verdict inject their body; others attach as an honest note.')}</p>
			{:else}
				<p class="text-xs text-gray-400">{$i18n.t('No skills yet — create them in the Skills section above.')}</p>
			{/if}
		</div>

		<div>
			<div class="text-xs font-medium text-gray-500 mb-1.5">{$i18n.t('Connectors (MCP)')}</div>
			{#if conns.length}
				<div class="space-y-1 max-h-32 overflow-y-auto pr-1">
					{#each conns as c (c.id)}
						<label class="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-900">
							<input type="checkbox" bind:checked={fMcps[String(c.id)]} class="accent-blue-600 size-4" />
							<span class="truncate text-gray-800 dark:text-gray-100">{c.name}</span>
						</label>
					{/each}
				</div>
				<p class="text-[11px] text-amber-500 mt-1">{$i18n.t('Connectors are stored as config — live MCP tool-calling in runs is deferred.')}</p>
			{:else}
				<p class="text-xs text-gray-400">{$i18n.t('No connectors attached — add some in the MCP section below.')}</p>
			{/if}
		</div>

		<div class="flex justify-end gap-2 pt-1">
			<button on:click={resetForm} class="rounded-lg px-3 py-2 text-sm text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-850">{$i18n.t('Cancel')}</button>
			<button
				on:click={saveAgent}
				disabled={saving || !fName.trim()}
				class="rounded-lg bg-blue-600 text-white px-4 py-2 text-sm font-medium hover:bg-blue-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 disabled:opacity-40"
				>{saving ? $i18n.t('Saving…') : editingId ? $i18n.t('Save') : $i18n.t('Create sub-agent')}</button
			>
		</div>
	</div>
{/if}

{#if loadError}
	<div class="rounded-xl border border-gray-100 dark:border-gray-850 px-3 py-6 text-center text-sm text-gray-500">
		{$i18n.t('Could not load sub-agents.')}
		<button class="ml-2 text-blue-600 dark:text-blue-400 hover:underline" on:click={load}
			>{$i18n.t('Retry')}</button
		>
	</div>
{:else if subagents.length}
	<div class="space-y-1.5">
		{#each subagents as a (a.id)}
			<div class="group rounded-xl border {a.enabled ? 'border-gray-100 dark:border-gray-850' : 'border-dashed border-gray-200 dark:border-gray-800 opacity-70'} bg-white dark:bg-gray-950 px-3 py-2.5">
				<div class="flex items-center gap-3">
					<div class="min-w-0 flex-1">
						<div class="flex items-center gap-2">
							<span class="truncate text-sm font-medium font-mono text-gray-800 dark:text-gray-100">{a.name}</span>
							{#if !a.enabled}
								<span class="shrink-0 text-[10px] text-gray-500 bg-gray-100 dark:bg-gray-850 rounded px-1.5 py-0.5">{$i18n.t('disabled')}</span>
							{/if}
						</div>
						{#if a.description}
							<div class="text-xs text-gray-500 line-clamp-1 mt-0.5">{a.description}</div>
						{/if}
						<div class="flex flex-wrap items-center gap-1.5 mt-1">
							<span class="text-[10px] text-gray-500 bg-gray-100 dark:bg-gray-850 rounded px-1.5 py-0.5 font-mono">{a.model || $i18n.t('run model')}</span>
							<span class="text-[10px] text-gray-500 bg-gray-100 dark:bg-gray-850 rounded px-1.5 py-0.5">{(a.allowed_tools?.length ?? 0) ? $i18n.t('{{n}} tools', { n: a.allowed_tools.length }) : $i18n.t('all tools')}</span>
							{#if a.skill_ids?.length}
								<span class="text-[10px] text-gray-500 bg-gray-100 dark:bg-gray-850 rounded px-1.5 py-0.5">{$i18n.t('{{n}} skills', { n: a.skill_ids.length })}</span>
							{/if}
							{#if a.mcp_ids?.length}
								<span class="text-[10px] text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950 rounded px-1.5 py-0.5">{$i18n.t('{{n}} connectors', { n: a.mcp_ids.length })}</span>
							{/if}
						</div>
					</div>
					<button
						on:click={() => toggleAgent(a)}
						class="shrink-0 rounded-lg px-2.5 py-1.5 text-xs font-medium text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-850"
						>{a.enabled ? $i18n.t('Disable') : $i18n.t('Enable')}</button
					>
					<button on:click={() => editAgent(a)} title={$i18n.t('Edit')} class="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-blue-500 transition shrink-0">
						<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" /></svg>
					</button>
					<button on:click={() => removeAgent(a)} title={$i18n.t('Delete')} class="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 transition shrink-0">
						<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m2 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" /></svg>
					</button>
				</div>
			</div>
		{/each}
	</div>
{:else if !showForm && loaded}
	<div class="text-xs text-gray-500 py-1">{$i18n.t('No sub-agents yet. Create one to give the orchestrator a specialist to delegate to.')}</div>
{/if}
