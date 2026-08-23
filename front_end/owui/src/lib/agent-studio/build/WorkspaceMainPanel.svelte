<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';

	const dispatch = createEventDispatcher();
	const i18n: any = getContext('i18n');

	// The dominant center workspace. Pure props — no fetch, no stores.
	export let tab: 'chat' | 'diff' | 'logs' | 'editor' | 'preview' = 'chat';
	export let selectedFile = '';
	// Unified-diff hunk lines for the selected file (DIFF view; EDITOR falls back to
	// these only when no real content was supplied).
	export let diffLines: string[] = [];
	// Real read-only file content for the EDITOR tab (Phase 2 workspace browsing).
	// null = not fetched (fall back to diff hunks); '' is a legit empty file.
	export let fileContent: string | null = null;
	export let fileLoading = false;
	export let fileBinary = false;
	export let fileTruncated = false;
	export let hasRepo = false;
	export let hasConversation = false;
	// Bottom-right quadrant context: the project name (for the "Ready to build in X"
	// state), whether the session has any changed files, and a file-read error flag.
	export let projectName = '';
	export let hasChanges = false;
	export let fileError = false;
	// When false (dock mode), drop the Chat tab — the conversation lives in the main
	// column, and this panel is just File / Diff / Preview / Logs.
	export let showChat = true;

	// The Preview tab renders whatever the parent puts in the `preview` slot — the run's
	// primary artifact, rendered big. It stays hidden until the parent says one exists, so
	// the tab is never a permanent empty promise. Editor still follows file selection.
	export let hasPreview = false;
	$: hasFile = !!selectedFile;
	$: tabs = [
		...(showChat ? [{ id: 'chat', label: $i18n.t('Chat') }] : []),
		...(hasPreview ? [{ id: 'preview', label: $i18n.t('Preview') }] : []),
		{ id: 'diff', label: $i18n.t('Diff') },
		{ id: 'logs', label: $i18n.t('Logs') },
		...(hasFile ? [{ id: 'editor', label: $i18n.t('Editor') }] : [])
	];
	// In dock mode never sit on the (now-absent) Chat tab.
	$: if (!showChat && tab === 'chat') tab = 'diff';
	$: if (!hasPreview && tab === 'preview') tab = hasFile ? 'editor' : 'diff';

	const selectTab = (id: 'chat' | 'diff' | 'logs' | 'editor' | 'preview') => {
		tab = id;
		dispatch('tab', { tab: id });
	};

	// Editor: split fetched content into numbered lines (read-only viewer).
	$: contentLines = fileContent !== null && !fileBinary ? fileContent.split('\n') : [];

	// Per-line diff coloring shared by DIFF + EDITOR views.
	const lineClass = (line: string): string => {
		if (line.startsWith('+') && !line.startsWith('+++')) {
			return 'text-emerald-600 dark:text-emerald-400';
		}
		if (line.startsWith('-') && !line.startsWith('---')) {
			return 'text-red-500';
		}
		if (line.startsWith('@@')) {
			return 'text-blue-500';
		}
		return 'text-gray-500 dark:text-gray-400';
	};
</script>

