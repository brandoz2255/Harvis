<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { chatMode, pendingComposerPrompt } from '$lib/stores';
	import {
		listCronJobs,
		createCronJob,
		setCronJobStatus,
		deleteCronJob,
		scheduleSummary,
		type CronJob,
		type ScheduleType
	} from '$lib/apis/cron';
	import {
		TEMPLATE_TABS,
		templatesForTab,
		type TemplateTab,
		type AutomationTemplate
	} from '$lib/agent-studio/automationTemplates';

	const i18n: any = getContext('i18n');

	// 'full' = the Automations sub-page (under the Agent Studio hub). 'dock' is
	// reserved for a future right-rail mount.
	export let mode: 'full' | 'dock' = 'full';

	// ── Automations (cron jobs that launch orchestrated runs) ──
	let jobs: CronJob[] = [];
	let loaded = false;
	let scope: 'mine' | 'team' = 'mine';

	const load = async () => {
		loaded = false;
		jobs = await listCronJobs();
		loaded = true;
	};
	onMount(load);

	$: total = jobs.length;
	$: successful = jobs.filter((j) => j.run_count > 0 && j.status !== 'error').length;
	$: failed = jobs.filter((j) => j.status === 'error').length;

	// ── Template gallery ──
	let templateTab: TemplateTab = 'Popular';
	$: templates = templatesForTab(templateTab);

	// One click → fresh chat, Orchestrate mode, auto-send the template prompt.
	const launch = (prompt: string) => {
		chatMode.set('orchestrate');
		pendingComposerPrompt.set(prompt);
		goto('/');
	};
	const useTemplate = (t: AutomationTemplate) => launch(t.prompt);
	const runNow = (j: CronJob) => launch(j.prompt);

	const togglePause = async (j: CronJob) => {
		const next = j.status === 'paused' ? 'scheduled' : 'paused';
		if (await setCronJobStatus(j.id, next)) await load();
	};
	const remove = async (j: CronJob) => {
		if (await deleteCronJob(j.id)) await load();
	};

	const statusColor = (s: string): string =>
		({
			scheduled: 'text-blue-600 dark:text-blue-300 bg-blue-500/10',
			running: 'text-blue-600 dark:text-blue-300 bg-blue-500/10',
			paused: 'text-gray-500 dark:text-gray-400 bg-gray-500/10',
			completed: 'text-green-600 dark:text-green-300 bg-green-500/10',
			error: 'text-red-600 dark:text-red-300 bg-red-500/10'
		})[s] || 'text-gray-500 bg-gray-500/10';

	// ── New Automation modal ──
	let showNew = false;
	let nName = '';
	let nPrompt = '';
	let nType: ScheduleType = 'interval';
	let nExpr = '30m';
	let nSaving = false;
	let nError = '';

	const exprPlaceholder: Record<ScheduleType, string> = {
		interval: '30m  ·  6h  ·  1d',
		cron: '0 9 * * *  (daily 9am)',
		once: '2026-06-20T09:00'
	};

	const openNew = (seed?: AutomationTemplate) => {
		nName = seed?.title ?? '';
		nPrompt = seed?.prompt ?? '';
		nType = 'interval';
		nExpr = '30m';
		nError = '';
		showNew = true;
	};

	const createAutomation = async () => {
		if (!nName.trim() || !nPrompt.trim() || !nExpr.trim()) {
			nError = $i18n.t('Name, task, and schedule are required.');
			return;
		}
		nSaving = true;
		nError = '';
		const res = await createCronJob({
			name: nName.trim(),
			schedule_type: nType,
			schedule_expr: nExpr.trim(),
			prompt: nPrompt.trim(),
			delivery: 'internal',
			metadata: { agent_id: 'orchestrated', source: 'agent-studio' }
		});
		nSaving = false;
		if (res.ok) {
			showNew = false;
			await load();
		} else {
			nError = res.error || $i18n.t('Could not create automation.');
		}
	};
</script>

