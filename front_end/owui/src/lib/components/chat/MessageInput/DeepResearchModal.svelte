<script lang="ts">
	import { getContext, onDestroy } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { startResearch, streamResearch, peekResult, openReportInNewTab, cancelResearch } from '$lib/apis/research';
	import Search from '$lib/components/icons/Search.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';

	const i18n: any = getContext('i18n');

	export let show = false;
	export let autoQuery = '';

	const token = () => localStorage.token;

	let query = '';
	let phase: 'idle' | 'running' | 'done' | 'error' = 'idle';
	let progress = '';
	let stats = '';
	let sessionId = '';
	let resultMd = '';
	let sources: any[] = [];
	let errMsg = '';
	let controller: AbortController | null = null;

	const PHASE_LABEL: Record<string, string> = {
		probing: 'Checking model…',
		planning: 'Planning research…',
		searching: 'Searching the web…',
		reading: 'Reading sources…',
		analyzing: 'Analyzing findings…',
		writing: 'Writing the report…'
	};

	const reset = () => {
		phase = 'idle';
		progress = '';
		stats = '';
		sessionId = '';
		resultMd = '';
		sources = [];
		errMsg = '';
	};

	const close = () => {
		controller?.abort();
		controller = null;
		show = false;
	};

	const start = async () => {
		const q = query.trim();
		if (!q) return;
		reset();
		phase = 'running';
		progress = 'Starting…';
		try {
			const r = await startResearch(token(), { query: q });
			sessionId = r.session_id;
			controller = new AbortController();
			await streamResearch(
				token(),
				sessionId,
				(ev) => {
					if (ev?.phase && PHASE_LABEL[ev.phase]) progress = PHASE_LABEL[ev.phase];
					if (ev?.total_sources != null) stats = `${ev.total_sources} sources`;
					if (ev?.round) stats = `round ${ev.round}${ev?.total_sources != null ? ` · ${ev.total_sources} sources` : ''}`;
					if (ev?.phase === 'error' || ev?.error) {
						errMsg = ev?.message || ev?.error || 'Research failed';
						phase = 'error';
					}
					if (ev?.final || ev?.status === 'done') {
						phase = 'done';
					}
				},
				controller.signal
			);
			if (phase !== 'error') {
				phase = 'done';
				try {
					const res = await peekResult(token(), sessionId);
					resultMd = res?.result ?? '';
					sources = res?.sources ?? [];
				} catch (e) {
					// result not retrievable — the report button still works
				}
			}
		} catch (e: any) {
			errMsg = e?.detail ?? `${e}`;
			phase = 'error';
		}
	};

	const cancel = async () => {
		controller?.abort();
		if (sessionId) await cancelResearch(token(), sessionId).catch(() => {});
		reset();
	};

	const openReport = async () => {
		try {
			await openReportInNewTab(token(), sessionId);
		} catch (e: any) {
			toast.error(`${e?.message ?? e}`);
		}
	};

	const onKeydown = (e: KeyboardEvent) => {
		if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
			e.preventDefault();
			start();
		}
	};

	// Auto-start when opened with a query (from the chat send path) — no textbox shown.
	let lastShow = false;
	$: if (show && !lastShow) {
		lastShow = true;
		if (autoQuery && autoQuery.trim()) {
			reset();
			query = autoQuery;
			start();
		}
	}
	$: if (!show) lastShow = false;

	onDestroy(() => controller?.abort());
</script>

{#if show}
	<!-- backdrop -->
	<div
		class="fixed inset-0 z-[9999] bg-black/40 flex items-center justify-center p-4"
		on:click|self={close}
	>
		<div
			class="w-full max-w-lg rounded-2xl bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-850 shadow-xl flex flex-col max-h-[80vh]"
		>
			<!-- header -->
			<div class="flex items-center gap-2 px-4 py-3 border-b border-gray-100 dark:border-gray-850">
				<Search className="size-4 text-amber-500" />
				<div class="text-sm font-medium text-gray-800 dark:text-gray-100">{$i18n.t('Deep Research')}</div>
				<button class="ml-auto text-gray-400 hover:text-gray-600 dark:hover:text-gray-200" on:click={close}>
					<XMark className="size-4" />
				</button>
			</div>

			<div class="px-4 py-3 overflow-y-auto">
				{#if phase === 'idle'}
					<div class="text-xs text-gray-400 mb-2">
						{$i18n.t('Multi-step web research → a cited, visual report. Takes a few minutes.')}
					</div>
					<textarea
						bind:value={query}
						on:keydown={onKeydown}
						rows="3"
						placeholder={$i18n.t('What should I research? (⌘/Ctrl+Enter to start)')}
						class="w-full resize-none rounded-xl bg-gray-50 dark:bg-gray-850 border border-gray-100 dark:border-gray-800 px-3 py-2 text-sm outline-none focus:border-amber-500/50"
					></textarea>
					<div class="flex justify-end mt-3">
						<button
							class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm bg-amber-500 hover:bg-amber-600 text-white transition disabled:opacity-50"
							on:click={start}
							disabled={!query.trim()}
						>
							<Search className="size-4" />
							{$i18n.t('Start Research')}
						</button>
					</div>
				{:else if phase === 'running'}
					<div class="flex flex-col items-center justify-center py-8 gap-3">
						<Spinner className="size-6" />
						<div class="text-sm text-gray-700 dark:text-gray-200">{progress}</div>
						{#if stats}<div class="text-xs text-gray-400 tabular-nums">{stats}</div>{/if}
						<div class="text-[11px] text-gray-400 max-w-xs text-center truncate">{query}</div>
						<button class="mt-2 text-xs text-gray-400 hover:text-red-500 transition" on:click={cancel}>{$i18n.t('Cancel')}</button>
					</div>
				{:else if phase === 'error'}
					<div class="text-sm text-red-500 py-4">{errMsg || $i18n.t('Research failed')}</div>
					<div class="flex justify-end">
						<button class="text-xs text-gray-400 hover:text-gray-700 dark:hover:text-gray-200" on:click={reset}>{$i18n.t('Try again')}</button>
					</div>
				{:else if phase === 'done'}
					<div class="flex items-center gap-2 mb-2">
						<span class="text-xs text-blue-500">✓ {$i18n.t('Done')}</span>
						{#if sources.length}<span class="text-[11px] text-gray-400">{sources.length} {$i18n.t('sources')}</span>{/if}
						<button
							class="ml-auto flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg bg-amber-500 hover:bg-amber-600 text-white transition"
							on:click={openReport}
						>
							{$i18n.t('Open full report')}
						</button>
					</div>
					{#if resultMd}
						<div
							class="markdown-prose markdown-prose-sm max-h-[45vh] overflow-y-auto text-sm whitespace-pre-wrap text-gray-700 dark:text-gray-200 leading-relaxed"
						>{resultMd}</div>
					{:else}
						<div class="text-xs text-gray-400 py-2">{$i18n.t('Report ready — open it for the full, cited write-up.')}</div>
					{/if}
					<div class="flex justify-end mt-3">
						<button class="text-xs text-gray-400 hover:text-gray-700 dark:hover:text-gray-200" on:click={reset}>{$i18n.t('New research')}</button>
					</div>
				{/if}
			</div>
		</div>
	</div>
{/if}
