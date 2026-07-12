<script lang="ts">
	// Plugins panel — read-only catalog of the agent's built-in capabilities
	// (Harvis-native: the orchestration runner + OpenClaw allowlist). Extracted
	// from Customize.svelte's "Tools" section so the Settings modal and the
	// Customize page share one implementation. Connectors extend this list.
	import { getContext } from 'svelte';

	const i18n: any = getContext('i18n');

	const AGENT_TOOLS: { name: string; desc: string; group: string }[] = [
		{ name: 'read_file', desc: 'Read a file in the workspace.', group: 'Code & files' },
		{ name: 'edit_file', desc: 'Create or overwrite a file.', group: 'Code & files' },
		{ name: 'str_replace', desc: 'Make a targeted edit to a file.', group: 'Code & files' },
		{ name: 'exec', desc: 'Run a shell command in the workspace.', group: 'Code & files' },
		{ name: 'run_tests', desc: 'Run the project test suite.', group: 'Code & files' },
		{ name: 'run_code', desc: 'Execute code and capture the output.', group: 'Code & files' },
		{ name: 'repo_read', desc: 'Read from an attached git repository.', group: 'Repositories' },
		{ name: 'repo_write', desc: 'Write changes to an attached repository.', group: 'Repositories' },
		{ name: 'web_search', desc: 'Search the web (when web access is on).', group: 'Knowledge & web' },
		{ name: 'local_rag', desc: 'Search your knowledge bases and notebooks.', group: 'Knowledge & web' },
		{ name: 'create_docx', desc: 'Generate a Word document.', group: 'Documents' },
		{ name: 'create_pdf', desc: 'Generate a PDF.', group: 'Documents' }
	];
	const TOOL_GROUPS = ['Code & files', 'Repositories', 'Knowledge & web', 'Documents'];
</script>

<div class="w-full">
	<div class="flex items-center gap-2 mb-1">
		<svg class="size-5 text-blue-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18v3h3l6.3-6.3a4 4 0 0 0 5.4-5.4l-2.7 2.7-2-2 2.7-2.7z" /></svg>
		<h2 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{$i18n.t('Plugins')}</h2>
	</div>
	<p class="text-sm text-gray-500 mb-3">
		{$i18n.t('Built-in capabilities your agents can use. Add connectors to extend this list.')}
	</p>
	<div class="space-y-3">
		{#each TOOL_GROUPS as g}
			{@const groupTools = AGENT_TOOLS.filter((t) => t.group === g)}
			{#if groupTools.length}
				<div>
					<div class="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-1.5">{$i18n.t(g)}</div>
					<div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
						{#each groupTools as t}
							<div class="rounded-xl border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-950 px-3 py-2">
								<div class="flex items-center gap-2">
									<code class="text-xs font-mono text-blue-600 dark:text-blue-400">{t.name}</code>
									<span class="text-[10px] text-gray-400 bg-gray-100 dark:bg-gray-850 rounded px-1.5 py-0.5">{$i18n.t('built-in')}</span>
								</div>
								<div class="text-xs text-gray-500 mt-0.5">{t.desc}</div>
							</div>
						{/each}
					</div>
				</div>
			{/if}
		{/each}
	</div>
</div>
