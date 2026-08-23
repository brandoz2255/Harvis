<script lang="ts">
	// Skills manager — Settings › Customize › Skills. Desktop-native list →
	// Add dropdown → in-panel detail/editor (Claude-desktop style). Talks to the
	// REAL skills API (lib/apis/skills → owui_compat/skills.py) and the existing
	// governance lane (skill_audit) — nothing here fabricates data. The shared
	// agent-studio SkillsPanel stays untouched for /harvis/agent-studio/customize.
	import { getContext, onMount, tick } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { user, skills as skillsStore } from '$lib/stores';
	import { parseFrontmatter, formatSkillName } from '$lib/utils';
	import { getSkills, getSkillById, createNewSkill, updateSkillById } from '$lib/apis/skills';

	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Skeleton from '$lib/components/common/Skeleton.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import Sparkles from '$lib/components/icons/Sparkles.svelte';
	import Pencil from '$lib/components/icons/Pencil.svelte';
	import DocumentArrowUp from '$lib/components/icons/DocumentArrowUp.svelte';
	import SkillEditor from '$lib/components/workspace/Skills/SkillEditor.svelte';
	import SkillDetail from './SkillDetail.svelte';
	import SkillsBrowse from './SkillsBrowse.svelte';

	export let token = '';

	const i18n: any = getContext('i18n');

	let view: 'list' | 'detail' | 'create' | 'edit' | 'browse' = 'list';
	let skills: any[] = [];
	let loading = true;
	let loadError = '';
	let selected: any = null;
	let draftSkill: any = null; // prefill for the create-mode editor (template / upload)

	let searchOpen = false;
	let searchQuery = '';
	let searchInputEl: HTMLInputElement;

	let showAddMenu = false;
	let addButtonEl: HTMLButtonElement;
	let uploadInputEl: HTMLInputElement;
	let uploadFiles: FileList | null = null;

	const loadSkills = async () => {
		loadError = '';
		const r = await getSkills(token).catch((e) => {
			loadError = `${e}`;
			return null;
		});
		if (r) {
			skills = Array.isArray(r) ? r : (r?.skills ?? r?.items ?? []);
			// Keep the chat skill-attachment store in sync (same as the workspace page).
			skillsStore.set(skills as any);
		}
		loading = false;
	};

	const verdictOf = (s: any): string | null => s?.meta?.audit?.verdict ?? null;
	// Owner-scoped API (WHERE user_id = current user) → author is the signed-in
	// user; fall back to meta.author if a record ever carries one. Never invented.
	const authorOf = (s: any): string =>
		$user && String($user.id) === String(s?.user_id)
			? $i18n.t('You')
			: String(s?.meta?.author ?? '—');
	const fmtDate = (ts: number | null): string =>
		ts
			? new Date(ts * 1000).toLocaleDateString(undefined, {
					month: 'numeric',
					day: 'numeric',
					year: '2-digit'
				})
			: '—';

	$: filtered = searchQuery.trim()
		? skills.filter((s) => {
				const q = searchQuery.trim().toLowerCase();
				return (
					(s.name ?? '').toLowerCase().includes(q) ||
					(s.description ?? '').toLowerCase().includes(q) ||
					authorOf(s).toLowerCase().includes(q)
				);
			})
		: skills;

	const openSearch = async () => {
		searchOpen = true;
		await tick();
		searchInputEl?.focus();
	};

	const openDetail = async (s: any) => {
		selected = s;
		view = 'detail';
		const full = await getSkillById(token, s.id).catch(() => null);
		if (full) {
			selected = full;
			skills = skills.map((x) => (x.id === full.id ? full : x));
		}
	};

	// ── Add menu ────────────────────────────────────────────────────────────
	// No AI-guided creation flow is wired in this panel yet (the composer "/"
	// skill creator is a queued project) — "Create with Harvis" honestly opens
	// the manual editor pre-filled with a starter SKILL.md template.
	const STARTER_SKILL = `---
name: my-skill
description: One line on when this skill applies.
---

# Instructions

Write the step-by-step instructions the agent should follow when this skill is attached.
`;

	const startCreate = (prefill: any = null) => {
		showAddMenu = false;
		draftSkill = prefill;
		view = 'create';
	};

	const onUploadChange = () => {
		if (!uploadFiles || uploadFiles.length === 0) return;
		const file = uploadFiles[0];
		const ext = file.name.split('.').pop()?.toLowerCase();
		const reader = new FileReader();
		reader.onload = async (event) => {
			const content = event.target?.result;
			if (typeof content !== 'string') return;
			if (ext === 'json') {
				// Same import contract as the workspace page: JSON export → create via API.
				try {
					const parsed = JSON.parse(content);
					const items = Array.isArray(parsed) ? parsed : [parsed];
					let created = 0;
					for (const skill of items) {
						const r = await createNewSkill(token, skill).catch((e) => {
							toast.error(`${e}`);
							return null;
						});
						if (r) created += 1;
					}
					if (created > 0) {
						toast.success($i18n.t('Skill imported successfully'));
						await loadSkills();
					}
				} catch (e) {
					toast.error($i18n.t('Invalid JSON file'));
				}
			} else {
				// Markdown: parse frontmatter and open the editor pre-filled for review.
				const fm: any = parseFrontmatter(content);
				const fileName = file.name.replace(/\.md$/, '');
				startCreate({
					name: formatSkillName(fm.name || fileName),
					id: fm.name || '',
					description: fm.description || '',
					content
				});
			}
		};
		reader.readAsText(file);
		uploadInputEl.value = '';
	};

	// ── Editor submit handlers ──────────────────────────────────────────────
	const submitCreate = async (payload: any) => {
		const res = await createNewSkill(token, payload).catch((e) => {
			toast.error(`${e}`);
			return null;
		});
		if (res) {
			toast.success($i18n.t('Skill created'));
			draftSkill = null;
			await loadSkills();
			selected = res;
			view = 'detail';
		}
	};

	const submitEdit = async (payload: any) => {
		if (!selected) return;
		// Preserve server-visible meta keys (requires_capabilities, risk_lane, …);
		// audit/revisions are server-managed and carried over by the backend.
		const res = await updateSkillById(token, selected.id, {
			...payload,
			meta: { ...(selected.meta ?? {}), ...(payload.meta ?? {}) }
		}).catch((e) => {
			toast.error(`${e}`);
			return null;
		});
		if (res) {
			// Honest governance surface: the backend nulls the verdict when the body
			// changes (stale_after_edit) — say so instead of a blanket "saved".
			if (res?.meta?.audit?.stale_after_edit && !verdictOf(res)) {
				toast.warning(
					$i18n.t(
						'Saved. The content changed, so the previous audit verdict was invalidated — re-audit before this skill can inject again.'
					)
				);
			} else {
				toast.success($i18n.t('Skill saved'));
			}
			selected = res;
			skills = skills.map((x) => (x.id === res.id ? res : x));
			skillsStore.set(skills as any);
			view = 'detail';
		}
	};

	onMount(async () => {
		if (!token) token = localStorage.getItem('token') || '';
		loadSkills();
	});
