<script lang="ts">
	// Skills panel — user skills CRUD + governance (Exec Core C2) + OpenClaw sync.
	// Extracted from Customize.svelte so the Settings modal, the Customize page
	// and any future mount share ONE implementation. Skills → /api/v1/skills.
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
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

	export let token = '';

	const i18n: any = getContext('i18n');

	// ── Skills ──────────────────────────────────────────────────────────────
	let skills: any[] = [];
	let skillsLoaded = false;
	let loadError = '';
	let showSkillForm = false;
	let sName = '';
	let sDesc = '';
	let sContent = '';
	let savingSkill = false;
	let editingSkillId: string | null = null;

	const loadSkills = async () => {
		loadError = '';
		const r = await getSkills(token).catch((e) => {
			// Keep whatever list is on screen — a failed refresh must not read as
			// "all skills deleted". The error branch below covers the empty case.
			loadError = `${e}`;
			if (skills.length) toast.error(`${$i18n.t('Could not refresh skills')} — ${e}`);
			return null;
		});
		if (r) {
			skills = Array.isArray(r) ? r : (r?.skills ?? r?.items ?? []);
			skillsLoaded = true;
		}
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
		// Only reflect a state change the server actually accepted.
		try {
			await toggleSkillById(token, id);
			await loadSkills();
		} catch (e) {
			toast.error(`${e}`);
		}
	};
	const removeSkill = async (id: string) => {
		// Don't drop the row unless the server confirmed the delete.
		try {
			await deleteSkillById(token, id);
			skills = skills.filter((s) => s.id !== id);
		} catch (e) {
			toast.error(`${e}`);
		}
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

	onMount(async () => {
		if (!token) token = localStorage.getItem('token') || '';
		loadSkills();
	});
</script>

<div class="w-full">
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
	{:else if loadError}
		<div class="rounded-xl border border-gray-100 dark:border-gray-850 px-3 py-6 text-center text-sm text-gray-500">
			{$i18n.t('Could not load skills')} — {loadError}
			<button class="ml-2 text-blue-600 dark:text-blue-400 hover:underline" on:click={loadSkills}>{$i18n.t('Retry')}</button>
		</div>
	{:else if !showSkillForm && !skillsLoaded}
		<div class="text-xs text-gray-500 py-1">{$i18n.t('Loading skills…')}</div>
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
</div>
