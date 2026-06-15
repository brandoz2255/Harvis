// P5 agent orchestration — run tree + artifacts (diff review).
// Backend: workspace_router.py → /api/workspace/run/{id}/tree, /run/{id}/artifacts, /artifact/{id}.

const BASE = '/api/workspace';
const headers = () => ({ Authorization: `Bearer ${localStorage.token}` });

export interface ArtifactMeta {
	id: string;
	artifact_type: string; // diff | changed_files | summary | log
	path: string | null;
	size: number;
	created_at: string | null;
}

export interface RunNode {
	id: string;
	parent_run_id: string | null;
	role: string | null;
	status: string;
	task: string | null;
	model_name: string | null;
	model_provider: string | null;
	branch_name: string | null;
	started_at: string | null;
	duration_ms: number | null;
	tool_calls: number | null;
	summary: string | null;
	error: string | null;
}

export const getRunTree = async (
	runId: string
): Promise<{ run: RunNode | null; children: RunNode[] }> => {
	try {
		const r = await fetch(`${BASE}/run/${runId}/tree`, { headers: headers(), credentials: 'include' });
		return r.ok ? await r.json() : { run: null, children: [] };
	} catch (_) {
		return { run: null, children: [] };
	}
};

export const getRunArtifacts = async (runId: string): Promise<ArtifactMeta[]> => {
	try {
		const r = await fetch(`${BASE}/run/${runId}/artifacts`, { headers: headers(), credentials: 'include' });
		return r.ok ? (await r.json()).artifacts ?? [] : [];
	} catch (_) {
		return [];
	}
};

export const getArtifact = async (
	artifactId: string
): Promise<{ content: string; artifact_type: string; path: string | null } | null> => {
	try {
		const r = await fetch(`${BASE}/artifact/${artifactId}`, { headers: headers(), credentials: 'include' });
		return r.ok ? await r.json() : null;
	} catch (_) {
		return null;
	}
};

export interface GlobalArtifactMeta {
	id: string;
	workspace_id: string;
	path: string | null;
	size: number;
	task_brief: string | null;
	created_at: string | null;
}

// Every FILE artifact across ALL the user's orchestrated runs — the global gallery.
export const getAllArtifacts = async (limit = 200): Promise<GlobalArtifactMeta[]> => {
	try {
		const r = await fetch(`${BASE}/artifacts?limit=${limit}`, {
			headers: headers(),
			credentials: 'include'
		});
		return r.ok ? (await r.json()).artifacts ?? [] : [];
	} catch (_) {
		return [];
	}
};
