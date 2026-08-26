// Typed client for the local CAD lane (`/api/cad/*`).
//
// Two things about this lane shape the client. First, every route except
// `capability` 404s when the operator has the lane switched off — a 404 here means
// "no such feature", not "no such project", so callers must not read it as an error
// worth showing. Second, builds are asynchronous: creating a revision answers 202
// with a build id, and the geometry appears later, so anything that wants a mesh
// polls `getBuild` until the status is terminal.

const BASE = '/api/cad';

const authHeaders = () => ({ Authorization: `Bearer ${localStorage.token}` });
const jsonHeaders = () => ({ ...authHeaders(), 'Content-Type': 'application/json' });

export type CadFormat = 'stl' | 'step' | 'glb' | '3mf';

export type CadArtifact = {
	id: string;
	format: CadFormat;
	media_type: string;
	size_bytes: number;
	sha256: string;
};

export type CadBuild = {
	id: string;
	revision_id: string;
	status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';
	duration_ms: number | null;
	peak_rss_bytes: number | null;
	validation: Record<string, any> | null;
	error_code: string | null;
	error_detail: string | null;
	created_at: string | null;
	finished_at: string | null;
	artifacts?: CadArtifact[];
};

export type CadRevision = {
	id: string;
	project_id: string;
	parent_id: string | null;
	seq: number;
	design_spec: Record<string, any>;
	source_kind: string;
	recipe_name: string | null;
	parameters: Record<string, number>;
	created_by: string;
	created_at: string | null;
	// Attached by the project read so a reloaded page can find geometry for a
	// revision it did not build itself. Null means this revision has never been built.
	latest_build?: CadBuild | null;
};

export type CadProject = {
	id: string;
	title: string;
	conversation_id: string | null;
	head_revision: string | null;
	next_seq: number;
	created_at: string | null;
	updated_at: string | null;
	revisions?: CadRevision[];
};

export type CadParamSpec = {
	name: string;
	kind: 'float' | 'int' | string;
	default: number;
	min: number;
	max: number;
};

export type CadCapability = {
	enabled: boolean;
	engine_reachable: boolean;
	recipes: string[];
	formats: CadFormat[];
	units: string;
	quota: {
		user_limit_bytes: number;
		project_limit_bytes: number;
		user_used_bytes: number;
	};
	engine?: Record<string, any>;
	recipe_params?: Record<
		string,
		{ parameters: CadParamSpec[]; expected_solids: number | null; cost_cap: number }
	>;
};

/** One operation the recipe's CadIR document declares, in execution order.
 *
 *  `selectable` is false on every feature today, and that is an answer rather than a
 *  placeholder: the Gate 5a spike proved a clicked face *can* be traced back to its
 *  `op_id` (one glTF primitive per B-Rep face, in face order), but nothing emits the
 *  selection manifest yet. The UI says so instead of implying a click will work. */
export type CadFeature = {
	op_id: string;
	op: string;
	mode: string;
	when: string | null;
	optional: boolean;
	selectable: boolean;
};

export type CadRecipeSource = {
	schema_version: string;
	recipe: string;
	units: string;
	document: Record<string, any>;
	features: CadFeature[];
};

// The lane speaks one error shape on both hops: {detail: {error_code, message}}.
export class CadApiError extends Error {
	status: number;
	code: string;
	constructor(status: number, code: string, message: string) {
		super(message);
		this.status = status;
		this.code = code;
	}
}

const parse = async (res: Response) => {
	if (res.ok) return res.status === 204 ? null : await res.json();
	let code = `http_${res.status}`;
	let message = res.statusText || 'Request failed';
	try {
		const body = await res.json();
		const d = body?.detail;
		if (d && typeof d === 'object') {
			code = d.error_code ?? code;
			message = d.message ?? message;
		} else if (typeof d === 'string') {
			message = d;
		}
	} catch {
		// A body that isn't JSON tells us nothing beyond the status, which we have.
	}
	throw new CadApiError(res.status, code, message);
};

/** Capability, or null when the lane is absent entirely (old backend → 404).
 *  Never throws for "not available" — that is an answer, not a failure. */
export const getCadCapability = async (): Promise<CadCapability | null> => {
	let res: Response;
	try {
		res = await fetch(`${BASE}/capability`, { headers: authHeaders() });
	} catch {
		return null;
	}
	if (res.status === 404) return null;
	if (!res.ok) return null;
	try {
		return await res.json();
	} catch {
		return null;
	}
};

/** A recipe's CadIR document and the operations it declares.
 *  Fetched lazily — only when a tab that shows it is opened — because these documents
 *  are an order of magnitude larger than the parameter surface the capability probe
 *  already carries on every mount. */
export const getCadRecipeSource = async (recipe: string): Promise<CadRecipeSource> =>
	await parse(
		await fetch(`${BASE}/recipes/${encodeURIComponent(recipe)}/source`, {
			headers: authHeaders()
		})
	);

