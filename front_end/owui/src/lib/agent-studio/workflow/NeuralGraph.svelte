<script lang="ts">
	// Live, Obsidian-graph-style force graph for the Neural Map. Unlike the old
	// SvelteFlow render (static positions ticked to convergence once), this runs a
	// CONTINUOUS d3-force simulation on an SVG: nodes drift + settle, dragging a
	// node perturbs the cloud and it springs back, hover highlights a node + its
	// neighbours (dimming the rest), and wheel/drag pan-zoom. Only d3-force is a
	// dependency — pan/zoom/drag are hand-rolled pointer math (no d3-zoom/drag).
	import { onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import {
		forceSimulation,
		forceLink,
		forceManyBody,
		forceCollide,
		forceX,
		forceY
	} from 'd3-force';
	import type { RunRow } from './runsToGraph';

	export let runs: RunRow[] = [];

	type GNode = {
		id: string;
		kind: 'session' | 'run';
		r: number;
		label: string;
		status?: string;
		sessionId?: string;
		runId?: string;
		count?: number;
		x?: number;
		y?: number;
		fx?: number | null;
		fy?: number | null;
	};
	type GLink = { source: any; target: any };

	let nodes: GNode[] = [];
	let links: GLink[] = [];
	const adj = new Map<string, Set<string>>();
	let sim: any = null;

	let wrap: HTMLDivElement;
	let W = 600;
	let H = 400;
	// view transform (pan tx/ty in px, zoom k); origin is the container centre.
	let tx = 0;
	let ty = 0;
	let k = 1;
	let hovered: string | null = null;
	let fitted = false;

	const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

	const colorFor = (n: GNode): string =>
		n.kind === 'session'
			? '#9ca3af'
			: n.status === 'error'
				? '#ef4444'
				: n.status === 'cancelled'
					? '#f59e0b'
					: '#3b82f6';

	// ── Build the graph (sessions = hubs, runs = spokes) + adjacency for hover. ──
	function build(rs: RunRow[]) {
		const bySession = new Map<string, RunRow[]>();
		const floaters: RunRow[] = [];
		for (const r of rs) {
			if (r.session_id) {
				const a = bySession.get(r.session_id) ?? [];
				a.push(r);
				bySession.set(r.session_id, a);
			} else floaters.push(r);
		}

		const ns: GNode[] = [];
		const ls: GLink[] = [];
		const mkRun = (r: RunRow): GNode => {
			const weight = r.tool_calls ?? (r.duration_ms ? r.duration_ms / 60000 : 0);
			return {
				id: `run:${r.id}`,
				kind: 'run',
				r: clamp(4 + 1.6 * Math.log2(1 + weight), 4, 11),
				label: r.task_brief || 'Workspace run',
				status: r.status || '',
				runId: r.id,
				sessionId: r.session_id
			};
		};
		for (const [sid, sruns] of bySession) {
			ns.push({
				id: `session:${sid}`,
				kind: 'session',
				r: Math.min(16, 9 + 2 * Math.log2(1 + sruns.length)),
				label: sid.startsWith('discord-') ? 'Discord session' : sruns[0]?.task_brief || 'Session',
				sessionId: sid,
				count: sruns.length
			});
			for (const r of sruns) {
				ns.push(mkRun(r));
				ls.push({ source: `session:${sid}`, target: `run:${r.id}` });
			}
		}
		for (const r of floaters) ns.push(mkRun(r));

		// adjacency by id (for hover neighbour highlight)
		adj.clear();
		for (const n of ns) adj.set(n.id, new Set());
		for (const l of ls) {
			adj.get(l.source as string)?.add(l.target as string);
			adj.get(l.target as string)?.add(l.source as string);
		}

		// seed positions in a small disc so it animates inward (Obsidian settle).
		ns.forEach((n, i) => {
			const a = (i / Math.max(1, ns.length)) * Math.PI * 2;
			n.x = Math.cos(a) * 60 + (i % 5) - 2;
			n.y = Math.sin(a) * 60 + (i % 3) - 1;
		});

		nodes = ns;
		links = ls;
		fitted = false;
		startSim();
	}

	function startSim() {
		if (sim) sim.stop();
		sim = forceSimulation(nodes as any)
			.force(
				'link',
				forceLink(links as any)
					.id((d: any) => d.id)
					.distance((l: any) => 42 + (l.source.r ?? 8) + (l.target.r ?? 8))
					.strength(0.6)
			)
			.force('charge', forceManyBody().strength(-170))
			.force('collide', forceCollide().radius((d: any) => d.r + 8))
			.force('x', forceX(0).strength(0.05))
			.force('y', forceY(0).strength(0.05))
			.alpha(0.9)
			.on('tick', () => {
				// reassign to trigger Svelte re-render each frame
				nodes = nodes;
				links = links;
				if (!fitted && sim.alpha() < 0.06) {
					fitted = true;
					fit();
				}
			});
	}

	// One-shot zoom/pan so the settled cloud fills the viewport.
	function fit() {
		if (!nodes.length || !W || !H) return;
		let minX = Infinity,
			minY = Infinity,
			maxX = -Infinity,
			maxY = -Infinity;
		for (const n of nodes) {
			minX = Math.min(minX, (n.x ?? 0) - n.r);
			minY = Math.min(minY, (n.y ?? 0) - n.r);
			maxX = Math.max(maxX, (n.x ?? 0) + n.r);
			maxY = Math.max(maxY, (n.y ?? 0) + n.r);
		}
		const gw = Math.max(1, maxX - minX);
		const gh = Math.max(1, maxY - minY);
		k = clamp(Math.min((W * 0.82) / gw, (H * 0.82) / gh), 0.25, 1.6);
		// centre the bbox midpoint at the container centre
		tx = -((minX + maxX) / 2) * k;
		ty = -((minY + maxY) / 2) * k;
	}

	// ── Hover dim logic (Obsidian-style: highlight node + neighbours). ──
	const nodeActive = (id: string): boolean =>
		hovered === null || id === hovered || (adj.get(hovered)?.has(id) ?? false);
	const linkActive = (l: GLink): boolean =>
		hovered === null || (l.source as any).id === hovered || (l.target as any).id === hovered;

	// ── Pointer interaction: pan (drag bg), zoom (wheel), drag node (spring-back). ──
	let dragNode: GNode | null = null;
	let panning = false;
	let lastPX = 0;
	let lastPY = 0;

	const toGraph = (px: number, py: number) => ({
		x: (px - W / 2 - tx) / k,
		y: (py - H / 2 - ty) / k
	});

	function onNodeDown(e: PointerEvent, n: GNode) {
		e.stopPropagation();
		(e.target as Element).setPointerCapture?.(e.pointerId);
		dragNode = n;
		sim?.alphaTarget(0.3).restart();
	}
	function onBgDown(e: PointerEvent) {
		panning = true;
		lastPX = e.offsetX;
		lastPY = e.offsetY;
	}
	function onMove(e: PointerEvent) {
		if (dragNode) {
			const g = toGraph(e.offsetX, e.offsetY);
			dragNode.fx = g.x;
			dragNode.fy = g.y;
			nodes = nodes;
		} else if (panning) {
			tx += e.offsetX - lastPX;
			ty += e.offsetY - lastPY;
			lastPX = e.offsetX;
			lastPY = e.offsetY;
		}
	}
	function onUp() {
		if (dragNode) {
			dragNode.fx = null;
			dragNode.fy = null;
			sim?.alphaTarget(0);
			dragNode = null;
		}
		panning = false;
	}
	function onWheel(e: WheelEvent) {
		e.preventDefault();
		const g = toGraph(e.offsetX, e.offsetY);
		const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
		k = clamp(k * factor, 0.2, 4);
		// keep the point under the cursor fixed
		tx = e.offsetX - W / 2 - g.x * k;
		ty = e.offsetY - H / 2 - g.y * k;
	}

	let moved = false;
	function onNodeClick(n: GNode) {
		if (moved) return;
		if (n.kind === 'session' && n.sessionId && !n.sessionId.startsWith('discord-')) {
			goto(`/c/${n.sessionId}`);
		} else if (n.kind === 'run' && n.runId) {
			goto(`/harvis/agent-studio/run/${n.runId}`);
		}
	}

	let ro: ResizeObserver | null = null;
	onMount(() => {
		const measure = () => {
			if (!wrap) return;
			W = wrap.clientWidth || 600;
			H = wrap.clientHeight || 400;
		};
		measure();
		ro = new ResizeObserver(measure);
		if (wrap) ro.observe(wrap);
		lastKey = runs.map((r) => r.id).join(',');
		build(runs);
	});
	onDestroy(() => {
		sim?.stop();
		ro?.disconnect();
	});

	// Rebuild when the run set changes (scope toggle / refresh).
	let lastKey = '';
	$: {
		const key = runs.map((r) => r.id).join(',');
		if (wrap && key !== lastKey) {
			lastKey = key;
			build(runs);
		}
	}

	// label visibility ~ Obsidian: fade out when zoomed far out
	$: labelOpacity = k < 0.45 ? 0 : k < 0.7 ? 0.5 : 1;
</script>

<div
	bind:this={wrap}
	class="w-full h-full overflow-hidden select-none touch-none"
	style="cursor: {panning ? 'grabbing' : 'grab'};"
	role="application"
	on:pointerdown={onBgDown}
	on:pointermove={(e) => {
		onMove(e);
		moved = true;
	}}
	on:pointerup={onUp}
	on:pointerleave={onUp}
	on:wheel={onWheel}
>
	<svg width={W} height={H} class="block">
		<g transform="translate({W / 2 + tx},{H / 2 + ty}) scale({k})">
			<!-- links -->
			{#each links as l}
				<line
					x1={(l.source.x ?? 0)}
					y1={(l.source.y ?? 0)}
					x2={(l.target.x ?? 0)}
					y2={(l.target.y ?? 0)}
					stroke="currentColor"
					class="text-gray-400 dark:text-gray-600"
					stroke-width={1 / k}
					opacity={hovered === null ? 0.35 : linkActive(l) ? 0.6 : 0.06}
				/>
			{/each}

			<!-- nodes -->
			{#each nodes as n (n.id)}
				<g
					transform="translate({n.x ?? 0},{n.y ?? 0})"
					opacity={nodeActive(n.id) ? 1 : 0.15}
					style="cursor: pointer;"
					role="button"
					tabindex="-1"
					on:pointerdown={(e) => {
						moved = false;
						onNodeDown(e, n);
					}}
					on:click={() => onNodeClick(n)}
					on:mouseenter={() => (hovered = n.id)}
					on:mouseleave={() => (hovered = null)}
				>
					{#if n.kind === 'run' && n.status === 'running'}
						<circle r={n.r + 3} fill={colorFor(n)} opacity="0.5">
							<animate attributeName="r" values="{n.r};{n.r + 5};{n.r}" dur="1.4s" repeatCount="indefinite" />
							<animate attributeName="opacity" values="0.5;0;0.5" dur="1.4s" repeatCount="indefinite" />
						</circle>
					{/if}
					<circle
						r={n.r}
						fill={colorFor(n)}
						stroke={n.kind === 'session' ? 'rgba(156,163,175,0.5)' : 'none'}
						stroke-width={n.kind === 'session' ? 2 / k : 0}
						class="transition-[r] duration-150"
						class:hovered={hovered === n.id}
					/>
					{#if labelOpacity > 0 || hovered === n.id}
						<text
							y={n.r + 9 / k}
							text-anchor="middle"
							font-size={9 / k}
							class="fill-gray-500 dark:fill-gray-400"
							opacity={hovered === n.id ? 1 : nodeActive(n.id) ? labelOpacity : 0}
							style="pointer-events:none;"
						>
							{n.label.length > 22 ? n.label.slice(0, 21) + '…' : n.label}
						</text>
					{/if}
				</g>
			{/each}
		</g>
	</svg>
</div>

<style>
	circle.hovered {
		filter: brightness(1.15);
	}
</style>
