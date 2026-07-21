<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';

	const dispatch = createEventDispatcher();
	const i18n: any = getContext('i18n');

	export let projectName = '';
	export let hasProject = false;
	export let sourceLabel = '';
	export let isolationLabel = '';
	export let modeLabel = '';
	export let model = '';
	export let isRunning = false;
	// Branch-lock meta (Build Space preflight) — all optional; each chip hides when null
	// so sessions created before preflight existed render the header unchanged.
	export let repoLabel: string | null = null; // session.repo_display_path
	export let baseBranch: string | null = null;
	export let workBranch: string | null = null;
	export let headSha: string | null = null;
	export let lifecycle = ''; // created | ready | blocked | running
	export let preflight: { clean?: boolean | null; dirty_count?: number } | null = null;
	// Workspace-dock panel toggles for the ⋯ menu: [{ key, label, visible }].
	export let panels: Array<{ key: string; label: string; visible: boolean }> = [];
	export let dockOpen = true;
	// A running #harvis-code (Discord-launched) session, or null. Shown as a live chip
	// on the right → clicking it jumps the user into that session so the web thread
	// mirrors what's happening in Discord. Independent of this tab's own session.
	export let discordSession: any = null;

	let panelsMenuOpen = false;

	$: metaParts = [sourceLabel, isolationLabel, modeLabel, model].filter(
		(p) => typeof p === 'string' && p.trim() !== ''
	);

	$: shortSha = headSha ? headSha.slice(0, 7) : '';
	$: hasBranchMeta = !!(
		(repoLabel && repoLabel !== projectName) ||
		workBranch ||
		shortSha ||
		preflight ||
		lifecycle
	);
</script>

<div
	class="h-11 px-4 flex items-center justify-between border-b border-gray-200 dark:border-white/10 bg-gray-100 dark:bg-gray-950"
