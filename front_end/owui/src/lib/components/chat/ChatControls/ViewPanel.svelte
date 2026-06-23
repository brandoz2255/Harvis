<script lang="ts">
	import { onMount, onDestroy, getContext } from 'svelte';
	import { WEBUI_BASE_URL } from '$lib/constants';
	import { chatId, dockedRunId } from '$lib/stores';
	import RunRow from '$lib/agent-studio/RunRow.svelte';
	import ArrowPath from '$lib/components/icons/ArrowPath.svelte';

	const i18n: any = getContext('i18n');

	// The process rail = THIS chat's background tasks, as one dense scannable column.
	// Runs are DB-persisted keyed by session_id (= the OWUI chat_id), so the list +
	// statuses persist with the chat: reopening it re-shows its tasks. Compact rows
	// expand IN PLACE to the run's detail — no separate page, stays linked to the chat.
	type Run = {
		id: string;
		session_id?: string;
		task_brief?: string;
		status?: string;
		duration_ms?: number;
		tool_calls?: number;
		child_count?: number;
		completed_at?: string;
		final_summary?: string;
		error_message?: string;
	};

	let runs: Run[] = [];
	let loaded = false;
	let error = '';
	let timer: ReturnType<typeof setTimeout> | null = null;
	let destroyed = false;
	let expandedId: string | null = null;
	let finishedOpen = true;

	$: cid = $chatId || '';

	// Per-chat "Clear": hide finished runs completed at/before this mark. Persisted in
	// localStorage keyed by chat so the cleared state survives reloads + is per-chat.
	let clearedAt = 0;
	const clearKey = (c: string) => `harvis-tasks-cleared:${c}`;
	const loadCleared = (c: string) => {
		try {
			clearedAt = c ? Number(localStorage.getItem(clearKey(c)) || 0) : 0;
		} catch (_) {
			clearedAt = 0;
		}
	};

	const tick = async () => {
		try {
			if (!cid) {
				runs = [];
				error = '';
				loaded = true;
				schedule();
				return;
			}
			// /active FIRST — it orphan-cleans stale `running` rows server-side, so the
			// /history snapshot that follows is trustworthy.
			await fetch(`${WEBUI_BASE_URL}/api/workspace/active`, {
				headers: { Authorization: `Bearer ${localStorage.token}` },
				credentials: 'include'
			}).catch(() => {});

			const res = await fetch(
				`${WEBUI_BASE_URL}/api/workspace/history?top_level=1&session_id=${encodeURIComponent(cid)}`,
				{
					headers: { Authorization: `Bearer ${localStorage.token}` },
					credentials: 'include'
				}
			);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			runs = data?.runs ?? [];
			error = '';
		} catch (e: any) {
			error = String(e?.message ?? e);
		} finally {
			loaded = true;
			schedule();
		}
	};

	// 4s while anything is running, 30s when idle.
	const schedule = () => {
		if (destroyed) return;
		if (timer) clearTimeout(timer);
		timer = setTimeout(tick, runs.some((r) => r.status === 'running') ? 4000 : 30000);
	};

	// Refetch + reset the cleared mark when the active chat changes.
	let lastCid = ' ';
	$: if (cid !== lastCid) {
		lastCid = cid;
		loaded = false;
		expandedId = null;
		loadCleared(cid);
		tick();
	}

	// WorkspaceRunCard's "View activity" docks a run → expand its row in the list.
	$: if ($dockedRunId && $dockedRunId !== expandedId) expandedId = $dockedRunId;

	const ts = (s?: string) => (s ? Date.parse(s) : 0);
	$: running = runs.filter((r) => r.status === 'running');
	$: finished = runs.filter((r) => r.status !== 'running' && ts(r.completed_at) > clearedAt);

	const toggle = (id: string) => {
		expandedId = expandedId === id ? null : id;
		if (expandedId === null) dockedRunId.set(null);
	};

	const clearFinished = () => {
		clearedAt = Date.now();
		try {
			localStorage.setItem(clearKey(cid), String(clearedAt));
		} catch (_) {}
		if (expandedId && !running.some((r) => r.id === expandedId)) {
			expandedId = null;
			dockedRunId.set(null);
		}
	};

	const stopRun = async (id: string) => {
		try {
			await fetch(`${WEBUI_BASE_URL}/api/workspace/cancel/${id}`, {
				method: 'POST',
				headers: { Authorization: `Bearer ${localStorage.token}` },
				credentials: 'include'
			});
		} catch (e) {
			console.error('workspace cancel failed', e);
		}
		tick();
	};

	onMount(tick);
	onDestroy(() => {
		destroyed = true;
		if (timer) clearTimeout(timer);
	});
</script>

<div class="space-y-3 pb-4">
	{#if !loaded}
		<div class="text-gray-400 text-xs py-3 px-1">{$i18n.t('Loading…')}</div>
	{:else if error}
		<div class="text-red-500 text-xs py-2 px-1">{error}</div>
	{:else}
		{#if running.length}
			<div class="space-y-1.5">
				<div class="px-1 flex items-center gap-2">
					<span class="size-1.5 rounded-full bg-blue-500 animate-pulse"></span>
					<span class="text-[10px] uppercase tracking-wider text-gray-400"
						>{$i18n.t('Running')} {running.length}</span
					>
				</div>
				{#each running as r (r.id)}
					<RunRow run={r} expanded={expandedId === r.id} onToggle={toggle} onStop={stopRun} />
				{/each}
			</div>
		{/if}

		<div class="space-y-1.5">
			<div class="px-1 flex items-center gap-2">
				<button
					type="button"
					class="flex items-center gap-1 text-[10px] uppercase tracking-wider text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition"
					on:click={() => (finishedOpen = !finishedOpen)}
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2.5"
						class="size-3 transition {finishedOpen ? 'rotate-90' : ''}"
						><path d="M9 6l6 6-6 6" stroke-linecap="round" stroke-linejoin="round" /></svg
					>
					{$i18n.t('Finished')} {finished.length}
				</button>
				<button
					type="button"
					class="ml-auto p-1 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition"
					aria-label={$i18n.t('Refresh')}
					on:click={tick}
				>
					<ArrowPath className="size-3.5" />
				</button>
				{#if finished.length}
					<button
						type="button"
						class="text-[10px] text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition"
						on:click={clearFinished}>{$i18n.t('Clear')}</button
					>
				{/if}
			</div>
			{#if finishedOpen}
				{#if finished.length}
					{#each finished as r (r.id)}
						<RunRow run={r} expanded={expandedId === r.id} onToggle={toggle} onStop={stopRun} />
					{/each}
				{:else if !running.length}
					<div class="text-gray-400 text-xs py-2 px-1">
						{$i18n.t('No tasks for this chat yet.')}
					</div>
				{/if}
			{/if}
		</div>
	{/if}
</div>
