<script lang="ts">
	// P6: per-integration recent-activity drawer. Read-only view over
	// GET /api/owui/integrations/{id}/logs (redacted server-side).
	import { getContext } from 'svelte';

	const i18n: any = getContext('i18n');

	export let show = false;
	export let integrationId = '';
	export let name = '';

	type Entry = { ts?: string; kind?: string; title?: string; detail?: string; status?: string };
	let entries: Entry[] = [];
	let loading = false;
	let error = '';
	let loadedFor = '';

	const load = async () => {
		if (!integrationId) return;
		loading = true;
		error = '';
		try {
			const r = await fetch(`/api/owui/integrations/${encodeURIComponent(integrationId)}/logs?limit=50`, {
				headers: { Authorization: `Bearer ${localStorage.token}` },
				credentials: 'include'
			});
			if (!r.ok) throw new Error((await r.json())?.detail || `HTTP ${r.status}`);
			entries = (await r.json())?.entries ?? [];
			loadedFor = integrationId;
		} catch (e: any) {
			error = e?.message || 'Failed to load logs';
			entries = [];
		}
		loading = false;
	};

	$: if (show && integrationId && loadedFor !== integrationId) load();
	$: if (!show) loadedFor = '';

	const dotFor = (s?: string) =>
		s === 'error'
			? 'bg-red-500'
			: s === 'ok' || s === 'done' || s === 'success'
				? 'bg-emerald-500'
				: s === 'running'
					? 'bg-blue-500 animate-pulse'
					: 'bg-gray-400';

	const fmtTs = (ts?: string) => {
		if (!ts) return '';
		try {
			return new Date(ts).toLocaleString(undefined, {
				month: 'short',
				day: 'numeric',
				hour: '2-digit',
				minute: '2-digit'
			});
		} catch {
			return ts;
		}
	};
</script>

{#if show}
	<!-- click-away -->
	<button
		class="fixed inset-0 z-40 bg-black/30 cursor-default"
		aria-label={$i18n.t('Close')}
		on:click={() => (show = false)}
	></button>
	<aside
		class="fixed right-0 top-0 bottom-0 z-50 w-full max-w-md bg-white dark:bg-gray-950 border-l border-gray-100 dark:border-gray-850 shadow-2xl flex flex-col"
	>
		<div class="shrink-0 flex items-center gap-2 px-4 py-3 border-b border-gray-100 dark:border-gray-850">
			<div class="min-w-0">
				<div class="text-sm font-semibold text-gray-800 dark:text-gray-100 truncate">
					{name || integrationId} — {$i18n.t('Recent activity')}
				</div>
				<div class="text-[11px] text-gray-500 dark:text-gray-400">{$i18n.t('Read-only · secrets redacted server-side')}</div>
			</div>
			<button
				class="ml-auto shrink-0 text-xs px-2 py-1 rounded-lg border border-gray-200 dark:border-gray-800 text-gray-500 hover:text-gray-700 dark:hover:text-gray-200 transition disabled:opacity-50"
				disabled={loading}
				on:click={load}>{loading ? $i18n.t('Loading…') : $i18n.t('Refresh')}</button
			>
			<button
				class="shrink-0 text-gray-500 dark:text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 p-1"
				aria-label={$i18n.t('Close')}
				on:click={() => (show = false)}
			>
				<svg viewBox="0 0 20 20" fill="currentColor" class="size-4"><path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" /></svg>
			</button>
		</div>
		<div class="flex-1 min-h-0 overflow-y-auto px-4 py-3">
			{#if error}
				<div class="text-xs text-red-500 py-2">{error}</div>
			{:else if loading && !entries.length}
				<div class="text-xs text-gray-500 dark:text-gray-400 py-2">{$i18n.t('Loading…')}</div>
			{:else if !entries.length}
				<div class="text-xs text-gray-500 dark:text-gray-400 py-6 text-center">
					{$i18n.t('No recent activity for this integration.')}
				</div>
			{:else}
				<ol class="space-y-2">
					{#each entries as e, i (i)}
						<li class="flex items-start gap-2.5">
							<span class="mt-1.5 size-1.5 rounded-full shrink-0 {dotFor(e.status)}"></span>
							<div class="min-w-0 flex-1">
								<div class="flex items-baseline gap-2">
									<span class="text-xs font-medium text-gray-800 dark:text-gray-100 truncate">
										{e.title || e.kind || $i18n.t('Event')}
									</span>
									<span class="ml-auto text-[10px] text-gray-500 dark:text-gray-400 tabular-nums shrink-0">{fmtTs(e.ts)}</span>
								</div>
								{#if e.detail}
									<div class="text-[11px] text-gray-500 leading-snug break-words">{e.detail}</div>
								{/if}
							</div>
						</li>
					{/each}
				</ol>
			{/if}
		</div>
	</aside>
{/if}
