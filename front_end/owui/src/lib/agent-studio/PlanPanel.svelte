<script lang="ts">
	import { getContext, onDestroy, createEventDispatcher } from 'svelte';
	import { subscribeRun } from '$lib/apis/streaming/runStream';

	const i18n: any = getContext('i18n');
	const dispatch = createEventDispatcher();

	// The run whose plan to stream. Empty = idle. The backend's orchestrator emits a
	// structured `plan` event (steps) + agent_start/agent_end — we map those to status.
	// Consumes the SHARED per-run stream store (subscribeRun) so this panel rides the same
	// single SSE connection as RunView / the Workflow Inspector instead of opening a second
	// one; steps are re-folded from the full event array on each batched flush.
	export let wsId = '';

	type Step = {
		role?: string;
		label: string;
		model?: string;
		task?: string;
		status: 'queued' | 'running' | 'done' | 'error';
	};
	let steps: Step[] = [];
	// Tell the host whether a plan exists (so the dock can auto-show the Plan panel).
	$: dispatch('steps', { count: steps.length });
	let uniform = false;
	let activeId = '';
	let _sub: ReturnType<typeof subscribeRun> | null = null;
	let _unsubStore: (() => void) | null = null;

	// Fold the run's full event history into step states. Deterministic full re-fold (the
	// shared store replays history on reconnect), reproducing exactly what the old
	// incremental consumer rendered: `plan` seeds queued steps, agent_start/agent_end
	// advance the FIRST matching not-yet-finished label, a terminal event settles the rest.
	const fold = (events: any[]) => {
		let next: Step[] = [];
		let uni = false;
		const mark = (label: string, status: Step['status']) => {
			const s = next.find((x) => x.label === label && x.status !== 'done' && x.status !== 'error');
			if (s) s.status = status;
		};
		for (const evt of events) {
			const e = evt as any;
			if (evt.type === 'plan' && Array.isArray(e.steps)) {
				next = e.steps.map((s: any) => ({ ...s, status: 'queued' as const }));
				uni = !!e.uniform;
			} else if (evt.type === 'agent_start' && e.agent_label) {
				mark(e.agent_label, 'running');
			} else if (evt.type === 'agent_end' && e.agent_label) {
				mark(e.agent_label, e.success === false ? 'error' : 'done');
			} else if (['done', 'cancelled', 'error'].includes(evt.type)) {
				next = next.map((s) =>
					s.status === 'running' || s.status === 'queued'
						? { ...s, status: evt.type === 'error' ? 'error' : 'done' }
						: s
				);
			}
		}
		steps = next;
		uniform = uni;
	};

	const stop = () => {
		_unsubStore?.();
		_unsubStore = null;
		_sub?.unsubscribe();
		_sub = null;
	};
	const start = (id: string) => {
		stop();
		steps = [];
		uniform = false;
		activeId = id;
		if (!id) return;
		_sub = subscribeRun(id);
		_unsubStore = _sub.store.subscribe((s) => fold(s.events));
	};
	$: if (wsId !== activeId) start(wsId);
	onDestroy(stop);

	// Matches the unified cockpit palette in runFormat.ts (done = emerald, not blue).
	const dot = (s: Step['status']) =>
		s === 'done'
			? 'bg-emerald-500'
			: s === 'error'
				? 'bg-red-500'
				: s === 'running'
					? 'bg-blue-500 animate-pulse'
					: 'bg-gray-400 dark:bg-gray-600';
</script>

<div class="text-xs">
	{#if !steps.length}
		<div class="text-gray-400 px-1 py-2">{$i18n.t('No plan yet — start a run.')}</div>
	{:else}
		<div class="space-y-1.5">
			{#each steps as s}
				<div class="flex items-start gap-2">
					<span class="size-2 rounded-full mt-1 shrink-0 {dot(s.status)}"></span>
					<div class="min-w-0">
						<div class="text-gray-700 dark:text-gray-200 leading-snug break-words">
							{s.label}{#if s.model}<span class="text-gray-400"> · {s.model}</span>{/if}
						</div>
						{#if s.task}<div class="text-[11px] text-gray-400 line-clamp-2">{s.task}</div>{/if}
					</div>
				</div>
			{/each}
		</div>
		{#if uniform}
			<div class="text-[10px] text-gray-400 mt-2">{$i18n.t('All sub-agents on one model.')}</div>
		{/if}
	{/if}
</div>
