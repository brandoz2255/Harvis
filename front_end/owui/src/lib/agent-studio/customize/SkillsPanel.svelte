<script lang="ts">
	// Skills panel — user skills CRUD + governance (Exec Core C2) + engine sync.
	// Extracted from Customize.svelte so the Settings modal, the Customize page
	// and any future mount share ONE implementation. Skills → /api/v1/skills.
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { fly } from 'svelte/transition';
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
	// The directory half of this surface. Entirely client-side (GitHub API +
	// raw.githubusercontent.com), and it imports ONLY SKILL.md text as an
	// unaudited draft — no scripts are downloaded or executed.
	import SkillsBrowse from '$lib/components/chat/Settings/Skills/SkillsBrowse.svelte';

	export let token = '';
	// 'full' = the /harvis/agent-studio/skills page (storefront header + Plugins|Skills
	// switch + browse view). 'dock' = embedded in Customize/Settings, compact header.
	export let mode: 'full' | 'dock' = 'dock';

	const i18n: any = getContext('i18n');

	// full-page only: which half of the surface is showing
	let view: 'yours' | 'browse' = 'yours';
	let skillQuery = '';

	// Row identity — an emoji if the skill has one, else a lettermark tile whose
	// color is derived from the name so the same skill always looks the same.
	const TILES = [
		'bg-blue-500',
		'bg-emerald-500',
		'bg-violet-500',
		'bg-amber-500',
		'bg-rose-500',
		'bg-cyan-600',
		'bg-indigo-500'
	];
	const tileOf = (name: string) => {
		let h = 0;
		for (const ch of name ?? '') h = (h * 31 + ch.charCodeAt(0)) >>> 0;
		return TILES[h % TILES.length];
	};
	const initialOf = (name: string) => (name ?? '').trim().charAt(0).toUpperCase() || '?';

	let menuOpenId: string | null = null; // one row overflow menu at a time

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

	// Header search. `skills` and `skillQuery` are read directly inside the reactive
	// statement so Svelte tracks them — routing this through a helper would leave the
	// list stale after a keystroke or a refresh.
	$: visibleSkills = (() => {
		const q = skillQuery.trim().toLowerCase();
		if (!q) return skills;
		return skills.filter((s) => `${s.name ?? ''} ${s.description ?? ''}`.toLowerCase().includes(q));
	})();
	// Two honest groups: what's live for your agents, and what isn't.
	$: installedSkills = visibleSkills.filter((s) => s.enabled);
	$: offSkills = visibleSkills.filter((s) => !s.enabled);
	// Empty groups drop out entirely, so a fresh install shows one "Installed" heading
	// rather than a "Turned off (0)" stub.
	$: skillSections = [
		{ id: 'installed', label: $i18n.t('Installed'), items: installedSkills },
		{ id: 'off', label: $i18n.t('Turned off'), items: offSkills }
	].filter((s) => s.items.length);

	// ── Skill governance (Exec Core C2) — audit → human verdict → engine sync ──
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

	// Engine sync — dry-run preview, then an explicit apply (server-flag gated).
	// Publishes to the SHARED engine skills tree, mounted into every engine sidecar
	// (OpenClaw, Claude Code, Codex, Hermes) — not to OpenClaw alone as it once did.
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
				toast.error(`${_w} written · ${_s} skipped · ${_e} failed — check the engine skills mount.`);
			else if (_w === 0)
				toast.warning(
					`Nothing written — ${_s} skill(s) skipped (need a "supported" verdict, or HARVIS_OPENCLAW_SKILLS_DIR is unset).`
				);
			else toast.success(`Sync applied: ${_w} written · ${_s} skipped. Restart the engine sidecars to load changes.`);
			if (!override) await previewSync(); // refresh the dry run (skip after override — it would contradict what was just written)
			syncApplyResult = r; // surface exactly what the apply wrote/skipped
		}
	};

	onMount(async () => {
		if (!token) token = localStorage.getItem('token') || '';
		loadSkills();
	});
</script>

