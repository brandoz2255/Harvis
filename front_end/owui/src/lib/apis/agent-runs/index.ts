// P5 agent orchestration — run tree + artifacts (diff review).
// Backend: workspace_router.py → /api/workspace/run/{id}/tree, /run/{id}/artifacts, /artifact/{id}.

const BASE = '/api/workspace';
const headers = () => ({ Authorization: `Bearer ${localStorage.token}` });

export interface ArtifactMeta {
	id: string;
	artifact_type: string; // diff | changed_files | summary | log | file
	path: string | null;
	size: number;
	created_at: string | null;
	category?: string; // html | pdf | image | markdown | text | data | office | archive | unknown
	mime?: string;
	is_binary?: boolean; // content is base64 (image/pdf/office) — fetch /raw for bytes
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
	// Phase 5 background-job fields (workspace_jobs) — present only when the record
	// is (or carries) a persisted background job; all optional / additive.
	command?: string | null;
	exit_code?: number | null;
	timeout_secs?: number | null;
	log_tail?: string | string[] | null; // last ~40 lines of the job's output
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

// Latest RUNNING workspace for the current user (scoped by the JWT). Used by the
// "Harvis on Discord is running" indicator. Returns the active run (with a
// `source` field — "discord" for Discord-launched runs) or null.
export const getActiveWorkspace = async (): Promise<any | null> => {
	try {
		const r = await fetch(`${BASE}/active`, { headers: headers() });
		if (!r.ok) return null;
		const j = await r.json();
		return j?.active ?? null;
	} catch {
		return null;
	}
};

// A Discord-launched (#harvis-code) session that's actively running for this user,
// or null. Powers the Build header's "Discord session online" chip → clicking it
// jumps the user into that live session so the web UI mirrors Discord.
export const getActiveDiscordSession = async (): Promise<any | null> => {
	try {
		const r = await fetch(`${BASE}/active-discord`, { headers: headers() });
		if (!r.ok) return null;
		const j = await r.json();
		return j?.active ?? null;
	} catch {
		return null;
	}
};

// The user's currently-running agent review (coder↔reviewer), or null. Powers the main-Chat
// "Agent review live" chip + the side panel that mirrors the review conversation into Chat.
export const getActiveReview = async (): Promise<any | null> => {
	try {
		const r = await fetch(`${BASE}/active-review`, { headers: headers() });
		if (!r.ok) return null;
		const j = await r.json();
		return j?.active ?? null;
	} catch {
		return null;
	}
};

// Shared workspace model (openclaw_llm_config, last-write-wins). Discord /set-model
// and the Build picker both write it; both read it → the selection follows whichever
// surface changed it most recently. `updated_at` is a unix epoch (seconds).
export const getWorkspaceModel = async (): Promise<{ model_id: string; updated_at: number }> => {
	try {
		const r = await fetch(`${BASE}/workspace-model`, { headers: headers() });
		if (!r.ok) return { model_id: '', updated_at: 0 };
		return await r.json();
	} catch {
		return { model_id: '', updated_at: 0 };
	}
};

// Point the shared workspace model at the Build picker's selection (so Discord
// reflects it). Returns the new updated_at epoch (0 on failure) so the caller can
// avoid re-adopting its own write on the next poll.
export const setWorkspaceModel = async (
	modelId: string
): Promise<{ ok: boolean; updated_at: number }> => {
	try {
		const r = await fetch(`${BASE}/workspace-model`, {
			method: 'POST',
			headers: { ...headers(), 'Content-Type': 'application/json' },
			body: JSON.stringify({ model_id: modelId })
		});
		if (!r.ok) return { ok: false, updated_at: 0 };
		return await r.json();
	} catch {
		return { ok: false, updated_at: 0 };
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

// Re-run a finished/failed background job with the SAME command under a NEW job id
// (harvis_jobs.py → POST /api/harvis/jobs/{id}/retry — human-triggered). Returns the
// new { job_id } or null on failure (endpoint missing / not owned / still running).
export const retryWorkspaceJob = async (jobId: string): Promise<{ job_id: string } | null> => {
	try {
		const r = await fetch(`/api/harvis/jobs/${encodeURIComponent(jobId)}/retry`, {
			method: 'POST',
			headers: headers(),
			credentials: 'include'
		});
		if (!r.ok) return null;
		const j = await r.json();
		return j?.job_id ? { job_id: j.job_id } : null;
	} catch (_) {
		return null;
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
): Promise<{
	content: string;
	artifact_type: string;
	path: string | null;
	category?: string;
	mime?: string;
	is_binary?: boolean;
} | null> => {
	try {
		const r = await fetch(`${BASE}/artifact/${artifactId}`, { headers: headers(), credentials: 'include' });
		return r.ok ? await r.json() : null;
	} catch (_) {
		return null;
	}
};

// Fetch a binary artifact's bytes (auth'd) → an object URL for <img>/<iframe> preview. The caller
// MUST URL.revokeObjectURL() it when done. Text artifacts use their content directly (no /raw).
export const artifactRawBlobUrl = async (artifactId: string): Promise<string> => {
	const r = await fetch(`${BASE}/artifact/${artifactId}/raw`, { headers: headers(), credentials: 'include' });
	if (!r.ok) throw new Error(`artifact raw ${r.status}`);
	return URL.createObjectURL(await r.blob());
};

// Download any (non-secret) artifact as a file — fetch bytes auth'd → trigger a browser download.
export const downloadArtifactFile = async (artifactId: string, name = 'artifact'): Promise<void> => {
	const r = await fetch(`${BASE}/artifact/${artifactId}/download`, { headers: headers(), credentials: 'include' });
	if (!r.ok) throw new Error(`artifact download ${r.status}`);
	const url = URL.createObjectURL(await r.blob());
	const a = document.createElement('a');
	a.href = url;
	a.download = name || 'artifact';
	document.body.appendChild(a);
	a.click();
	a.remove();
	setTimeout(() => URL.revokeObjectURL(url), 4000);
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
	reason?: string; // Phase 2: WHY the gate fired (policy/rule text), shown in the modal
}

// The gated action(s) awaiting approval for a turn run — poll while in-place.
// Phase 2 backends may return a QUEUE (array); older ones return a single object.
export const getPendingAction = async (
	runId: string
): Promise<PendingAction | PendingAction[] | null> => {
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

// scope 'session' = "approve for this session" — the backend remembers the rule and
// stops gating matching actions for the rest of the session. Omitted = one-shot.
export const resolveAction = async (
	runId: string,
	actionId: string,
	approve: boolean,
	scope?: 'once' | 'session'
): Promise<void> => {
	// Backend reads `scope` from the QUERY STRING (approve_run_action: scope: str = "once"),
	// not the body — send it there. Only meaningful on approve; deny ignores it.
	const qs = approve && scope === 'session' ? '?scope=session' : '';
	const r = await fetch(`${BASE}/run/${runId}/action/${actionId}/${approve ? 'approve' : 'deny'}${qs}`, {
		method: 'POST',
		headers: { ...headers() },
		credentials: 'include'
	});
	if (!r.ok) throw new Error(`HTTP ${r.status}`);
};

// ─── VibeCode cumulative multi-turn sessions ─────────────────────────────────
// A session is a durable, named coding conversation holding a THREAD of turns that
// build on ONE persistent working clone. Separate from the main chat ($chats).
// Backend: workspace_router.py → /api/workspace/vibecode/*.

// run_preflight() report — attached to a session by the backend (null on legacy sessions).
export interface VibecodePreflightReport {
	repo_ok?: boolean;
	remote_ok?: boolean | null;
	remote_url?: string | null;
	base_branch?: string | null;
	current_branch?: string | null;
	head_sha?: string | null;
	clean?: boolean | null;
	dirty_count?: number;
	blockers?: { code?: string; message?: string }[];
	ok?: boolean;
}

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
	engine?: string; // Build engine: native | opencode | codex | claude-code | hermes-*
	local_folder_name?: string | null; // set ⇒ browser File System Access session
	needs_seed?: boolean; // local-folder session awaiting its browser-supplied baseline
	// Branch-lock (Build Space preflight) — null/absent on sessions created before it.
	work_branch?: string | null; // the harvis/* branch the session works on
	head_sha?: string | null; // HEAD at session creation
	lifecycle?: string; // created | ready | blocked | running
	// Agent review loop (opt-in per session; absent on older backends/sessions).
	review_enabled?: boolean; // false/absent ⇒ review mode off, no PR gating
	review_status?: string; // 'off' | 'pending' | 'agreed' | 'needs_human'
	preflight?: VibecodePreflightReport | null;
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
	final_summary?: string | null; // the short engine summary (titles/history previews)
	analysis_md?: string | null; // Build Result Narrator: the full written analysis (the assistant message)
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

// Returns null when the status could NOT be determined — a failed check is not the same
// claim as "not connected", and telling a user their account is disconnected when we simply
// couldn't reach the server is a false (and security-flavoured) assurance.
export const getGithubStatus = async (): Promise<GitHubStatus | null> => {
	try {
		const r = await fetch(`/api/vibecode/github/status`, { headers: headers(), credentials: 'include' });
		if (!r.ok) return null;
		return await r.json();
	} catch (_) {
		return null;
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

export const disconnectGithub = async (): Promise<boolean> => {
	// Honest result: callers must not flip their UI to "disconnected" unless this
	// returns true — the credential may still be live server-side otherwise.
	try {
		const r = await fetch(`/api/vibecode/github/disconnect`, {
			method: 'POST',
			headers: headers(),
			credentials: 'include'
		});
		return r.ok;
	} catch (_) {
		return false;
	}
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

// Detected branches for a GitHub repo (owner/name) so the repo-attach UI can let the user pick
// which branch/worktree to work in. Returns {default_branch, branches[]} with default first.
export const getRepoBranches = async (
	owner: string,
	name: string
): Promise<{ default_branch: string; branches: string[] }> => {
	try {
		const r = await fetch(
			`${BASE}/repo-branches?owner=${encodeURIComponent(owner)}&repo=${encodeURIComponent(name)}`,
			{ headers: headers(), credentials: 'include' }
		);
		if (!r.ok) return { default_branch: '', branches: [] };
		return await r.json();
	} catch (_) {
		return { default_branch: '', branches: [] };
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

// ── Read-only workspace browsing (Phase 2) ──
// The session's WHOLE workspace tree (not just touched files). Read-only; .git is
// hidden server-side and the listing is capped (~5000 entries).
export interface VibecodeFileEntry {
	path: string; // relative to the workspace root
	type: 'file' | 'dir';
	size?: number;
}

export const getVibecodeSessionFiles = async (
	sessionId: string,
	subpath?: string
): Promise<{ entries: VibecodeFileEntry[] } | null> => {
	// null = the fetch FAILED (vs a genuinely empty listing) so callers can keep their
	// last-known tree and surface an honest error instead of rendering "no files".
	try {
		const qs = subpath ? `?subpath=${encodeURIComponent(subpath)}` : '';
		const r = await fetch(`${BASE}/vibecode/session/${sessionId}/files${qs}`, {
			headers: headers(),
			credentials: 'include'
		});
		if (!r.ok) return null;
		const j = await r.json();
		return { entries: Array.isArray(j?.entries) ? j.entries : [] };
	} catch (_) {
		return null;
	}
};

// ONE file's content, read-only. Content is capped (~512KB → truncated:true);
// binary files come back with content:'' + binary:true. null = fetch failed.
export const getVibecodeSessionFile = async (
	sessionId: string,
	path: string
): Promise<{
	path: string;
	content: string;
	truncated: boolean;
	binary: boolean;
	size: number;
} | null> => {
	try {
		const r = await fetch(
			`${BASE}/vibecode/session/${sessionId}/file?path=${encodeURIComponent(path)}`,
			{
				headers: headers(),
				credentials: 'include'
			}
		);
		return r.ok ? await r.json() : null;
	} catch (_) {
		return null;
	}
};

// HUMAN-only: open ONE PR from the session's accumulated diff. Throws Error(detail).
// Backend refuses main/master + requires the source to have a GitHub origin.
// `base` (optional, additive) = the PR TARGET branch; older backends ignore it and
// fall back to the session's base_branch.
// `override` (optional, additive) = explicit human bypass of the agent-review gate
// (review_enabled sessions refuse Create-PR until review_status='agreed' unless set).
export const createPrForVibecodeSession = async (
	sessionId: string,
	body: { branch?: string; title?: string; body?: string; base?: string; override?: boolean }
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

// Kick off (or re-run) the coder↔reviewer agent review loop for a session.
// Backend flips review_status → 'pending' and streams agent_message events on the
// session's runs. Throws Error(detail) so callers can surface it.
// `mode` (additive, default 'thread' = today's in-thread loop): 'github' runs the
// SAME loop on a real GitHub DRAFT PR — the backend opens a draft PR from the
// session's diff (persisted to code_pull_requests with status 'draft'), posts each
// reviewer critique as a PR review and each coder reply as a PR comment, and marks
// the PR ready-for-review on agreement. The session therefore carries a draft PR
// while a github review is running; the human still merges.
export const startVibecodeSessionReview = async (
	sessionId: string,
	mode: 'thread' | 'github' = 'thread',
	reviewerIds: string[] = []
): Promise<{ review_status?: string; pr_url?: string; pr_number?: number }> => {
	const r = await fetch(`${BASE}/vibecode/session/${sessionId}/review`, {
		method: 'POST',
		headers: { ...headers(), 'Content-Type': 'application/json' },
		credentials: 'include',
		// reviewer_ids = custom sub-agents that join the coder↔reviewer loop as extra
		// reviewers (each with its own persona/model). Empty ⇒ the built-in reviewer.
		body: JSON.stringify({ mode, reviewer_ids: reviewerIds.filter(Boolean) })
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

// Custom sub-agents (owui_subagents) — used to populate the reviewer roster picker.
export interface SubAgentLite {
	id: string;
	name: string;
	description?: string;
	model?: string | null;
	enabled?: boolean;
}
export const listSubagents = async (): Promise<SubAgentLite[]> => {
	try {
		const r = await fetch(`/api/owui/subagents`, { headers: headers(), credentials: 'include' });
		if (!r.ok) return [];
		const data = await r.json();
		return Array.isArray(data?.items) ? data.items : [];
	} catch (_) {
		return [];
	}
};

// ── Phase 4: tracked AI edits + persisted PRs (per-session audit trail) ──────
// Backed by code_file_changes / code_pull_requests (orchestration schema).

// One row per tracked AI edit (apply_patch etc.) in the session.
export interface CodeFileChange {
	id: string;
	session_id: string;
	run_id: string | null;
	file_path: string;
	change_type: string; // create | modify | delete
	patch_id: string | null;
	before_sha: string | null;
	after_sha: string | null;
	created_at: string | null;
}

// A PR opened from this session, persisted server-side. Usually human-opened
// (status 'open'/'merged'/'closed'); a github-mode agent review additionally
// persists its DRAFT PR here with status 'draft' — it flips to 'open' when the
// reviewer approves and the PR is marked ready-for-review.
export interface CodePullRequest {
	id: string;
	session_id: string;
	provider: string;
	pr_url: string | null;
	pr_number: number | null;
	base_branch: string | null;
	head_branch: string | null;
	title: string | null;
	status: string | null;
	created_at: string | null;
	updated_at: string | null;
}

// Per-file audit list of the session's tracked AI edits. Fail-soft: [] until the
// backend endpoint exists / the session has no tracked edits.
export const getVibecodeSessionChanges = async (
	sessionId: string
): Promise<{ changes: CodeFileChange[] }> => {
	try {
		const r = await fetch(`${BASE}/vibecode/session/${sessionId}/changes`, {
			headers: headers(),
			credentials: 'include'
		});
		if (!r.ok) return { changes: [] };
		const j = await r.json();
		return { changes: Array.isArray(j?.changes) ? j.changes : [] };
	} catch (_) {
		return { changes: [] };
	}
};

// PRs previously opened from this session (persisted records). Fail-soft: [].
export const getVibecodeSessionPullRequests = async (
	sessionId: string
): Promise<{ pull_requests: CodePullRequest[] }> => {
	try {
		const r = await fetch(`${BASE}/vibecode/session/${sessionId}/pull-requests`, {
			headers: headers(),
			credentials: 'include'
		});
		if (!r.ok) return { pull_requests: [] };
		const j = await r.json();
		return { pull_requests: Array.isArray(j?.pull_requests) ? j.pull_requests : [] };
	} catch (_) {
		return { pull_requests: [] };
	}
};
