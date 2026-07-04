<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';

	const dispatch = createEventDispatcher();
	const i18n: any = getContext('i18n');

	// ── Props (data in ONLY — no fetch, no stores, no onMount loading) ──────────
	// Agents currently in the run: { name, status: 'running' | 'pending' | 'done' }.
	export let agents: Array<{ name: string; status?: string }> = [];
	// Background tasks split by lane:
	//   runningTasks  — live tasks for THIS session (shown first)
	//   finishedTasks — completed/failed tasks for THIS session (under "This session")
	//   otherRuns     — every other workspace run (under "All workspace runs")
	// Each task: { id, task_brief?, task?, status, model_name?, source? }.
	export let runningTasks: Array<any> = [];
	export let finishedTasks: Array<any> = [];
	export let otherRuns: Array<any> = [];
	// Pending approval, or null. { tool, command?, risk? }.
	export let approval: { tool?: string; command?: string; risk?: string } | null = null;
	// Whether a run is live (drives the Plan empty-state copy nuance).
	export let isRunning = false;
	// True when the orchestrator has not produced a plan yet.
	export let planEmpty = false;

	// ── Section model ───────────────────────────────────────────────────────────
	const SECTIONS = [
		{ key: 'plan', title: () => $i18n.t('Plan') },
		{ key: 'agents', title: () => $i18n.t('Agents') },
		{ key: 'background', title: () => $i18n.t('Background tasks') },
		{ key: 'approvals', title: () => $i18n.t('Approvals') }
	];

	// Per-section collapse state (content visibility) — default all open.
	let open: Record<string, boolean> = { plan: true, agents: true, background: true, approvals: true };
	// Per-section hide state (removed from the rail until restored).
	let hidden: Set<string> = new Set();

	const toggle = (key: string) => {
		open = { ...open, [key]: !open[key] };
	};

	const dismiss = (key: string) => {
		hidden = new Set(hidden).add(key);
		dispatch('dismiss', { key });
	};

	const restore = (key: string) => {
		const next = new Set(hidden);
		next.delete(key);
		hidden = next;
	};

	$: visibleSections = SECTIONS.filter((s) => !hidden.has(s.key));
	$: hiddenSections = SECTIONS.filter((s) => hidden.has(s.key));

	// ── Status helpers (Harvis status-dot palette) ──────────────────────────────
	const dot = (s?: string): string =>
		s === 'done'
			? 'bg-emerald-500'
			: s === 'error'
				? 'bg-red-500'
				: s === 'cancelled'
					? 'bg-amber-500'
					: s === 'running'
						? 'bg-blue-500 animate-pulse'
						: 'bg-gray-400';

	const statusWord = (s?: string): string =>
		s === 'running'
			? $i18n.t('Running')
			: s === 'done'
				? $i18n.t('Completed')
				: s === 'error'
					? $i18n.t('Failed')
					: s === 'cancelled'
						? $i18n.t('Cancelled')
						: $i18n.t('Pending');

	const taskLabel = (t: any): string => t?.task_brief || t?.task || $i18n.t('Run');

	$: bgEmpty = !runningTasks.length && !finishedTasks.length && !otherRuns.length;
</script>

