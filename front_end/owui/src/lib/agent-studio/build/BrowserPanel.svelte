<script lang="ts">
	// In-app "Browse and verify" browser panel for the Build dock. Self-contained: a URL bar +
	// sandboxed iframe + back/forward/reload/open-in-new-tab, so you can preview a running dev
	// server, the Harvis app, or any site without leaving Build. No backend port-proxy required.
	import { getContext } from 'svelte';
	const i18n: any = getContext('i18n');

	export let initialUrl = '';

	let url = initialUrl; // committed iframe src
	let urlInput = initialUrl; // the URL bar text
	let iframeKey = 0;
	let history: string[] = [];
	let historyIndex = -1;

	const normalize = (u: string): string => {
		let s = (u || '').trim();
		if (!s) return '';
		if (!/^https?:\/\//i.test(s) && !s.startsWith('/')) s = 'http://' + s;
		return s;
	};
	const go = (raw?: string) => {
		const s = normalize(raw ?? urlInput);
		if (!s) return;
		url = s;
		urlInput = s;
		history = [...history.slice(0, historyIndex + 1), s];
		historyIndex = history.length - 1;
		iframeKey += 1;
	};
	$: canBack = historyIndex > 0;
	$: canFwd = historyIndex < history.length - 1;
	const back = () => {
		if (!canBack) return;
		historyIndex -= 1;
		url = history[historyIndex];
		urlInput = url;
		iframeKey += 1;
	};
	const fwd = () => {
		if (!canFwd) return;
		historyIndex += 1;
		url = history[historyIndex];
		urlInput = url;
		iframeKey += 1;
	};
	const reload = () => (iframeKey += 1);
	const openExternal = () => {
		if (url) window.open(url, '_blank', 'noopener');
	};
	// Prefer this origin over hardcoded localhost — LAN / reverse-proxy deployments differ.
	$: origin =
		typeof window !== 'undefined' ? window.location.origin : 'http://localhost:9000';
	$: quick = [
		{ label: '3000', url: 'http://127.0.0.1:3000' },
		{ label: '5173', url: 'http://127.0.0.1:5173' },
		{ label: '8080', url: 'http://127.0.0.1:8080' },
		{ label: $i18n.t('This Harvis'), url: origin }
	];
</script>

<div class="h-full flex flex-col min-h-0 bg-white dark:bg-gray-950">
	<!-- URL bar -->
	<div class="shrink-0 flex items-center gap-1 px-2 py-1.5 border-b border-gray-100 dark:border-white/8">
		<button
			class="p-1 rounded text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 disabled:opacity-30 disabled:hover:text-gray-400"
			disabled={!canBack}
			on:click={back}
			title={$i18n.t('Back')}
		>
			<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="size-3.5"><path d="M15 18l-6-6 6-6" stroke-linecap="round" stroke-linejoin="round" /></svg>
		</button>
		<button
			class="p-1 rounded text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 disabled:opacity-30 disabled:hover:text-gray-400"
			disabled={!canFwd}
			on:click={fwd}
			title={$i18n.t('Forward')}
		>
			<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="size-3.5"><path d="M9 6l6 6-6 6" stroke-linecap="round" stroke-linejoin="round" /></svg>
		</button>
		<button
			class="p-1 rounded text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 disabled:opacity-30"
			disabled={!url}
			on:click={reload}
			title={$i18n.t('Reload')}
		>
			<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="size-3.5"><path d="M3 12a9 9 0 1 0 3-6.7L3 8m0-5v5h5" stroke-linecap="round" stroke-linejoin="round" /></svg>
		</button>
		<input
			bind:value={urlInput}
			on:keydown={(e) => e.key === 'Enter' && go()}
			placeholder={$i18n.t('Enter a URL to preview…')}
			class="flex-1 min-w-0 px-2 py-1 text-[11px] rounded-md border border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-white/5 text-gray-700 dark:text-gray-200 outline-none focus:border-blue-500/40"
		/>
		<button
			class="shrink-0 px-2 py-1 text-[11px] rounded-md bg-blue-600 text-white hover:bg-blue-500 transition"
			on:click={() => go()}>{$i18n.t('Go')}</button
		>
		<button
			class="shrink-0 p-1 rounded text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 disabled:opacity-30"
			disabled={!url}
			on:click={openExternal}
			title={$i18n.t('Open in a new tab')}
		>
			<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="size-3.5"><path d="M14 5h5v5M19 5l-8 8M12 5H6a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-6" stroke-linecap="round" stroke-linejoin="round" /></svg>
		</button>
	</div>

	<!-- body -->
	<div class="flex-1 min-h-0">
		{#if url}
			{#key iframeKey}
				<iframe
					title="preview"
					src={url}
					class="w-full h-full border-0 bg-white"
					sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"
				></iframe>
			{/key}
		{:else}
			<div class="h-full flex flex-col items-center justify-center text-center px-6 gap-3 text-gray-500">
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" class="size-8 text-gray-400 dark:text-gray-600"><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 9h18" stroke-linecap="round" /><circle cx="6.5" cy="6.5" r=".6" fill="currentColor" /><circle cx="9" cy="6.5" r=".6" fill="currentColor" /></svg>
				<div class="text-sm font-medium text-gray-500 dark:text-gray-300">{$i18n.t('Browse and verify')}</div>
				<div class="text-[11px] max-w-xs leading-relaxed">
					{$i18n.t('Enter a URL above to preview a running app — your dev server, the Harvis app, or any site.')}
				</div>
				<div class="flex flex-wrap items-center justify-center gap-1.5 pt-1">
					{#each quick as q}
						<button
							class="text-[11px] px-2 py-1 rounded-md border border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-white/5 hover:bg-gray-100 dark:hover:bg-white/10 text-gray-600 dark:text-gray-300 transition"
							on:click={() => go(q.url)}>{q.label}</button
						>
					{/each}
				</div>
			</div>
		{/if}
	</div>
</div>
