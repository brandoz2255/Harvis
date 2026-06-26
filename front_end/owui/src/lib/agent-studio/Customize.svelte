<script lang="ts">
	// Customize — Agent Studio surface for creating user Skills + MCP Connections.
	// Skills → /api/v1/skills (owui_skills); Connections → /api/owui/mcp (mcp_servers).
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { models } from '$lib/stores';
	import {
		getSkills,
		createNewSkill,
		updateSkillById,
		toggleSkillById,
		deleteSkillById
	} from '$lib/apis/skills';

	export let mode: 'full' | 'dock' = 'full';

	const i18n: any = getContext('i18n');
	let token = '';

	// ── Skills ──────────────────────────────────────────────────────────────
	let skills: any[] = [];
	let showSkillForm = false;
	let sName = '';
	let sDesc = '';
	let sContent = '';
	let savingSkill = false;
	let editingSkillId: string | null = null;

	const loadSkills = async () => {
		const r = await getSkills(token).catch(() => []);
		skills = Array.isArray(r) ? r : (r?.skills ?? r?.items ?? []);
	};
	const resetSkillForm = () => {
		sName = sDesc = sContent = '';
		editingSkillId = null;
		showSkillForm = false;
	};
	const editSkill = (s: any) => {
		editingSkillId = s.id;
		sName = s.name ?? '';
		sDesc = s.description ?? '';
		sContent = s.content ?? '';
		showSkillForm = true;
	};
	const saveSkill = async () => {
		if (!sName.trim() || savingSkill) return;
		savingSkill = true;
		const payload = { name: sName.trim(), description: sDesc.trim(), content: sContent };
		const res = await (editingSkillId
			? updateSkillById(token, editingSkillId, payload)
			: createNewSkill(token, payload)
		).catch((e) => {
			toast.error(`${e}`);
			return null;
		});
		savingSkill = false;
		if (res) {
			resetSkillForm();
			await loadSkills();
		}
	};
	const toggleSkill = async (id: string) => {
		await toggleSkillById(token, id).catch(() => {});
		await loadSkills();
	};
	const removeSkill = async (id: string) => {
		await deleteSkillById(token, id).catch(() => {});
		skills = skills.filter((s) => s.id !== id);
	};

	// ── MCP Connections ───────────────────────────────────────────────────────
	let conns: any[] = [];
	let showConnForm = false;
	let cName = '';
	let cTransport = 'stdio';
	let cCommand = '';
	let cUrl = '';
	let savingConn = false;

	// Read-only catalog of the agent's built-in tools (Harvis-native: the
	// orchestration runner + OpenClaw allowlist). MCP connections below extend it.
	const AGENT_TOOLS: { name: string; desc: string; group: string }[] = [
		{ name: 'read_file', desc: 'Read a file in the workspace.', group: 'Code & files' },
		{ name: 'edit_file', desc: 'Create or overwrite a file.', group: 'Code & files' },
		{ name: 'str_replace', desc: 'Make a targeted edit to a file.', group: 'Code & files' },
		{ name: 'exec', desc: 'Run a shell command in the workspace.', group: 'Code & files' },
		{ name: 'run_tests', desc: 'Run the project test suite.', group: 'Code & files' },
		{ name: 'run_code', desc: 'Execute code and capture the output.', group: 'Code & files' },
		{ name: 'repo_read', desc: 'Read from an attached git repository.', group: 'Repositories' },
		{ name: 'repo_write', desc: 'Write changes to an attached repository.', group: 'Repositories' },
		{ name: 'web_search', desc: 'Search the web (when web access is on).', group: 'Knowledge & web' },
		{ name: 'local_rag', desc: 'Search your knowledge bases and notebooks.', group: 'Knowledge & web' },
		{ name: 'create_docx', desc: 'Generate a Word document.', group: 'Documents' },
		{ name: 'create_pdf', desc: 'Generate a PDF.', group: 'Documents' }
	];
	const TOOL_GROUPS = ['Code & files', 'Repositories', 'Knowledge & web', 'Documents'];

	const loadConns = async () => {
		const r = await fetch('/api/owui/mcp/connections', {
			headers: { authorization: `Bearer ${token}` }
		})
			.then((x) => (x.ok ? x.json() : { items: [] }))
			.catch(() => ({ items: [] }));
		conns = r?.items ?? [];
	};
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

	// ── Orchestration model pool (opt-in) ──────────────────────────────────────
	// When Active, a multi-agent (Agents) run draws models from this pool instead of
	// the session's model. Single-agent turns are unaffected. Persisted per-user.
	let poolActive = false;
	let poolModels: string[] = [];
	let poolModelToAdd = '';
	let poolLoaded = false;
	const loadPool = async () => {
		const r = await fetch('/api/owui/orchestration/pool', {
			headers: { authorization: `Bearer ${token}` }
		})
			.then((x) => (x.ok ? x.json() : null))
			.catch(() => null);
		if (r) {
			poolActive = !!r.active;
			poolModels = Array.isArray(r.models) ? r.models : [];
		}
		poolLoaded = true;
	};
	const savePool = async () => {
		if (!poolLoaded) return;
		await fetch('/api/owui/orchestration/pool', {
			method: 'PUT',
			headers: { 'Content-Type': 'application/json', authorization: `Bearer ${token}` },
			body: JSON.stringify({ active: poolActive, models: poolModels })
		}).catch(() => {});
	};
	const addPoolModel = () => {
		const m = poolModelToAdd.trim();
		if (m && !poolModels.includes(m)) {
			poolModels = [...poolModels, m];
			poolModelToAdd = '';
			savePool();
		}
	};
	const removePoolModel = (m: string) => {
		poolModels = poolModels.filter((x) => x !== m);
		savePool();
	};
	const togglePoolActive = () => {
		poolActive = !poolActive;
		savePool();
	};

	onMount(async () => {
		token = localStorage.getItem('token') || '';
		loadSkills();
		loadConns();
		loadPool();
	});