<div class="w-full h-full overflow-y-auto">
	<div class="max-w-5xl mx-auto px-5 py-6 space-y-6">
		<!-- Header -->
		<header>
			<button
				class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
				on:click={() => goto('/harvis/agent-studio')}>← {$i18n.t('Agent Studio')}</button
			>
			<h1 class="text-2xl font-semibold text-gray-800 dark:text-gray-100 mt-2">
				{$i18n.t('Automations')}
			</h1>
			<p class="text-sm text-gray-500 mt-1">
				{$i18n.t(
					'Automate repetitive tasks with agents that run on a schedule — or launch one now from a template.'
				)}
			</p>
		</header>

		<!-- Stat cards -->
		<div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
			<div class="rounded-xl border border-gray-100 dark:border-gray-850 p-4">
				<div class="text-xs text-gray-500">{$i18n.t('Total Automations')}</div>
				<div class="text-2xl font-semibold text-gray-800 dark:text-gray-100 mt-1 tabular-nums">
					{loaded ? total : '—'}
				</div>
			</div>
			<div class="rounded-xl border border-gray-100 dark:border-gray-850 p-4">
				<div class="text-xs text-gray-500">{$i18n.t('Successful')}</div>
				<div class="text-2xl font-semibold text-green-600 dark:text-green-400 mt-1 tabular-nums">
					{loaded ? successful : '—'}
				</div>
			</div>
			<div class="rounded-xl border border-gray-100 dark:border-gray-850 p-4">
				<div class="text-xs text-gray-500">{$i18n.t('Failed')}</div>
				<div class="text-2xl font-semibold text-red-500 mt-1 tabular-nums">
					{loaded ? failed : '—'}
				</div>
			</div>
			<a
				href="/harvis/agent-studio/global-map"
				class="rounded-xl border border-gray-100 dark:border-gray-850 p-4 hover:border-blue-500/40 hover:bg-blue-500/5 transition flex flex-col"
			>
				<div class="text-xs text-gray-500 flex items-center gap-1">
					{$i18n.t('Run History')}
					<span class="text-blue-500">→</span>
				</div>
				<div class="text-sm text-gray-600 dark:text-gray-300 mt-auto pt-3">
					{$i18n.t('View all runs')}
				</div>
			</a>
		</div>

		<!-- Scope tabs + New Automation -->
		<div class="flex items-center justify-between">
			<div class="flex items-center gap-1 text-sm">
				<button
					class="px-3 py-1 rounded-full transition {scope === 'mine'
						? 'bg-gray-100 dark:bg-gray-850 text-gray-800 dark:text-gray-100 font-medium'
						: 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'}"
					on:click={() => (scope = 'mine')}
				>
					{$i18n.t('Mine')}
					<span class="text-xs text-gray-400">{loaded ? total : 0}</span>
				</button>
				<button
					class="px-3 py-1 rounded-full transition {scope === 'team'
						? 'bg-gray-100 dark:bg-gray-850 text-gray-800 dark:text-gray-100 font-medium'
						: 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300'}"
					on:click={() => (scope = 'team')}
				>
					{$i18n.t('Team')}
					<span class="text-xs text-gray-400">0</span>
				</button>
			</div>
			<button
				class="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white transition"
				on:click={() => openNew()}
			>
				<span class="text-base leading-none">+</span>
				{$i18n.t('New Automation')}
			</button>
		</div>

		<!-- Automation list / empty state -->
		{#if scope === 'team'}
			<div class="rounded-xl border border-gray-100 dark:border-gray-850 py-12 text-center">
				<div class="text-sm font-medium text-gray-700 dark:text-gray-200">
					{$i18n.t('No team automations')}
				</div>
				<p class="text-xs text-gray-500 mt-1">{$i18n.t('Shared automations will appear here.')}</p>
			</div>
		{:else if !loaded}
			<div class="rounded-xl border border-gray-100 dark:border-gray-850 py-12 text-center text-sm text-gray-400">
				{$i18n.t('Loading…')}
			</div>
		{:else if jobs.length === 0}
			<div class="rounded-xl border border-gray-100 dark:border-gray-850 py-12 px-4 text-center">
				<div class="text-base font-medium text-gray-700 dark:text-gray-200">
					{$i18n.t('No Automations Yet')}
				</div>
				<p class="text-sm text-gray-500 mt-1 max-w-md mx-auto">
					{$i18n.t('Run agents on a schedule or automatically in response to events.')}
				</p>
				<button
					class="mt-4 text-sm px-3.5 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-850 transition text-gray-700 dark:text-gray-200"
					on:click={() => openNew()}>{$i18n.t('New Automation')}</button
				>
			</div>
		{:else}
			<div class="space-y-2">
				{#each jobs as j (j.id)}
					<div
						class="rounded-xl border border-gray-100 dark:border-gray-850 px-4 py-3 flex items-center gap-3"
					>
						<div class="min-w-0 flex-1">
							<div class="flex items-center gap-2">
								<span class="text-sm font-medium text-gray-800 dark:text-gray-100 truncate"
									>{j.name}</span
								>
								<span
									class="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded-full shrink-0 {statusColor(
										j.status
									)}">{j.status}</span
								>
							</div>
							<div class="text-xs text-gray-500 mt-0.5 truncate">{j.prompt}</div>
							<div class="text-[11px] text-gray-400 mt-1 flex items-center gap-2 flex-wrap">
								<span>{scheduleSummary(j)}</span>
								<span>·</span>
								<span>{j.run_count} {j.run_count === 1 ? $i18n.t('run') : $i18n.t('runs')}</span>
								{#if j.error_message}
									<span class="text-red-500 truncate">· {j.error_message}</span>
								{/if}
							</div>
						</div>
						<div class="flex items-center gap-1 shrink-0">
							<button
								class="text-xs px-2 py-1 rounded-lg bg-gray-100 dark:bg-gray-850 hover:bg-gray-200 dark:hover:bg-gray-800 transition"
								on:click={() => runNow(j)}>{$i18n.t('Run now')}</button
							>
							<button
								class="text-xs px-2 py-1 rounded-lg bg-gray-100 dark:bg-gray-850 hover:bg-gray-200 dark:hover:bg-gray-800 transition"
								on:click={() => togglePause(j)}
								>{j.status === 'paused' ? $i18n.t('Resume') : $i18n.t('Pause')}</button
							>
							<button
								class="text-xs px-2 py-1 rounded-lg text-red-600 hover:bg-red-50 dark:hover:bg-red-950 transition"
								on:click={() => remove(j)}>{$i18n.t('Delete')}</button
							>
						</div>
					</div>
				{/each}
			</div>
		{/if}

		<!-- Template gallery -->
		<section class="pt-2">
			<h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
				{$i18n.t('Templates')}
			</h2>
			<div class="flex items-center gap-1 flex-wrap mb-3 text-sm">
				{#each TEMPLATE_TABS as t}
					<button
						class="px-3 py-1 rounded-full transition {templateTab === t
							? 'bg-gray-100 dark:bg-gray-850 text-gray-800 dark:text-gray-100 font-medium'
							: 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'}"
						on:click={() => (templateTab = t)}>{$i18n.t(t)}</button
					>
				{/each}
			</div>
			<div class="grid grid-cols-1 md:grid-cols-2 gap-3">
				{#each templates as t (t.id)}
					<div
						class="rounded-xl border border-gray-100 dark:border-gray-850 p-4 flex flex-col gap-2"
					>
						<div class="flex items-center gap-2 text-gray-400">
							<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>
							<span class="text-[10px] uppercase tracking-wide">{$i18n.t(t.category)}</span>
						</div>
						<div class="text-sm font-medium text-gray-800 dark:text-gray-100">{t.title}</div>
						<div class="text-xs text-gray-500 leading-relaxed">{t.description}</div>
						<div class="flex items-center gap-2 mt-1">
							<button
								class="text-xs px-2.5 py-1 rounded-lg bg-gray-100 dark:bg-gray-850 hover:bg-blue-500/10 hover:text-blue-600 dark:hover:text-blue-300 transition"
								on:click={() => useTemplate(t)}>{$i18n.t('Use')}</button
							>
							<button
								class="text-xs px-2.5 py-1 rounded-lg text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition"
								on:click={() => openNew(t)}>{$i18n.t('Schedule')}</button
							>
						</div>
					</div>
				{/each}
			</div>
		</section>
	</div>
</div>

<!-- New Automation modal -->
{#if showNew}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
		on:click|self={() => (showNew = false)}
		role="presentation"
	>
		<div
			class="w-full max-w-lg rounded-2xl bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-850 shadow-xl p-5 space-y-3"
		>
			<div class="flex items-center justify-between">
				<h2 class="text-base font-semibold text-gray-800 dark:text-gray-100">
					{$i18n.t('New Automation')}
				</h2>
				<button class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300" on:click={() => (showNew = false)}>✕</button>
			</div>

			<label class="block">
				<span class="text-xs text-gray-500">{$i18n.t('Name')}</span>
				<input
					bind:value={nName}
					placeholder={$i18n.t('Nightly bug scan')}
					class="w-full mt-1 px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-850 border border-gray-100 dark:border-gray-800 text-sm outline-none focus:border-blue-500/50"
				/>
			</label>

			<label class="block">
				<span class="text-xs text-gray-500">{$i18n.t('Task (runs in Orchestrate mode)')}</span>
				<textarea
					bind:value={nPrompt}
					rows="3"
					placeholder={$i18n.t('Describe what the agents should do…')}
					class="w-full mt-1 px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-850 border border-gray-100 dark:border-gray-800 text-sm outline-none focus:border-blue-500/50 resize-none"
				></textarea>
			</label>

			<div class="flex gap-2">
				<label class="block w-36">
					<span class="text-xs text-gray-500">{$i18n.t('Schedule')}</span>
					<select
						bind:value={nType}
						class="w-full mt-1 px-2 py-2 rounded-lg bg-gray-50 dark:bg-gray-850 border border-gray-100 dark:border-gray-800 text-sm outline-none focus:border-blue-500/50"
					>
						<option value="interval">{$i18n.t('Every…')}</option>
						<option value="cron">{$i18n.t('Cron')}</option>
						<option value="once">{$i18n.t('Once')}</option>
					</select>
				</label>
				<label class="block flex-1">
					<span class="text-xs text-gray-500">{$i18n.t('When')}</span>
					<input
						bind:value={nExpr}
						placeholder={exprPlaceholder[nType]}
						class="w-full mt-1 px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-850 border border-gray-100 dark:border-gray-800 text-sm font-mono outline-none focus:border-blue-500/50"
					/>
				</label>
			</div>

			{#if nError}<div class="text-xs text-red-500">{nError}</div>{/if}

			<div class="flex items-center justify-end gap-2 pt-1">
				<button
					class="text-sm px-3 py-1.5 rounded-lg text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
					on:click={() => (showNew = false)}>{$i18n.t('Cancel')}</button
				>
				<button
					class="text-sm px-3.5 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white transition disabled:opacity-50"
					disabled={nSaving}
					on:click={createAutomation}
					>{nSaving ? $i18n.t('Creating…') : $i18n.t('Create Automation')}</button
				>
			</div>
		</div>
	</div>
{/if}
