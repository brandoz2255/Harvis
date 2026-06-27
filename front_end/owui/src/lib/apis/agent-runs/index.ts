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
	prompt_tokens?: number | null; // per-agent token usage (Background-tasks table)
	completion_tokens?: number | null;
	summary: string | null;
	error: string | null;
}

// All workspace/orchestration runs (account-wide) — feeds the Build Background-tasks panel.
export const getWorkspaceHistory = async (limit = 50): Promise<any[]> => {
	try {
		const r = await fetch(`${BASE}/history?limit=${limit}`, { headers: headers() });
		if (!r.ok) return [];
		const j = await r.json();
		return j?.runs ?? j ?? [];
	} catch {
		return [];
	}
};

// Cancel a running workspace/vibecode turn (best-effort).
export const cancelWorkspaceRun = async (runId: string): Promise<void> => {
	try {
		await fetch(`${BASE}/cancel/${runId}`, {
			method: 'POST',
			headers: headers(),
			credentials: 'include'
		});
	} catch (_) {
		/* best-effort */
	}
};

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

export interface AttachedRepo {
	path: string; // container path, e.g. /data/attached-repos/harvis
	name: string; // basename
	branch: string; // current branch (HEAD)
	writable?: boolean; // RW mount → eligible for opt-in in-place mode
}

// Git repos bind-mounted READ-ONLY into the backend — available to attach to an
// orchestrated run for clone-local isolation (each sub-agent works on a clone and
// produces a real `git diff` vs HEAD). Backend: GET /api/workspace/attached-repos.
export const getAttachedRepos = async (): Promise<AttachedRepo[]> => {
	try {
		const r = await fetch(`${BASE}/attached-repos`, { headers: headers(), credentials: 'include' });
		return r.ok ? (await r.json()).repos ?? [] : [];
	} catch (_) {
		return [];
	}
};

export interface BrowseEntry {
	name: string;
	path: string;
	display_path?: string;
	is_repo: boolean;
	rw_capable?: boolean; // under the RW browse root ⇒ eligible for real in-place editing
}
export interface BrowseResult {
	enabled: boolean;
	rw?: boolean; // this listing is of the read-WRITE root
	root: string;
	path: string;
	display_root?: string;
	display_path?: string;
	parent: string | null;
	is_repo: boolean;
	rw_capable?: boolean;
	host_root?: string; // host-side path of the browse root (display-only)
	is_default_root?: boolean; // root is still the default sandbox → show the config hint
	at_root?: boolean; // the current listing IS the browse root (vs a subfolder)
	entries: BrowseEntry[];
}