</script>

<div class="w-full {mode === 'full' ? 'max-w-4xl mx-auto px-1 py-2' : ''} space-y-5">
	{#if mode === 'full'}
		<div>
			<h1 class="text-xl font-semibold text-gray-800 dark:text-gray-100">{$i18n.t('Customize')}</h1>
			<p class="text-sm text-gray-500 mt-1">
				{$i18n.t('Create your own skills and connect MCP plugins. Your agents can use what you add here.')}
			</p>
		</div>
	{/if}

	<!-- Orchestration models (the custom agent model pool) -->
	<section class="rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-5">
		<div class="flex items-center justify-between gap-2 mb-1">
			<div class="flex items-center gap-2">
				<svg class="size-5 text-violet-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="5" r="2.2" /><circle cx="5" cy="19" r="2.2" /><circle cx="19" cy="19" r="2.2" /><path d="M12 7.2v3m0 0-5 6.6m5-6.6 5 6.6" /></svg>
				<h2 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{$i18n.t('Orchestration models')}</h2>
			</div>
			<button
				on:click={togglePoolActive}
				class="inline-flex items-center gap-1.5 text-xs font-medium {poolActive
					? 'text-green-600 dark:text-green-400'
					: 'text-gray-400'}"
				title={$i18n.t('Use this pool for multi-agent runs')}
			>
				<span
					class="relative inline-block w-9 h-5 rounded-full transition {poolActive
						? 'bg-green-500'
						: 'bg-gray-300 dark:bg-gray-700'}"
				>
					<span
						class="absolute top-0.5 size-4 rounded-full bg-white transition-all {poolActive
							? 'left-[1.125rem]'
							: 'left-0.5'}"
					></span>
				</span>
				{poolActive ? $i18n.t('Active') : $i18n.t('Off')}
			</button>
		</div>
		<p class="text-sm text-gray-500 mb-3">
			{$i18n.t(
				'When active, a multi-agent (Agents) run splits work across these models instead of your session model. Single-agent turns are never affected.'
			)}
		</p>

		<div class="flex gap-2 mb-3">
			<select
				bind:value={poolModelToAdd}
				class="flex-1 rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent dark:bg-gray-950 px-3 py-1.5 text-sm outline-none focus:border-blue-500"
			>
				<option value="">{$i18n.t('Choose a model to add…')}</option>
				{#each ($models || []).filter((m) => m?.id && !poolModels.includes(m.id)) as m}
					<option value={m.id}>{m.name || m.id}</option>
				{/each}
			</select>
			<button
				on:click={addPoolModel}
				disabled={!poolModelToAdd}
				class="rounded-lg bg-blue-600 text-white px-4 py-1.5 text-sm font-medium hover:bg-blue-700 disabled:opacity-40"
				>{$i18n.t('Add')}</button
			>
		</div>

		{#if poolModels.length}
			<div class="flex flex-wrap gap-1.5">
				{#each poolModels as m (m)}
					<span
						class="inline-flex items-center gap-1.5 rounded-full border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 pl-3 pr-1.5 py-1 text-xs text-gray-700 dark:text-gray-200"
					>
						<code class="font-mono">{m}</code>
						<button
							on:click={() => removePoolModel(m)}
							title={$i18n.t('Remove')}
							class="text-gray-400 hover:text-red-500 transition"
							><svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18" /></svg></button
						>
					</span>
				{/each}
			</div>
		{:else}
			<div class="text-xs text-gray-500 py-1">
				{$i18n.t('No models in the pool. Add a few to fan multi-agent work across them.')}
			</div>
		{/if}
	</section>

	<!-- Skills -->
	<section class="rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-5">
		<div class="flex items-center justify-between gap-2 mb-1">
			<div class="flex items-center gap-2">
				<svg class="size-5 text-blue-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.9 5.8H20l-4.9 3.6 1.9 5.8L12 14.6 7 18.2l1.9-5.8L4 8.8h6.1L12 3z" /></svg>
				<h2 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{$i18n.t('Skills')}</h2>
			</div>
			<button
				on:click={() => {
					if (showSkillForm) resetSkillForm();
					else {
						resetSkillForm();
						showSkillForm = true;
					}
				}}
				class="inline-flex items-center gap-1.5 rounded-full bg-blue-600 text-white px-3 py-1.5 text-xs font-medium hover:bg-blue-700 transition"
			>
				<svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg>
				{$i18n.t('New skill')}
			</button>
		</div>
		<p class="text-sm text-gray-500 mb-3">{$i18n.t('A skill is a capability with instructions your agent can apply.')}</p>

		{#if showSkillForm}
			<div class="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 p-3 mb-3 space-y-2">
				<input bind:value={sName} placeholder={$i18n.t('Skill name')} class="w-full rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent px-3 py-1.5 text-sm outline-none focus:border-blue-500" />
				<input bind:value={sDesc} placeholder={$i18n.t('Short description')} class="w-full rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent px-3 py-1.5 text-sm outline-none focus:border-blue-500" />
				<textarea bind:value={sContent} rows="5" placeholder={$i18n.t('Instructions (markdown) — how the agent should perform this skill')} class="w-full rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent px-3 py-2 text-sm outline-none focus:border-blue-500 resize-y font-mono"></textarea>
				<div class="flex justify-end gap-2">
					<button on:click={resetSkillForm} class="rounded-lg px-3 py-1.5 text-sm text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-850">{$i18n.t('Cancel')}</button>
					<button on:click={saveSkill} disabled={savingSkill || !sName.trim()} class="rounded-lg bg-blue-600 text-white px-4 py-1.5 text-sm font-medium hover:bg-blue-700 disabled:opacity-40">{savingSkill ? $i18n.t('Saving…') : editingSkillId ? $i18n.t('Save') : $i18n.t('Create skill')}</button>
				</div>
			</div>
		{/if}

		{#if skills.length}
			<div class="space-y-1.5">
				{#each skills as s (s.id)}
					<div class="group rounded-xl border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-950 px-3 py-2.5 flex items-center gap-3">
						<div class="min-w-0 flex-1">
							<div class="truncate text-sm font-medium text-gray-800 dark:text-gray-100">{s.emoji ? s.emoji + ' ' : ''}{s.name}</div>
							{#if s.description}<div class="truncate text-xs text-gray-500">{s.description}</div>{/if}
						</div>
						<button on:click={() => editSkill(s)} title={$i18n.t('Edit')} class="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-blue-500 transition shrink-0">
							<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" /></svg>
						</button>
						<button on:click={() => toggleSkill(s.id)} title={s.enabled ? $i18n.t('Enabled') : $i18n.t('Disabled')} class="shrink-0 text-[11px] {s.enabled ? 'text-green-600 dark:text-green-400' : 'text-gray-400'}">● {s.enabled ? $i18n.t('On') : $i18n.t('Off')}</button>
						<button on:click={() => removeSkill(s.id)} title={$i18n.t('Delete')} class="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 transition shrink-0">
							<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m2 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" /></svg>
						</button>
					</div>
				{/each}
			</div>
		{:else if !showSkillForm}
			<div class="text-xs text-gray-500 py-1">{$i18n.t('No skills yet. Create one to get started.')}</div>
		{/if}
	</section>

	<!-- Tools (read-only catalog) -->
	<section class="rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-5">
		<div class="flex items-center gap-2 mb-1">
			<svg class="size-5 text-blue-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18v3h3l6.3-6.3a4 4 0 0 0 5.4-5.4l-2.7 2.7-2-2 2.7-2.7z" /></svg>
			<h2 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{$i18n.t('Tools')}</h2>
		</div>
		<p class="text-sm text-gray-500 mb-3">
			{$i18n.t('Built-in capabilities your agents can use. Connect MCP servers below to add more.')}
		</p>
		<div class="space-y-3">
			{#each TOOL_GROUPS as g}
				{@const groupTools = AGENT_TOOLS.filter((t) => t.group === g)}
				{#if groupTools.length}
					<div>
						<div class="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-1.5">{$i18n.t(g)}</div>
						<div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
							{#each groupTools as t}
								<div class="rounded-xl border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-950 px-3 py-2">
									<div class="flex items-center gap-2">
										<code class="text-xs font-mono text-blue-600 dark:text-blue-400">{t.name}</code>
										<span class="text-[10px] text-gray-400 bg-gray-100 dark:bg-gray-850 rounded px-1.5 py-0.5">{$i18n.t('built-in')}</span>
									</div>
									<div class="text-xs text-gray-500 mt-0.5">{t.desc}</div>
								</div>
							{/each}
						</div>
					</div>
				{/if}
			{/each}
		</div>
	</section>

	<!-- MCP Connections -->
	<section class="rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-5">
		<div class="flex items-center justify-between gap-2 mb-1">
			<div class="flex items-center gap-2">
				<svg class="size-5 text-blue-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 2v6m6-6v6M5 8h14a2 2 0 0 1 2 2v2a7 7 0 0 1-7 7h-4a7 7 0 0 1-7-7v-2a2 2 0 0 1 2-2zM12 19v3" /></svg>
				<h2 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{$i18n.t('MCP Connections')}</h2>
			</div>
			<button
				on:click={() => (showConnForm = !showConnForm)}
				class="inline-flex items-center gap-1.5 rounded-full bg-blue-600 text-white px-3 py-1.5 text-xs font-medium hover:bg-blue-700 transition"
			>
				<svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg>
				{$i18n.t('Add connection')}
			</button>
		</div>
		<p class="text-sm text-gray-500 mb-3">{$i18n.t('Connect an MCP server (plugin) to give your agents more tools.')}</p>

		{#if showConnForm}
			<div class="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 p-3 mb-3 space-y-2">
				<div class="flex gap-2">
					<input bind:value={cName} placeholder={$i18n.t('Connection name')} class="flex-1 rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent px-3 py-1.5 text-sm outline-none focus:border-blue-500" />
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

		{#if conns.length}
			<div class="space-y-1.5">
				{#each conns as c (c.id)}
					<div class="group rounded-xl border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-950 px-3 py-2.5 flex items-center gap-3">
						<div class="min-w-0 flex-1">
							<div class="truncate text-sm font-medium text-gray-800 dark:text-gray-100">{c.name} <span class="text-[11px] text-gray-400">· {c.transport}</span></div>
							<div class="truncate text-xs text-gray-500 font-mono">{c.command || c.url || ''}</div>
						</div>
						<button on:click={() => toggleConn(c.id)} title={c.enabled ? $i18n.t('Enabled') : $i18n.t('Disabled')} class="shrink-0 text-[11px] {c.enabled ? 'text-green-600 dark:text-green-400' : 'text-gray-400'}">● {c.enabled ? $i18n.t('On') : $i18n.t('Off')}</button>
						<button on:click={() => removeConn(c.id)} title={$i18n.t('Delete')} class="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 transition shrink-0">
							<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m2 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" /></svg>
						</button>
					</div>
				{/each}
			</div>
		{:else if !showConnForm}
			<div class="text-xs text-gray-500 py-1">{$i18n.t('No connections yet.')}</div>
		{/if}
	</section>
</div>
