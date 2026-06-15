<script lang="ts">
	import { onDestroy, tick, getContext } from 'svelte';
	import { writable } from 'svelte/store';
	import {
		SvelteFlow,
		Background,
		BackgroundVariant,
		Controls,
		useSvelteFlow,
		useNodesInitialized
	} from '@xyflow/svelte';
	import '@xyflow/svelte/dist/style.css';
	import { goto } from '$app/navigation';
	import { theme } from '$lib/stores';
	import WorkflowNode from './WorkflowNode.svelte';
	import NeuralMapNode from './NeuralMapNode.svelte';
	import { eventsToGraph } from './eventsToGraph';
	import type { WorkspaceEvent } from '$lib/apis/streaming/workspace-stream';

	const i18n: any = getContext('i18n');

	// Either stream `events` (run-view) OR a precomputed `graph` (Global Map).
	// `graph` wins when set; otherwise the graph is derived from events.
	export let events: WorkspaceEvent[] = [];
	export let graph: { nodes: any[]; edges: any[] } | null = null;
	// When true, smoothly pan/zoom to the newest node as it streams in (run view).
	// Parents pass `followLatest={running}` so it stops following once the run ends.
	export let followLatest = false;

	// A run node navigates to its run page; a session hub opens its chat
	// (discord-* session ids have no chat page → inert).
	const onNodeClick = (e: any) => {
		const n = e?.detail?.node;
		if (n?.data?.kind === 'run' && n.data.runId) {
			goto(`/harvis/agent-studio/run/${n.data.runId}`);
		} else if (
			n?.data?.kind === 'session' &&
			n.data.sessionId &&
			!String(n.data.sessionId).startsWith('discord-')
		) {
			goto(`/c/${n.data.sessionId}`);
		}
	};

	const nodes = writable<any[]>([]);
	const edges = writable<any[]>([]);
	const nodeTypes = { custom: WorkflowNode, neural: NeuralMapNode };

	const { fitView, setCenter } = useSvelteFlow();
	const nodesInitialized = useNodesInitialized();
	let fitted = false;

	// Whole-graph recompute on each event append. Stable ids + deterministic
	// positions mean SvelteFlow diffs cleanly. Set edges BEFORE nodes so an edge
	// never references a not-yet-present node for a frame.
	$: {
		const g = graph ?? eventsToGraph(events);
		edges.set(g.edges);
		nodes.set(g.nodes);
	}

	// fitView ONCE on first initialization (never in the recompute → no jitter).
	const unsub = nodesInitialized.subscribe(async (init) => {
		if (init && !fitted) {
			fitted = true;
			await tick();
			fitView();
		}
	});

	// Follow-latest: once the first fit has happened, glide to the newest node as
	// it streams in (smooth zoom toward the freshest tool "pill"). Guarded on the
	// last-followed id so it only fires when a genuinely new node appears.
	let lastFollowedId = '';
	$: if (followLatest && fitted && $nodes.length) {
		const latest = $nodes[$nodes.length - 1];
		if (latest && latest.id !== lastFollowedId) {
			lastFollowedId = latest.id;
			tick().then(() => {
				try {
					// setCenter (vs fitView{nodes}) is supported across xyflow versions and
					// keeps the motion a smooth pan/zoom INTO the freshest box's center —
					// zoom 1.6 so the camera visibly closes in on that single node.
					const p = latest.position ?? { x: 0, y: 0 };
					const w = latest.width ?? latest.measured?.width ?? 200;
					const h = latest.height ?? latest.measured?.height ?? 64;
					setCenter(p.x + w / 2, p.y + h / 2, { zoom: 1.6, duration: 500 });
				} catch (_) {
					// node not measured yet — skip this hop, the next one will catch up.
				}
			});
		}
	}

	const resolveColorMode = (t: string): 'dark' | 'light' =>
		t.includes('dark')
			? 'dark'
			: t === 'system'
				? window.matchMedia('(prefers-color-scheme: dark)').matches
					? 'dark'
					: 'light'
				: 'light';

	onDestroy(() => {
		unsub();
		nodes.set([]);
		edges.set([]);
	});
</script>

<div class="w-full h-full">
	{#if $nodes.length > 0}
		<SvelteFlow
			{nodes}
			{nodeTypes}
			{edges}
			minZoom={0.2}
			nodesConnectable={false}
			nodesDraggable={false}
			colorMode={resolveColorMode($theme)}
			on:nodeclick={onNodeClick}
		>
			<Controls showLock={false} />
			<Background variant={BackgroundVariant.Dots} />
		</SvelteFlow>
	{:else}
		<div class="w-full h-full flex items-center justify-center text-xs text-gray-400">
			{$i18n.t('Waiting for run activity…')}
		</div>
	{/if}
</div>

<style>
	/* Hide the SvelteFlow attribution watermark inside Harvis canvases. */
	:global(.svelte-flow__attribution) {
		display: none;
	}
</style>
