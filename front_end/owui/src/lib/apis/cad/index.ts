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

/** The camera presets a render can be taken from. Mirrors `cad_store.RENDER_PRESETS`;
 *  the server rejects anything else, so this is a convenience, not the gate. */
export type CadRenderPreset =
	| 'iso'
	| 'front'
	| 'rear'
	| 'left'
	| 'right'
	| 'top'
	| 'bottom'
	| 'four_view';

/** Recipe ids. They live in the same `variant` column as the camera presets above and
 *  must never collide with one — `cad_render_recipes.RECIPE_IDS`, asserted server-side. */
export type CadRecipeId = 'ev_overview' | 'ev_section_cavity' | 'ev_separation' | 'ev_contact_sheet';

export type CadRenderVariant = CadRenderPreset | CadRecipeId;

/** A render is an artifact like any other — same row, same route, same quota — with a
 *  `variant` naming its camera and a `meta` binding it to the geometry it depicts.
 *  `source_sha256` is the digest of the export the viewport had loaded, so a render
 *  can always be told apart from a picture of an older solid. */
export type CadRender = CadArtifact & {
	variant: CadRenderVariant;
	meta: {
		preset?: string;
		revision_id?: string;
		source_sha256?: string;
		source_format?: string;
		label?: string;
		// Written by the server when a recipe's object-mask pass was uploaded with the
		// picture (HE-7). `qc` is a list of findings, never a verdict — a render cannot
		// decide whether the part is right.
		recipe_id?: string;
		dhash?: number;
		coverage?: number;
		visible_parts?: string[];
		qc?: CadRenderFinding[];
		disclaimer?: string;
	};
};

/** One QC finding about one picture. Severity is always `warn` on a stored render:
 *  the single `reject` finding stops the write, so it never reaches a row. */
export type CadRenderFinding = {
	code: string;
	severity: 'warn' | 'reject';
	detail: string;
	missing?: string[];
	unexpected?: string[];
	similar_to?: string[];
};

/** A server-issued instruction for one picture (HE-7). The viewport renders what it
 *  is told from the viewer's own camera and section vocabulary, so two recipes are
 *  distinct because the request was, not because the pixels turned out different.
 *
 *  `required` is never true in this tranche: a render needs an open browser, so a
 *  missing one is a fact about the client and never fails a build. */
export type CadRenderRecipe = {
	recipe_id: CadRecipeId;
	purpose: string;
	label: string;
	view: CadRenderPreset;
	section: { axis: 'x' | 'y' | 'z'; offset: number; flipped: boolean; capped: boolean } | null;
	expected_visible_parts: string[];
	/** node id → `#rrggbb`. Empty when the build has more bodies than the palette has
	 *  colours, in which case the picture ships unmeasured rather than mis-measured. */
	mask_palette: Record<string, string>;
	passes: ('beauty' | 'object_mask')[];
	rotationally_symmetric: boolean;
	exempt_from_similarity: boolean;
	required: boolean;
	corroborates: string[];
	disclaimer: string;
};

export type CadBuild = {
	id: string;
	revision_id: string;
	status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';
	duration_ms: number | null;
	peak_rss_bytes: number | null;
	validation: Record<string, any> | null;
	// Two verdicts, never merged. `validation` says the solid is well-formed;
	// `conformance` says it is the part that was asked for. A build can be
	// `status: 'succeeded'` and `conformance_status: 'failed'` at once — that is the
	// case where the geometry ran perfectly and produced the wrong part. `'unverified'`
	// means the DesignSpec stated nothing checkable, not that anything passed.
	conformance: CadConformance | null;
	conformance_status: CadConformanceStatus | null;
	error_code: string | null;
	error_detail: string | null;
	created_at: string | null;
	finished_at: string | null;
	artifacts?: CadArtifact[];
	// Kept apart from `artifacts` on purpose: a download row that listed a PNG beside
	// the STEP would offer a picture of the part as though it were the part.
	renders?: CadRender[];
	// The semantic scene tree the engine emitted for this build (UX-A). Stored on the
	// build rather than derived from geometry, which is what lets a FAILED build still
	// carry a tree — the explorer can then point at the operation that went wrong
	// instead of showing nothing. Null on builds made before the column existed.
	scene_manifest?: CadSceneManifest | null;
};

export type CadConformanceStatus = 'passed' | 'failed' | 'unverified';

