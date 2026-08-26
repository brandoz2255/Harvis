<script lang="ts">
	// One repo section inside the Skills Browse surface — purely presentational.
	// Rows show ONLY data actually fetched (frontmatter, repo license, tree file
	// counts); anything not loaded yet renders as a skeleton or an honest "—".
	import { getContext } from 'svelte';
	import { formatSkillName } from '$lib/utils';

	import Tooltip from '$lib/components/common/Tooltip.svelte';

	export let title = ''; // collection label ('' = URL-tab section, header shows source only)
	export let source = ''; // owner/repo
	export let status: 'idle' | 'loading' | 'ready' | 'error' = 'idle';
	export let error = '';
	export let rateLimited = false;
	export let truncated = false;
	export let entries: any[] = []; // visible + search-filtered rows
	export let hiddenCount = 0; // filtered rows beyond the visible window
	export let searching = false; // true when a search filter is active
	export let onPreview: (entry: any, el: HTMLElement | null) => void = () => {};
	export let onLoadMore: () => void = () => {};
	export let onRetry: () => void = () => {};

	const i18n: any = getContext('i18n');

	const titleOf = (e: any): string =>
		formatSkillName(e?.fm?.name || (e.dir ? e.dir.split('/').pop() : e.repo) || '');
</script>

<section class="mt-3">
	<div class="flex items-baseline gap-2">
		{#if title}
			<h4 class="text-sm font-semibold text-gray-700 dark:text-gray-200">{title}</h4>
		{/if}
		<a
			href={`https://github.com/${source}`}
			target="_blank"
			rel="noopener noreferrer"
			class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:underline"
			>{source}</a
		>
	</div>

	{#if status === 'loading'}
		<div class="mt-2 space-y-2" aria-hidden="true">
			{#each Array(4) as _}
				<div class="flex items-center gap-3 py-2">
					<div class="min-w-0 flex-1 space-y-1.5">
						<div class="h-3.5 w-44 animate-pulse rounded bg-gray-100 dark:bg-gray-850"></div>
						<div class="h-3 w-72 animate-pulse rounded bg-gray-100 dark:bg-gray-850"></div>
					</div>
					<div class="h-6 w-16 animate-pulse rounded-lg bg-gray-100 dark:bg-gray-850"></div>
				</div>
			{/each}
		</div>
	{:else if status === 'error'}
		<div
			class="mt-2 rounded-xl border border-gray-100 dark:border-gray-850 px-3 py-3 text-xs text-gray-500"
		>
			{#if rateLimited}
				{$i18n.t('GitHub API rate limit reached — try again later or paste a URL.')}
			{:else}
				{$i18n.t('Could not load this repository')} — {error}
			{/if}
			<button
				class="ml-2 text-blue-600 dark:text-blue-400 hover:underline"
				on:click={onRetry}>{$i18n.t('Retry')}</button
			>
		</div>
	{:else if status === 'ready'}
		{#if truncated}
			<p class="mt-1 text-[11px] text-gray-400">
				{$i18n.t('GitHub truncated this repository listing — some skills may be missing.')}
			</p>
		{/if}
		{#if entries.length === 0}
			<p class="mt-2 text-xs text-gray-500">
				{searching
					? $i18n.t('No skills in this repository match your search.')
					: $i18n.t('No SKILL.md files found in this repository.')}
			</p>
		{:else}
			<div class="mt-1">
				{#each entries as entry (entry.key)}
					<div
						class="flex items-center gap-3 border-b border-gray-100 dark:border-gray-850 py-2.5"
					>
						<div class="min-w-0 flex-1">
							<div class="flex min-w-0 items-center gap-2">
								<span class="truncate text-sm font-medium text-gray-800 dark:text-gray-100"
									>{titleOf(entry)}</span
								>
								{#if entry.extras > 0}
									<Tooltip
										content={$i18n.t(
											'This skill directory contains files beyond SKILL.md/references — scripts are never imported or executed.'
										)}
									>
										<span
											class="shrink-0 rounded-md border border-gray-200 dark:border-gray-800 px-1.5 py-px text-[10px] text-gray-500"
											>{$i18n.t('scripts')}</span
										>
									</Tooltip>
								{/if}
							</div>
							{#if entry.fmState === 'loading' || entry.fmState === 'idle'}
								<div
									class="mt-1 h-3 w-56 animate-pulse rounded bg-gray-100 dark:bg-gray-850"
									aria-hidden="true"
								></div>
							{:else}
								<div class="mt-0.5 line-clamp-1 text-xs text-gray-500">
									{entry.fm?.description || '—'}
								</div>
							{/if}
						</div>
						<span class="hidden whitespace-nowrap text-xs text-gray-400 md:block"
							>{entry.owner}/{entry.repo}</span
						>
						<span class="hidden w-20 truncate text-right text-xs text-gray-400 sm:block"
							>{entry.license ?? '—'}</span
						>
						<button
							class="shrink-0 rounded-lg border border-gray-200 dark:border-gray-800 px-2.5 py-1 text-xs font-medium text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-900 transition"
							on:click={(e) => onPreview(entry, e.currentTarget)}
						>
							{$i18n.t('Preview')}
						</button>
					</div>
				{/each}
			</div>
			{#if hiddenCount > 0}
				<button
					class="mt-2 text-xs text-blue-600 dark:text-blue-400 hover:underline"
					on:click={onLoadMore}
				>
					{$i18n.t('Load more')} ({hiddenCount})
				</button>
			{/if}
		{/if}
	{/if}
</section>
