<script lang="ts">
	import { getContext, onDestroy } from 'svelte';
	import { createWorkspaceStream } from '$lib/apis/streaming/workspace-stream';

	const i18n: any = getContext('i18n');

	// The run whose plan to stream. Empty = idle. The backend's orchestrator emits a
	// structured `plan` event (steps) + agent_start/agent_end — we map those to status.
	export let wsId = '';

	type Step = {
		role?: string;
		label: string;
		model?: string;
		task?: string;
		status: 'queued' | 'running' | 'done' | 'error';
	};
	let steps: Step[] = [];
	let uniform = false;
	let controller: AbortController | null = null;
	let activeId = '';

	const markByLabel = (label: string, status: Step['status']) => {
		const s = steps.find((x) => x.label === label && x.status !== 'done' && x.status !== 'error');
		if (s) {
			s.status = status;
			steps = [...steps];
		}
	};

	const consume = async (id: string) => {
		controller = new AbortController();
		try {
			for await (const evt of createWorkspaceStream(id, localStorage.token, controller.signal)) {
				const e = evt as any;
				if (evt.type === 'stream_end') break;
				if (evt.type === 'plan' && Array.isArray(e.steps)) {
					steps = e.steps.map((s: any) => ({ ...s, status: 'queued' }));
					uniform = !!e.uniform;
				} else if (evt.type === 'agent_start' && e.agent_label) {
					markByLabel(e.agent_label, 'running');
				} else if (evt.type === 'agent_end' && e.agent_label) {
					markByLabel(e.agent_label, e.success === false ? 'error' : 'done');
				} else if (['done', 'cancelled', 'error'].includes(evt.type)) {
					steps = steps.map((s) =>
						s.status === 'running' || s.status === 'queued'
							? { ...s, status: evt.type === 'error' ? 'error' : 'done' }
							: s
					);
					break;
				}
			}
		} catch (e: any) {
			if (e?.name === 'AbortError') return;
		}
	};

	const start = (id: string) => {
		controller?.abort();
		steps = [];
		uniform = false;
		activeId = id;
		if (id) consume(id);
	};
	$: if (wsId !== activeId) start(wsId);
	onDestroy(() => controller?.abort());

	const dot = (s: Step['status']) =>
		s === 'done'
			? 'bg-blue-500'
			: s === 'error'
				? 'bg-red-500'
				: s === 'running'
					? 'bg-blue-500 animate-pulse'
					: 'bg-gray-300 dark:bg-gray-600';
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