<div class="flex flex-col gap-2 text-xs">
	{#each visibleSections as section (section.key)}
		<section class="rounded-xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900">
			<!-- Header: chevron toggle · title · dismiss(x) -->
			<div class="flex items-center gap-1.5 px-2 py-1.5">
				<button
					type="button"
					class="shrink-0 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition"
					aria-label={open[section.key] ? $i18n.t('Collapse') : $i18n.t('Expand')}
					on:click={() => toggle(section.key)}
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 20 20"
						fill="currentColor"
						class="size-3.5 transition-transform duration-150 {open[section.key] ? 'rotate-90' : ''}"
					>
						<path
							fill-rule="evenodd"
							d="M7.21 14.77a.75.75 0 0 1 .02-1.06L11.168 10 7.23 6.29a.75.75 0 1 1 1.04-1.08l4.5 4.25a.75.75 0 0 1 0 1.08l-4.5 4.25a.75.75 0 0 1-1.06-.02Z"
							clip-rule="evenodd"
						/>
					</svg>
				</button>
				<span class="text-xs font-medium text-gray-700 dark:text-gray-200">{section.title()}</span>
				<button
					type="button"
					class="ml-auto shrink-0 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition"
					aria-label={$i18n.t('Hide section')}
					on:click={() => dismiss(section.key)}
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 20 20"
						fill="currentColor"
						class="size-3.5"
					>
						<path
							d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z"
						/>
					</svg>
				</button>
			</div>

			{#if open[section.key]}
				<div class="px-2 pb-2">
					<!-- ── PLAN ─────────────────────────────────────────────── -->
					{#if section.key === 'plan'}
						{#if planEmpty}
							<div class="text-[11px] text-gray-400 leading-snug px-0.5 py-1">
								{$i18n.t(
									'No plan yet. Harvis will outline steps here once an agent starts.'
								)}
							</div>
						{:else}
							<slot name="plan" />
						{/if}

					<!-- ── AGENTS ───────────────────────────────────────────── -->
					{:else if section.key === 'agents'}
						{#if agents.length}
							<div class="space-y-0.5">
								{#each agents as agent (agent.name)}
									<div class="flex items-center gap-2 px-0.5 py-1 rounded-md">
										<span class="size-1.5 rounded-full shrink-0 {dot(agent.status)}"></span>
										<span class="truncate text-[11px] text-gray-700 dark:text-gray-200"
											>{agent.name}</span
										>
										<span class="ml-auto text-[10px] text-gray-400 shrink-0"
											>{statusWord(agent.status)}</span
										>
									</div>
								{/each}
							</div>
						{:else}
							<div class="text-[11px] text-gray-400 px-0.5 py-1">
								{$i18n.t('No agents active.')}
							</div>
						{/if}

					<!-- ── BACKGROUND TASKS ─────────────────────────────────── -->
					{:else if section.key === 'background'}
						{#if bgEmpty}
							<div class="text-[11px] text-gray-400 px-0.5 py-1">
								{$i18n.t('Nothing running.')}
							</div>
						{:else}
							<!-- live tasks first -->
							{#each runningTasks as task (task.id)}
								<div
									class="group flex items-center gap-2 px-1 py-1 rounded-md hover:bg-gray-100 dark:hover:bg-gray-850 transition cursor-pointer"
									role="button"
									tabindex="0"
									on:click={() => dispatch('openRun', { id: task.id })}
									on:keydown={(e) => e.key === 'Enter' && dispatch('openRun', { id: task.id })}
								>
									<span class="size-1.5 rounded-full shrink-0 {dot(task.status)}"></span>
									<span class="truncate text-[11px] text-gray-700 dark:text-gray-200"
										>{taskLabel(task)}</span
									>
									<span class="ml-auto text-[10px] text-gray-400 shrink-0">{statusWord(task.status)}</span>
									<button
										type="button"
										class="shrink-0 text-[10px] text-red-500 hover:text-red-400 transition"
										on:click|stopPropagation={() => dispatch('stopTask', { id: task.id })}
										>{$i18n.t('Stop')}</button
									>
								</div>
							{/each}

							<!-- this-session finished -->
							{#if finishedTasks.length}
								<div class="flex items-center gap-1.5 mt-1.5 mb-0.5 px-0.5">
									<span class="text-[10px] font-medium text-gray-500 uppercase tracking-wide"
										>{$i18n.t('This session')}</span
									>
									<button
										type="button"
										class="ml-auto text-[10px] text-blue-600 dark:text-blue-400 hover:underline"
										on:click={() => dispatch('clearBg')}>{$i18n.t('Clear')}</button
									>
								</div>
								{#each finishedTasks as task (task.id)}
									<div
										class="flex items-center gap-2 px-1 py-1 rounded-md hover:bg-gray-100 dark:hover:bg-gray-850 transition cursor-pointer"
										role="button"
										tabindex="0"
										on:click={() => dispatch('openRun', { id: task.id })}
										on:keydown={(e) => e.key === 'Enter' && dispatch('openRun', { id: task.id })}
									>
										<span class="size-1.5 rounded-full shrink-0 {dot(task.status)}"></span>
										<span class="truncate text-[11px] text-gray-700 dark:text-gray-200"
											>{taskLabel(task)}</span
										>
										<span class="ml-auto text-[10px] text-gray-400 shrink-0"
											>{statusWord(task.status)}</span
										>
									</div>
								{/each}
							{/if}

							<!-- all other workspace runs -->
							{#if otherRuns.length}
								<div class="mt-1.5 mb-0.5 px-0.5">
									<span class="text-[10px] font-medium text-gray-500 uppercase tracking-wide"
										>{$i18n.t('All workspace runs')}</span
									>
								</div>
								{#each otherRuns as task (task.id)}
									<div
										class="flex items-center gap-2 px-1 py-1 rounded-md hover:bg-gray-100 dark:hover:bg-gray-850 transition cursor-pointer"
										role="button"
										tabindex="0"
										on:click={() => dispatch('openRun', { id: task.id })}
										on:keydown={(e) => e.key === 'Enter' && dispatch('openRun', { id: task.id })}
									>
										<span class="size-1.5 rounded-full shrink-0 {dot(task.status)}"></span>
										<span class="truncate text-[11px] text-gray-700 dark:text-gray-200"
											>{taskLabel(task)}</span
										>
										<span class="ml-auto text-[10px] text-gray-400 shrink-0"
											>{statusWord(task.status)}</span
										>
									</div>
								{/each}
							{/if}
						{/if}

					<!-- ── APPROVALS ────────────────────────────────────────── -->
					{:else if section.key === 'approvals'}
						{#if approval}
							<div class="rounded-lg border border-amber-300 dark:border-amber-500/40 bg-amber-50 dark:bg-amber-500/10 p-2">
								<div class="flex items-center gap-1.5">
									<span class="size-1.5 rounded-full bg-amber-500 shrink-0"></span>
									<span class="text-[11px] font-medium text-amber-700 dark:text-amber-300"
										>{$i18n.t('Approval needed')}</span
									>
								</div>
								<div class="text-[11px] text-gray-500 mt-1.5">{$i18n.t('Harvis wants to run:')}</div>
								<code
									class="block mt-1 px-1.5 py-1 rounded-md bg-gray-100 dark:bg-gray-850 text-[11px] font-mono text-gray-800 dark:text-gray-100 break-all whitespace-pre-wrap"
									>{approval.command || approval.tool}</code
								>
								<div class="flex items-center gap-1.5 mt-2">
									<button
										type="button"
										class="px-2.5 py-1 rounded-md text-[11px] font-medium bg-blue-600 text-white hover:bg-blue-700 transition"
										on:click={() => dispatch('approve')}>{$i18n.t('Approve')}</button
									>
									<button
										type="button"
										class="px-2.5 py-1 rounded-md text-[11px] font-medium text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-850 transition"
										on:click={() => dispatch('deny')}>{$i18n.t('Deny')}</button
									>
								</div>
							</div>
						{:else}
							<div class="text-[11px] text-gray-400 px-0.5 py-1">
								{$i18n.t('No approvals pending.')}
							</div>
						{/if}
					{/if}
				</div>
			{/if}
		</section>
	{/each}

	<!-- Restore strip for hidden sections -->
	{#if hiddenSections.length}
		<div class="flex flex-wrap items-center gap-1 pt-0.5">
			{#each hiddenSections as section (section.key)}
				<button
					type="button"
					class="px-2 py-0.5 rounded-full text-[10px] text-gray-500 border border-gray-100 dark:border-gray-850 hover:bg-gray-100 dark:hover:bg-gray-850 hover:text-gray-700 dark:hover:text-gray-200 transition"
					on:click={() => restore(section.key)}>+ {section.title()}</button
				>
			{/each}
		</div>
	{/if}
</div>