// The per-check shape `cad_conformance.grade()` actually emits. A check is NOT a small
// report: it has no `status` and no `label`. Its verdict is the tri-state `ok`
// (true / false / null-when-unmeasured) and its human sentence is `requirement`. Only
// the report as a whole carries a `status`.
//
// This type used to claim `status` and `label`, and the Validate panel believed it:
// every row rendered as an indeterminate grey "?" with no text, so a FAILED requirement
// was indistinguishable from a passed one.
export type CadConformanceCheck = {
	id: string;
	kind: string;
	requirement: string;
	/** Whatever the grader could state: a number, a list of numbers, or null. */
	expected: number | string | (number | string)[] | null;
	measured: number | string | (number | string)[] | null;
	tolerance_mm?: number | null;
	/** Why this check exists — including any assumption Harvis made to write it. */
	note?: string | null;
	/** What was observed, in words. The failure explanation when `ok` is false. */
	detail?: string | null;
	ok: boolean | null;
	// --- HE-5: present only on checks graded against a real engine measurement -----
	//
	// These say *what* was measured and *how*, which is the difference between a card
	// that shows two numbers and a card that can defend them. All optional: a check
	// graded from the recovered bounding-box path has none of them, and so does every
	// build made before this gate.
	/** Typed tolerance band — `{kind, nominal, plus, minus, unit}`. */
	tolerance?: Record<string, any> | null;
	comparator?: 'eq' | 'gte' | 'lte' | 'between' | null;
	/** REQUIRED on a circular dimension. Radial and diametral differ by a factor of two. */
	basis?: 'radial' | 'diametral' | null;
	/** Joins this check to its record in the build's `measurements` list. */
	measurement_id?: string | null;
	/** The resolved part/faces the number came off — never a solid index. */
	target?: Record<string, any> | null;
	method?: string | null;
	method_version?: string | null;
	unit?: 'mm' | 'deg' | 'mm3' | 'count' | null;
	/** OCCT's own precision on the faces involved. A miss inside this cannot be `failed`. */
	numeric_error_bound?: number | null;
};

export type CadConformance = {
	schema_version: string;
	status: CadConformanceStatus;
	summary: string;
	checks: CadConformanceCheck[];
	counts?: Record<string, number>;
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
	// Null until someone accepts this revision. A model-authored revision lands as a
	// proposal and stays one until a person says otherwise, whatever the grade — which
	// is why `state` is derived from this timestamp rather than stored beside it.
	accepted_at?: string | null;
	state?: 'proposal' | 'accepted';
	// Present only on an imported revision: the file's own name, digest and size. Its
	// presence is how a client tells "this body came from a file somebody uploaded"
	// from "this body was authored here", without parsing `source_kind`. What the
	// parser made of those bytes — exact or mesh, which reader, how many solids — is a
	// separate verdict and lives on the build, in `validation.provenance`.
	provenance?: CadProvenance | null;
	// The whole CadIR document, on every `source_kind: 'cadir'` revision — not a name
	// pointing at one. That is the difference between a document and a recipe: a recipe
	// name can be looked up in the engine's registry, an authored document exists
	// nowhere else, so the revision has to carry it or it would be unrestorable. The
	// server has always sent this; declaring it is what lets the panels read it.
	cadir?: Record<string, any> | null;
	// Attached by the project read so a reloaded page can find geometry for a
	// revision it did not build itself. Null means this revision has never been built.
	latest_build?: CadBuild | null;
};

export type CadProvenance = {
	source: string;
	name: string;
	kind: string;
	bytes: number;
	sha256: string;
	file_id?: string | null;
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
	// What can be READ, which is shorter than `formats` and must be read separately.
	// A file picker built from `formats` would offer GLB, and every GLB the user chose
	// would be refused: build123d writes glTF and ships no reader for it.
	import_kinds?: string[];
	import_max_bytes?: number;
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
	// The rest of the error body, kept because some refusals carry the evidence for
	// themselves — a `conformance_failed` 409 arrives with the full check list, and a
	// caller that wants to show which dimension missed has nowhere else to get it.
	detail: Record<string, any>;
	constructor(status: number, code: string, message: string, detail: Record<string, any> = {}) {
		super(message);
		this.status = status;
		this.code = code;
		this.detail = detail;
	}
}