>
	<!-- LEFT -->
	<div class="flex items-center gap-3 min-w-0">
		<div class="flex items-center gap-1.5 text-sm shrink-0">
			<span class="text-gray-500">{$i18n.t('Build')}</span>
			{#if hasProject && projectName}
				<span class="text-gray-700">/</span>
				<span class="text-gray-800 dark:text-gray-100 font-medium truncate max-w-[16rem]">
					{projectName}
				</span>
			{/if}
		</div>

		{#if hasProject}
			{#if metaParts.length > 0}
				<div class="flex items-center gap-1.5 min-w-0 text-[11px] text-gray-500">
					<span
						class="w-1.5 h-1.5 rounded-full shrink-0 {isRunning
							? 'bg-blue-500 animate-pulse'
							: 'bg-emerald-500'}"
					/>
					<span class="truncate">{metaParts.join(' · ')}</span>
				</div>
			{:else}
				<div class="flex items-center gap-1.5 shrink-0">
					<span
						class="w-1.5 h-1.5 rounded-full {isRunning
							? 'bg-blue-500 animate-pulse'
							: 'bg-emerald-500'}"
					/>
				</div>
			{/if}

			<!-- Branch-lock meta strip: repo · base → work branch · HEAD sha · clean/dirty · lifecycle.
			     Every chip guards its own null so pre-preflight sessions render nothing extra. -->
			{#if hasBranchMeta}
				<div class="hidden md:flex items-center gap-1 min-w-0 text-[10px] text-gray-400">
					{#if repoLabel && repoLabel !== projectName}
						<span
							class="px-1.5 py-0.5 rounded border border-gray-200 dark:border-white/10 bg-black/[0.03] dark:bg-white/[0.05] truncate max-w-[12rem]"
							title={repoLabel}>{repoLabel}</span
						>
					{/if}
					{#if workBranch}
						<span
							class="px-1.5 py-0.5 rounded border border-gray-200 dark:border-white/10 bg-black/[0.03] dark:bg-white/[0.05] truncate max-w-[16rem]"
							title={baseBranch ? `${baseBranch} → ${workBranch}` : workBranch}
						>
							{#if baseBranch}<span class="text-gray-500">{baseBranch}</span><span
									class="text-gray-600 px-1">→</span
								>{/if}<span class="text-gray-600 dark:text-gray-300">{workBranch}</span>
						</span>
					{/if}
					{#if shortSha}
						<span class="px-1.5 py-0.5 rounded border border-gray-200 dark:border-white/10 bg-black/[0.03] dark:bg-white/[0.05] font-mono text-gray-500"
							>{shortSha}</span
						>
					{/if}
					{#if preflight}
						{#if preflight.clean}
							<span
								class="px-1.5 py-0.5 rounded border border-emerald-500/15 bg-emerald-500/8 text-emerald-400/90"
								>{$i18n.t('clean')}</span
							>
						{:else}
							<span
								class="px-1.5 py-0.5 rounded border border-amber-500/15 bg-amber-500/8 text-amber-400/90"
								>{preflight.dirty_count ?? 0} {$i18n.t('changed')}</span
							>
						{/if}
					{/if}
					{#if lifecycle}
						<span
							class="flex items-center gap-1 px-1.5 py-0.5 rounded border {lifecycle === 'blocked'
								? 'border-amber-500/15 bg-amber-500/8 text-amber-400/90'
								: 'border-gray-200 dark:border-white/10 bg-black/[0.03] dark:bg-white/[0.05] text-gray-400'}"
						>
							<span
								class="w-1 h-1 rounded-full shrink-0 {lifecycle === 'running'
									? 'bg-blue-500 animate-pulse'
									: lifecycle === 'blocked'
										? 'bg-amber-500'
										: lifecycle === 'ready'
											? 'bg-emerald-500'
											: 'bg-gray-400 dark:bg-gray-600'}"
							/>
							{lifecycle}
						</span>
					{/if}
				</div>
			{/if}
		{:else}
			<span class="text-[11px] text-gray-500 truncate">
				{$i18n.t('Choose a repo to start a coding session.')}
			</span>
		{/if}
	</div>

	<!-- RIGHT -->
	<div class="flex items-center gap-1.5 shrink-0">
		{#if discordSession}
			<button
				class="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-lg text-indigo-200 border border-indigo-400/25 bg-indigo-500/12 hover:bg-indigo-500/20 transition"
				on:click={() => dispatch('openDiscord')}
				title={discordSession?.task_brief
					? $i18n.t('Discord session running: {{brief}} — open it here', {
							brief: String(discordSession.task_brief).slice(0, 80)
						})
					: $i18n.t('A Discord #harvis-code session is running — open it here')}
			>
				<span class="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse shrink-0" />
				{$i18n.t('Discord session live')}
			</button>
		{/if}
		{#if hasProject}
			{#if isRunning}
				<button
					class="text-xs px-2.5 py-1 rounded-lg text-red-400 border border-red-500/20 bg-red-500/8 hover:bg-red-500/14 transition"
					on:click={() => dispatch('stop')}
				>
					{$i18n.t('Stop')}
				</button>
			{/if}

			<button
				class="text-xs px-2.5 py-1 rounded-lg text-white border border-sky-400/20 bg-sky-500/80 hover:bg-sky-500 transition"
				on:click={() => dispatch('createPR')}
			>
				{$i18n.t('Create PR')}
			</button>
			<!-- "Open Run" removed: the run inspector overlay pegs the main thread when opened on a
			     LIVE run (unpinned cause). Inspect a finished run via "View run details" on its turn. -->
		{/if}

		<!-- ⋯ menu: choose which workspace-dock panels are open -->
		<div class="relative">
			<button
				class="p-1.5 rounded-lg transition hover:bg-black/[0.04] dark:hover:bg-white/[0.06] {panelsMenuOpen
					? 'text-gray-700 dark:text-gray-200'
					: 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-200'}"
				title={$i18n.t('Workspace panels')}
				aria-label={$i18n.t('Workspace panels')}
				on:click={() => (panelsMenuOpen = !panelsMenuOpen)}
			>
				<svg viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4"
					><path
						d="M10 6a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Zm0 5.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Zm0 5.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z"
					/></svg
				>
			</button>
			{#if panelsMenuOpen}
				<button
					class="fixed inset-0 z-30 cursor-default"
					aria-label={$i18n.t('Close')}
					on:click={() => (panelsMenuOpen = false)}
				></button>
				<div
					class="absolute right-0 top-full mt-1 z-40 w-56 rounded-lg bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-white/10 shadow-xl py-1 text-xs"
				>
					<div class="px-3 pt-1.5 pb-1 text-[10px] uppercase tracking-wider text-gray-500">
						{$i18n.t('Workspace panels')}
					</div>
					{#each panels as p (p.key)}
						<button
							class="w-full flex items-center gap-2 px-3 py-1.5 text-gray-700 dark:text-gray-200 hover:bg-black/[0.04] dark:hover:bg-white/[0.06] transition"
							on:click={() => dispatch('togglePanel', { key: p.key })}
						>
							<span
								class="size-3.5 rounded border flex items-center justify-center shrink-0 {p.visible
									? 'bg-blue-600 border-blue-600'
									: 'border-gray-600'}"
							>
								{#if p.visible}<svg viewBox="0 0 20 20" fill="white" class="size-2.5"
										><path
											fill-rule="evenodd"
											d="M16.7 5.3a1 1 0 0 1 0 1.4l-7.5 7.5a1 1 0 0 1-1.4 0L3.3 9.7a1 1 0 1 1 1.4-1.4l3.1 3.1 6.8-6.8a1 1 0 0 1 1.4 0Z"
											clip-rule="evenodd"
										/></svg
									>{/if}
							</span>
							<span class="flex-1 text-left">{p.label}</span>
						</button>
					{/each}
					<div class="border-t border-gray-200 dark:border-white/10 my-1"></div>
					<button
						class="w-full flex items-center gap-2 px-3 py-1.5 text-gray-600 dark:text-gray-300 hover:bg-black/[0.04] dark:hover:bg-white/[0.06] transition"
						on:click={() => {
							dispatch('toggleDock');
							panelsMenuOpen = false;
						}}
					>
						<svg
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="1.7"
							class="size-3.5"><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M15 4v16" /></svg
						>
						<span class="flex-1 text-left"
							>{dockOpen ? $i18n.t('Hide workspace dock') : $i18n.t('Show workspace dock')}</span
						>
					</button>
				</div>
			{/if}
		</div>

		<button
			class="p-1.5 rounded-lg text-gray-500 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-black/[0.04] dark:hover:bg-white/[0.06] transition"
			title={$i18n.t('Settings')}
			aria-label={$i18n.t('Settings')}
			on:click={() => dispatch('settings')}
		>
			<svg
				xmlns="http://www.w3.org/2000/svg"
				fill="none"
				viewBox="0 0 24 24"
				stroke-width="1.5"
				stroke="currentColor"
				class="w-4 h-4"
			>
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.241.437-.613.43-.992a6.932 6.932 0 0 1 0-.255c.007-.378-.138-.75-.43-.991l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z"
				/>
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z"
				/>
			</svg>
		</button>
	</div>
</div>