<div class="flex flex-col min-h-0 h-full">
	<!-- Tab bar -->
	<div
		class="flex items-center gap-0 px-2 py-1 border-b border-gray-200 dark:border-white/10 shrink-0 bg-gray-50 dark:bg-gray-900"
	>
		{#each tabs as t (t.id)}
			<button
				class="relative px-3 py-1.5 text-[11px] font-medium transition border-b border-transparent {tab === t.id
					? 'text-gray-800 dark:text-gray-100 bg-black/[0.03] dark:bg-white/[0.05] border-gray-200 dark:border-white/10'
					: 'text-gray-500 hover:text-gray-600 dark:hover:text-gray-300'}"
				on:click={() => selectTab(t.id)}
			>
				{t.label}
				{#if tab === t.id}
					<span
						class="absolute left-0 right-0 -bottom-px h-px bg-sky-400"
					/>
				{/if}
			</button>
		{/each}
	</div>

	<!-- Content area -->
	<div class="flex-1 min-h-0 overflow-auto bg-gray-50 dark:bg-gray-900">
		{#if tab === 'chat'}
			{#if hasConversation}
				<slot />
			{:else if hasRepo}
				<div class="h-full flex flex-col items-center justify-center text-center px-6 py-10">
					<div class="text-base font-medium text-gray-800 dark:text-gray-100">
						{$i18n.t('Ready to build in')}
						{projectName || $i18n.t('this project')}
					</div>
					<div class="mt-1.5 max-w-md text-xs text-gray-500">
						{$i18n.t('Ask Harvis to add a feature, fix a bug, write tests, or review code.')}
					</div>
				</div>
			{:else}
				<div class="h-full flex flex-col items-center justify-center text-center px-6 py-10">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						fill="none"
						viewBox="0 0 24 24"
						stroke-width="1.5"
						stroke="currentColor"
						class="size-9 text-gray-400 mb-3"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21l2.755-4.133a1.14 1.14 0 0 1 .865-.501 48.172 48.172 0 0 0 3.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0 0 12 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018Z"
						/>
					</svg>
					<div class="text-base font-medium text-gray-800 dark:text-gray-100">
						{$i18n.t('Start a coding session')}
					</div>
					<div class="mt-1.5 max-w-md text-xs text-gray-500">
						{$i18n.t(
							'Choose a repo, describe a task, and Harvis will plan, edit, test, and prepare a diff for review.'
						)}
					</div>
				</div>
			{/if}
		{:else if tab === 'diff'}
			{#if diffLines.length}
				<div class="px-3 py-2 font-mono">
					{#each diffLines as line, i (i)}
						<div class="whitespace-pre text-[11px] leading-[1.45] {lineClass(line)}">{line || ' '}</div>
					{/each}
				</div>
			{:else if fileError}
				<div class="h-full flex flex-col items-center justify-center text-center px-6 py-10">
					<div class="text-base font-medium text-gray-800 dark:text-gray-100">{$i18n.t('File unavailable')}</div>
					<div class="mt-1.5 max-w-md text-xs text-gray-500">{$i18n.t('This file may have moved, been deleted, or be outside the active workspace boundary.')}</div>
					<button class="mt-3 text-xs px-3 py-1.5 border border-gray-200 dark:border-white/10 text-gray-600 dark:text-gray-300 hover:bg-black/[0.04] dark:hover:bg-white/[0.06] transition" on:click={() => dispatch('refresh')}>{$i18n.t('Refresh files')}</button>
				</div>
			{:else if !hasChanges}
				<div class="h-full flex flex-col items-center justify-center text-center px-6 py-10">
					<div class="text-base font-medium text-gray-800 dark:text-gray-100">{$i18n.t('No changes yet')}</div>
					<div class="mt-1.5 max-w-md text-xs text-gray-500">{$i18n.t('When Harvis edits files, they will appear here for review.')}</div>
				</div>
			{:else}
				<div class="h-full flex flex-col items-center justify-center text-center px-6 py-10">
					<div class="text-base font-medium text-gray-800 dark:text-gray-100">{$i18n.t('No file selected')}</div>
					<div class="mt-1.5 max-w-md text-xs text-gray-500">{$i18n.t('Choose a file from the explorer to preview it here.')}</div>
				</div>
			{/if}
		{:else if tab === 'logs'}
			<slot name="logs" />
		{:else if tab === 'editor'}
			{#if selectedFile}
				<div class="flex flex-col min-h-0 h-full">
					<div
						class="shrink-0 flex items-center gap-2 px-3 py-1.5 border-b border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-gray-900"
					>
						<span class="font-mono text-[11px] text-gray-400 truncate block min-w-0">{selectedFile}</span>
						<span
							class="ml-auto shrink-0 text-[10px] uppercase tracking-wide text-gray-600 border border-gray-200 dark:border-white/10 rounded px-1.5 py-0.5"
							>{$i18n.t('Read-only')}</span
						>
					</div>
					{#if fileLoading}
						<div class="flex-1 flex items-center justify-center text-xs text-gray-500">
							{$i18n.t('Loading file…')}
						</div>
					{:else if fileBinary}
						<div class="flex-1 flex flex-col items-center justify-center text-center px-6 py-10">
							<div class="text-sm text-gray-600 dark:text-gray-300">{$i18n.t('Binary file')}</div>
							<div class="mt-1 text-xs text-gray-500">
								{$i18n.t('This file cannot be displayed as text.')}
							</div>
						</div>
					{:else if fileContent !== null}
						{#if fileTruncated}
							<div
								class="shrink-0 px-3 py-1 text-[10px] text-amber-500/90 border-b border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-gray-900"
							>
								{$i18n.t('Truncated at 512KB — showing the beginning of the file.')}
							</div>
						{/if}
						<div class="flex-1 min-h-0 overflow-auto py-2 font-mono">
							{#each contentLines as line, i (i)}
								<div class="flex text-[11px] leading-[1.45]">
									<span
										class="shrink-0 w-10 pr-2 text-right text-gray-600 select-none tabular-nums"
										>{i + 1}</span
									>
									<span class="whitespace-pre text-gray-600 dark:text-gray-300 flex-1">{line || ' '}</span>
								</div>
							{/each}
						</div>
					{:else}
						<!-- No fetched content (legacy host / fetch failed) → fall back to diff hunks. -->
						<div class="flex-1 min-h-0 overflow-auto px-3 py-2 font-mono">
							{#if fileError}
								<!-- honest: the content fetch FAILED (diff hunks below may still help) -->
								<div class="flex items-center gap-2 px-1 py-1.5 text-[11px] font-sans text-red-500 dark:text-red-400">
									<span>{$i18n.t("Couldn't load this file's content.")}</span>
									<button
										class="underline hover:no-underline"
										on:click={() => dispatch('refresh')}>{$i18n.t('Retry')}</button
									>
								</div>
							{/if}
							{#each diffLines as line, i (i)}
								<div class="whitespace-pre text-[11px] leading-[1.45] {lineClass(line)}">
									{line || ' '}
								</div>
							{/each}
							{#if !diffLines.length && !fileError}
								<div class="px-1 py-2 text-xs text-gray-500">
									{$i18n.t('File content unavailable.')}
								</div>
							{/if}
						</div>
					{/if}
				</div>
			{:else}
				<div class="h-full flex flex-col items-center justify-center text-center px-6 py-10">
					<div class="text-base font-medium text-gray-800 dark:text-gray-100">
						{$i18n.t('No file selected')}
					</div>
					<div class="mt-1.5 max-w-md text-xs text-gray-500">
						{$i18n.t('Choose a file from the explorer or ask Harvis to start a task.')}
					</div>
				</div>
			{/if}
		{:else if tab === 'preview'}
			<div class="h-full min-h-0">
				<slot name="preview">
					<div class="h-full flex flex-col items-center justify-center text-center px-6 py-10">
						<div class="text-sm text-gray-400">{$i18n.t('No preview available yet.')}</div>
					</div>
				</slot>
			</div>
		{/if}
	</div>

	<!-- Composer (always visible) -->
	<div class="shrink-0">
		<slot name="composer" />
	</div>
</div>
