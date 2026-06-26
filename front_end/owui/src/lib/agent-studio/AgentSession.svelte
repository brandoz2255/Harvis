<script lang="ts">
	import { getContext } from 'svelte';
	import { statusDot, statusLabel, fmtDuration, fmtTokens } from './runFormat';
	import AgentTimeline from './AgentTimeline.svelte';
	import RunArtifacts from './RunArtifacts.svelte';
	import type { RunNode } from '$lib/apis/agent-runs';
	import type { WorkspaceEvent } from '$lib/apis/streaming/workspace-stream';

	const i18n: any = getContext('i18n');

	// One sub-agent's chat-like session: assigned task → its message/tool timeline → its
	// result → its diff. `events` is THIS agent's slice (the inspector groups by run_id).
	// `running` is the PARENT run's flag — orchestrated diffs are written when the parent
	// completes, so the diff reloads on `!running`, not on the child finishing.
	export let agent: RunNode;
	export let events: WorkspaceEvent[] = [];
	export let running = false;
	export let parentId = '';

	const TERMINAL = new Set(['done', 'error', 'cancelled']);
	$: agentRunning = running && !TERMINAL.has(agent?.status || '');
	$: tokens = Number(agent?.prompt_tokens || 0) + Number(agent?.completion_tokens || 0);
	// The agent's display name = the label carried on its events (matches the diff's label
	// "{agent_label} · {branch}" exactly); fall back to its role/task.
	$: displayLabel =
		events.find((e) => e.agent_label)?.agent_label ||
		agent?.role ||
		(agent?.task ? agent.task.slice(0, 32) : 'Agent');
	$: task = agent?.task || '';
</script>

<div class="h-full flex flex-col min-h-0">
	<!-- header: who · model · status · elapsed · tokens · tools -->
	<div class="shrink-0 px-1 pb-2 mb-1 border-b border-white/8">
		<div class="flex items-center gap-2 flex-wrap text-xs">
			<span class="size-2 rounded-full shrink-0 {statusDot(agent?.status)}"></span>
			<span class="text-sm font-medium text-gray-100 truncate">{displayLabel}</span>
			{#if agent?.model_name}<span class="text-gray-500 truncate">· {agent.model_name}</span>{/if}
			<span class="text-gray-500">· {$i18n.t(statusLabel(agent?.status))}</span>
			{#if fmtDuration(agent?.duration_ms)}<span class="text-gray-500">· {fmtDuration(agent.duration_ms)}</span>{/if}
			<span class="ml-auto text-gray-500 tabular-nums shrink-0"
				>{fmtTokens(tokens)} {$i18n.t('tok')} · {agent?.tool_calls ?? 0} {$i18n.t('tools')}</span
			>
		</div>
	</div>

	<!-- scrollable session body -->
	<div class="flex-1 min-h-0 overflow-y-auto px-1 py-2 space-y-3">
		{#if task}
			<div>
				<div class="text-[10px] uppercase tracking-wider text-gray-500 mb-1">{$i18n.t('Task')}</div>
				<div
					class="rounded-2xl bg-white/[0.04] border border-white/8 px-3 py-2 text-sm text-gray-200 whitespace-pre-wrap break-words"
				>
					{task}
				</div>
			</div>
		{/if}

		<AgentTimeline {events} running={agentRunning} />

		{#if agent?.error}
			<div class="text-sm text-red-400 whitespace-pre-wrap break-words">{agent.error}</div>
		{/if}

		<!-- This agent's diff (filtered out of the parent's artifacts by label). -->
		<RunArtifacts wsId={parentId} mode="changes" bare agentLabel={displayLabel} done={!running} />
	</div>
</div>
