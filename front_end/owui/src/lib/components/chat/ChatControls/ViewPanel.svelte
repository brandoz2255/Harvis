<script lang="ts">
	import { onMount, onDestroy, getContext } from 'svelte';
	import { WEBUI_BASE_URL } from '$lib/constants';
	import { workspaceControlsTab, dockedRunId } from '$lib/stores';
	import WorkspaceActivity from '$lib/components/chat/WorkspaceActivity.svelte';
	import RailCard from '$lib/components/common/RailCard.svelte';
	import Bolt from '$lib/components/icons/Bolt.svelte';
	import ClockRotateRight from '$lib/components/icons/ClockRotateRight.svelte';
	import ArrowPath from '$lib/components/icons/ArrowPath.svelte';

	const i18n: any = getContext('i18n');

	type Run = {
		id: string;
		task_brief?: string;
		status?: string;
		duration_ms?: number;
		tool_calls?: number;
		final_summary?: string;
		error_message?: string;
	};

	let runs: Run[] = [];
	let loaded = false;
	let error = '';
	let timer: ReturnType<typeof setTimeout> | null = null;
	let destroyed = false;

	let progressOpen = true;
	let recentOpen = true;

	$: progress = runs.filter((r) => r.status === 'running');
	$: recent = runs.filter((r) => r.status !== 'running');

	const tick = async () => {
		try {
			// /active FIRST — it orphan-cleans stale `running` rows server-side,
			// so the /history snapshot that follows is trustworthy.
			await fetch(`${WEBUI_BASE_URL}/api/workspace/active`, {
				headers: { Authorization: `Bearer ${localStorage.token}` },
				credentials: 'include'
			}).catch(() => {});

			const res = await fetch(`${WEBUI_BASE_URL}/api/workspace/history`, {
				headers: { Authorization: `Bearer ${localStorage.token}` },
				credentials: 'include'
			});
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

	// 5s while anything is running, 30s when idle
	const schedule = () => {
		if (destroyed) return;
		if (timer) clearTimeout(timer);
		timer = setTimeout(tick, runs.some((r) => r.status === 'running') ? 5000 : 30000);
	};

	const dockRun = (id: string) => {
		// Mirrors WorkspaceRunCard.dockRun — the pane is already open here
		dockedRunId.set(id);
		workspaceControlsTab.set('overview');
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

<div class="space-y-2 pb-4">
	<RailCard title={$i18n.t('Progress')} icon={Bolt} bind:open={progressOpen}>
		<svelte:fragment slot="actions">
			<button
				type="button"
				class="p-1 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition"
				aria-label={$i18n.t('Refresh')}
				on:click={tick}
			>
				<ArrowPath className="size-3.5" />
			</button>
		</svelte:fragment>

		{#if !loaded}
			<div class="text-gray-400 text-xs py-2">{$i18n.t('Loading…')}</div>
		{:else if error}
			<div class="text-red-500 text-xs py-2">{error}</div>
		{:else if progress.length === 0}
			<div class="text-gray-400 text-xs py-2">{$i18n.t('No tasks running.')}</div>
		{:else}
			<WorkspaceActivity embed runsOverride={progress} onOpenRun={dockRun} />
			<div class="mt-2 flex flex-wrap gap-1.5">
				{#each progress as r (r.id)}
					<button
						type="button"
						class="text-[11px] px-2 py-0.5 rounded-lg border border-red-200 dark:border-red-900/50 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition"
						on:click={() => stopRun(r.id)}
					>
						{$i18n.t('Stop')}
						{(r.task_brief || r.id).slice(0, 24)}
					</button>
				{/each}
			</div>
		{/if}
	</RailCard>

	<RailCard title={$i18n.t('Recent')} icon={ClockRotateRight} bind:open={recentOpen}>
		{#if !loaded}
			<div class="text-gray-400 text-xs py-2">{$i18n.t('Loading…')}</div>
		{:else if recent.length === 0}
			<div class="text-gray-400 text-xs py-2">{$i18n.t('No workspace runs yet.')}</div>
		{:else}
			<WorkspaceActivity embed runsOverride={recent} onOpenRun={dockRun} />
		{/if}
	</RailCard>
</div>
