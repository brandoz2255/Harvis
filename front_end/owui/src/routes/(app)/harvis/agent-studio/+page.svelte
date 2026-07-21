<script lang="ts">
	// Agent Studio = a CAPABILITY LAUNCHER + customization surface (NOT an ops
	// monitor — active runs / approvals / schedules live on /harvis/automations).
	// "What can I make Harvis do, customize, or plug into my workflow?"
	import { getContext } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';
	import { WEBUI_NAME, chatId, researchEnabled } from '$lib/stores';
	import IntentPills from '$lib/agent-studio/IntentPills.svelte';
	import UnderConstruction from '$lib/components/common/UnderConstruction.svelte';

	const i18n: any = getContext('i18n');

	// Old ?ws= deep-link shape → redirect to the dedicated run view.
	$: wsId = $page.url.searchParams.get('ws');
	$: if (wsId) goto(`/harvis/agent-studio/run/${wsId}`, { replaceState: true });

	const backToChat = () => goto($chatId ? `/c/${$chatId}` : '/');
	const tuning = () => goto('/harvis/agent-studio/tuning');
	const customize = () => goto('/harvis/agent-studio/customize');
	const soon = (what: string) => toast.info($i18n.t('{{what}} — coming soon.', { what }));

	// Capabilities — what Harvis can DO. [Use] launches the real surface; [Customize] → agent instructions.
	const capabilities: {
		label: string;
		desc: string;
		svg: string;
		use: () => void;
		accent?: boolean;
	}[] = [
		{
			label: 'Research Agent',
			desc: 'Search sources, summarize, compare, and generate reports.',
			svg: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
			use: () => {
				researchEnabled.set(true);
				goto('/');
			}
		},
		{
			label: 'Code Agent',
			desc: 'Work with repos, diffs, CLI projects, and code review.',
			svg: '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
			use: () => goto('/harvis/vibecode')
		},
		{
			label: 'Data / Log Analyst',
			desc: 'Analyze logs, CSVs, traces, and system outputs.',
			svg: '<path d="M3 3v18h18"/><rect x="7" y="9" width="3" height="9" rx="1"/><rect x="13" y="5" width="3" height="13" rx="1"/>',
			use: () =>
				goto(
					`/?q=${encodeURIComponent(
						'Analyze this data — paste a log, CSV, or trace and surface the key signals:\n'
					)}&submit=false`
				)
		},
		{
			label: 'Knowledge Builder',
			desc: 'Turn sources into notebooks, quizzes, podcasts, and study guides.',
			svg: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
			use: () => goto('/harvis/notebooks')
		},
		{
			label: 'Browser / Tool Runner',
			desc: 'Use connected tools and integrations.',
			svg: '<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15 15 0 0 1 0 20 15 15 0 0 1 0-20z"/>',
			use: () => goto('/harvis/integrations')
		},
		{
			label: 'Automations',
			desc: 'Schedule recurring tasks and background workflows.',
			svg: '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/>',
			accent: true,
			use: () => goto('/harvis/automations')
		}
	];

	// Customization — how Harvis behaves.
	const customization: { label: string; desc: string; svg: string; open: () => void; soon?: boolean }[] = [
		{
			label: 'Agent Instructions',
			desc: 'Set default behavior, tone, and guardrails.',
			svg: '<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>',
			open: tuning
		},
		{
			label: 'Tool Permissions',
			desc: 'Choose which tools agents can use.',
			svg: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
			open: () => goto('/workspace/tools')
		},
		{
			label: 'Memory & Context',
			desc: 'Decide what agents remember or pull into tasks.',
			svg: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/>',
			open: () => goto('/harvis/agent-studio/brain')
		},
		{
			label: 'Layout Presets',
			desc: 'Simple, developer, research, or automation layouts.',
			svg: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18"/><path d="M9 12h12"/>',
			open: () => soon('Layout presets'),
			soon: true
		}
	];

	// The local stack — quick status row; click through to Integrations to manage.
	const stack: { label: string; on: boolean }[] = [
		{ label: 'OpenClaw', on: true },
		{ label: 'Hermes', on: true },
		{ label: 'OpenCode', on: false },
		{ label: 'Ollama', on: true },
		{ label: 'Custom Tools', on: false }
	];
</script>

<svelte:head>
	<title>{$i18n.t('Agent Studio')} • {$WEBUI_NAME}</title>
</svelte:head>

