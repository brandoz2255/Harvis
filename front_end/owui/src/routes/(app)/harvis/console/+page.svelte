<script lang="ts">
	// Dev Console v0 — one operator dashboard composing already-live Harvis endpoints:
	// provider readiness (/api/harvis/providers), background jobs (/api/harvis/jobs),
	// and recent runs (/api/workspace/history). Read-mostly: the only action is killing
	// a running background job. No auto-push/deploy — coding stays inside the visible
	// plan→sandbox→diff→approve loop that lives in the VibeCode surface.
	import { getContext, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';
	import { chatId } from '$lib/stores';

	const i18n: any = getContext('i18n');
	const backToChat = () => goto($chatId ? `/c/${$chatId}` : '/');

	let providers: any[] = [];
	let providerNote = '';
	let jobs: any[] = [];
	let runs: any[] = [];
	let loading = true;
	let refreshing = false;
	// per-source failure flags — getJSON's null means the request failed, and a
	// failed fetch must never render as "no providers / no jobs / no runs"
	let providersError = false;
	let jobsError = false;
	let runsError = false;

	const auth = () => ({ Authorization: `Bearer ${localStorage.token}` });
	const getJSON = async (url: string) =>
		fetch(url, { headers: auth(), credentials: 'include' })
			.then((r) => (r.ok ? r.json() : null))
			.catch(() => null);

	const load = async () => {
		refreshing = true;
		const [p, j, h] = await Promise.all([
			getJSON('/api/harvis/providers'),
			getJSON('/api/harvis/jobs?limit=25'),
			getJSON('/api/workspace/history?top_level=1')
		]);
		providersError = p === null;
		jobsError = j === null;
		runsError = h === null;
		providers = Array.isArray(p?.providers) ? p.providers : [];
		providerNote = p?.note ?? '';
		jobs = Array.isArray(j?.jobs) ? j.jobs : [];
		runs = (Array.isArray(h?.runs) ? h.runs : []).slice(0, 12);
		loading = false;
		refreshing = false;
	};

	// backend fully unreachable — one honest error branch instead of three
	$: allDown = providersError && jobsError && runsError;

	const killJob = async (id: string) => {
		const res = await fetch(`/api/harvis/jobs/${id}`, { method: 'DELETE', headers: auth() });
		if (res.ok) {
			toast.success($i18n.t('Job stopped.'));
			await load();
		} else {
			toast.error($i18n.t('Could not stop the job.'));
		}
	};

	const fmtTime = (ts: number | null) => {
		if (!ts) return '—';
		try {
			return new Date(ts * 1000).toLocaleString(undefined, {
				month: 'short',
				day: 'numeric',
				hour: '2-digit',
				minute: '2-digit'
			});
		} catch {
			return '—';
		}
	};
	const dur = (ms: number | null) => (ms ? (ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`) : '—');
	const isLive = (s: string) => ['running', 'started', 'active', 'in_progress'].includes(String(s || '').toLowerCase());
	const isErr = (s: string) => ['error', 'failed', 'killed', 'cancelled', 'canceled'].includes(String(s || '').toLowerCase());

	// status → semantic colour (form, not just number, per the operator glance)
	const runDot = (s: string) => (isLive(s) ? 'bg-blue-500' : isErr(s) ? 'bg-red-500' : 'bg-emerald-500');

	onMount(load);
</script>

<div class="max-w-6xl mx-auto w-full px-4 py-5">
	<!-- Header -->
	<div class="flex items-center justify-between gap-3 mb-1">
		<div class="flex items-center gap-2.5">
			<button on:click={backToChat} class="text-gray-400 hover:text-gray-700 dark:hover:text-gray-200" title={$i18n.t('Back to chat')} aria-label={$i18n.t('Back to chat')}>
				<svg class="size-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6" /></svg>
			</button>
			<svg class="size-6 text-blue-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="14" rx="2" /><path d="M8 21h8M9 8l3 3-3 3M14 14h3" /></svg>
			<div>
				<h1 class="text-xl font-semibold text-gray-800 dark:text-gray-100">{$i18n.t('Dev Console')}</h1>
				<p class="text-xs text-gray-500">{$i18n.t('Providers, background jobs and recent runs — one operator view.')}</p>
			</div>
		</div>
		<button
			on:click={load}
			disabled={refreshing}
			class="inline-flex items-center gap-1.5 rounded-full border border-gray-200 dark:border-gray-800 px-3 py-2 text-xs font-medium text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-850 disabled:opacity-40 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
		>
			<svg class="size-3.5 {refreshing ? 'animate-spin' : ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6" /></svg>
			{$i18n.t('Refresh')}
		</button>
	</div>

	{#if loading}
		<div class="text-sm text-gray-500 py-10 text-center">{$i18n.t('Loading…')}</div>
	{:else if allDown}
		<div class="text-sm text-gray-500 py-10 text-center">
			{$i18n.t('Could not reach the backend — providers, jobs and runs are unavailable.')}
			<button on:click={load} class="ml-2 text-blue-600 dark:text-blue-400 hover:underline"
				>{$i18n.t('Retry')}</button
			>
		</div>
	{:else}
		<div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-4">
			<!-- Provider readiness -->
			<section class="rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-4">
				<h2 class="text-sm font-semibold text-gray-700 dark:text-gray-200 mb-2.5">{$i18n.t('Provider readiness')}</h2>
				<div class="space-y-1.5">
					{#if providersError}
						<div class="text-xs text-red-500 dark:text-red-400 py-1">{$i18n.t('Could not load providers.')} <button on:click={load} class="text-blue-600 dark:text-blue-400 hover:underline">{$i18n.t('Retry')}</button></div>
					{:else}
					{#each providers as p (p.id)}
						<div class="rounded-xl border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-950 px-3 py-2">
							<div class="flex items-center gap-2">
								<span class="size-2 rounded-full {p.ready ? 'bg-emerald-500' : 'bg-amber-500'}"></span>
								<span class="text-sm font-medium text-gray-800 dark:text-gray-100">{p.id}</span>
								<span class="text-[10px] text-gray-400 bg-gray-100 dark:bg-gray-850 rounded px-1.5 py-0.5">{p.kind}{p.lane ? ` · lane ${p.lane}` : ''}</span>
								<span class="ml-auto text-[11px] {p.ready ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'}">{p.ready ? $i18n.t('ready') : $i18n.t('not ready')}</span>
							</div>
							{#if !p.ready && p.reason}
								<div class="text-[11px] text-amber-600 dark:text-amber-400 mt-1">{p.reason}</div>
							{/if}
							{#if p.capabilities?.length}
								<div class="flex flex-wrap gap-1 mt-1.5">
									{#each p.capabilities as c}
										<span class="text-[10px] text-gray-500 bg-gray-100 dark:bg-gray-850 rounded px-1.5 py-0.5">{c}</span>
									{/each}
								</div>
							{/if}
						</div>
					{:else}
						<div class="text-xs text-gray-500 py-1">{$i18n.t('No providers reported.')}</div>
					{/each}
					{/if}
				</div>
				{#if providerNote}
					<p class="text-[11px] text-gray-400 mt-2 leading-snug">{providerNote}</p>
				{/if}
			</section>

			<!-- Background jobs -->
			<section class="rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-4">
				<h2 class="text-sm font-semibold text-gray-700 dark:text-gray-200 mb-2.5">{$i18n.t('Background jobs')}</h2>
				<div class="space-y-1.5">
					{#if jobsError}
						<div class="text-xs text-red-500 dark:text-red-400 py-1">{$i18n.t('Could not load background jobs.')} <button on:click={load} class="text-blue-600 dark:text-blue-400 hover:underline">{$i18n.t('Retry')}</button></div>
					{:else}
					{#each jobs as j (j.id)}
						<div class="rounded-xl border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-950 px-3 py-2">
							<div class="flex items-center gap-2">
								<span class="size-2 rounded-full {runDot(j.status)}"></span>
								<span class="text-xs font-mono text-gray-700 dark:text-gray-200 truncate">{j.command || j.id}</span>
								<span class="ml-auto shrink-0 text-[10px] text-gray-500 bg-gray-100 dark:bg-gray-850 rounded px-1.5 py-0.5">{j.status || '—'}{j.exit_code != null ? ` · exit ${j.exit_code}` : ''}</span>
								{#if isLive(j.status)}
									<button on:click={() => killJob(j.id)} class="shrink-0 text-[11px] text-red-500 hover:bg-red-50 dark:hover:bg-red-950 rounded px-1.5 py-1">{$i18n.t('Stop')}</button>
								{/if}
							</div>
							<div class="text-[10px] text-gray-400 mt-0.5">{fmtTime(j.started_at)}{j.finished_at ? ` → ${fmtTime(j.finished_at)}` : ''}</div>
						</div>
					{:else}
						<div class="text-xs text-gray-500 py-1">{$i18n.t('No background jobs.')}</div>
					{/each}
					{/if}
				</div>
			</section>

			<!-- Recent runs (full width) -->
			<section class="lg:col-span-2 rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-4">
				<h2 class="text-sm font-semibold text-gray-700 dark:text-gray-200 mb-2.5">{$i18n.t('Recent runs')}</h2>
				<div class="space-y-1.5">
					{#if runsError}
						<div class="text-xs text-red-500 dark:text-red-400 py-1">{$i18n.t('Could not load recent runs.')} <button on:click={load} class="text-blue-600 dark:text-blue-400 hover:underline">{$i18n.t('Retry')}</button></div>
					{:else}
					{#each runs as r (r.id)}
						<button
							on:click={() => goto(`/harvis/agent-studio/run/${r.id}`)}
							class="w-full text-left rounded-xl border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-950 px-3 py-2 hover:border-gray-200 dark:hover:border-gray-800 transition"
						>
							<div class="flex items-center gap-2">
								<span class="size-2 rounded-full {runDot(r.status)}"></span>
								<span class="text-sm text-gray-800 dark:text-gray-100 truncate flex-1">{r.task_brief || r.final_summary || r.id}</span>
								<span class="shrink-0 text-[10px] text-gray-500 bg-gray-100 dark:bg-gray-850 rounded px-1.5 py-0.5">{r.status || '—'}</span>
							</div>
							<div class="flex flex-wrap items-center gap-1.5 mt-1 text-[10px] text-gray-400">
								{#if r.model_name}<span class="font-mono text-gray-500">{r.model_name}</span>{/if}
								<span>· {fmtTime(r.started_at)}</span>
								{#if r.duration_ms}<span>· {dur(r.duration_ms)}</span>{/if}
								{#if (r.prompt_tokens || r.completion_tokens)}
									<span>· {(r.prompt_tokens || 0) + (r.completion_tokens || 0)} tok</span>
								{/if}
								{#if r.tool_calls}<span>· {r.tool_calls} tools</span>{/if}
							</div>
						</button>
					{:else}
						<div class="text-xs text-gray-500 py-1">{$i18n.t('No recent runs.')}</div>
					{/each}
					{/if}
				</div>
			</section>
		</div>
	{/if}
</div>
