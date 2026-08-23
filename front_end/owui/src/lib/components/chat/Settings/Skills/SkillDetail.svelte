<script lang="ts">
	// Skill detail — in-panel viewer for one skill (Settings › Skills). Enable
	// toggle NEVER bypasses governance: injection stays gated on a human
	// 'supported' verdict (owui_compat/skills.gated_skill_blocks), and this view
	// says so honestly. Audit / verdict / export / delete all hit the real API.
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import fileSaver from 'file-saver';
	const { saveAs } = fileSaver;

	import {
		getSkillById,
		toggleSkillById,
		deleteSkillById,
		auditSkill,
		setSkillVerdict
	} from '$lib/apis/skills';
	import { user } from '$lib/stores';

	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Markdown from '$lib/components/chat/Messages/Markdown.svelte';
	import ChevronLeft from '$lib/components/icons/ChevronLeft.svelte';
	import InfoCircle from '$lib/components/icons/InfoCircle.svelte';
	import EllipsisHorizontal from '$lib/components/icons/EllipsisHorizontal.svelte';
	import Document from '$lib/components/icons/Document.svelte';
	import Download from '$lib/components/icons/Download.svelte';
	import GarbageBin from '$lib/components/icons/GarbageBin.svelte';
	import Pencil from '$lib/components/icons/Pencil.svelte';

	export let skill: any;
	export let token = '';
	export let onBack: () => void = () => {};
	export let onEdit: () => void = () => {};
	export let onChanged: (s: any) => void = () => {};
	export let onDeleted: () => void = () => {};

	const i18n: any = getContext('i18n');

	// Same FactCheckVerdict vocabulary as SkillsPanel / skill_audit.py.
	const VERDICTS = [
		'supported',
		'partially_supported',
		'unsupported',
		'contradicted',
		'insufficient_evidence'
	] as const;

	let showMenu = false;
	let menuButtonEl: HTMLButtonElement;
	let viewMode: 'rendered' | 'source' = 'rendered';
	let descExpanded = false;
	let showAuditInfo = false;
	let showDeleteConfirm = false;
	let auditing = false;
	let auditResult: any = null; // last audit response this session (real API payload)
	let verdictDraft = '';
	let verdictNotes = '';
	let savingVerdict = false;

	$: verdict = skill?.meta?.audit?.verdict ?? null;
	$: audit = skill?.meta?.audit ?? {};
	$: author =
		$user && String($user.id) === String(skill?.user_id)
			? $i18n.t('You')
			: (skill?.meta?.author ?? '—');
	$: descLong = (skill?.description ?? '').length > 160;

	const refresh = async () => {
		const full = await getSkillById(token, skill.id).catch(() => null);
		if (full) {
			skill = full;
			onChanged(full);
		}
	};

	const toggle = async () => {
		const res = await toggleSkillById(token, skill.id).catch((e) => {
			toast.error(`${e}`);
			return null;
		});
		if (res) {
			skill = res;
			onChanged(res);
		} else {
			await refresh(); // revert the optimistic switch to server truth
		}
	};

	const runAudit = async () => {
		if (auditing) return;
		showMenu = false;
		auditing = true;
		showAuditInfo = true;
		const r = await auditSkill(token, skill.id).catch((e) => {
			toast.error(`${e}`);
			return null;
		});
		auditing = false;
		if (r) {
			auditResult = r;
			await refresh();
		}
	};

	const exportSkill = async () => {
		showMenu = false;
		const full = await getSkillById(token, skill.id).catch((e) => {
			toast.error(`${e}`);
			return null;
		});
		if (full) {
			saveAs(
				new Blob([JSON.stringify([full])], { type: 'application/json' }),
				`skill-${full.id}-export-${Date.now()}.json`
			);
		}
	};

	const saveVerdict = async () => {
		if (!verdictDraft || savingVerdict) return;
		savingVerdict = true;
		const r = await setSkillVerdict(
			token,
			skill.id,
			verdictDraft as any,
			verdictNotes.trim() || null
		).catch((e) => {
			toast.error(`${e}`);
			return null;
		});
		savingVerdict = false;
		if (r) {
			toast.success(
				r.publishable
					? $i18n.t('Verdict recorded — this skill can now inject and publish.')
					: $i18n.t('Verdict recorded — only a "supported" verdict injects/publishes.')
			);
			await refresh();
		}
	};

	const removeSkill = async () => {
		const res = await deleteSkillById(token, skill.id).catch((e) => {
			toast.error(`${e}`);
			return null;
		});
		if (res) {
			toast.success($i18n.t('Skill deleted'));
			onDeleted();
		}
	};
