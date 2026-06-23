<script lang="ts">
	// The session's ACCUMULATED diff (union of all turns, vs the fixed base_sha) +
	// the one human-gated Create-PR action. Opens ONE PR from the whole session.
	// Create-PR is human-only (this button), refuses main/master, never agent-fired.
	import { getContext } from 'svelte';
	import { getVibecodeSessionDiff, createPrForVibecodeSession } from '$lib/apis/agent-runs';

	const i18n: any = getContext('i18n');

	export let sessionId = '';
	export let refreshKey: any = 0; // bump to re-fetch (e.g. when a turn completes)

	let diff = '';
	let hasGithub = false;
	let repo: string | null = null;
	let showDiff = false; // diff is collapsed by default — "View diff" expands it (chat-style)

	let lastKey = '';
	const load = async () => {
		if (!sessionId) {
			diff = '';
			return;
		}
		const d = await getVibecodeSessionDiff(sessionId);
		if (d) {
			diff = d.diff || '';
			hasGithub = !!d.has_github;
			repo = d.repo;
		}
	};
	$: {
		const k = `${sessionId}:${refreshKey}`;
		if (k !== lastKey) {
			lastKey = k;
			load();
		}
	}

	$: stats = (() => {
		let add = 0,
			del = 0;
		for (const ln of diff.split('\n')) {
			if (ln.startsWith('+') && !ln.startsWith('+++')) add++;
			else if (ln.startsWith('-') && !ln.startsWith('---')) del++;
		}
		return { add, del };
	})();

	// Create-PR (human-gated) state.
	let prOpen = false;
	let prTitle = '';
	let prBusy = false;
	let prError = '';
	let prResult: { pr_url?: string; pr_number?: number; branch?: string } | null = null;

	const openPr = async () => {
		prBusy = true;
		prError = '';
		try {
			prResult = await createPrForVibecodeSession(sessionId, {
				title: prTitle.trim() || undefined
			});
			prOpen = false;
		} catch (e: any) {
			prError = String(e?.message ?? e);
		} finally {
			prBusy = false;
		}
	};

	const lineClass = (ln: string) => {
		if (ln.startsWith('+') && !ln.startsWith('+++')) return 'text-green-600 dark:text-green-400';
		if (ln.startsWith('-') && !ln.startsWith('---')) return 'text-red-600 dark:text-red-400';
		if (ln.startsWith('@@')) return 'text-blue-500';
		if (ln.startsWith('diff --git') || ln.startsWith('index ') || ln.startsWith('new file') || ln.startsWith('deleted file'))
			return 'text-gray-400';
		return 'text-gray-600 dark:text-gray-300';
	};
</script>

{#if diff.trim()}
	<div class="rounded-2xl border border-gray-100 dark:border-gray-850 overflow-hidden">
		<!-- header: accumulated changes + stats + Create PR -->
		<div class="flex items-center gap-2 px-3 py-2 border-b border-gray-100 dark:border-gray-850">
			<span class="text-xs font-medium text-gray-700 dark:text-gray-200">{$i18n.t('Session changes')}</span>
			{#if repo}<span class="text-[11px] text-gray-400 font-mono truncate">{repo}</span>{/if}
			<span class="text-[11px] font-mono">
				<span class="text-green-600 dark:text-green-400">+{stats.add}</span>
				<span class="text-red-600 dark:text-red-400">−{stats.del}</span>
			</span>
			<div class="flex-1"></div>
			<button
				class="text-xs px-2.5 py-1 rounded-lg text-gray-500 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-850 transition"
				on:click={() => (showDiff = !showDiff)}
			>
				{showDiff ? $i18n.t('Hide diff') : $i18n.t('View diff')}
			</button>
			{#if hasGithub && !prResult}
				<button
					class="text-xs px-2.5 py-1 rounded-lg bg-gray-100 dark:bg-gray-850 text-gray-700 dark:text-gray-200 hover:bg-gray-200 dark:hover:bg-gray-800 transition"
					on:click={() => (prOpen = !prOpen)}
				>
					{$i18n.t('Create PR')}
				</button>
			{/if}
		</div>

		<!-- Create-PR confirm (human-gated) -->
		{#if prOpen && !prResult}
			<div class="px-3 py-2 border-b border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 space-y-2">
				<input
					class="w-full text-xs rounded-lg bg-white dark:bg-gray-850 border border-gray-200 dark:border-gray-800 px-2 py-1.5 outline-none"
					placeholder={$i18n.t('PR title (optional)')}
					bind:value={prTitle}
				/>
				<div class="flex items-center gap-2">
					<button
						class="text-xs px-3 py-1.5 rounded-lg bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50 transition"
						disabled={prBusy}
						on:click={openPr}>{prBusy ? $i18n.t('Opening…') : $i18n.t('Open pull request')}</button
					>
					<button
						class="text-xs px-3 py-1.5 rounded-lg text-gray-500 hover:text-gray-700 dark:hover:text-gray-200"
						disabled={prBusy}
						on:click={() => (prOpen = false)}>{$i18n.t('Cancel')}</button
					>
					<span class="text-[11px] text-gray-400">{$i18n.t('Refuses main/master.')}</span>
				</div>
				{#if prError}<div class="text-[11px] text-red-500">{prError}</div>{/if}
			</div>
		{/if}

		{#if prResult}
			<div class="px-3 py-2 border-b border-gray-100 dark:border-gray-850 text-xs">
				<a
					href={prResult.pr_url}
					target="_blank"
					rel="noopener noreferrer"
					class="text-blue-500 hover:underline"
				>
					{$i18n.t('Pull request opened')}{prResult.pr_number ? ` #${prResult.pr_number}` : ''} ↗
				</a>
			</div>
		{/if}

		<!-- the accumulated diff — hidden until "View diff" (keeps the thread compact) -->
		{#if showDiff}
			<pre
				class="text-[11px] leading-relaxed font-mono overflow-x-auto px-3 py-2 max-h-80 overflow-y-auto"><code
					>{#each diff.split('\n') as ln}<span class={lineClass(ln)}>{ln}
</span>{/each}</code
				></pre>
		{/if}
	</div>
{/if}