</script>

{#if view === 'create'}
	<div class="h-[min(36rem,calc(100dvh-12rem))] pt-1">
		<SkillEditor
			onSubmit={submitCreate}
			skill={draftSkill}
			onBack={() => {
				draftSkill = null;
				view = 'list';
			}}
		/>
	</div>
{:else if view === 'edit' && selected}
	<div class="h-[min(36rem,calc(100dvh-12rem))] pt-1">
		<SkillEditor edit onSubmit={submitEdit} skill={selected} onBack={() => (view = 'detail')} />
	</div>
{:else if view === 'browse'}
	<SkillsBrowse
		{token}
		onBack={() => (view = 'list')}
		onInstalled={async () => {
			await loadSkills();
			view = 'list';
		}}
	/>
{:else if view === 'detail' && selected}
	<SkillDetail
		skill={selected}
		{token}
		onBack={() => {
			view = 'list';
			loadSkills();
		}}
		onEdit={() => (view = 'edit')}
		onChanged={(s) => {
			if (s) {
				selected = s;
				skills = skills.map((x) => (x.id === s.id ? s : x));
				skillsStore.set(skills as any);
			}
		}}
		onDeleted={() => {
			skills = skills.filter((x) => x.id !== selected.id);
			skillsStore.set(skills as any);
			selected = null;
			view = 'list';
		}}
	/>
{:else}
	<div class="pt-1">
		<div class="flex items-center gap-1.5 mb-1">
			<h2 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{$i18n.t('Skills')}</h2>
			<div class="flex-1"></div>

			{#if searchOpen}
				<div
					class="flex items-center gap-1.5 rounded-lg border border-gray-200 dark:border-gray-800 px-2 py-1"
				>
					<Search className="size-3.5 text-gray-400" />
					<input
						bind:this={searchInputEl}
						bind:value={searchQuery}
						class="w-40 bg-transparent text-sm outline-hidden placeholder:text-gray-400"
						placeholder={$i18n.t('Search skills')}
						aria-label={$i18n.t('Search skills')}
						on:keydown={(e) => {
							if (e.key === 'Escape') {
								e.stopPropagation();
								searchQuery = '';
								searchOpen = false;
							}
						}}
					/>
					<button
						class="rounded-lg p-0.5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition"
						aria-label={$i18n.t('Close search')}
						on:click={() => {
							searchQuery = '';
							searchOpen = false;
						}}
					>
						<XMark className="size-3.5" />
					</button>
				</div>
			{:else}
				<Tooltip content={$i18n.t('Search skills')}>
					<button
						class="rounded-lg p-1.5 text-gray-500 hover:text-gray-800 dark:hover:text-gray-100 hover:bg-gray-50 dark:hover:bg-gray-900 transition"
						aria-label={$i18n.t('Search skills')}
						on:click={openSearch}
					>
						<Search className="size-4" />
					</button>
				</Tooltip>
			{/if}

			<!-- Browse lives as a row at the bottom of the list now (see below) —
			     one action in the header, everything else in the list. -->
			<Dropdown
				bind:show={showAddMenu}
				align="end"
				onOpenChange={(state) => {
					if (!state) addButtonEl?.focus();
				}}
			>
				<button
					bind:this={addButtonEl}
					class="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 transition"
					aria-haspopup="menu"
					aria-expanded={showAddMenu}
				>
					{$i18n.t('Add')}
					<ChevronDown className="size-3" strokeWidth="2.5" />
				</button>

				<div slot="content">
					<div
						class="w-60 rounded-xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-900 p-1 shadow-lg"
						role="menu"
					>
						<button
							class="flex w-full items-start gap-2.5 rounded-lg px-2.5 py-2 text-left hover:bg-gray-50 dark:hover:bg-gray-850 transition"
							role="menuitem"
							on:click={() => startCreate({ content: STARTER_SKILL })}
						>
							<Sparkles className="size-4 mt-0.5 shrink-0 text-blue-500" strokeWidth="1.8" />
							<span>
								<span class="block text-sm text-gray-800 dark:text-gray-100"
									>{$i18n.t('Create with Harvis')}</span
								>
								<span class="block text-xs text-gray-400"
									>{$i18n.t('Opens a starter SKILL.md template')}</span
								>
							</span>
						</button>
						<button
							class="flex w-full items-start gap-2.5 rounded-lg px-2.5 py-2 text-left hover:bg-gray-50 dark:hover:bg-gray-850 transition"
							role="menuitem"
							on:click={() => startCreate()}
						>
							<Pencil className="size-4 mt-0.5 shrink-0 text-gray-400" strokeWidth="1.8" />
							<span>
								<span class="block text-sm text-gray-800 dark:text-gray-100"
									>{$i18n.t('Write skill instructions')}</span
								>
								<span class="block text-xs text-gray-400"
									>{$i18n.t('Start from a blank editor')}</span
								>
							</span>
						</button>
						<button
							class="flex w-full items-start gap-2.5 rounded-lg px-2.5 py-2 text-left hover:bg-gray-50 dark:hover:bg-gray-850 transition"
							role="menuitem"
							on:click={() => {
								showAddMenu = false;
								uploadInputEl?.click();
							}}
						>
							<DocumentArrowUp className="size-4 mt-0.5 shrink-0 text-gray-400" strokeWidth="1.8" />
							<span>
								<span class="block text-sm text-gray-800 dark:text-gray-100"
									>{$i18n.t('Upload a skill')}</span
								>
								<span class="block text-xs text-gray-400">{$i18n.t('.md or exported .json')}</span>
							</span>
						</button>
					</div>
				</div>
			</Dropdown>

			<input
				bind:this={uploadInputEl}
				bind:files={uploadFiles}
				type="file"
				accept=".md,.json"
				hidden
				on:change={onUploadChange}
			/>
		</div>
		<p class="text-sm text-gray-500 mb-3">
			{$i18n.t('Reusable instructions your agent can apply when a skill is attached to a chat.')}
		</p>

		{#if loading}
			<!-- Content-shaped skeleton mirroring the skills table rows (title + status
			     chip, description line, date + author columns) — bound to `loading`,
			     which always resolves to the table, empty state, or loadError. -->
			<div aria-busy="true">
				<div aria-hidden="true">
					{#each Array.from({ length: 5 }) as _, i}
						<div class="flex items-start gap-3 border-b border-gray-100 dark:border-gray-850 py-3">
							<div class="min-w-0 flex-1">
								<div class="flex items-center gap-2">
									<Skeleton width={['42%', '30%', '52%', '36%', '46%'][i]} height="0.875rem" delay={i * 90} />
									<Skeleton width="2.5rem" height="0.625rem" rounded="rounded-lg" delay={i * 90} />
								</div>
								<Skeleton width={['64%', '48%', '70%', '56%', '60%'][i]} height="0.625rem" className="mt-1.5" delay={i * 90} />
							</div>
							<Skeleton width="3.5rem" height="0.75rem" className="mt-0.5 shrink-0" delay={i * 90} />
							<Skeleton width="2.5rem" height="0.75rem" className="mt-0.5 shrink-0" delay={i * 90} />
						</div>
					{/each}
				</div>
				<span class="sr-only" role="status">{$i18n.t('Loading skills…')}</span>
			</div>
		{:else if loadError}
			<div
				class="rounded-xl border border-gray-100 dark:border-gray-850 px-3 py-6 text-center text-sm text-gray-500"
			>
				{$i18n.t('Could not load skills')} — {loadError}
				<button
					class="ml-2 text-blue-600 dark:text-blue-400 hover:underline"
					on:click={() => {
						loading = true;
						loadSkills();
					}}>{$i18n.t('Retry')}</button
				>
			</div>
		{:else if filtered.length}
			<!-- Rows, not a table: icon tile · name + one-line description · chevron.
			     The date/author columns moved into one muted line so the row stays
			     readable at Settings width. -->
			<div>
				{#each filtered as s (s.id)}
					<button
						type="button"
						class="w-full flex items-center gap-3 py-3 px-2 -mx-2 rounded-lg border-b border-gray-100 dark:border-gray-850 text-left hover:bg-gray-50 dark:hover:bg-gray-900/60 transition"
						aria-label={`${$i18n.t('Open')} ${s.name}`}
						on:click={() => openDetail(s)}
					>
						<div
							class="shrink-0 size-9 grid place-items-center rounded-lg bg-gray-50 dark:bg-gray-800/70 border border-gray-200/70 dark:border-gray-700/60 text-base text-gray-500 dark:text-gray-300"
						>
							{s.emoji ? s.emoji : (s.name ?? '·').trim().charAt(0).toUpperCase()}
						</div>
						<div class="min-w-0 flex-1">
							<div class="flex items-center gap-2 min-w-0">
								<span class="truncate text-sm font-medium text-gray-900 dark:text-gray-100"
									>{s.name}</span
								>
								<!-- Quiet governance state — same semantics as SkillsPanel:
								     meta.audit.verdict; only 'supported' injects/publishes. -->
								{#if !s.enabled}
										<Tooltip content={$i18n.t('Disabled — this skill is off')}>
											<span
												class="inline-flex shrink-0 items-center gap-1 text-[11px] text-gray-400"
											>
												<span class="size-1.5 rounded-full bg-gray-300 dark:bg-gray-600"></span>
												{$i18n.t('Off')}
											</span>
										</Tooltip>
									{:else if verdictOf(s) === 'supported'}
										<Tooltip
											content={$i18n.t('Human audit verdict "supported" — injects and publishes')}
										>
											<span
												class="inline-flex shrink-0 items-center gap-1 text-[11px] text-blue-600 dark:text-blue-400"
											>
												<span class="size-1.5 rounded-full bg-blue-500"></span>
												{$i18n.t('Supported')}
											</span>
										</Tooltip>
									{:else if verdictOf(s)}
										<Tooltip
											content={$i18n.t(
												'Human audit verdict — only "supported" lets this skill inject/publish'
											)}
										>
											<span
												class="inline-flex shrink-0 items-center gap-1 text-[11px] text-gray-400"
											>
												<span class="size-1.5 rounded-full bg-gray-400 dark:bg-gray-500"></span>
												{verdictOf(s)?.replaceAll('_', ' ')}
											</span>
										</Tooltip>
									{:else}
										<Tooltip
											content={$i18n.t(
												'Not audited — a human must mark it "supported" before it can inject'
											)}
										>
											<span
												class="inline-flex shrink-0 items-center gap-1 text-[11px] text-gray-400"
											>
												<span class="size-1.5 rounded-full bg-gray-300 dark:bg-gray-600"></span>
												{$i18n.t('Unaudited')}
											</span>
										</Tooltip>
							{/if}
						</div>
						{#if s.description}
							<div class="mt-0.5 truncate text-xs text-gray-500">{s.description}</div>
						{/if}
					</div>
					<span class="hidden sm:block shrink-0 text-[11px] text-gray-400 whitespace-nowrap"
						>{fmtDate(s.updated_at)} · {authorOf(s)}</span
					>
					<svg
						class="size-4 shrink-0 text-gray-300 dark:text-gray-600"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2.2"
						stroke-linecap="round"
						stroke-linejoin="round"
						aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg
					>
					</button>
				{/each}
			</div>
		{:else if skills.length}
			<div class="py-10 text-center text-sm text-gray-500">
				{$i18n.t('No skills match')} “{searchQuery}”
			</div>
		{:else}
			<div class="py-10 text-center">
				<div class="text-sm font-medium text-gray-700 dark:text-gray-200">
					{$i18n.t('No skills yet')}
				</div>
				<div class="mt-1 text-xs text-gray-500">
					{$i18n.t('Use Add to write, upload, or start a skill from a template.')}
				</div>
			</div>
		{/if}

		<!-- Always reachable, whether or not you have skills yet. Browsing is free
		     and installs a SKILL.md as an unaudited draft — see SkillsBrowse. -->
		<button
			type="button"
			class="w-full flex items-center gap-3 py-3 px-2 -mx-2 mt-1 rounded-lg text-left hover:bg-gray-50 dark:hover:bg-gray-900/60 transition"
			on:click={() => (view = 'browse')}
		>
			<div
				class="shrink-0 size-9 grid place-items-center rounded-lg bg-gray-50 dark:bg-gray-800/70 border border-gray-200/70 dark:border-gray-700/60 text-gray-400"
			>
				<Search className="size-4" />
			</div>
			<div class="min-w-0 flex-1">
				<div class="text-sm font-medium text-gray-900 dark:text-gray-100">
					{$i18n.t('Browse skill directory')}
				</div>
				<div class="truncate text-xs text-gray-500">
					{$i18n.t('Install skills published by Anthropic and the community')}
				</div>
			</div>
			<svg
				class="size-4 shrink-0 text-gray-300 dark:text-gray-600"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2.2"
				stroke-linecap="round"
				stroke-linejoin="round"
				aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg
			>
		</button>
	</div>
{/if}
