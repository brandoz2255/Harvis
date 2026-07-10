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
		deleteSkillById,
		auditSkill,
		selfEditSkill,
		setSkillVerdict,
		getSkillSyncPreview,
		applySkillSync
	} from '$lib/apis/skills';
	// P4/P5 (marathon): model routing matrix + agent presets + guided MCP wizard.
	import ModelRoutingMatrix from './customize/ModelRoutingMatrix.svelte';
	import AgentPresets from './customize/AgentPresets.svelte';
	import McpWizard from './customize/McpWizard.svelte';

	export let mode: 'full' | 'dock' = 'full';

	// Guided MCP setup (wizard) — the quick-add form below stays for power users.
	let showMcpWizard = false;

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

	// ── Skill governance (Exec Core C2) — audit → human verdict → OpenClaw sync ──
	// Only a human 'supported' verdict lets a skill inject into chats / publish.
	const VERDICTS = [
		'supported',
		'partially_supported',
		'unsupported',
		'contradicted',
		'insufficient_evidence'
	] as const;
	const verdictOf = (s: any): string | null => s?.meta?.audit?.verdict ?? null;
	const verdictBadgeClass = (v: string | null) =>
		v === 'supported'
			? 'border-green-200 dark:border-green-900 text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-950/40'
			: v
				? 'border-amber-200 dark:border-amber-900 text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/40'
				: 'border-gray-200 dark:border-gray-800 text-gray-400 bg-gray-50 dark:bg-gray-900';

	let govOpenId: string | null = null; // one governance panel open at a time
	let auditResults: Record<string, any> = {}; // skill id → last audit response this session
	let auditingId: string | null = null;
	let selfEditingId: string | null = null;
	let verdictDraft = '';
	let verdictNotes = '';
	let savingVerdict = false;

	const toggleGov = (s: any) => {
		if (govOpenId === s.id) {
			govOpenId = null;
			return;
		}
		govOpenId = s.id;
		verdictDraft = verdictOf(s) ?? '';
		verdictNotes = s?.meta?.audit?.notes ?? '';
	};
	const runAudit = async (s: any) => {
		if (auditingId) return;
		auditingId = s.id;
		govOpenId = s.id;
		const r = await auditSkill(token, s.id).catch((e) => {
			toast.error(`${e}`);
			return null;
		});
		auditingId = null;
		if (r) {
			auditResults = { ...auditResults, [s.id]: r };
			await loadSkills();
		}
	};
	const runSelfEdit = async (s: any) => {
		if (selfEditingId) return;
		selfEditingId = s.id;
		const r = await selfEditSkill(token, s.id).catch((e) => {
			toast.error(`${e}`);
			return null;
		});
		selfEditingId = null;
		if (r) {
			toast.success(
				`${$i18n.t('Revision stored')} (#${r.revision_count ?? '?'}) — ${r.note ?? $i18n.t('not published')}`
			);
			await loadSkills();
		}
	};
	const saveVerdict = async (s: any) => {
		if (!verdictDraft || savingVerdict) return;
		savingVerdict = true;
		const r = await setSkillVerdict(token, s.id, verdictDraft as any, verdictNotes.trim() || null).catch(
			(e) => {
				toast.error(`${e}`);
				return null;
			}
		);
		savingVerdict = false;
		if (r) {
			toast.success(
				r.publishable
					? $i18n.t('Verdict recorded — this skill can now inject and publish.')
					: $i18n.t('Verdict recorded — only a "supported" verdict injects/publishes.')
			);
			await loadSkills();
		}
	};

	// OpenClaw sync — dry-run preview, then an explicit apply (server-flag gated).
	let syncPreview: any = null;
	let syncPreviewing = false;
	let syncApplying = false;
	let syncApplyResult: any = null;
	// skills the dry run would skip: prefer the API field if present, else derive
	// from the loaded skills with the same rule (verdict !== 'supported').
	$: syncSkipped =
		syncPreview?.skipped_unverified ??
		skills.filter((s) => s.enabled && verdictOf(s) !== 'supported').map((s) => s.name);
	const previewSync = async () => {
		if (syncPreviewing) return;
		syncPreviewing = true;
		syncApplyResult = null;
		const r = await getSkillSyncPreview(token).catch((e) => {
			toast.error(`${e}`);
			return null;
		});
		syncPreviewing = false;
		if (r) syncPreview = r;
	};
	const applySync = async (override = false) => {
		if (syncApplying) return;
		if (
			override &&
			!confirm(
				$i18n.t(
					'Override publishes skills WITHOUT a human "supported" verdict. This bypasses the audit gate. Continue?'
				)
			)
		)
			return;
		syncApplying = true;
		const r = await applySkillSync(token, override).catch((e) => {
			toast.error(`${e}`);
			return null;
		});
		syncApplying = false;
		if (r) {
			// Honest result: reflect the per-item apply statuses, not a blanket success.
			const _sk = r?.applied?.skills ?? [];
			const _w = _sk.filter((x) => x.status === 'written').length;
			const _s = _sk.filter((x) => x.status === 'skipped').length;
			const _e = _sk.filter((x) => x.status === 'error').length;
			if (_e > 0)
				toast.error(`${_w} written · ${_s} skipped · ${_e} failed — check the OpenClaw skills mount.`);
			else if (_w === 0)
				toast.warning(
					`Nothing written — ${_s} skill(s) skipped (need a "supported" verdict, or HARVIS_OPENCLAW_SKILLS_DIR is unset).`
				);
			else toast.success(`Sync applied: ${_w} written · ${_s} skipped. Restart OpenClaw to load changes.`);
			if (!override) await previewSync(); // refresh the dry run (skip after override — it would contradict what was just written)
			syncApplyResult = r; // surface exactly what the apply wrote/skipped
		}
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

	<!-- Section nav — nothing buried: jump chips to every settings group. -->
	<nav class="sticky top-0 z-10 -mx-1 px-1 py-1.5 bg-gray-50/90 dark:bg-gray-950/90 backdrop-blur flex flex-wrap gap-1.5">
		{#each [
			{ id: 'sec-routing', label: $i18n.t('Model routing') },
			{ id: 'sec-presets', label: $i18n.t('Presets') },
			{ id: 'sec-models', label: $i18n.t('Orchestration') },
			{ id: 'sec-skills', label: $i18n.t('Skills') },
			{ id: 'sec-tools', label: $i18n.t('Tools') },
			{ id: 'sec-mcp', label: $i18n.t('MCP') }
		] as chip (chip.id)}
			<button
				type="button"
				class="text-[11px] px-2.5 py-1 rounded-full border border-gray-200 dark:border-gray-800 text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-100 hover:border-gray-300 dark:hover:border-gray-700 transition"
				on:click={() => document.getElementById(chip.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
				>{chip.label}</button
			>
		{/each}
	</nav>

	<!-- ── Models & routing ─────────────────────────────────────────────── -->
	<!-- P4: task-type → model routing (explicit user config; never keyword auto-routing) -->
	{#if token}
		<section id="sec-routing" class="scroll-mt-12 rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-5">
			<ModelRoutingMatrix {token} />
		</section>

		<!-- P4: named agent presets (model + persona + engine + run-mode defaults) -->
		<section id="sec-presets" class="scroll-mt-12 rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-5">
			<AgentPresets {token} />
		</section>
	{/if}

	<!-- Orchestration models (the custom agent model pool) -->
	<section id="sec-models" class="scroll-mt-12 rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-5">
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
	<section id="sec-skills" class="scroll-mt-12 rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-5">
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
					<div class="rounded-xl border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-950">
						<div class="group px-3 py-2.5 flex items-center gap-3">
							<div class="min-w-0 flex-1">
								<div class="flex items-center gap-1.5 min-w-0">
									<div class="truncate text-sm font-medium text-gray-800 dark:text-gray-100">{s.emoji ? s.emoji + ' ' : ''}{s.name}</div>
									<!-- Governance badge: reads meta.audit.verdict; only 'supported' publishes -->
									<span class="shrink-0 text-[10px] px-1.5 py-0.5 rounded-full border {verdictBadgeClass(verdictOf(s))}" title={$i18n.t('Human audit verdict — only "supported" lets this skill inject/publish')}>{verdictOf(s) ?? $i18n.t('unaudited')}</span>
								</div>
								{#if s.description}<div class="truncate text-xs text-gray-500">{s.description}</div>{/if}
							</div>
							<button on:click={() => toggleGov(s)} title={$i18n.t('Audit & verdict')} class="shrink-0 inline-flex items-center gap-1 text-[11px] {govOpenId === s.id ? 'text-blue-600 dark:text-blue-400' : 'text-gray-400 hover:text-blue-500'} transition">
								<svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2 4 5.5v5.2c0 4.9 3.4 9.5 8 10.8 4.6-1.3 8-5.9 8-10.8V5.5L12 2z" /></svg>
								{$i18n.t('Audit')}
								<svg class="size-3 transition-transform {govOpenId === s.id ? 'rotate-180' : ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6" /></svg>
							</button>
							<button on:click={() => editSkill(s)} title={$i18n.t('Edit')} class="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-blue-500 transition shrink-0">
								<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" /></svg>
							</button>
							<button on:click={() => toggleSkill(s.id)} title={s.enabled ? $i18n.t('Enabled') : $i18n.t('Disabled')} class="shrink-0 text-[11px] {s.enabled ? 'text-green-600 dark:text-green-400' : 'text-gray-400'}">● {s.enabled ? $i18n.t('On') : $i18n.t('Off')}</button>
							<button on:click={() => removeSkill(s.id)} title={$i18n.t('Delete')} class="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 transition shrink-0">
								<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m2 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" /></svg>
							</button>
						</div>

						{#if govOpenId === s.id}
							<!-- Governance panel (C2): audit → analysis + runnable → human verdict -->
							<div class="border-t border-gray-100 dark:border-gray-850 px-3 py-2.5 space-y-2">
								<div class="flex items-center justify-between gap-2">
									<div class="text-xs font-semibold uppercase tracking-wide text-gray-400">{$i18n.t('Governance')}</div>
									<div class="flex items-center gap-1.5">
										<button on:click={() => runAudit(s)} disabled={auditingId === s.id} class="rounded-lg border border-gray-200 dark:border-gray-800 px-3 py-1 text-xs font-medium text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-850 disabled:opacity-40 transition">{auditingId === s.id ? $i18n.t('Auditing…') : $i18n.t('Run audit')}</button>
										<button on:click={() => runSelfEdit(s)} disabled={selfEditingId === s.id} title={$i18n.t('Store a candidate revision for review — never overwrites approved content')} class="rounded-lg border border-gray-200 dark:border-gray-800 px-3 py-1 text-xs font-medium text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-850 disabled:opacity-40 transition">{selfEditingId === s.id ? $i18n.t('Storing…') : $i18n.t('Self-edit')}</button>
									</div>
								</div>

								{#if auditResults[s.id]}
									{@const a = auditResults[s.id]}
									<div class="rounded-lg border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-2.5 space-y-1.5">
										<div class="flex items-center gap-2 text-[11px]">
											<span class="px-1.5 py-0.5 rounded-full border {a.runnable ? 'border-green-200 dark:border-green-900 text-green-600 dark:text-green-400' : 'border-amber-200 dark:border-amber-900 text-amber-600 dark:text-amber-400'}">{a.runnable ? $i18n.t('runnable here') : $i18n.t('not runnable here')}</span>
											{#if a.run_id}<code class="font-mono text-gray-400">run {a.run_id}</code>{/if}
										</div>
										{#if a.analysis_md}
											<pre class="whitespace-pre-wrap text-xs text-gray-600 dark:text-gray-300 font-mono max-h-64 overflow-y-auto">{a.analysis_md}</pre>
										{/if}
									</div>
								{:else if s.meta?.audit?.last_run_id}
									<div class="text-[11px] text-gray-400">{$i18n.t('Last audited')}: <code class="font-mono">run {s.meta.audit.last_run_id}</code>{s.meta.audit.last_run_at ? ` · ${s.meta.audit.last_run_at}` : ''} — {$i18n.t('run a fresh audit to see the analysis here')}</div>
								{:else}
									<div class="text-[11px] text-gray-400">{$i18n.t('Not audited yet. Run an audit, then record a verdict below.')}</div>
								{/if}

								<div class="flex flex-col sm:flex-row gap-2">
									<select bind:value={verdictDraft} class="rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent dark:bg-gray-950 px-3 py-1.5 text-xs outline-none focus:border-blue-500">
										<option value="">{$i18n.t('Choose a verdict…')}</option>
										{#each VERDICTS as v}
											<option value={v}>{v}</option>
										{/each}
									</select>
									<input bind:value={verdictNotes} placeholder={$i18n.t('Notes (optional)')} class="flex-1 rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent px-3 py-1.5 text-xs outline-none focus:border-blue-500" />
									<button on:click={() => saveVerdict(s)} disabled={!verdictDraft || savingVerdict} class="rounded-lg bg-blue-600 text-white px-3 py-1.5 text-xs font-medium hover:bg-blue-700 disabled:opacity-40">{savingVerdict ? $i18n.t('Saving…') : $i18n.t('Record verdict')}</button>
								</div>
								<p class="text-[11px] text-gray-400">{$i18n.t('Only a "supported" verdict lets this skill inject into chats and publish to OpenClaw. Editing the skill body invalidates the verdict.')}</p>
							</div>
						{/if}
					</div>
				{/each}
			</div>
		{:else if !showSkillForm}
			<div class="text-xs text-gray-500 py-1">{$i18n.t('No skills yet. Create one to get started.')}</div>
		{/if}

		<!-- OpenClaw sync (C2): dry-run preview + explicit apply of human-verified skills -->
		<div class="mt-4 rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 p-3 space-y-2">
			<div class="flex items-center justify-between gap-2">
				<div class="flex items-center gap-2">
					<svg class="size-4 text-blue-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.6-6.4M21 3v6h-6" /></svg>
					<div class="text-sm font-medium text-gray-800 dark:text-gray-100">{$i18n.t('OpenClaw sync')}</div>
				</div>
				<div class="flex items-center gap-1.5">
					<button on:click={previewSync} disabled={syncPreviewing} class="rounded-lg border border-gray-200 dark:border-gray-800 px-3 py-1.5 text-xs font-medium text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-850 disabled:opacity-40 transition">{syncPreviewing ? $i18n.t('Previewing…') : $i18n.t('Preview sync')}</button>
					<button on:click={() => applySync(false)} disabled={syncApplying || !syncPreview} title={syncPreview ? $i18n.t('Write verified skills to the OpenClaw mounts') : $i18n.t('Run a preview first')} class="rounded-lg bg-blue-600 text-white px-3 py-1.5 text-xs font-medium hover:bg-blue-700 disabled:opacity-40">{syncApplying ? $i18n.t('Applying…') : $i18n.t('Apply sync')}</button>
				</div>
			</div>
			<p class="text-xs text-gray-500">
				{$i18n.t('Publishes your skills to the live OpenClaw agent. Only skills with a human "supported" verdict are included. Preview is a dry run — nothing is written until you apply.')}
			</p>

			{#if syncPreview}
				<div class="rounded-lg border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-2.5 space-y-2 text-xs">
					<div>
						<div class="font-semibold uppercase tracking-wide text-[10px] text-gray-400 mb-1">{$i18n.t('Will publish')}</div>
						{#if (syncPreview.skills?.items ?? []).length}
							<div class="flex flex-wrap gap-1">
								{#each syncPreview.skills.items as it (it.id)}
									<span class="px-1.5 py-0.5 rounded-full border border-green-200 dark:border-green-900 text-green-600 dark:text-green-400">{it.name}</span>
								{/each}
							</div>
						{:else}
							<div class="text-gray-500">{$i18n.t('No skills qualify — none have a "supported" verdict yet.')}</div>
						{/if}
					</div>
					{#if syncSkipped.length}
						<div>
							<div class="font-semibold uppercase tracking-wide text-[10px] text-gray-400 mb-1">{$i18n.t('Skipped — not human-verified')}</div>
							<div class="flex flex-wrap gap-1">
								{#each syncSkipped as name}
									<span class="px-1.5 py-0.5 rounded-full border border-amber-200 dark:border-amber-900 text-amber-600 dark:text-amber-400" title={$i18n.t('No "supported" audit verdict — audit the skill and record a verdict to publish it')}>{name}</span>
								{/each}
							</div>
						</div>
					{/if}
					{#if (syncPreview.notes ?? []).length}
						<ul class="space-y-0.5 text-gray-500">
							{#each syncPreview.notes as n}
								<li>· {n}</li>
							{/each}
						</ul>
					{/if}
					{#if syncSkipped.length}
						<button on:click={() => applySync(true)} disabled={syncApplying} class="text-[11px] text-amber-600 dark:text-amber-400 hover:underline disabled:opacity-40">{$i18n.t('Apply with override (includes unverified skills)…')}</button>
					{/if}
				</div>
			{/if}

			{#if syncApplyResult}
				{@const _sk = syncApplyResult.applied?.skills ?? []}
				{@const _w = _sk.filter((x) => x.status === 'written').length}
				{@const _s = _sk.filter((x) => x.status === 'skipped').length}
				{@const _e = _sk.filter((x) => x.status === 'error').length}
				<div
					class="rounded-lg border p-2.5 text-xs {_e > 0
						? 'border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-950/40 text-red-700 dark:text-red-400'
						: _w === 0
							? 'border-amber-200 dark:border-amber-900 bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400'
							: 'border-green-200 dark:border-green-900 bg-green-50 dark:bg-green-950/40 text-green-700 dark:text-green-400'}"
				>
					{_w} {$i18n.t('written')} · {_s} {$i18n.t('skipped')}{_e > 0
						? ` · ${_e} ${$i18n.t('failed')}`
						: ''}{syncApplyResult.config_set ? ` · ${$i18n.t('config')}: ${syncApplyResult.config_set}` : ''}{#if _w > 0}
						— {$i18n.t('restart the OpenClaw container to load the changes.')}{/if}
				</div>
			{/if}
		</div>
	</section>

	<!-- Tools (read-only catalog) -->
	<section id="sec-tools" class="scroll-mt-12 rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-5">
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
	<section id="sec-mcp" class="scroll-mt-12 rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-5">
		<div class="flex items-center justify-between gap-2 mb-1">
			<div class="flex items-center gap-2">
				<svg class="size-5 text-blue-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 2v6m6-6v6M5 8h14a2 2 0 0 1 2 2v2a7 7 0 0 1-7 7h-4a7 7 0 0 1-7-7v-2a2 2 0 0 1 2-2zM12 19v3" /></svg>
				<h2 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{$i18n.t('MCP Connections')}</h2>
			</div>
			<div class="flex items-center gap-1.5">
				<button
					on:click={() => (showMcpWizard = !showMcpWizard)}
					class="inline-flex items-center gap-1.5 rounded-full bg-blue-600 text-white px-3 py-1.5 text-xs font-medium hover:bg-blue-700 transition"
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
		<p class="text-sm text-gray-500 mb-3">{$i18n.t('Connect an MCP server (plugin) to give your agents more tools.')}</p>

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