const parse = async (res: Response) => {
	if (res.ok) return res.status === 204 ? null : await res.json();
	let code = `http_${res.status}`;
	let message = res.statusText || 'Request failed';
	let detail: Record<string, any> = {};
	try {
		const body = await res.json();
		const d = body?.detail;
		if (d && typeof d === 'object') {
			code = d.error_code ?? code;
			message = d.message ?? message;
			detail = d;
		} else if (typeof d === 'string') {
			message = d;
		}
	} catch {
		// A body that isn't JSON tells us nothing beyond the status, which we have.
	}
	throw new CadApiError(res.status, code, message, detail);
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

/** One file in the virtual project a revision is shown as (CS-3).
 *
 *  There is no file table behind these — the server derives every one of them from the
 *  stored revision on each read, which is why `content` arrives with the listing rather
 *  than behind a second fetch, and why nothing here can be saved.
 *
 *  `node_id` is the body this file builds, when the revision has a successful build to
 *  name one. It is what lets a click in the code view select the same part in the
 *  viewport (CS-6); `null` means the part has no body on screen to point at yet. */
export type CadFile = {
	path: string;
	language: string;
	/** The engine's vocabulary, not a paraphrase of it. `main` is the model file; this
	 *  used to read `model`, which no response ever carried, so every `kind === 'model'`
	 *  test in the UI silently matched nothing. */
	kind: 'spec' | 'main' | 'assembly' | 'part' | 'annotations' | 'recipe' | 'import';
	description: string;
	component: string | null;
	node_id: string | null;
	bytes: number;
	content: string;
	/** JSON-pointer → `[firstLine, lastLine]`, 1-based, into this file's own text. The
	 *  source map that lets a parameter highlight the lines that declare it. Empty on the
	 *  metadata records the backend builds itself, which have no pointers. */
	spans: Record<string, [number, number]>;
};

/** Where something is written: a file, a JSON pointer into it, and the lines it occupies. */
export type CadSourceLoc = {
	path: string | null;
	pointer: string | null;
	line: number | null;
	line_end: number | null;
};

/** One place a parameter is read. `location` is the exact slot — `shaft_extrude.size[0]`
 *  — and is what distinguishes two edges that share a feature and a field. */
export type CadParamUse = CadSourceLoc & {
	op_id: string | null;
	op: string | null;
	component: string | null;
	label: string;
	field: string;
	location: string;
	unit: string;
	formula: string;
};

export type CadParameter = {
	name: string;
	/** `input` is declared and can be given a value; `derived` is computed from the
	 *  inputs by a formula the document carries. */
	kind: 'input' | 'derived';
	value_type: string;
	/** What the build used, when the caller supplied an environment. Null when nothing
	 *  computed it — never a default dressed up as a result. */
	value: number | null;
	default: number | null;
	resolved: boolean;
	min: number | null;
	max: number | null;
	/** Inferred from the fields that consume it, because CadIR parameters carry no unit
	 *  of their own. Empty for counts. */
	unit: string;
	status: 'ok' | 'at_min' | 'at_max' | 'out_of_range' | 'unknown';
	defined_in: CadSourceLoc;
	used_by: CadParamUse[];
};

export type CadFeature = {
	op_id: string;
	op: string;
	mode: string | null;
	component: string | null;
	label: string;
	/** The parameters this operation reads, by name. */
	reads: string[];
	defined_in: CadSourceLoc;
};

/** Parameters, features and the edges between them, over one revision's source.
 *
 *  Built by the engine from the same document it executes, which is what lets the
 *  parameter panel, the feature tree and the code view be three views of one thing
 *  rather than three opinions. `complete: false` means the document did not parse and
 *  the relationships are partial — the files are still real. */
export type CadSourceGraph = {
	source_version: string;
	complete: boolean;
	parameters: CadParameter[];
	features: CadFeature[];
};

export type CadFileTree = {
	revision_id: string;
	seq: number;
	source_kind: string;
	/** The layout version of the emitted project. Null when no document was read. */
	source_version: string | null;
	/** Always true today. Read it rather than assuming it: the day a writer exists, a
	 *  panel that hardcoded read-only would silently keep hiding the save control. */
	read_only: boolean;
	files: CadFile[];
	/** Null when there is no document to graph, or when the engine could not be reached.
	 *  Never an empty graph standing in for one — that would render as "this design has
	 *  no parameters", which is a different claim. */
	source_graph: CadSourceGraph | null;
	/** Plain sentences about what this revision does NOT have — an imported body with no
	 *  steps, a single-body design with no per-part files. The panel shows them instead
	 *  of leaving someone to wonder which file is missing. */
	notes: string[];
};

export const getCadRevisionFiles = async (
	projectId: string,
	revisionId: string
): Promise<CadFileTree> =>
	await parse(
		await fetch(`${BASE}/projects/${projectId}/revisions/${revisionId}/files`, {
			headers: authHeaders()
		})
	);

/** One row of the project's durable design timeline.
 *
 *  It is a superset of `CadJobEvent`, because job activity is one of the three sources
 *  the server merges — the other two are revisions and builds, which is what makes a
 *  slider edit (no job row at all) appear in the same list as the model's tool calls.
 *
 *  `id` is stable and collision-free across sources (`job:<jid>:<seq>`, `rev:<rid>`,
 *  `acc:<rid>`, `build:<bid>`), so a live stream event and its persisted twin collapse
 *  into one row instead of appearing twice. */
export type CadActivityEvent = {
	id: string;
	at: string;
	/** `say` is the model's own narration between tool calls — what it told the reader
	 *  it was about to do, and the reason the timeline reads as a turn rather than a
	 *  list of tool names.
	 *
	 *  `think` is the reasoning that produced it (DE-9), which the agent used to drop
	 *  and now records instead. It arrives redacted and it arrives FOLDED: `label` is
	 *  a heading taken from the reasoning's own opening line, and `thinking` — the
	 *  body — is only ever shown when a reader presses for it. */
	kind:
		| 'started'
		| 'spec'
		| 'say'
		| 'think'
		| 'tool'
		| 'project'
		| 'build'
		| 'done'
		| 'revision'
		| 'accepted'
		/** DE-10: a viewport capture, dated by when the shutter fired. The row carries
		 *  the ids needed to fetch the picture itself — the timeline shows it inline,
		 *  the same authorized bytes the render gallery shows. */
		| 'render';
	label: string;
	seq?: number;
	/** Position in the project's event stream, and the cursor to resume from. Distinct
	 *  from `seq`, which means *which revision* on a revision or build row — one field
	 *  that meant both would be a bug waiting for a client to write it. It is a position
	 *  and it moves; `id` is the identity. */
	stream_seq?: number;
	job_id?: string;
	tool?: string;
	ok?: boolean;
	status?: string;
	duration_ms?: number;
	error_code?: string;
	/** A `think` row's body — absent when the job spent its reasoning budget, in which
	 *  case `truncated` says so rather than the row pretending it had nothing to say.
	 *  `clipped` is the narrower fact: the body is here, but it stops at the server's
	 *  per-thought limit, mid-word. */
	thinking?: string;
	truncated?: boolean;
	clipped?: boolean;
	error_detail?: string;
	conformance?: string;
	project_id?: string;
	revision_id?: string;
	build_id?: string;
	title?: string;
	recipe?: string;
	source_kind?: string;
	created_by?: string;
	model?: string;
	provider?: string;
	provenance?: { filename?: string; sha256?: string; size_bytes?: number; reader?: string } | null;
	measurements?: {
		volume_mm3?: number;
		surface_area_mm2?: number;
		solid_count?: number;
		bbox_mm?: { x: number; y: number; z: number };
	};
	/** On a `spec` row: the dimensions the server's regex extractor read out of the
	 *  request, before the model was asked anything. This is the same answer key
	 *  conformance grades the finished part against, which is why the concept sketch
	 *  drawn from it can never disagree with the verdict. Empty when the sentence
	 *  pinned nothing down — the extractor refuses to guess, and so does the sketch. */
	stated?: Record<string, any> | null;
	unknowns?: string[] | null;
	units?: string | null;
	/** On a `render` row. `render_id` addresses the PNG through the same artifact route
	 *  as every export, so the timeline never gets a second, looser way to read bytes. */
	render_id?: string;
	preset?: CadRenderPreset;
	filename?: string;
	size_bytes?: number;
	source_sha256?: string | null;
};

export const getCadProjectActivity = async (projectId: string): Promise<CadActivityEvent[]> => {
	const body = await parse(
		await fetch(`${BASE}/projects/${projectId}/activity`, { headers: authHeaders() })
	);
	return body?.activity ?? [];
};

// ---------------------------------------------------------------------------
// The workspace snapshot and the replayable event stream (UX-B)
// ---------------------------------------------------------------------------

/** One row of the semantic scene tree the engine emitted for a build.
 *
 *  `node_id` is opaque and derived from *structure* — the document name, the kind, the
 *  op_id or the part's own name — so it survives a slider edit: the explorer keeps its
 *  expansion and its selection across a rebuild instead of collapsing on every revision.
 *
 *  `glb_pick_key` is the same id written into the GLB node's `extras.harvis_node_id`,
 *  and it is null unless the exporter actually produced a mesh subtree for that body.
 *  That null is the difference between a row that can be clicked and a row that would
 *  highlight nothing, so the UI gates on it rather than on `kind === 'body'`. */
export type CadSceneNode = {
	node_id: string;
	parent_id: string | null;
	label: string;
	kind: 'assembly' | 'body' | 'feature' | 'reference';
	status: 'planned' | 'building' | 'valid' | 'error' | 'suppressed';
	selectable: boolean;
	/** The name the document gave this part, or null when it named none (CS-2). Both
	 *  the node id and the colour below derive from it, which is what makes "the
	 *  bottle" the same row and the same colour after a sibling part is added. */
	component?: string | null;
	/** The part's stable pastel, chosen server-side so the tree and the viewport can
	 *  never disagree about which body is which. Presentation only — the exported
	 *  STEP/STL geometry carries no colour and is unaffected. */
	color?: string;
	cadir_operation_id?: string;
	glb_pick_key?: string | null;
	op?: string;
	mode?: string;
	instances?: number;
	optional?: boolean;
	/** The guard that dropped a suppressed operation, in its written form
	 *  (`rib_count >= 1`) — which names the parameter to change. A boolean would not. */
	when?: string;
};

export type CadSceneManifest = {
	schema_version: string;
	root_id: string;
	nodes: CadSceneNode[];
	selection: {
		selectable_kinds: string[];
		faces: boolean;
		edges: boolean;
		reason: string;
	};
};

/** Pick key → colour, for handing a manifest's palette to the viewer (CS-2).
 *
 *  Keyed on `glb_pick_key` rather than `node_id` because that is the id the exporter
 *  actually wrote into the GLB; a body the exporter produced no mesh for has nothing to
 *  paint. Bodies without a colour are left out entirely so the viewer falls back to its
 *  own default instead of being handed `undefined` — a manifest built before per-part
 *  colours existed then renders exactly as it did before. */
export const cadNodeColors = (manifest: CadSceneManifest | null | undefined) =>
	Object.fromEntries(
		(manifest?.nodes ?? [])
			.filter((n) => n.glb_pick_key && n.color)
			.map((n) => [n.glb_pick_key as string, n.color as string])
	);

/** The revision whose geometry belongs on screen — decided by the server, not here.
 *
 *  It is the newest revision that actually *built*, which is deliberately neither the
 *  newest revision (that one may be mid-build or failed) nor the accepted one (a
 *  proposal has to be visible for anyone to judge it). Keeping the rule server-side is
 *  what stops three panels from each deriving a different answer. */
export type CadDisplayed = {
	revision_id: string;
	seq: number;
	state: 'accepted' | 'proposal';
	build_id: string;
	glb_artifact_id: string | null;
	scene_manifest: CadSceneManifest | null;
	validation: Record<string, any> | null;
	conformance: CadConformance | null;
	conformance_status: CadConformanceStatus | null;
};

/** What this workspace can do right now, derived from the state above it rather than
 *  declared. `selection_reason` is the engine's own sentence — the UI shows it instead
 *  of writing a second explanation that can drift from the code that makes it true. */
export type CadWorkspaceCapabilities = {
	units: string;
	hierarchy: boolean;
	select_bodies: boolean;
	select_faces: boolean;
	select_edges: boolean;
	selection_reason?: string | null;
};

export type CadWorkspace = {
	project: CadProject;
	conversation_id: string | null;
	accepted: CadRevision | null;
	latest: CadRevision | null;
	displayed: CadDisplayed | null;
	active_build: CadBuild | null;
	active_job: CadJob | null;
	history: CadRevision[];
	activity: CadActivityEvent[];
	event_cursor: number;
	capabilities: CadWorkspaceCapabilities;
};

/** One read that draws all three panels. Everything they need is decided here, so a
 *  refresh restores the same workspace rather than three panels re-deriving it. */
export const getCadWorkspace = async (projectId: string): Promise<CadWorkspace> =>
	await parse(await fetch(`${BASE}/projects/${projectId}/workspace`, { headers: authHeaders() }));

/** A CAD session: the room one part is made in.
 *
 *  `project_id` is null for a moment after the room opens — a request from chat creates
 *  the room before the model has created anything — so a client must be able to draw
 *  "still starting" rather than assume a project is there. */
export type CadSession = {
	id: string;
	project_id: string | null;
	job_id: string | null;
	source_conversation_id: string | null;
	cad_conversation_id: string;
	title: string;
	view_state: Record<string, any>;
	created_at: string | null;
	updated_at: string | null;
};

/** Session plus the workspace it shows, in one read, for the same reason
 *  `getCadWorkspace` exists: the panels are views of one state, and fetching them
 *  separately means rendering an empty shell first and deciding `displayed` twice. */
export type CadSessionView = {
	session: CadSession;
	workspace: CadWorkspace | null;
};

export const listCadSessions = async (): Promise<CadSession[]> => {
	const body = await parse(await fetch(`${BASE}/sessions`, { headers: authHeaders() }));
	return body?.sessions ?? [];
};

/** Is this chat a CAD room? Null means no, which is the common answer and not an error.
 *  The server decides — the client knows only that it has a chat id. */
export const getCadSessionForConversation = async (
	conversationId: string
): Promise<CadSession | null> => {
	const body = await parse(
		await fetch(`${BASE}/sessions?conversation_id=${encodeURIComponent(conversationId)}`, {
			headers: authHeaders()
		})
	);
	return body?.sessions?.[0] ?? null;
};

/** The room a project is being made in, so a card in the source chat can open it. */
export const getCadSessionForProject = async (projectId: string): Promise<CadSession | null> => {
	const body = await parse(
		await fetch(`${BASE}/sessions?project_id=${encodeURIComponent(projectId)}`, {
			headers: authHeaders()
		})
	);
	return body?.sessions?.[0] ?? null;
};

export const getCadSession = async (sessionId: string): Promise<CadSessionView> =>
	await parse(await fetch(`${BASE}/sessions/${sessionId}`, { headers: authHeaders() }));

/** Remember where the user was. Merged server-side, so send only the corner that
 *  changed — a camera save from the viewport must not drop the open code file. */
export const saveCadSessionView = async (
	sessionId: string,
	viewState: Record<string, any>
): Promise<CadSession> => {
	const body = await parse(
		await fetch(`${BASE}/sessions/${sessionId}`, {
			method: 'PATCH',
			headers: { ...authHeaders(), 'Content-Type': 'application/json' },
			body: JSON.stringify({ view_state: viewState })
		})
	);
	return body?.session;
};

export const renameCadSession = async (sessionId: string, title: string): Promise<CadSession> => {
	const body = await parse(
		await fetch(`${BASE}/sessions/${sessionId}`, {
			method: 'PATCH',
			headers: { ...authHeaders(), 'Content-Type': 'application/json' },
			body: JSON.stringify({ title })
		})
	);
	return body?.session;
};

/** The durable timeline after `afterSeq`, as one JSON body.
 *
 *  The cursor that comes back is the row actually last returned, not the highest that
 *  exists — pass it straight back to continue, and the same cursor twice returns the
 *  same rows both times. Nothing here is generated at connect time. */
export const getCadProjectEvents = async (
	projectId: string,
	afterSeq = 0
): Promise<{ events: CadActivityEvent[]; cursor: number }> => {
	const body = await parse(
		await fetch(`${BASE}/projects/${projectId}/events?stream=0&after_seq=${afterSeq}`, {
			headers: authHeaders()
		})
	);
	return { events: body?.events ?? [], cursor: body?.cursor ?? afterSeq };
};

/** The same timeline as server-sent events, resuming from `afterSeq`.
 *
 *  Reconnection is a resume, not a replay: hand back the last cursor seen and only the
 *  rows after it arrive. The `reconnect` frame is the server rotating a long-lived
 *  connection deliberately, which a client should tell apart from a drop — hence
 *  `onReconnect`, which fires with the cursor to come back on.
 *
 *  Resolves when the stream ends or the signal aborts, and never throws for a dropped
 *  connection: the caller's snapshot refresh is the fallback, and an exception here
 *  would only make an ordinary close look like a fault. */
export const streamCadProjectEvents = async (
	projectId: string,
	afterSeq: number,
	handlers: {
		onActivity?: (ev: CadActivityEvent) => void;
		onCursor?: (seq: number) => void;
		onReconnect?: (seq: number) => void;
		signal?: AbortSignal;
	}
): Promise<void> => {
	let res: Response;
	try {
		res = await fetch(`${BASE}/projects/${projectId}/events?after_seq=${afterSeq}`, {
			headers: authHeaders(),
			signal: handlers.signal
		});
	} catch {
		return;
	}
	if (!res.ok || !res.body) return;

	const reader = res.body.getReader();
	const decoder = new TextDecoder();
	let buf = '';
	try {
		for (;;) {
			const { done, value } = await reader.read();
			if (done) break;
			buf += decoder.decode(value, { stream: true });
			// SSE frames are separated by a blank line; a partial frame stays in the
			// buffer until its terminator arrives rather than being parsed half-read.
			let cut: number;
			while ((cut = buf.indexOf('\n\n')) !== -1) {
				const frame = buf.slice(0, cut);
				buf = buf.slice(cut + 2);
				let kind = 'message';
				let data = '';
				for (const line of frame.split('\n')) {
					if (line.startsWith('event: ')) kind = line.slice(7).trim();
					else if (line.startsWith('data: ')) data += line.slice(6);
					// A line starting with ':' is a keep-alive comment. Ignored on purpose.
				}
				if (!data) continue;
				let payload: any;
				try {
					payload = JSON.parse(data);
				} catch {
					continue;
				}
				if (kind === 'activity') handlers.onActivity?.(payload);
				else if (kind === 'cursor') handlers.onCursor?.(payload.stream_seq);
				else if (kind === 'reconnect') handlers.onReconnect?.(payload.stream_seq);
			}
		}
	} catch {
		// Aborted, or the connection dropped. The caller resumes from its cursor.
	}
};

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
	// Which kind of revision this call appended. A proposal did NOT become the head, so
	// a caller that assumed 202 meant "this is now the project" would draw the wrong
	// thing for every model-authored part.
	state?: 'proposal' | 'accepted';
	created: boolean;
};

