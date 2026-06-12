// Neural Map v1 — sessions as hub dots, runs as spokes (Obsidian-graph-view style).
// Static d3-force layout: the simulation is ticked to convergence synchronously and
// only the final positions are emitted, so the canvas stays deterministic-enough and
// WorkflowFlow's fitView-once contract holds (no live jitter).
//
// Scope rule (locked design): account-wide = sessions + runs ONLY. No memory nodes
// here, ever — memory is project-scoped and opt-in (v1.5, see
// docs/design/neural-map-knowledge-graph.md).

import {
	forceSimulation,
	forceLink,
	forceManyBody,
	forceCollide,
	forceX,
	forceY
} from 'd3-force';
import type { RunRow } from './runsToGraph';

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

const runSimNode = (r: RunRow) => {
	const weight = r.tool_calls ?? (r.duration_ms ? r.duration_ms / 60000 : 0);
	return {
		id: `run:${r.id}`,
		r: clamp(4 + 1.6 * Math.log2(1 + weight), 4, 11),
		data: {
			kind: 'run',
			runId: r.id,
			label: r.task_brief || 'Workspace run',
			status: r.status || '',
			durationMs: r.duration_ms,
			toolCalls: r.tool_calls,
			sessionId: r.session_id
		}
	};
};

export function sessionsToGraph(runs: RunRow[]): { nodes: any[]; edges: any[] } {
	const bySession = new Map<string, RunRow[]>();
	const floaters: RunRow[] = [];
	for (const r of runs) {
		if (r.session_id) {
			const arr = bySession.get(r.session_id) ?? [];
			arr.push(r);
			bySession.set(r.session_id, arr);
		} else {
			// No session → free-floating dot. No fake hub, no edge.
			floaters.push(r);
		}
	}

	const simNodes: any[] = [];
	const simLinks: { source: string; target: string }[] = [];

	for (const [sid, sruns] of bySession) {
		simNodes.push({
			id: `session:${sid}`,
			r: Math.min(16, 9 + 2 * Math.log2(1 + sruns.length)),
			data: {
				kind: 'session',
				sessionId: sid,
				label: sid.startsWith('discord-')
					? 'Discord session'
					: sruns[0]?.task_brief || 'Session',
				count: sruns.length
			}
		});
		for (const r of sruns) {
			simNodes.push(runSimNode(r));
			simLinks.push({ source: `session:${sid}`, target: `run:${r.id}` });
		}
	}
	for (const r of floaters) simNodes.push(runSimNode(r));

	// Capture edge endpoints as STRINGS before simulating — d3's forceLink mutates
	// each link's source/target into node object references.
	const edges = simLinks.map((l) => ({
		id: `e:${l.source}->${l.target}`,
		source: l.source,
		target: l.target,
		type: 'straight',
		selectable: false,
		style: 'stroke: rgba(120, 130, 150, 0.35); stroke-width: 1;'
	}));

	if (simNodes.length > 0) {
		const sim = forceSimulation(simNodes)
			.force(
				'link',
				forceLink(simLinks)
					.id((d: any) => d.id)
					.distance((l: any) => 46 + (l.source.r ?? 8) + (l.target.r ?? 8))
					.strength(0.7)
			)
			.force('charge', forceManyBody().strength(-160))
			// +22 keeps room for the label under each dot
			.force('collide', forceCollide().radius((d: any) => d.r + 22))
			.force('x', forceX(0).strength(0.04))
			.force('y', forceY(0).strength(0.04))
			.stop();
		for (let i = 0; i < 300; i++) sim.tick();
	}

	// xyflow position = top-left of the node box; our box is the r*2 dot itself.
	const nodes = simNodes.map((n) => ({
		id: n.id,
		type: 'neural',
		data: { ...n.data, r: n.r },
		position: { x: (n.x ?? 0) - n.r, y: (n.y ?? 0) - n.r }
	}));

	return { nodes, edges };
}
