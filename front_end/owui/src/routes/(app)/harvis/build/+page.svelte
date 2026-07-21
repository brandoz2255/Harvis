<script lang="ts">
	// Build = the HUB (bridged from the prototype): GitHub Workspace + Local CLI
	// entry cards, then Recent Projects / Recent Runs / Agent Templates. The full
	// VibeCode IDE is the deep "coding session" surface at /harvis/vibecode that
	// this hub opens into.
	import { getContext, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';
	import { WEBUI_NAME, chatId } from '$lib/stores';
	import { listVibecodeSessions, type VibecodeSession } from '$lib/apis/agent-runs';
	import Skeleton from '$lib/components/common/Skeleton.svelte';

	const i18n: any = getContext('i18n');
	const backToChat = () => goto($chatId ? `/c/${$chatId}` : '/');
	const soon = (what: string) => toast.info($i18n.t('{{what}} — coming soon.', { what }));
	const openVibe = () => goto('/harvis/vibecode');

	type ProjectRow = { id: string; label: string; repo: string | null; emoji: string | null };
	let projects: ProjectRow[] = [];
	let loadingP = true;
	let runs: any[] = [];
	let loadingR = true;

	// "What the chat is doing" = the session's latest task. Repo (codespace) sessions
	// set their title to the repo name, so for those we pull the turn's task_brief.
	const sessionTask = async (id: string): Promise<string | null> => {
		try {
			const r = await fetch(`/api/workspace/vibecode/session/${id}`, {
				headers: { Authorization: `Bearer ${localStorage.token}` },
				credentials: 'include'
			});
			if (!r.ok) return null;
			const turns = (await r.json()).turns ?? [];
			return turns.length ? turns[turns.length - 1].task_brief || turns[0].task_brief || null : null;
		} catch {
			return null;
		}
	};

	onMount(async () => {
		let sessions: VibecodeSession[] = [];
		try {
			sessions = (await listVibecodeSessions())?.slice(0, 5) ?? [];
		} catch {
			sessions = [];
		}
		projects = await Promise.all(
			sessions.map(async (s) => {
				// Subtitle only when there's a real owner/repo display name — never the clone-dir UUID.
				const repo = s.repo_display_path || null;
				let label = s.title || '';
				if (s.repo_path) {
					const t = await sessionTask(s.id);
					if (t) label = t;
				}
				if (!label) label = repo || $i18n.t('Untitled session');
				return {
					id: s.id,
					label,
					repo: s.repo_path && repo && repo !== label ? repo : null,
					emoji: s.emoji ?? null
				};
			})
		);
		loadingP = false;
		try {
			const r = await fetch('/api/workspace/history', {
				headers: { Authorization: `Bearer ${localStorage.token}` },
				credentials: 'include'
			});
			runs = r.ok ? ((await r.json()).runs ?? []).slice(0, 6) : [];
		} catch {
			runs = [];
		}
		loadingR = false;
	});

	// Unified cockpit palette (see runFormat.ts): running=blue-pulse · done=emerald ·
	// error=red · cancelled=gray (inert). amber = "needs YOU" only.
	const runDot = (s?: string) =>
		s === 'error'
			? 'bg-red-500'
			: s === 'running'
				? 'bg-blue-500 animate-pulse'
				: s === 'cancelled'
					? 'bg-gray-400 dark:bg-gray-600'
					: 'bg-emerald-500';

	const openProject = (id: string) => goto(`/harvis/vibecode?session=${id}`);

	const templates = [
		{ label: 'Backend API', desc: 'Scaffold and iterate a backend service.' },
		{ label: 'Data Pipeline', desc: 'Build an ingestion / transform job.' },
		{ label: 'Code Review', desc: 'Review a repo and propose fixes.' }
	];

	const chevron =
		'<svg class="size-4 text-gray-400 shrink-0 group-hover:text-blue-500 transition" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>';
</script>

<svelte:head>
	<title>{$i18n.t('Build')} • {$WEBUI_NAME}</title>
</svelte:head>

<div class="w-full h-full overflow-y-auto">
	<div class="max-w-5xl mx-auto px-5 py-6 space-y-8">
		<!-- Header -->
		<header>
			<button
				class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
				on:click={backToChat}>← {$i18n.t('Back to chat')}</button
			>
			<div class="flex items-center justify-between gap-3 mt-2">
				<h1 class="text-2xl font-semibold text-gray-800 dark:text-gray-100">{$i18n.t('Build')}</h1>
				<button
					on:click={() => goto('/harvis/console')}
					class="inline-flex items-center gap-1.5 rounded-full border border-gray-200 dark:border-gray-800 px-3 py-2 text-xs font-medium text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-850 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
				>
					<svg class="size-3.5 text-blue-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="14" rx="2" /><path d="M8 21h8M9 8l3 3-3 3" /></svg>
					{$i18n.t('Dev Console')}
				</button>
			</div>
			<p class="text-sm text-gray-500 mt-1">
				{$i18n.t(
					'Build with Harvis agents. Use GitHub for web repo workflows or the Harvis CLI for local projects.'
				)}
			</p>
		</header>

		<!-- Entry cards -->
		<div class="grid grid-cols-1 md:grid-cols-2 gap-3">
			<!-- GitHub Workspace -->
			<div
				class="rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-5 flex flex-col"
			>
				<div
					class="size-9 rounded-xl flex items-center justify-center bg-gray-100 dark:bg-gray-850 text-gray-600 dark:text-gray-300 mb-3"
				>
					<svg class="size-5" viewBox="0 0 24 24" fill="currentColor"
						><path
							d="M12 2C6.48 2 2 6.48 2 12c0 4.42 2.87 8.17 6.84 9.5.5.08.66-.22.66-.48v-1.7c-2.78.6-3.37-1.34-3.37-1.34-.45-1.16-1.1-1.47-1.1-1.47-.9-.62.07-.6.07-.6 1 .07 1.53 1.03 1.53 1.03.89 1.52 2.34 1.08 2.91.83.09-.65.35-1.09.63-1.34-2.22-.25-4.55-1.11-4.55-4.94 0-1.09.39-1.99 1.03-2.69-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.02a9.6 9.6 0 0 1 5 0c1.91-1.29 2.75-1.02 2.75-1.02.55 1.38.2 2.4.1 2.65.64.7 1.03 1.6 1.03 2.69 0 3.84-2.34 4.69-4.57 4.94.36.31.68.92.68 1.85v2.74c0 .27.16.57.67.48A10 10 0 0 0 22 12c0-5.52-4.48-10-10-10z"
						/></svg
					>
				</div>
				<div class="text-base font-medium text-gray-800 dark:text-gray-100">
					{$i18n.t('GitHub Workspace')}
				</div>
				<div class="text-xs text-gray-500 leading-relaxed mt-1 flex-1">
					{$i18n.t(
						'Connect your GitHub account to import repos, create branches, review diffs, and open pull requests.'
					)}
				</div>
				<button
					class="mt-4 w-full text-sm font-medium px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white transition"
					on:click={openVibe}>{$i18n.t('Open Codespace')}</button
				>
			</div>

			<!-- Local Machine Pipeline -->
			<div
				class="rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-5 flex flex-col"
			>
				<div
					class="size-9 rounded-xl flex items-center justify-center bg-gray-100 dark:bg-gray-850 text-gray-600 dark:text-gray-300 mb-3"
				>
					<svg
						class="size-5"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="1.8"
						stroke-linecap="round"
						stroke-linejoin="round"><polyline points="4 17 10 11 4 5" /><line x1="12" y1="19" x2="20" y2="19" /></svg
					>
				</div>
				<div class="text-base font-medium text-gray-800 dark:text-gray-100">
					{$i18n.t('Local Machine Pipeline')}
				</div>
				<div class="text-xs text-gray-500 leading-relaxed mt-1 flex-1">
					{$i18n.t(
						'Use the Harvis CLI to run agents, pipelines, and local workflows against folders on your machine.'
					)}
				</div>
				<button
					class="mt-4 w-full text-sm font-medium px-4 py-2 rounded-xl border border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300 hover:border-blue-500/50 hover:text-blue-600 dark:hover:text-blue-400 transition inline-flex items-center justify-center gap-2"
					on:click={() => soon('Harvis CLI')}
				>
					{$i18n.t('Set up CLI')}
					<span
						class="text-[10px] uppercase tracking-wide text-gray-400 border border-gray-200 dark:border-gray-700 rounded-full px-1.5 py-0.5"
						>{$i18n.t('Soon')}</span
					>
				</button>
			</div>
		</div>

		<!-- Recent Projects · Recent Runs · Agent Templates -->
		<div class="grid grid-cols-1 lg:grid-cols-3 gap-3">
			<!-- Recent Projects -->
			<div
				class="rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-4"
			>
				<div class="text-sm font-medium text-gray-800 dark:text-gray-100 mb-1">
					{$i18n.t('Recent Projects')}
				</div>
				{#if loadingP}
					<!-- Skeleton mirrors a project row: title line + repo sub-line, py-2 rows. -->
					<div class="divide-y divide-gray-100 dark:divide-gray-850" aria-busy="true">
						<div aria-hidden="true" class="divide-y divide-gray-100 dark:divide-gray-850">
							{#each Array.from({ length: 3 }) as _, i}
								<div class="py-2">
									<Skeleton width={['62%', '44%', '54%'][i]} height="0.875rem" delay={i * 90} />
									<Skeleton width={['48%', '34%', '40%'][i]} height="0.625rem" className="mt-1.5" delay={i * 90} />
								</div>
							{/each}
						</div>
						<span class="sr-only" role="status">{$i18n.t('Loading recent projects…')}</span>
					</div>
				{:else if projects.length === 0}
					<div class="text-xs text-gray-500 py-2">
						{$i18n.t('No projects yet.')}
						<button class="text-blue-500 hover:underline" on:click={openVibe}
							>{$i18n.t('Start one')} →</button
						>
					</div>
				{:else}
					<div class="divide-y divide-gray-100 dark:divide-gray-850">
						{#each projects as p (p.id)}
							<button
								type="button"
								class="w-full flex items-center justify-between gap-2 py-2 text-left group"
								on:click={() => openProject(p.id)}
							>
								<div class="min-w-0">
									<div
										class="truncate text-sm text-gray-800 dark:text-gray-100 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition"
									>
										{p.emoji ? p.emoji + ' ' : ''}{p.label}
									</div>
									{#if p.repo}
										<div class="truncate text-xs text-gray-500">{p.repo}</div>
									{/if}
								</div>
								{@html chevron}
							</button>
						{/each}
					</div>
				{/if}
			</div>

			<!-- Recent Runs -->
			<div
				class="rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-4"
			>
				<div class="text-sm font-medium text-gray-800 dark:text-gray-100 mb-1">
					{$i18n.t('Recent Runs')}
				</div>
				{#if loadingR}
					<!-- Skeleton mirrors a run row: status dot + single title line, py-2 rows. -->
					<div class="divide-y divide-gray-100 dark:divide-gray-850" aria-busy="true">
						<div aria-hidden="true" class="divide-y divide-gray-100 dark:divide-gray-850">
							{#each Array.from({ length: 3 }) as _, i}
								<div class="flex items-center gap-2 py-2">
									<span class="size-1.5 rounded-full shrink-0 bg-gray-200 dark:bg-gray-800"></span>
									<Skeleton width={['72%', '52%', '64%'][i]} height="0.875rem" delay={i * 90} />
								</div>
							{/each}
						</div>
						<span class="sr-only" role="status">{$i18n.t('Loading recent runs…')}</span>
					</div>
				{:else if runs.length === 0}
					<div class="text-xs text-gray-500 py-2">{$i18n.t('No runs yet.')}</div>
				{:else}
					<div class="divide-y divide-gray-100 dark:divide-gray-850">
						{#each runs as r (r.id)}
							<button
								type="button"
								class="w-full flex items-center gap-2 py-2 text-left group"
								on:click={() => goto(`/harvis/agent-studio/run/${r.id}`)}
							>
								<span class="size-1.5 rounded-full shrink-0 {runDot(r.status)}"></span>
								<span
									class="flex-1 truncate text-sm text-gray-800 dark:text-gray-100 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition"
									>{r.task_brief || r.title || $i18n.t('Run')}</span
								>
							</button>
						{/each}
					</div>
				{/if}
			</div>

			<!-- Agent Templates -->
			<div
				class="rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-4"
			>
				<div class="text-sm font-medium text-gray-800 dark:text-gray-100 mb-1">
					{$i18n.t('Agent Templates')}
				</div>
				<div class="divide-y divide-gray-100 dark:divide-gray-850">
					{#each templates as t (t.label)}
						<button
							type="button"
							class="w-full flex items-center justify-between gap-2 py-2 text-left group"
							on:click={openVibe}
						>
							<div class="min-w-0">
								<div
									class="text-sm text-gray-800 dark:text-gray-100 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition truncate"
								>
									{$i18n.t(t.label)}
								</div>
								<div class="text-xs text-gray-500 truncate">{$i18n.t(t.desc)}</div>
							</div>
							{@html chevron}
						</button>
					{/each}
				</div>
			</div>
		</div>
	</div>
</div>