// Browse a configured host filesystem tree one directory at a time so the user can attach a
// local git repo under it. rw=false → the read-only root (HARVIS_FS_BROWSE_ROOT, clone-mode);
// rw=true → the read-WRITE root (HARVIS_FS_BROWSE_ROOT_RW, in-place eligible). Path-contained
// server-side. Backend: GET /api/workspace/fs/browse?path=&rw=
export const browseFolders = async (path = '', rw = false): Promise<BrowseResult> => {
	const empty: BrowseResult = {
		enabled: false,
		rw,
		root: '',
		path: '',
		parent: null,
		is_repo: false,
		rw_capable: false,
		entries: []
	};
	try {
		const r = await fetch(
			`${BASE}/fs/browse?path=${encodeURIComponent(path)}${rw ? '&rw=1' : ''}`,
			{ headers: headers(), credentials: 'include' }
		);
		return r.ok ? await r.json() : empty;
	} catch (_) {
		return empty;
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

export interface RunRepo {
	name: string;
	branch: string;
	path: string;
	has_github: boolean; // can a PR be opened (does the source have a GitHub origin)
}

// The attached repo for a run (diff-row `repo · branch` header + Create-PR gating).
// null if the run had no attached repo. Backend: GET /api/workspace/run/{id}/repo.
export const getRunRepo = async (runId: string): Promise<RunRepo | null> => {
	try {
		const r = await fetch(`${BASE}/run/${runId}/repo`, { headers: headers(), credentials: 'include' });
		return r.ok ? (await r.json()).repo ?? null : null;
	} catch (_) {
		return null;
	}
};

// HUMAN-only: open a GitHub PR from a run's diff. Throws Error(detail) on failure.
// Backend refuses main/master + requires the attached repo to have a GitHub origin.
export const createPrForRun = async (
	runId: string,
	body: { artifact_id?: string; branch?: string; title?: string; body?: string }
): Promise<{ pr_url?: string; pr_number?: number; branch?: string; base?: string }> => {
	const r = await fetch(`${BASE}/run/${runId}/create-pr`, {
		method: 'POST',
		headers: { ...headers(), 'Content-Type': 'application/json' },
		credentials: 'include',
		body: JSON.stringify(body)
	});
	if (!r.ok) {
		let detail = `HTTP ${r.status}`;
		try {
			detail = (await r.json()).detail || detail;
		} catch (_) {}
		throw new Error(detail);
	}
	return await r.json();
};

// ─── In-place permission gate (the acknowledge-popup) ────────────────────────
export interface PendingAction {
	action_id: string;
	tool?: string;
	args?: Record<string, any>;
	risk?: 'low' | 'med' | 'high';
}

// The gated action (if any) awaiting approval for a turn run — poll while in-place.
export const getPendingAction = async (runId: string): Promise<PendingAction | null> => {
	try {
		const r = await fetch(`${BASE}/run/${runId}/pending-action`, {
			headers: headers(),
			credentials: 'include'
		});
		return r.ok ? (await r.json()).pending ?? null : null;
	} catch (_) {
		return null;
	}
};

export const resolveAction = async (
	runId: string,
	actionId: string,
	approve: boolean
): Promise<void> => {
	const r = await fetch(`${BASE}/run/${runId}/action/${actionId}/${approve ? 'approve' : 'deny'}`, {
		method: 'POST',
		headers: headers(),
		credentials: 'include'
	});
	if (!r.ok) throw new Error(`HTTP ${r.status}`);
};

// ─── VibeCode cumulative multi-turn sessions ─────────────────────────────────
// A session is a durable, named coding conversation holding a THREAD of turns that
// build on ONE persistent working clone. Separate from the main chat ($chats).
// Backend: workspace_router.py → /api/workspace/vibecode/*.

export interface VibecodeSession {
	id: string;
	title?: string | null;
	emoji?: string | null;
	repo_path?: string | null;
	repo_display_path?: string | null;
	base_branch?: string | null;
	status?: string;
	isolation_mode?: string; // 'session' (clone) | 'inplace'
	permission_mode?: string; // in-place ladder
	local_folder_name?: string | null; // set ⇒ browser File System Access session
	needs_seed?: boolean; // local-folder session awaiting its browser-supplied baseline
	created_at?: string | null;
	updated_at?: string | null;
}

export interface VibecodeTurn {
	id: string; // the turn's workspace_id (stream via /api/workspace/stream/{id})
	task_brief?: string;
	status?: string;
	started_at?: string | null;
	completed_at?: string | null;
	duration_ms?: number | null;
	tool_calls?: number | null;
	final_summary?: string | null;
	error_message?: string | null;
	model_name?: string | null; // the model this turn ran on
	prompt_tokens?: number | null; // ≈ context occupancy at the last step
	completion_tokens?: number | null;
	context_window?: number | null; // num_ctx the model ran with
	child_count?: number | null; // >0 ⇒ a multi-agent (orchestrated) turn → "Workflow · N agents"
	// The user's original attachments (image/file refs) — rendered inline in the chat bubble.
	attachments?: { url?: string; name?: string; mime_type?: string; file_id?: string }[] | null;
}

export const createVibecodeSession = async (body: {
	repo_path?: string;
	model_name?: string;
	title?: string;
	isolation_mode?: string; // 'session' (clone, default) | 'inplace'
	permission_mode?: string; // in-place: plan | ask | auto-accept | full-auto
	local_folder_name?: string; // browser File System Access session (edits your real folder)
	github_owner?: string; // GitHub-clone source (always clone-mode)
	github_repo?: string;
	github_branch?: string;
	engine?: string; // Phase E1: 'native' (OpenClaw runner) | 'opencode' (external CLI, clone-only, flag-gated)
}): Promise<VibecodeSession> => {
	const r = await fetch(`${BASE}/vibecode/sessions`, {
		method: 'POST',
		headers: { ...headers(), 'Content-Type': 'application/json' },
		credentials: 'include',
		body: JSON.stringify(body)
	});
	if (!r.ok) {
		let detail = `HTTP ${r.status}`;
		try {
			detail = (await r.json()).detail || detail;
		} catch (_) {}
		throw new Error(detail);
	}
	return await r.json();
};

// ── GitHub (connect → list your repos → clone into a session) ──
export interface GitHubStatus {
	connected: boolean;
	login?: string;
	name?: string;
	avatar_url?: string;
}
export interface GitHubRepoItem {
	full_name: string;
	owner: string;
	name: string;
	default_branch?: string;
	private?: boolean;
	description?: string;
	html_url?: string;
}

export const getGithubStatus = async (): Promise<GitHubStatus> => {
	try {
		const r = await fetch(`/api/vibecode/github/status`, { headers: headers(), credentials: 'include' });
		if (!r.ok) return { connected: false };
		return await r.json();
	} catch (_) {
		return { connected: false };
	}
};

// The GitHub authorize URL, or {ok:false,error} when OAuth isn't configured on the server.
export const getGithubStartUrl = async (): Promise<{ ok: boolean; redirect?: string; error?: string }> => {
	try {
		const r = await fetch(`/api/vibecode/github/start`, { headers: headers(), credentials: 'include' });
		if (!r.ok) {
			let error = `HTTP ${r.status}`;
			try {
				error = (await r.json()).detail || error;
			} catch (_) {}
			return { ok: false, error };
		}
		const d = await r.json();
		return { ok: true, redirect: d.redirect };
	} catch (e) {
		return { ok: false, error: String(e) };
	}
};

export const disconnectGithub = async (): Promise<void> => {
	try {
		await fetch(`/api/vibecode/github/disconnect`, {
			method: 'POST',
			headers: headers(),
			credentials: 'include'
		});
	} catch (_) {}
};

export const listUserGithubRepos = async (): Promise<GitHubRepoItem[]> => {
	try {
		const r = await fetch(`${BASE}/user-repos`, { headers: headers(), credentials: 'include' });
		if (!r.ok) return [];
		const d = await r.json();
		return d.repos || [];
	} catch (_) {
		return [];
	}
};

export const listVibecodeSessions = async (): Promise<VibecodeSession[]> => {
	try {
		const r = await fetch(`${BASE}/vibecode/sessions`, {
			headers: headers(),
			credentials: 'include'
		});
		return r.ok ? (await r.json()).sessions ?? [] : [];
	} catch (_) {
		return [];
	}
};

export const getVibecodeSession = async (
	sessionId: string
): Promise<{ session: VibecodeSession; turns: VibecodeTurn[] } | null> => {
	try {
		const r = await fetch(`${BASE}/vibecode/session/${sessionId}`, {
			headers: headers(),
			credentials: 'include'
		});
		return r.ok ? await r.json() : null;
	} catch (_) {
		return null;
	}
};

// Send a follow-up message → spawns a turn run on the session's persistent clone.
// Returns the new turn's workspace_id (stream it via /api/workspace/stream/{id}).
export const startVibecodeTurn = async (
	sessionId: string,
	body: {
		task_brief: string;
		model_name?: string;
		attachments?: any[];
		run_mode?: string;
		orchestrate?: boolean; // fan the turn out to N task-delegated sub-agents (multi-agent)
	}
): Promise<{ workspace_id: string }> => {
	const r = await fetch(`${BASE}/vibecode/session/${sessionId}/turn`, {
		method: 'POST',
		headers: { ...headers(), 'Content-Type': 'application/json' },
		credentials: 'include',
		body: JSON.stringify(body)
	});
	if (!r.ok) {
		let detail = `HTTP ${r.status}`;
		try {
			detail = (await r.json()).detail || detail;
		} catch (_) {}
		throw new Error(detail);
	}
	return await r.json();
};

// ─── Local-folder mode (browser File System Access) ──────────────────────────
// Seed a local-folder session's backend workspace with the browser-walked folder
// snapshot — establishes the fixed cumulative-diff baseline (base_sha). Must run
// before the first turn.
export const seedVibecodeLocalFolder = async (
	sessionId: string,
	files: { path: string; content: string }[]
): Promise<{ base_sha: string; written: number }> => {
	const r = await fetch(`${BASE}/vibecode/session/${sessionId}/seed`, {
		method: 'POST',
		headers: { ...headers(), 'Content-Type': 'application/json' },
		credentials: 'include',
		body: JSON.stringify({ files })
	});
	if (!r.ok) {
		let detail = `HTTP ${r.status}`;
		try {
			detail = (await r.json()).detail || detail;
		} catch (_) {}
		throw new Error(detail);
	}
	return await r.json();
};

// Files the agent changed/deleted this session — the browser writes these back into
// the user's real folder (local-folder mode). Call after each turn completes.
export const getVibecodeWriteback = async (
	sessionId: string
): Promise<{ changed: { path: string; content: string }[]; deleted: string[] }> => {
	try {
		const r = await fetch(`${BASE}/vibecode/session/${sessionId}/writeback`, {
			headers: headers(),
			credentials: 'include'
		});
		return r.ok ? await r.json() : { changed: [], deleted: [] };
	} catch (_) {
		return { changed: [], deleted: [] };
	}
};

// Auto-name a session (title + emoji) from its first turn — open-notebook pattern.
// Deterministic fallback server-side, so this never blanks the title.
export const autonameVibecodeSession = async (
	sessionId: string
): Promise<{ title: string; emoji: string } | null> => {
	try {
		const r = await fetch(`${BASE}/vibecode/session/${sessionId}/autoname`, {
			method: 'POST',
			headers: headers(),
			credentials: 'include'
		});
		return r.ok ? await r.json() : null;
	} catch (_) {
		return null;
	}
};

export const renameVibecodeSession = async (
	sessionId: string,
	title: string
): Promise<void> => {
	const r = await fetch(`${BASE}/vibecode/session/${sessionId}`, {
		method: 'PATCH',
		headers: { ...headers(), 'Content-Type': 'application/json' },
		credentials: 'include',
		body: JSON.stringify({ title })
	});
	if (!r.ok) throw new Error(`HTTP ${r.status}`);
};

// Change the in-place permission ladder rung mid-session (the composer mode pill).
export const setVibecodePermission = async (
	sessionId: string,
	permission_mode: string
): Promise<void> => {
	const r = await fetch(`${BASE}/vibecode/session/${sessionId}`, {
		method: 'PATCH',
		headers: { ...headers(), 'Content-Type': 'application/json' },
		credentials: 'include',
		body: JSON.stringify({ permission_mode })
	});
	if (!r.ok) throw new Error(`HTTP ${r.status}`);
};

export const deleteVibecodeSession = async (sessionId: string): Promise<void> => {
	const r = await fetch(`${BASE}/vibecode/session/${sessionId}`, {
		method: 'DELETE',
		headers: headers(),
		credentials: 'include'
	});
	if (!r.ok) throw new Error(`HTTP ${r.status}`);
};

// The session's LIVE accumulated diff (all turns, vs the fixed base_sha).
// has_github gates the Create-PR button (the source needs a GitHub origin).
export const getVibecodeSessionDiff = async (
	sessionId: string
): Promise<{ diff: string; has_github: boolean; repo: string | null } | null> => {
	try {
		const r = await fetch(`${BASE}/vibecode/session/${sessionId}/diff`, {
			headers: headers(),
			credentials: 'include'
		});
		return r.ok ? await r.json() : null;
	} catch (_) {
		return null;
	}
};

// HUMAN-only: open ONE PR from the session's accumulated diff. Throws Error(detail).
// Backend refuses main/master + requires the source to have a GitHub origin.
export const createPrForVibecodeSession = async (
	sessionId: string,
	body: { branch?: string; title?: string; body?: string }
): Promise<{ pr_url?: string; pr_number?: number; branch?: string; base?: string }> => {
	const r = await fetch(`${BASE}/vibecode/session/${sessionId}/create-pr`, {
		method: 'POST',
		headers: { ...headers(), 'Content-Type': 'application/json' },
		credentials: 'include',
		body: JSON.stringify(body)
	});
	if (!r.ok) {
		let detail = `HTTP ${r.status}`;
		try {
			detail = (await r.json()).detail || detail;
		} catch (_) {}
		throw new Error(detail);
	}
	return await r.json();
};