/** 202 — the revision exists immediately, the geometry does not. Poll `getBuild`.
 *  A stale `base_revision_id` throws a CadApiError with status 409. */
export const createCadRevision = async (
	projectId: string,
	body: {
		base_revision_id: string;
		recipe?: string;
		/** A whole CadIR document, for a part that was authored rather than picked from
		 *  the engine's recipe registry. Mutually exclusive with `recipe`: the server
		 *  takes the document when both are present, and an authored part's name is not
		 *  a recipe the engine could look up. */
		document?: Record<string, any>;
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

export type CadImportAccepted = CadRevisionAccepted & { project_id: string };

/** Import an uploaded STEP/STL/3MF/BREP file as geometry. 202, like a revision.
 *
 *  The file is named by an id the server can resolve and check ownership on — never
 *  by a path, and never by the bytes going back out through the browser. Upload it
 *  first (OWUI's file API) and pass the id you get back.
 *
 *  Omitting `project_id` creates a project around the file. Passing one appends to it,
 *  and then `base_revision_id` is required: an append with no base is a silent fork,
 *  and the server answers 409 rather than making one.
 *
 *  An imported revision cannot be restored — the source bytes were never kept, so
 *  there is nothing to rebuild from, and `restoreCadRevision` answers 400
 *  `import_not_rebuildable` for one. Import the file again instead. */
export const importCadAsset = async (body: {
	attachment: { name: string; file_id?: string; url?: string; mime_type?: string };
	project_id?: string;
	base_revision_id?: string;
	title?: string;
	conversation_id?: string | null;
	formats?: CadFormat[];
	idempotency_key?: string;
}): Promise<CadImportAccepted> =>
	await parse(
		await fetch(`${BASE}/imports`, {
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

/** Promote a proposal to the project head — the only call that moves the head.
 *
 *  Throws `CadApiError` with status 409 and one of three codes, each meaning something
 *  different to the person who hit it: `not_built` (build it first), `stale_proposal`
 *  (restore it instead), and `conformance_failed` — the geometry missed the frozen
 *  DesignSpec, and `err.detail.conformance` carries the checks that say how. Retrying
 *  that last one with `acknowledge = true` accepts it anyway, which is a decision a
 *  person is allowed to make and a client must never make for them. */
export const acceptCadRevision = async (
	projectId: string,
	revisionId: string,
	acknowledge = false
): Promise<CadRevision> =>
	await parse(
		await fetch(`${BASE}/projects/${projectId}/revisions/${revisionId}/accept`, {
			method: 'POST',
			headers: jsonHeaders(),
			body: JSON.stringify({ acknowledge_conformance: acknowledge })
		})
	);

// ---------------------------------------------------------------------------
// Authoring jobs
//
// A build is what the engine made; a job is the turn a model spent making it. In the
// authoring lane the model creates the project itself, several seconds in, so the job
// id is the only id that exists when the chat card has to appear. Everything else
// arrives over the stream as the model discovers it.
// ---------------------------------------------------------------------------

/** `queued` (UX-G) is a turn that exists and has not begun — a follow-up sent while
 *  another turn was still authoring. It is a real, nameable, stoppable turn rather
 *  than a message the browser is holding on to, which is why it has a status of its
 *  own instead of being drawn as a running one that happens to be quiet. */
export type CadJobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';

/** One row of design activity. Public by construction: a tool name, a verdict, a
 *  duration, the narration the model wrote for the reader on a `say` row, or on a
 *  `think` row the reasoning behind it — redacted server-side and folded behind a
 *  press. Never a prompt, a credential, a path, or a storage key. */
export type CadJobEvent = {
	seq: number;
	at: string;
	kind: 'started' | 'spec' | 'say' | 'think' | 'tool' | 'project' | 'build' | 'done';
	label: string;
	tool?: string;
	ok?: boolean;
	duration_ms?: number;
	error_code?: string;
	thinking?: string;
	truncated?: boolean;
	clipped?: boolean;
	stated?: Record<string, any> | null;
	unknowns?: string[] | null;
	units?: string | null;
	project_id?: string;
	revision_id?: string;
	build_id?: string;
	title?: string;
	conformance?: string;
};

export type CadJob = {
	id: string;
	status: CadJobStatus;
	phase: string | null;
	description?: string;
	provider: string | null;
	model: string | null;
	title: string | null;
	project_id: string | null;
	revision_id: string | null;
	build_id: string | null;
	conformance: string | null;
	error_code: string | null;
	error_detail: string | null;
	activity?: CadJobEvent[];
	created_at?: string | null;
	finished_at: string | null;
};

export const getCadJob = async (jobId: string): Promise<CadJob> =>
	await parse(await fetch(`${BASE}/jobs/${jobId}`, { headers: authHeaders() }));

/** What a cancel actually achieved. `cancelled` false is a real answer, not a failure:
 *  a turn that already finished had nothing to stop, and one running in another
 *  backend process has its row marked but its work untouched. The UI has to say which
 *  of those happened rather than showing "Cancelled" over something still running. */
export type CadCancelResult = {
	ok: boolean;
	status: string;
	cancelled: boolean;
	engine_acknowledged?: boolean;
	reason?: string;
	build_id?: string | null;
};

export const cancelCadJob = async (jobId: string): Promise<CadCancelResult> =>
	await parse(
		await fetch(`${BASE}/jobs/${jobId}/cancel`, {
			method: 'POST',
			headers: authHeaders()
		})
	);

/** Follow one authoring turn. `onActivity` fires per design-activity row, `onStatus`
 *  whenever the job's own fields move, and the promise resolves with the final job.
 *
 *  It is an EventSource-shaped stream read through `fetch`, because `EventSource`
 *  cannot send an Authorization header and this route is authorized like every other.
 *
 *  The stream is an optimisation, never a source of truth of its own: everything it
 *  says is also readable from `getCadJob`, so a caller that loses it can fall back to
 *  polling and see the same timeline. */
export const streamCadJob = async (
	jobId: string,
	handlers: {
		onActivity?: (ev: CadJobEvent) => void;
		onStatus?: (job: CadJob) => void;
		signal?: AbortSignal;
	} = {}
): Promise<CadJob | null> => {
	const res = await fetch(`${BASE}/jobs/${jobId}/stream`, {
		headers: authHeaders(),
		signal: handlers.signal
	});
	if (!res.ok || !res.body) {
		await parse(res); // throws with the lane's error shape
		return null;
	}
	const reader = res.body.getReader();
	const decoder = new TextDecoder();
	let buf = '';
	let last: CadJob | null = null;
	try {
		for (;;) {
			const { done, value } = await reader.read();
			if (done) break;
			buf += decoder.decode(value, { stream: true });
			let cut = buf.indexOf('\n\n');
			while (cut !== -1) {
				const raw = buf.slice(0, cut);
				buf = buf.slice(cut + 2);
				cut = buf.indexOf('\n\n');
				if (!raw || raw.startsWith(':')) continue; // keep-alive comment
				let kind = '';
				let data = '';
				for (const line of raw.split('\n')) {
					if (line.startsWith('event: ')) kind = line.slice(7);
					else if (line.startsWith('data: ')) data = line.slice(6);
				}
				if (!data) continue;
				let payload: any;
				try {
					payload = JSON.parse(data);
				} catch {
					continue; // a truncated frame is not worth killing the stream over
				}
				if (kind === 'activity') handlers.onActivity?.(payload as CadJobEvent);
				else if (kind === 'status' || kind === 'done') {
					last = payload as CadJob;
					handlers.onStatus?.(last);
				}
			}
		}
	} finally {
		try {
			await reader.cancel();
		} catch {
			// the stream is already gone; nothing left to release
		}
	}
	return last;
};

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

/** Post a viewport capture. `sourceSha256` is the digest of the export the viewer
 *  loaded — the server refuses any render that does not match an artifact this build
 *  produced, so a picture can never drift onto the wrong solid. */
export const uploadCadRender = async (
	buildId: string,
	preset: CadRenderVariant,
	blob: Blob,
	sourceSha256: string,
	label = '',
	mask: Blob | null = null
): Promise<CadRender> => {
	const form = new FormData();
	form.append('file', blob, `view-${preset}.png`);
	form.append('preset', preset);
	form.append('source_sha256', sourceSha256);
	form.append('label', label);
	// The object-mask pass, when the recipe asked for one. It is QC input, not a second
	// picture: the server measures it, keeps the findings on this render's `meta`, and
	// throws the bytes away — the gallery still shows beauty passes only.
	if (mask) form.append('mask', mask, `mask-${preset}.png`);
	// No Content-Type here on purpose: the browser writes the multipart boundary and
	// setting the header by hand loses it.
	const res = await fetch(`${BASE}/builds/${buildId}/renders`, {
		method: 'POST',
		headers: authHeaders(),
		body: form
	});
	return (await parse(res)).render;
};

/** The views this build is worth photographing, and why. Server-derived from what the
 *  request stated and what the build produced, so a build that claimed no cavity gets no
 *  cut view arguing about one. An empty list means there is nothing to photograph. */
export const getCadRenderRecipes = async (buildId: string): Promise<CadRenderRecipe[]> =>
	(await parse(
		await fetch(`${BASE}/builds/${buildId}/render-recipes`, { headers: authHeaders() })
	)).recipes ?? [];

export const getCadRenders = async (buildId: string): Promise<CadRender[]> =>
	(await parse(await fetch(`${BASE}/builds/${buildId}/renders`, { headers: authHeaders() })))
		.renders ?? [];

/** Renders need an Authorization header like every other artifact, so an `<img src>`
 *  pointed at the route would 401. Fetch the bytes and hand back an object URL — the
 *  caller revokes it. */
export const fetchCadRenderObjectUrl = async (
	buildId: string,
	renderId: string
): Promise<string> => {
	const res = await fetch(cadArtifactUrl(buildId, renderId), { headers: authHeaders() });
	if (!res.ok) await parse(res);
	return URL.createObjectURL(await res.blob());
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