</script>

<div class="pt-1">
	<button
		class="-ml-1.5 inline-flex items-center gap-1 rounded-lg px-1.5 py-1 text-sm text-gray-500 hover:text-gray-800 dark:hover:text-gray-100 hover:bg-gray-50 dark:hover:bg-gray-900 transition"
		on:click={onBack}
	>
		<ChevronLeft className="size-4" strokeWidth="2" />
		{$i18n.t('Skills')}
	</button>

	<div class="mt-2 flex items-start gap-2">
		<div class="min-w-0 flex-1">
			<div class="flex min-w-0 flex-wrap items-center gap-1.5">
				<h3 class="truncate text-xl font-semibold text-gray-800 dark:text-gray-100">
					{skill.emoji ? `${skill.emoji} ` : ''}{skill.name}
				</h3>
				<Tooltip content={`ID: ${skill.id}`}>
					<button
						type="button"
						class="cursor-default text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition"
						aria-label={`${$i18n.t('Skill ID')}: ${skill.id}`}
					>
						<InfoCircle className="size-4" strokeWidth="1.8" />
					</button>
				</Tooltip>
				<span class="text-sm text-gray-500">{$i18n.t('by')} {author}</span>
			</div>
		</div>

		<div class="flex shrink-0 items-center gap-1.5 pt-1">
			<Tooltip content={skill.enabled ? $i18n.t('Enabled') : $i18n.t('Disabled')}>
				<Switch bind:state={skill.enabled} on:change={toggle} />
			</Tooltip>

			<Dropdown
				bind:show={showMenu}
				align="end"
				onOpenChange={(state) => {
					if (!state) menuButtonEl?.focus();
				}}
			>
				<button
					bind:this={menuButtonEl}
					class="rounded-lg p-1.5 text-gray-500 hover:text-gray-800 dark:hover:text-gray-100 hover:bg-gray-50 dark:hover:bg-gray-900 transition"
					aria-label={$i18n.t('Skill actions')}
					aria-haspopup="menu"
					aria-expanded={showMenu}
				>
					<EllipsisHorizontal className="size-5" />
				</button>

				<div slot="content">
					<div
						class="w-60 rounded-xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-900 p-1 shadow-lg"
						role="menu"
					>
						<button
							class="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-sm text-gray-800 dark:text-gray-100 hover:bg-gray-50 dark:hover:bg-gray-850 transition"
							role="menuitem"
							on:click={() => {
								showMenu = false;
								onEdit();
							}}
						>
							<Pencil className="size-4 text-gray-400" strokeWidth="1.8" />
							{$i18n.t('Edit skill')}
						</button>
						<button
							class="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-sm text-gray-800 dark:text-gray-100 hover:bg-gray-50 dark:hover:bg-gray-850 transition disabled:opacity-40"
							role="menuitem"
							disabled={auditing}
							on:click={runAudit}
						>
							<svg
								class="size-4 text-gray-400"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.8"
								stroke-linecap="round"
								stroke-linejoin="round"
								><path d="M12 2 4 5.5v5.2c0 4.9 3.4 9.5 8 10.8 4.6-1.3 8-5.9 8-10.8V5.5L12 2z" /></svg
							>
							{auditing ? $i18n.t('Auditing…') : $i18n.t('Audit skill')}
						</button>
						<button
							class="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-sm text-gray-800 dark:text-gray-100 hover:bg-gray-50 dark:hover:bg-gray-850 transition"
							role="menuitem"
							on:click={() => {
								showMenu = false;
								showAuditInfo = !showAuditInfo;
							}}
						>
							<InfoCircle className="size-4 text-gray-400" strokeWidth="1.8" />
							{showAuditInfo ? $i18n.t('Hide audit info') : $i18n.t('View audit info')}
						</button>
						<button
							class="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-sm text-gray-800 dark:text-gray-100 hover:bg-gray-50 dark:hover:bg-gray-850 transition"
							role="menuitem"
							on:click={exportSkill}
						>
							<Download className="size-4 text-gray-400" strokeWidth="1.8" />
							{$i18n.t('Export')}
						</button>
						<button
							class="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-sm text-gray-800 dark:text-gray-100 hover:bg-gray-50 dark:hover:bg-gray-850 transition"
							role="menuitem"
							on:click={() => {
								showMenu = false;
								toggle();
							}}
						>
							<span class="size-4 flex items-center justify-center">
								<span
									class="size-1.5 rounded-full {skill.enabled
										? 'bg-blue-500'
										: 'bg-gray-300 dark:bg-gray-600'}"
								></span>
							</span>
							{skill.enabled ? $i18n.t('Disable') : $i18n.t('Enable')}
						</button>
						<hr class="my-1 border-gray-100 dark:border-gray-850" />
						<button
							class="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-sm text-gray-800 dark:text-gray-100 hover:bg-gray-50 dark:hover:bg-gray-850 transition"
							role="menuitem"
							on:click={() => {
								showMenu = false;
								showDeleteConfirm = true;
							}}
						>
							<GarbageBin className="size-4 text-gray-400" strokeWidth="1.8" />
							{$i18n.t('Delete')}
						</button>
					</div>
				</div>
			</Dropdown>
		</div>
	</div>

	{#if skill.enabled && verdict !== 'supported'}
		<!-- Governance honesty: enabling never makes an unaudited skill injectable
		     (fail-closed gate in gated_skill_blocks). -->
		<p class="mt-1 text-xs text-gray-400">
			{$i18n.t(
				'Enabled, but not injectable yet — a human "supported" audit verdict is required before this skill applies in chats.'
			)}
		</p>
	{/if}

	{#if skill.description}
		<p class="mt-2 text-sm text-gray-500 {descExpanded ? '' : 'line-clamp-2'}">
			{skill.description}
		</p>
		{#if descLong}
			<button
				class="mt-0.5 text-xs text-blue-600 dark:text-blue-400 hover:underline"
				on:click={() => (descExpanded = !descExpanded)}
			>
				{descExpanded ? $i18n.t('See less') : $i18n.t('See more')}
			</button>
		{/if}
	{/if}

	{#if showAuditInfo}
		<div
			class="mt-3 rounded-xl border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-950 px-3 py-2.5 space-y-2"
		>
			<div class="text-xs font-semibold uppercase tracking-wide text-gray-400">
				{$i18n.t('Audit & verdict')}
			</div>
			<div class="text-xs text-gray-500 space-y-0.5">
				<div>
					{$i18n.t('Verdict')}:
					<span class={verdict === 'supported' ? 'text-blue-600 dark:text-blue-400' : ''}
						>{verdict ? verdict.replaceAll('_', ' ') : $i18n.t('none — unaudited')}</span
					>
					{#if audit?.stale_after_edit && !verdict}
						· {$i18n.t('invalidated by a content edit')}
					{/if}
				</div>
				{#if audit?.notes}<div>{$i18n.t('Notes')}: {audit.notes}</div>{/if}
				{#if audit?.last_run_id}
					<div>
						{$i18n.t('Last audit')}: <code class="font-mono">run {audit.last_run_id}</code
						>{audit?.last_run_at ? ` · ${audit.last_run_at}` : ''}
					</div>
				{/if}
			</div>

			{#if auditing}
				<div class="flex items-center gap-2 text-xs text-gray-500">
					<Spinner className="size-3.5" />
					{$i18n.t('Running audit…')}
				</div>
			{:else if auditResult}
				<div
					class="rounded-lg border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-2.5 space-y-1.5"
				>
					<div class="flex items-center gap-2 text-[11px]">
						<span
							class="rounded-md border px-1.5 py-0.5 {auditResult.runnable
								? 'border-blue-200 dark:border-blue-900 text-blue-600 dark:text-blue-400'
								: 'border-gray-200 dark:border-gray-800 text-gray-500'}"
							>{auditResult.runnable
								? $i18n.t('runnable here')
								: $i18n.t('not runnable here')}</span
						>
						{#if auditResult.run_id}<code class="font-mono text-gray-400"
								>run {auditResult.run_id}</code
							>{/if}
					</div>
					{#if (auditResult.findings ?? []).length}
						<ul class="space-y-0.5 text-xs text-gray-600 dark:text-gray-300">
							{#each auditResult.findings as f}
								<li>· {f}</li>
							{/each}
						</ul>
					{/if}
					{#if auditResult.analysis_md}
						<pre
							class="max-h-48 overflow-y-auto whitespace-pre-wrap font-mono text-xs text-gray-600 dark:text-gray-300">{auditResult.analysis_md}</pre>
					{/if}
				</div>
			{:else}
				<div class="text-[11px] text-gray-400">
					{$i18n.t('Run an audit, then record a verdict — only "supported" injects/publishes.')}
				</div>
			{/if}

			<!-- Human verdict recorder — same API + vocabulary as the agent-studio panel. -->
			<div class="flex flex-col gap-2 sm:flex-row">
				<select
					bind:value={verdictDraft}
					class="rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent dark:bg-gray-950 px-3 py-1.5 text-xs outline-none focus:border-blue-500"
					aria-label={$i18n.t('Audit verdict')}
				>
					<option value="">{$i18n.t('Choose a verdict…')}</option>
					{#each VERDICTS as v}
						<option value={v}>{v}</option>
					{/each}
				</select>
				<input
					bind:value={verdictNotes}
					placeholder={$i18n.t('Notes (optional)')}
					class="flex-1 rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent px-3 py-1.5 text-xs outline-none focus:border-blue-500"
				/>
				<button
					class="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-40 transition"
					disabled={!verdictDraft || savingVerdict}
					on:click={saveVerdict}
					>{savingVerdict ? $i18n.t('Saving…') : $i18n.t('Record verdict')}</button
				>
			</div>
		</div>
	{/if}

	<!-- Viewer — single content field on the backend, so the only real file is SKILL.md. -->
	<div
		class="mt-3 overflow-hidden rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900"
	>
		<div
			class="flex items-center justify-between gap-2 border-b border-gray-100 dark:border-gray-850 px-3 py-2"
		>
			<span
				class="inline-flex items-center gap-1.5 text-xs font-medium text-gray-600 dark:text-gray-300"
			>
				<Document className="size-3.5 text-gray-400" strokeWidth="1.8" />
				SKILL.md
			</span>
			<div class="flex items-center gap-0.5 rounded-lg bg-gray-100 dark:bg-gray-850 p-0.5">
				<button
					class="rounded-md px-2 py-0.5 text-xs transition {viewMode === 'rendered'
						? 'bg-white dark:bg-gray-900 text-gray-800 dark:text-gray-100 shadow-sm'
						: 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'}"
					aria-pressed={viewMode === 'rendered'}
					on:click={() => (viewMode = 'rendered')}
				>
					{$i18n.t('Rendered')}
				</button>
				<button
					class="rounded-md px-2 py-0.5 text-xs transition {viewMode === 'source'
						? 'bg-white dark:bg-gray-900 text-gray-800 dark:text-gray-100 shadow-sm'
						: 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'}"
					aria-pressed={viewMode === 'source'}
					on:click={() => (viewMode = 'source')}
				>
					{$i18n.t('Source')}
				</button>
			</div>
		</div>
		<div class="max-h-[22rem] overflow-y-auto px-4 py-3">
			{#if !(skill.content ?? '').trim()}
				<p class="text-sm text-gray-500">
					{$i18n.t('This skill has no instructions yet.')}
				</p>
			{:else if viewMode === 'rendered'}
				<div class="text-sm">
					<Markdown id={`settings-skill-${skill.id}`} content={skill.content} />
				</div>
			{:else}
				<pre
					class="whitespace-pre-wrap font-mono text-xs text-gray-700 dark:text-gray-300">{skill.content}</pre>
			{/if}
		</div>
	</div>
</div>

<ConfirmDialog
	bind:show={showDeleteConfirm}
	title={$i18n.t('Delete skill?')}
	on:confirm={removeSkill}
>
	<div class="text-sm text-gray-500 truncate">
		{$i18n.t('This will delete')} <span class="font-medium">{skill.name}</span>.
	</div>
</ConfirmDialog>
