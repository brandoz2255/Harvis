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
		getCronStats,
		type CronJob,
		type AutomationStats,
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
	export let embed = false; // mounted inside another page → drop the page wrapper + header
	// Two lenses over the ONE cron store, split on metadata.context:
	//   'coding' → Routines: fires launch workspace runs (the original behavior)
	//   'chat'   → Schedules: fires run the prompt and post the reply into a chat
	export let context: 'coding' | 'chat' = 'coding';

	$: lensTitle = context === 'chat' ? 'Schedules' : 'Routines';
	$: lensNoun = context === 'chat' ? 'Schedule' : 'Routine';
	$: lensBlurb =
		context === 'chat'
			? 'Schedules run a prompt on a timer and post the reply into a chat.'
			: 'Routines run agent tasks on a schedule — they run server-side while Harvis is up.';

	// ── Cron jobs for this lens ──
	let jobs: CronJob[] = [];
	let stats: AutomationStats = { successful_7d: 0, failed_7d: 0, recent: [] };
	let loaded = false;
	let scope: 'mine' | 'team' = 'mine';

	const load = async () => {
		loaded = false;
		// Stats aggregate workspace runs — only meaningful for the coding lens
		// (chat-context fires deliver into a chat, not workspace_runs).
		const [j, s] = await Promise.all([
			listCronJobs(context),
			context === 'coding' ? getCronStats() : Promise.resolve(stats)
		]);
		jobs = j;
		stats = s;
		loaded = true;
	};
	onMount(load);

	$: total = jobs.length;
	// Real 7-day run outcomes (from the runs the cron tick actually launched).
	$: successful = stats.successful_7d;
	$: failed = stats.failed_7d;

	const relTime = (iso: string | null): string => {
		if (!iso) return '';
		const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
		if (s < 60) return 'just now';
		if (s < 3600) return `${Math.floor(s / 60)}m ago`;
		if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
		return `${Math.floor(s / 86400)}d ago`;
	};
	const inTime = (iso: string | null): string => {
		if (!iso) return '';
		const s = (new Date(iso).getTime() - Date.now()) / 1000;
		if (s <= 0) return 'due now';
		if (s < 60) return 'in <1m';
		if (s < 3600) return `in ${Math.round(s / 60)}m`;
		if (s < 86400) return `in ${Math.round(s / 3600)}h`;
		return `in ${Math.round(s / 86400)}d`;
	};
	const runStatusColor = (s: string): string =>
		s === 'done'
			? 'text-green-500'
			: s === 'error'
				? 'text-red-500'
				: s === 'cancelled'
					? 'text-amber-500'
					: 'text-blue-500';

	// ── Template gallery ──
	let templateTab: TemplateTab = 'Popular';
	$: templates = templatesForTab(templateTab);

	// One click → fresh chat, auto-send the prompt. Coding lens fires in
	// Orchestrate mode (matching how its scheduled fires run); the chat lens
	// sends a plain chat message (matching its chat delivery).
	const launch = (prompt: string) => {
		if (context === 'coding') chatMode.set('orchestrate');
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

	// ── New Routine/Schedule modal ──
	let showNew = false;
	let nName = '';
	let nPrompt = '';
	let nSaving = false;
	let nError = '';

	// Basic schedule picker — produces the cron/interval expr under the hood.
	// 'advanced' is the raw-expression escape hatch (the old input).
	type PickerMode = 'daily' | 'weekly' | 'hours' | 'advanced';
	let pMode: PickerMode = 'daily';
	let pTime = '09:00';
	let pDay = 1; // 0=Sun … 6=Sat
	let pHours = 6;
	let nType: ScheduleType = 'interval';
	let nExpr = '30m';
	const DAYS: { value: number; label: string }[] = [
		{ value: 1, label: 'Monday' },
		{ value: 2, label: 'Tuesday' },
		{ value: 3, label: 'Wednesday' },
		{ value: 4, label: 'Thursday' },
		{ value: 5, label: 'Friday' },
		{ value: 6, label: 'Saturday' },
		{ value: 0, label: 'Sunday' }
	];

	const exprPlaceholder: Record<ScheduleType, string> = {
		interval: '30m  ·  6h  ·  1d',
		cron: '0 9 * * *  (daily 9am)',
		once: '2026-06-20T09:00'
	};

	const builtSchedule = (): { type: ScheduleType; expr: string } | null => {
		if (pMode === 'advanced') {
			return nExpr.trim() ? { type: nType, expr: nExpr.trim() } : null;
		}
		if (pMode === 'hours') {
			const n = Math.floor(Number(pHours));
			return n >= 1 ? { type: 'interval', expr: `${n}h` } : null;
		}
		const [h, m] = (pTime || '').split(':').map((x) => parseInt(x, 10));
		if (Number.isNaN(h) || Number.isNaN(m)) return null;
		// The backend evaluates crons in UTC, but the picker shows the user's LOCAL time —
		// convert local → UTC so "Daily at 9:00" fires at the user's 9:00 (weekly day can
		// roll across midnight). scheduleSummary() converts back to local for display.
		const d = new Date();
		d.setHours(h, m, 0, 0);
		if (pMode === 'daily') return { type: 'cron', expr: `${d.getUTCMinutes()} ${d.getUTCHours()} * * *` };
		d.setDate(d.getDate() + (((pDay - d.getDay()) + 7) % 7));
		return { type: 'cron', expr: `${d.getUTCMinutes()} ${d.getUTCHours()} * * ${d.getUTCDay()}` };
	};

	const openNew = (seed?: AutomationTemplate) => {
		nName = seed?.title ?? '';
		nPrompt = seed?.prompt ?? '';
		pMode = 'daily';
		pTime = '09:00';
		pDay = 1;
		pHours = 6;
		nType = 'interval';
		nExpr = '30m';
		nError = '';
		showNew = true;
	};

	const createAutomation = async () => {
		const sched = builtSchedule();
		if (!nName.trim() || !nPrompt.trim() || !sched) {
			nError = $i18n.t('Name, task, and schedule are required.');
			return;
		}
		nSaving = true;
		nError = '';
		const res = await createCronJob({
			name: nName.trim(),
			schedule_type: sched.type,
			schedule_expr: sched.expr,
			prompt: nPrompt.trim(),
			delivery: 'internal',
			// context tags the lens; the tick loop dispatches on it (chat → post
			// the reply into a chat; coding → orchestrated workspace run).
			metadata:
				context === 'chat'
					? { agent_id: 'main', source: 'agent-studio', context }
					: { agent_id: 'orchestrated', source: 'agent-studio', context }
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

<div class={embed ? '' : 'w-full h-full overflow-y-auto'}>
	<div class={embed ? 'space-y-6' : 'max-w-5xl mx-auto px-5 py-6 space-y-6'}>
		{#if !embed}
			<!-- Header -->
			<header>
				<button
					class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
					on:click={() => goto('/harvis/agent-studio')}>← {$i18n.t('Agent Studio')}</button
				>
				<h1 class="text-2xl font-semibold text-gray-800 dark:text-gray-100 mt-2">
					{$i18n.t(lensTitle)}
				</h1>
				<p class="text-sm text-gray-500 mt-1">
					{context === 'chat'
						? $i18n.t(lensBlurb)
						: $i18n.t(
								'Automate repetitive tasks with agents that run on a schedule — or launch one now from a template.'
							)}
				</p>
			</header>
		{/if}

		<!-- Stat cards — workspace-run outcomes; only the coding lens launches runs. -->
		{#if context === 'coding'}
		<div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
			<div class="rounded-xl border border-gray-100 dark:border-gray-850 p-4">
				<div class="text-xs text-gray-500">{$i18n.t('Total Routines')}</div>
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
		{/if}

		<!-- Scope tabs + New Routine/Schedule -->
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
				{$i18n.t(`New ${lensNoun}`)}
			</button>
		</div>

		<!-- Automation list / empty state -->
		{#if scope === 'team'}
			<div class="rounded-xl border border-gray-100 dark:border-gray-850 py-12 text-center">
				<div class="text-sm font-medium text-gray-700 dark:text-gray-200">
					{$i18n.t(`No team ${lensTitle.toLowerCase()}`)}
				</div>
				<p class="text-xs text-gray-500 mt-1">
					{$i18n.t(`Shared ${lensTitle.toLowerCase()} will appear here.`)}
				</p>
			</div>
		{:else if !loaded}
			<div class="rounded-xl border border-gray-100 dark:border-gray-850 py-12 text-center text-sm text-gray-400">
				{$i18n.t('Loading…')}
			</div>
		{:else if jobs.length === 0}
			<div class="rounded-xl border border-gray-100 dark:border-gray-850 py-12 px-4 text-center">
				<div class="text-base font-medium text-gray-700 dark:text-gray-200">
					{$i18n.t(`No ${lensTitle} Yet`)}
				</div>
				<p class="text-sm text-gray-500 mt-1 max-w-md mx-auto">
					{context === 'chat'
						? $i18n.t(lensBlurb)
						: $i18n.t('Run agents on a schedule or automatically in response to events.')}
				</p>
				<button
					class="mt-4 text-sm px-3.5 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-850 transition text-gray-700 dark:text-gray-200"
					on:click={() => openNew()}>{$i18n.t(`New ${lensNoun}`)}</button
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
								{#if j.next_run_at && j.status === 'scheduled'}
									<span>· {$i18n.t('next')} {inTime(j.next_run_at)}</span>
								{/if}
								{#if j.last_run_at}
									<span>· {$i18n.t('last')} {relTime(j.last_run_at)}</span>
								{/if}
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

		<p class="text-[11px] text-gray-400">
			{context === 'chat'
				? $i18n.t('Schedules run a prompt on a timer and post the reply into a chat.')
				: $i18n.t('Routines run server-side while Harvis is up.')}
		</p>

		<!-- Recent runs — the workspace runs the coding-lens fires launched -->
		{#if context === 'coding' && stats.recent.length}
			<section>
				<h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
					{$i18n.t('Recent runs')}
				</h2>
				<div
					class="rounded-xl border border-gray-100 dark:border-gray-850 divide-y divide-gray-100 dark:divide-gray-850"
				>
					{#each stats.recent as r (r.id)}
						<a
							href={`/harvis/agent-studio/run/${r.id}`}
							class="flex items-center gap-2.5 px-4 py-2.5 hover:bg-gray-50 dark:hover:bg-gray-850 transition"
						>
							<span class="shrink-0 text-[10px] {runStatusColor(r.status)}">●</span>
							<span class="text-sm text-gray-700 dark:text-gray-200 truncate flex-1"
								>{r.task_brief || $i18n.t('Automation run')}</span
							>
							<span class="text-[10px] uppercase tracking-wide text-gray-400 shrink-0">{r.status}</span>
							<span class="text-xs text-gray-400 shrink-0 tabular-nums">{relTime(r.started_at)}</span>
						</a>
					{/each}
				</div>
			</section>
		{/if}

		<!-- Template gallery — agent/ops task seeds; coding lens only -->
		{#if context === 'coding'}
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
		{/if}
	</div>
</div>

<!-- New Routine/Schedule modal -->
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
					{$i18n.t(`New ${lensNoun}`)}
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
				<span class="text-xs text-gray-500"
					>{context === 'chat'
						? $i18n.t('Prompt (the reply is posted into a chat)')
						: $i18n.t('Task (runs in Orchestrate mode)')}</span
				>
				<textarea
					bind:value={nPrompt}
					rows="3"
					placeholder={context === 'chat'
						? $i18n.t('What should Harvis answer on this timer?')
						: $i18n.t('Describe what the agents should do…')}
					class="w-full mt-1 px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-850 border border-gray-100 dark:border-gray-800 text-sm outline-none focus:border-blue-500/50 resize-none"
				></textarea>
			</label>

			<!-- Basic schedule picker — builds the cron/interval expr under the hood. -->
			<div class="flex gap-2">
				<label class="block w-44">
					<span class="text-xs text-gray-500">{$i18n.t('Schedule')}</span>
					<select
						bind:value={pMode}
						class="w-full mt-1 px-2 py-2 rounded-lg bg-gray-50 dark:bg-gray-850 border border-gray-100 dark:border-gray-800 text-sm outline-none focus:border-blue-500/50"
					>
						<option value="daily">{$i18n.t('Daily at…')}</option>
						<option value="weekly">{$i18n.t('Weekly on…')}</option>
						<option value="hours">{$i18n.t('Every N hours')}</option>
						<option value="advanced">{$i18n.t('Advanced (cron)')}</option>
					</select>
				</label>
				{#if pMode === 'daily'}
					<label class="block flex-1">
						<span class="text-xs text-gray-500">{$i18n.t('Time')}</span>
						<input
							type="time"
							bind:value={pTime}
							class="w-full mt-1 px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-850 border border-gray-100 dark:border-gray-800 text-sm outline-none focus:border-blue-500/50"
						/>
					</label>
				{:else if pMode === 'weekly'}
					<label class="block w-32">
						<span class="text-xs text-gray-500">{$i18n.t('Day')}</span>
						<select
							bind:value={pDay}
							class="w-full mt-1 px-2 py-2 rounded-lg bg-gray-50 dark:bg-gray-850 border border-gray-100 dark:border-gray-800 text-sm outline-none focus:border-blue-500/50"
						>
							{#each DAYS as d (d.value)}
								<option value={d.value}>{$i18n.t(d.label)}</option>
							{/each}
						</select>
					</label>
					<label class="block flex-1">
						<span class="text-xs text-gray-500">{$i18n.t('Time')}</span>
						<input
							type="time"
							bind:value={pTime}
							class="w-full mt-1 px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-850 border border-gray-100 dark:border-gray-800 text-sm outline-none focus:border-blue-500/50"
						/>
					</label>
				{:else if pMode === 'hours'}
					<label class="block flex-1">
						<span class="text-xs text-gray-500">{$i18n.t('Hours between runs')}</span>
						<input
							type="number"
							min="1"
							step="1"
							bind:value={pHours}
							class="w-full mt-1 px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-850 border border-gray-100 dark:border-gray-800 text-sm outline-none focus:border-blue-500/50"
						/>
					</label>
				{:else}
					<label class="block w-28">
						<span class="text-xs text-gray-500">{$i18n.t('Type')}</span>
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
				{/if}
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
					>{nSaving ? $i18n.t('Creating…') : $i18n.t(`Create ${lensNoun}`)}</button
				>
			</div>
		</div>
	</div>
{/if}