<div class="w-full {mode === 'full' ? 'max-w-4xl mx-auto' : ''}">
	{#if mode === 'full'}
		<!-- Plugins | Skills — the two halves of "what your agents can do". Same switch
		     as ConnectorsPanel, so the pair reads as one surface with two tabs. -->
		<div class="flex justify-center mb-5">
			<div class="inline-flex items-center rounded-lg bg-gray-100 dark:bg-gray-850 p-0.5 text-sm">
				<a href="/harvis/agent-studio/mcp-shop" class="px-4 py-1.5 rounded-lg font-medium text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200 transition">{$i18n.t('Plugins')}</a>
				<span class="px-4 py-1.5 rounded-lg font-medium bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-50 shadow-sm" aria-current="page">{$i18n.t('Skills')}</span>
			</div>
		</div>

		<div class="flex flex-wrap items-start justify-between gap-3 mb-1">
			<div class="min-w-[15rem] flex-1">
				<h1 class="text-2xl font-semibold text-gray-900 dark:text-gray-50">{$i18n.t('Skills')}</h1>
				<p class="text-sm text-gray-500 mt-1">{$i18n.t('Instructions that extend what Harvis and its agents can do.')}</p>
			</div>
			<div class="flex items-center gap-1 shrink-0">
				{#if view === 'yours'}
					<div class="relative">
						<svg class="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
						<input
							bind:value={skillQuery}
							placeholder={$i18n.t('Search skills')}
							aria-label={$i18n.t('Search skills')}
							class="w-52 sm:w-60 h-9 rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 pl-9 pr-3 text-sm outline-none focus:border-gray-400 dark:focus:border-gray-600 transition"
						/>
					</div>
					<button type="button" on:click={loadSkills} title={$i18n.t('Refresh')} class="size-8 grid place-items-center rounded-lg text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-850 transition">
						<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.6-6.4M21 3v6h-6" /></svg>
					</button>
				{/if}
				<button
					type="button"
					title={$i18n.t('New skill')}
					aria-label={$i18n.t('New skill')}
					on:click={() => {
						view = 'yours';
						if (showSkillForm) resetSkillForm();
						else {
							resetSkillForm();
							showSkillForm = true;
						}
					}}
					class="size-9 grid place-items-center rounded-full border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-850 transition"
				>
					<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg>
				</button>
			</div>
		</div>

		<!-- your skills ↔ the community directory -->
		<div class="inline-flex items-center rounded-lg bg-gray-100 dark:bg-gray-850 p-0.5 text-sm mt-5 mb-4">
			<button type="button" on:click={() => (view = 'yours')} class="px-3.5 py-1.5 rounded-lg font-medium transition {view === 'yours' ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-50 shadow-sm' : 'text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200'}">{$i18n.t('Your skills')}</button>
			<button type="button" on:click={() => (view = 'browse')} class="px-3.5 py-1.5 rounded-lg font-medium transition {view === 'browse' ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-50 shadow-sm' : 'text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200'}">{$i18n.t('Directory')}</button>
		</div>
	{:else}
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
				class="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 text-white px-3 py-1.5 text-xs font-medium hover:bg-blue-700 transition"
			>
				<svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg>
				{$i18n.t('New skill')}
			</button>
		</div>
		<p class="text-sm text-gray-500 mb-3">{$i18n.t('A skill is a capability with instructions your agent can apply.')}</p>
	{/if}

	{#if mode === 'full' && view === 'browse'}
		<!-- Directory: GitHub collections + URL import. Its own "← Skills" button
		     returns here rather than to a route, so the tab state stays truthful. -->
		<SkillsBrowse
			{token}
			showBack={false}
			onBack={() => (view = 'yours')}
			onInstalled={() => {
				view = 'yours';
				loadSkills();
			}}
		/>
	{:else}

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

	{#if visibleSkills.length}
		{#each skillSections as sec (sec.id)}
			<div class="text-xs font-semibold text-gray-500 dark:text-gray-400 mt-4 mb-1.5 first:mt-0">{sec.label}</div>
			<div class="space-y-1.5">
			{#each sec.items as s (s.id)}
				<div class="rounded-xl border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-950">
					<div class="px-3 py-2.5 flex items-center gap-3">
						<!-- identity tile: the skill's emoji, else a lettermark keyed off its name -->
						<div class="size-9 shrink-0 rounded-lg grid place-items-center {s.emoji ? 'bg-gray-100 dark:bg-gray-850 text-base' : `${tileOf(s.name)} text-white text-sm font-semibold`}">
							{s.emoji ? s.emoji : initialOf(s.name)}
						</div>
						<div class="min-w-0 flex-1">
							<div class="flex items-center gap-1.5 min-w-0">
								<div class="truncate text-sm font-medium text-gray-800 dark:text-gray-100">{s.name}</div>
								<!-- Governance badge: reads meta.audit.verdict; only 'supported' publishes -->
								<span class="shrink-0 text-[10px] px-1.5 py-0.5 rounded-md border {verdictBadgeClass(verdictOf(s))}" title={$i18n.t('Human audit verdict — only "supported" lets this skill inject/publish')}>{verdictOf(s) ?? $i18n.t('unaudited')}</span>
							</div>
							{#if s.description}<div class="truncate text-xs text-gray-500">{s.description}</div>{/if}
						</div>
						<button on:click={() => toggleSkill(s.id)} title={s.enabled ? $i18n.t('Enabled — this skill is available to your agents') : $i18n.t('Disabled')} class="shrink-0 rounded-md border px-2 py-0.5 text-[11px] font-medium transition {s.enabled ? 'border-green-200 dark:border-green-900 text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-950/40' : 'border-gray-200 dark:border-gray-800 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300'}">{s.enabled ? $i18n.t('On') : $i18n.t('Off')}</button>
						<!-- Row actions live in one menu instead of hover-only icons — hover
						     affordances are unreachable on touch. -->
						<div class="relative shrink-0">
							<button type="button" on:click={() => (menuOpenId = menuOpenId === s.id ? null : s.id)} title={$i18n.t('More')} aria-label={$i18n.t('More')} class="size-8 grid place-items-center rounded-lg text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-850 transition">
								<svg class="size-4" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.7" /><circle cx="12" cy="12" r="1.7" /><circle cx="19" cy="12" r="1.7" /></svg>
							</button>
							{#if menuOpenId === s.id}
								<button type="button" class="fixed inset-0 z-40 cursor-default" on:click={() => (menuOpenId = null)} tabindex="-1" aria-hidden="true"></button>
								<div class="absolute right-0 top-9 z-50 w-48 rounded-xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-900 shadow-lg p-1" transition:fly={{ y: -6, duration: 120 }}>
									<button type="button" on:click={() => { menuOpenId = null; editSkill(s); }} class="w-full text-left px-3 py-1.5 rounded-lg text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-850 transition">{$i18n.t('Edit')}</button>
									<button type="button" on:click={() => { menuOpenId = null; toggleGov(s); }} class="w-full text-left px-3 py-1.5 rounded-lg text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-850 transition">{govOpenId === s.id ? $i18n.t('Hide audit & verdict') : $i18n.t('Audit & verdict')}</button>
									<button type="button" on:click={() => { menuOpenId = null; removeSkill(s.id); }} class="w-full text-left px-3 py-1.5 rounded-lg text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/40 transition">{$i18n.t('Delete')}</button>
								</div>
							{/if}
						</div>
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
										<span class="px-1.5 py-0.5 rounded-md border {a.runnable ? 'border-green-200 dark:border-green-900 text-green-600 dark:text-green-400' : 'border-amber-200 dark:border-amber-900 text-amber-600 dark:text-amber-400'}">{a.runnable ? $i18n.t('runnable here') : $i18n.t('not runnable here')}</span>
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
							<p class="text-[11px] text-gray-400">{$i18n.t('Only a "supported" verdict lets this skill inject into chats and publish to the engines. Editing the skill body invalidates the verdict.')}</p>
						</div>
					{/if}
				</div>
			{/each}
			</div>
		{/each}
	{:else if loadError}
		<div class="rounded-xl border border-gray-100 dark:border-gray-850 px-3 py-6 text-center text-sm text-gray-500">
			{$i18n.t('Could not load skills')} — {loadError}
			<button class="ml-2 text-blue-600 dark:text-blue-400 hover:underline" on:click={loadSkills}>{$i18n.t('Retry')}</button>
		</div>
	{:else if !showSkillForm && !skillsLoaded}
		<div class="text-xs text-gray-500 py-1">{$i18n.t('Loading skills…')}</div>
	{:else if skills.length}
		<!-- skills exist, the search just matched none of them -->
		<div class="rounded-xl border border-gray-100 dark:border-gray-850 px-3 py-8 text-center text-sm text-gray-500">
			{$i18n.t('No skills match your search.')}
			<button class="ml-2 text-blue-600 dark:text-blue-400 hover:underline" on:click={() => (skillQuery = '')}>{$i18n.t('Clear')}</button>
		</div>
	{:else if !showSkillForm}
		<div class="rounded-xl border border-gray-100 dark:border-gray-850 px-3 py-8 text-center text-sm text-gray-500">
			{$i18n.t('No skills yet.')}
			{#if mode === 'full'}
				<button class="ml-1 text-blue-600 dark:text-blue-400 hover:underline" on:click={() => (view = 'browse')}>{$i18n.t('Browse the directory')}</button>
				{$i18n.t('or create one.')}
			{:else}
				{$i18n.t('Create one to get started.')}
			{/if}
		</div>
	{/if}

	<!-- Engine sync (C2): dry-run preview + explicit apply of human-verified skills -->
	<div class="mt-4 rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 p-3 space-y-2">
		<div class="flex items-center justify-between gap-2">
			<div class="flex items-center gap-2">
				<svg class="size-4 text-blue-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.6-6.4M21 3v6h-6" /></svg>
				<div class="text-sm font-medium text-gray-800 dark:text-gray-100">{$i18n.t('Engine sync')}</div>
			</div>
			<div class="flex items-center gap-1.5">
				<button on:click={previewSync} disabled={syncPreviewing} class="rounded-lg border border-gray-200 dark:border-gray-800 px-3 py-1.5 text-xs font-medium text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-850 disabled:opacity-40 transition">{syncPreviewing ? $i18n.t('Previewing…') : $i18n.t('Preview sync')}</button>
				<button on:click={() => applySync(false)} disabled={syncApplying || !syncPreview} title={syncPreview ? $i18n.t('Write verified skills to the shared engine mounts') : $i18n.t('Run a preview first')} class="rounded-lg bg-blue-600 text-white px-3 py-1.5 text-xs font-medium hover:bg-blue-700 disabled:opacity-40">{syncApplying ? $i18n.t('Applying…') : $i18n.t('Apply sync')}</button>
			</div>
		</div>
		<p class="text-xs text-gray-500">
			{$i18n.t('Publishes your skills to every Build engine — OpenClaw, Claude Code, Codex and Hermes read the same skills tree. Only skills with a human "supported" verdict are included. Preview is a dry run — nothing is written until you apply.')}
		</p>

		{#if syncPreview}
			<div class="rounded-lg border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-2.5 space-y-2 text-xs">
				<div>
					<div class="font-semibold uppercase tracking-wide text-[10px] text-gray-400 mb-1">{$i18n.t('Will publish')}</div>
					{#if (syncPreview.skills?.items ?? []).length}
						<div class="flex flex-wrap gap-1">
							{#each syncPreview.skills.items as it (it.id)}
								<span class="px-1.5 py-0.5 rounded-md border border-green-200 dark:border-green-900 text-green-600 dark:text-green-400">{it.name}</span>
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
								<span class="px-1.5 py-0.5 rounded-md border border-amber-200 dark:border-amber-900 text-amber-600 dark:text-amber-400" title={$i18n.t('No "supported" audit verdict — audit the skill and record a verdict to publish it')}>{name}</span>
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
					— {$i18n.t('restart the engine sidecars to load the changes.')}{/if}
			</div>
		{/if}
	</div>
	{/if}
</div>