export const listCadProjects = async (): Promise<CadProject[]> => {
	const res = await fetch(`${BASE}/projects`, { headers: authHeaders() });
	const body = await parse(res);
	return body?.projects ?? [];
};

export const getCadProject = async (projectId: string): Promise<CadProject> =>
	await parse(await fetch(`${BASE}/projects/${projectId}`, { headers: authHeaders() }));

export const createCadProject = async (body: {
	title?: string;
	conversation_id?: string | null;
	recipe?: string;
	params?: Record<string, number>;
	design_spec?: Record<string, any>;
	formats?: CadFormat[];
}): Promise<CadProject> =>
	await parse(
		await fetch(`${BASE}/projects`, {
			method: 'POST',
			headers: jsonHeaders(),
			body: JSON.stringify(body)
		})
	);

export type CadRevisionAccepted = {
	revision_id: string;
	build_id: string;
	seq: number;
	status: string;
	created: boolean;
};

/** 202 — the revision exists immediately, the geometry does not. Poll `getBuild`.
 *  A stale `base_revision_id` throws a CadApiError with status 409. */
export const createCadRevision = async (
	projectId: string,
	body: {
		base_revision_id: string;
		recipe?: string;
		params?: Record<string, number>;
		design_spec?: Record<string, any>;
		formats?: CadFormat[];
		idempotency_key?: string;
	}
): Promise<CadRevisionAccepted> =>
	await parse(
		await fetch(`${BASE}/projects/${projectId}/revisions`, {
			method: 'POST',
			headers: jsonHeaders(),
			body: JSON.stringify(body)
		})
	);

/** Restore moves forward, never back: it appends a NEW revision carrying the old
 *  parameters, so the history it restores from stays intact. */
export const restoreCadRevision = async (
	projectId: string,
	revisionId: string
): Promise<CadRevisionAccepted> =>
	await parse(
		await fetch(`${BASE}/projects/${projectId}/revisions/${revisionId}/restore`, {
			method: 'POST',
			headers: jsonHeaders()
		})
	);

export const getCadBuild = async (buildId: string): Promise<CadBuild> =>
	await parse(await fetch(`${BASE}/builds/${buildId}`, { headers: authHeaders() }));

export const cancelCadBuild = async (buildId: string) =>
	await parse(
		await fetch(`${BASE}/builds/${buildId}/cancel`, {
			method: 'POST',
			headers: authHeaders()
		})
	);

/** The artifact URL. It needs an Authorization header, so it cannot be handed to
 *  `<img src>` or a plain anchor — fetch it and use the blob. */
export const cadArtifactUrl = (buildId: string, artifactId: string, download = false) =>
	`${BASE}/builds/${buildId}/artifacts/${artifactId}${download ? '?download=1' : ''}`;

export const fetchCadArtifact = async (
	buildId: string,
	artifactId: string
): Promise<ArrayBuffer> => {
	const res = await fetch(cadArtifactUrl(buildId, artifactId), { headers: authHeaders() });
	if (!res.ok) {
		await parse(res); // throws with the lane's error shape
	}
	return await res.arrayBuffer();
};

/** Downloads through a blob rather than a bare link: the route is authorized, and a
 *  plain anchor sends no Authorization header. */
export const downloadCadArtifact = async (
	buildId: string,
	artifact: CadArtifact,
	filename: string
) => {
	const res = await fetch(cadArtifactUrl(buildId, artifact.id, true), {
		headers: authHeaders()
	});
	if (!res.ok) await parse(res);
	const blob = await res.blob();
	const url = URL.createObjectURL(blob);
	const a = document.createElement('a');
	a.href = url;
	a.download = filename;
	document.body.appendChild(a);
	a.click();
	a.remove();
	URL.revokeObjectURL(url);
};

export const compareCadRevisions = async (projectId: string, a: string, b: string) =>
	await parse(
		await fetch(
			`${BASE}/projects/${projectId}/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`,
			{ headers: authHeaders() }
		)
	);

/** Poll a build to a terminal state. Returns the last build read either way —
 *  a timeout is reported as the build's own (still non-terminal) status, not as an
 *  exception, because "still running" is a real answer the panel has to show. */
export const pollCadBuild = async (
	buildId: string,
	opts: { intervalMs?: number; timeoutMs?: number; signal?: AbortSignal } = {}
): Promise<CadBuild> => {
	const interval = opts.intervalMs ?? 700;
	const deadline = Date.now() + (opts.timeoutMs ?? 90_000);
	let build = await getCadBuild(buildId);
	while (
		!['succeeded', 'failed', 'cancelled'].includes(build.status) &&
		Date.now() < deadline &&
		!opts.signal?.aborted
	) {
		await new Promise((r) => setTimeout(r, interval));
		if (opts.signal?.aborted) break;
		build = await getCadBuild(buildId);
	}
	return build;
};
