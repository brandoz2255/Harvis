import type { WorkspaceEvent } from '$lib/apis/streaming/workspace-stream';

// Map a workspace run's flat event stream → an n8n-style node/edge graph.
// Pure + deterministic: positions are a function of (lane, sequence) and node
// ids are stable, so re-running this on a growing event array never reflows or
// remounts existing nodes (no SvelteFlow "live-append jump").

export type WfNodeKind = 'agent' | 'tool' | 'summary' | 'error';

export interface WfNodeData {
	kind: WfNodeKind;
	// agent
	label?: string;
	model?: string;
	isRoot?: boolean;
	// tool
	tool?: string;
	status?: 'running' | 'done';
	ok?: boolean;
	output?: string;
	// summary / error
	summary?: string;
	cancelled?: boolean;
	message?: string;
	fixHint?: string;
}

export interface WfNode {
	id: string;
	type: 'custom';
	data: WfNodeData;
	position: { x: number; y: number };
}

export interface WfEdge {
	id: string;
	source: string;
	target: string;
	type: 'smoothstep';
	selectable: false;
	animated?: boolean;
	class?: string;
}

const COL = 320; // horizontal spacing between lanes (run_id columns)
const ROW = 110; // vertical step within a lane
const ROOT = '__root__'; // lane key for events that carry no run_id

export function eventsToGraph(events: WorkspaceEvent[]): { nodes: WfNode[]; edges: WfEdge[] } {
	const nodes: WfNode[] = [];
	const edges: WfEdge[] = [];
	const byId = new Map<string, WfNode>();

	const laneIndex = new Map<string, number>(); // laneKey → column index (first-seen order)
	const rowInLane = new Map<string, number>(); // laneKey → next row
	const tailByLane = new Map<string, string>(); // laneKey → last node id (sequential edges)
	const agentNodeByRun = new Map<string, string>(); // run_id → agent node id (spawn edges)

	// ⚠ SEQUENTIAL-TOOLS ASSUMPTION — one pending tool per run_id (lane). This pairs
	// each tool_call with the NEXT tool_result in the same lane. Correct ONLY while
	// tools run sequentially within an agent (true today). It BREAKS under parallel
	// tools (P5 orchestration): concurrent calls would mis-merge. When that lands,
	// key pending tools by a per-call id from the event, not one-per-lane.
	const pendingToolByLane = new Map<string, string>();

	const laneKeyOf = (e: WorkspaceEvent): string => (e.run_id as string) || ROOT;

	const ensureLane = (key: string): number => {
		if (!laneIndex.has(key)) laneIndex.set(key, laneIndex.size);
		return laneIndex.get(key) as number;
	};

	const pushNode = (laneKey: string, id: string, data: WfNodeData): WfNode => {
		const lane = ensureLane(laneKey);
		const row = rowInLane.get(laneKey) ?? 0;
		rowInLane.set(laneKey, row + 1);
		const node: WfNode = { id, type: 'custom', data, position: { x: lane * COL, y: row * ROW } };
		nodes.push(node);
		byId.set(id, node);
		// sequential edge from the lane's previous tail
		const tail = tailByLane.get(laneKey);
		if (tail) {
			edges.push({
				id: `${tail}->${id}`,
				source: tail,
				target: id,
				type: 'smoothstep',
				selectable: false,
				class: 'dark:fill-gray-300 fill-gray-300'
			});
		}
		tailByLane.set(laneKey, id);
		return node;
	};

	for (const e of events) {
		const laneKey = laneKeyOf(e);
		switch (e.type) {
			case 'agent_start': {
				const runId = (e.run_id as string) || ROOT;
				if (agentNodeByRun.has(runId)) break; // dedupe repeated agent_start for a run
				const id = `agent:${runId}`;
				pushNode(laneKey, id, {
					kind: 'agent',
					label: (e.agent_label as string) || 'Agent',
					model: e.model as string,
					isRoot: !e.parent_run_id
				});
				agentNodeByRun.set(runId, id);
				// spawn edge parent → child
				const parentRun = e.parent_run_id as string;
				if (parentRun && agentNodeByRun.has(parentRun)) {
					const parent = agentNodeByRun.get(parentRun) as string;
					edges.push({
						id: `${parent}=>${id}`,
						source: parent,
						target: id,
						type: 'smoothstep',
						selectable: false,
						animated: true,
						class: 'dark:fill-blue-400 fill-blue-400'
					});
				}
				break;
			}
			case 'tool_call': {
				const n = rowInLane.get(laneKey) ?? 0; // row this node will take (id stays stable)
				const id = `tool:${laneKey}:${n}`;
				pushNode(laneKey, id, { kind: 'tool', tool: e.tool as string, status: 'running', output: '' });
				pendingToolByLane.set(laneKey, id);
				break;
			}
			case 'tool_result': {
				const pendId = pendingToolByLane.get(laneKey);
				if (pendId) {
					const node = byId.get(pendId);
					if (node) {
						node.data.status = 'done';
						node.data.ok = e.success !== false;
						node.data.output = String(e.output ?? '').slice(0, 200);
					}
					pendingToolByLane.delete(laneKey);
				}
				break;
			}
			case 'done': {
				if (!byId.has('summary')) {
					pushNode(ROOT, 'summary', { kind: 'summary', summary: (e.summary as string) || '' });
				}
				break;
			}
			case 'cancelled': {
				if (!byId.has('cancelled')) {
					pushNode(ROOT, 'cancelled', { kind: 'summary', cancelled: true });
				}
				break;
			}
			case 'error': {
				if (!byId.has('error')) {
					pushNode(laneKey, 'error', {
						kind: 'error',
						message: (e.message as string) || 'Error',
						fixHint: e.fix_hint as string
					});
				}
				break;
			}
			default:
				// log / unknown → not a node (folds into the thought stream)
				break;
		}
	}

	// Animate edges that lead into a still-running tool node (live feedback).
	for (const edge of edges) {
		const target = byId.get(edge.target);
		if (target && target.data.kind === 'tool' && target.data.status === 'running') {
			edge.animated = true;
		}
	}

	return { nodes, edges };
}
