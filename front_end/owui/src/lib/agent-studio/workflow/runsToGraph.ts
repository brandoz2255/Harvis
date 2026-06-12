// Map the user's workspace runs → an n8n-style graph for the Global Map surface.
// v1: each run is one node; runs are independent (no edges). Inter-run
// interaction edges arrive with P5 (real parallel orchestration). Deterministic
// grid layout so the canvas never reflows.

export interface RunRow {
	id: string;
	session_id?: string;
	task_brief?: string;
	status?: string;
	duration_ms?: number;
	tool_calls?: number;
	final_summary?: string;
}

const COL = 280; // horizontal spacing
const ROW = 130; // vertical spacing
const PER_ROW = 4; // grid width

export function runsToGraph(runs: RunRow[]): { nodes: any[]; edges: any[] } {
	const nodes = runs.map((r, i) => ({
		id: `run:${r.id}`,
		type: 'custom',
		data: {
			kind: 'run',
			runId: r.id,
			label: r.task_brief || 'Workspace run',
			status: r.status || '',
			durationMs: r.duration_ms,
			toolCalls: r.tool_calls,
			sessionId: r.session_id
		},
		position: { x: (i % PER_ROW) * COL, y: Math.floor(i / PER_ROW) * ROW }
	}));
	return { nodes, edges: [] };
}