<div class="w-full h-full overflow-y-auto">
	<div class="max-w-5xl mx-auto px-5 py-6 space-y-8">
		<!-- Header -->
		<header>
			<div class="flex items-center justify-between">
				<button
					class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
					on:click={backToChat}>← {$i18n.t('Back to chat')}</button
				>
				<div class="flex items-center gap-2">
					<button
						class="text-xs px-3 py-1.5 rounded-full border border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300 hover:border-blue-500/50 hover:text-blue-600 dark:hover:text-blue-400 transition"
						on:click={customize}>{$i18n.t('Customize')}</button
					>
					<button
						class="text-xs px-3 py-1.5 rounded-full bg-blue-600 hover:bg-blue-500 text-white transition"
						on:click={() => soon('Create capability')}>{$i18n.t('Create capability')}</button
					>
				</div>
			</div>
			<h1 class="text-2xl font-semibold text-gray-800 dark:text-gray-100 mt-2 flex items-center gap-2.5">
				{$i18n.t('Agent Studio')}
				<span
					class="text-[10px] font-medium px-2 py-0.5 rounded-full border border-amber-300 dark:border-amber-800 text-amber-700 dark:text-amber-400 align-middle"
					>{$i18n.t('WIP')}</span
				>
			</h1>
			<p class="text-sm text-gray-500 mt-1">
				{$i18n.t('Configure Harvis capabilities, tools, and behavior.')}
			</p>
		</header>

		<!-- Honest marker: this hub is not finished. Deliberately non-blocking — the
		     individual surfaces underneath (Customize, Models, Connectors) still work. -->
		<UnderConstruction
			title={$i18n.t('Agent Studio is under construction')}
			note={$i18n.t(
				'This hub is still being designed. Individual surfaces below may work, but the layout and what lives here will change.'
			)}
		/>

		<!-- Quick start -->
		<section>
			<h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
				{$i18n.t('Quick start')}
			</h2>
			<IntentPills />
		</section>

		<!-- Capabilities -->
		<section>
			<h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
				{$i18n.t('Capabilities')}
			</h2>
			<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
				{#each capabilities as c (c.label)}
					<div
						class="rounded-2xl border p-4 flex flex-col gap-2 transition {c.accent
							? 'border-blue-500/30 bg-blue-500/10'
							: 'border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900'}"
					>
						<div
							class="size-9 rounded-xl flex items-center justify-center {c.accent
								? 'bg-blue-500/15 text-blue-600 dark:text-blue-300'
								: 'bg-gray-100 dark:bg-gray-850 text-gray-500'}"
						>
							<svg
								class="size-5"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.8"
								stroke-linecap="round"
								stroke-linejoin="round">{@html c.svg}</svg
							>
						</div>
						<div class="text-sm font-medium text-gray-800 dark:text-gray-100">{$i18n.t(c.label)}</div>
						<div class="text-xs text-gray-500 leading-relaxed flex-1">{$i18n.t(c.desc)}</div>
						<div class="flex items-center gap-3 pt-1">
							<button
								class="text-xs font-medium text-blue-600 dark:text-blue-400 hover:underline"
								on:click={c.use}>{$i18n.t('Use')}</button
							>
							<button
								class="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
								on:click={customize}>{$i18n.t('Customize')}</button
							>
						</div>
					</div>
				{/each}
			</div>
		</section>

		<!-- Customization -->
		<section>
			<h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
				{$i18n.t('Customization')}
			</h2>
			<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
				{#each customization as c (c.label)}
					<button
						class="group text-left rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-4 flex items-start gap-3 transition hover:border-blue-500/40 hover:bg-blue-500/5"
						on:click={c.open}
					>
						<div
							class="size-9 rounded-xl flex items-center justify-center bg-gray-100 dark:bg-gray-850 text-gray-500 group-hover:text-blue-600 dark:group-hover:text-blue-300 transition shrink-0"
						>
							<svg
								class="size-5"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.8"
								stroke-linecap="round"
								stroke-linejoin="round">{@html c.svg}</svg
							>
						</div>
						<div class="flex-1">
							<div class="text-sm font-medium text-gray-800 dark:text-gray-100 flex items-center gap-2">
								{$i18n.t(c.label)}
								{#if c.soon}
									<span
										class="text-[10px] uppercase tracking-wide text-gray-400 border border-gray-200 dark:border-gray-700 rounded-full px-1.5 py-0.5"
										>{$i18n.t('Soon')}</span
									>
								{/if}
							</div>
							<div class="text-xs text-gray-500 leading-relaxed mt-0.5">{$i18n.t(c.desc)}</div>
						</div>
					</button>
				{/each}
			</div>
		</section>

		<!-- Connected stack -->
		<section>
			<div class="flex items-center justify-between mb-2">
				<h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wide">
					{$i18n.t('Connected stack')}
				</h2>
				<a href="/harvis/integrations" class="text-xs text-gray-400 hover:text-blue-500"
					>{$i18n.t('Manage')} ›</a
				>
			</div>
			<div class="flex flex-wrap items-center gap-2">
				{#each stack as s (s.label)}
					<a
						href="/harvis/integrations"
						class="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 text-gray-600 dark:text-gray-300 hover:border-blue-500/40 transition"
					>
						<span class="size-1.5 rounded-full {s.on ? 'bg-green-500' : 'bg-gray-400 dark:bg-gray-600'}"
						></span>{s.label}
					</a>
				{/each}
			</div>
		</section>
	</div>
</div>
