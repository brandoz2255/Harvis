<script lang="ts">
	// Provider wrapper. The xyflow hooks (useSvelteFlow / useNodesInitialized) used
	// in WorkflowFlow require a SvelteFlowProvider ANCESTOR — it must wrap a CHILD,
	// not live in the same component that calls the hooks (mirrors Overview.svelte
	// → View.svelte). Keep this split.
	import { SvelteFlowProvider } from '@xyflow/svelte';
	import WorkflowFlow from './WorkflowFlow.svelte';
	import type { WorkspaceEvent } from '$lib/apis/streaming/workspace-stream';

	export let events: WorkspaceEvent[] = [];
	// Optional precomputed graph (Global Map). When set, WorkflowFlow uses it
	// instead of deriving from events. Run-view keeps passing only `events`.
	export let graph: { nodes: any[]; edges: any[] } | null = null;
	// Forwarded to WorkflowFlow — smoothly zoom the camera to each newest node as
	// it spawns (the live run-map "follow" behavior). MUST be forwarded or the
	// follow silently no-ops (WorkflowFlow's prop stays its default false).
	export let followLatest = false;
</script>

<SvelteFlowProvider>
	<WorkflowFlow {events} {graph} {followLatest} />
</SvelteFlowProvider>
