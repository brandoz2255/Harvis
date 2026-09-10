// Inference nodes = other machines (or this one) serving models over an OpenAI or
// Ollama dialect. Backend: plugins/inference_nodes/routes.py → /api/inference-nodes.
//
// The power switch is the odd one out. FreeToken runs as a `systemd --user` service on
// the host while the backend runs in a container, so the backend cannot start it
// directly — it writes a request into a shared directory that a host agent watches.
// That is why `controllable` exists: without the agent installed there is no switch to
// draw, and that is different from the node being off.

const BASE = '/api/inference-nodes';
const authHeaders = () => ({ Authorization: `Bearer ${localStorage.token}` });

export interface NodePower {
	node: string;
	known: boolean;
	controllable: boolean;
	running: boolean;
	loading: boolean; // port is open but the checkpoint is still loading
	auto_wake: boolean;
	desired: 'on' | 'off' | null;
	desired_at: number | null;
	desired_by: string | null;
	unit_state: string | null;
	applied_at: number | null;
	agent_error: string | null;
	agent_stale: boolean;
	error?: string | null;
	control_dir: string;
	hint?: string;
}

export type MoeVerdict = 'node_would_help' | 'served_by_node' | 'fits_anyway' | 'dense';

export interface MoeCandidate {
	name: string;
	moe: boolean;
	experts: { total: number; active: number | null; family: string } | null;
	params: number | null;
	active_params: number | null;
	family: string;
	verdict: MoeVerdict;
	why: string;
}

export interface MoeCandidates {
	models: MoeCandidate[];
	counts: Record<MoeVerdict, number>;
	note: string;
}

export const getNodePower = async (): Promise<NodePower | null> => {
	try {
		const r = await fetch(`${BASE}/power`, { headers: authHeaders(), credentials: 'include' });
		return r.ok ? await r.json() : null;
	} catch (_) {
		return null;
	}
};

// Turning a node on blocks server-side until it actually answers — a cold checkpoint
// load is 30–90 s — so the caller gets the real outcome, not an optimistic 200.
export const setNodePower = async (
	state: 'on' | 'off',
	node = ''
): Promise<{ ok: boolean; power?: NodePower; error?: string }> => {
	try {
		const r = await fetch(`${BASE}/power`, {
			method: 'POST',
			headers: { ...authHeaders(), 'Content-Type': 'application/json' },
			credentials: 'include',
			body: JSON.stringify({ state, node })
		});
		const data = await r.json().catch(() => null);
		if (!r.ok) return { ok: false, error: data?.detail ?? `HTTP ${r.status}` };
		return { ok: true, power: data };
	} catch (e: any) {
		return { ok: false, error: String(e?.message ?? e) };
	}
};

export const getMoeCandidates = async (): Promise<MoeCandidates | null> => {
	try {
		const r = await fetch(`${BASE}/moe-candidates`, {
			headers: authHeaders(),
			credentials: 'include'
		});
		return r.ok ? await r.json() : null;
	} catch (_) {
		return null;
	}
};
