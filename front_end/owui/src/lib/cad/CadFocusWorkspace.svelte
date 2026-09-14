<script lang="ts">
	// The CAD focus workspace (UX-1).
	//
	// This is not a route and not a second copy of anything. It renders inside the
	// chat page, over the pane group, and takes everything except a strip on the
	// right — where the conversation you were already having keeps running, in the
	// same component instance, with its history, its draft and its scroll position
	// untouched. Closing removes this element and the chat springs back to full
	// width. That is the whole reason it is an overlay rather than a `/harvis/cad`
	// route: a route would have to build a second chat, and two chats for one
	// conversation is the failure this design exists to avoid.
	//
	// The strip itself is not drawn here. Chat.svelte pins its own chat pane to the
	// right edge at `--cad-chat-w`; this component owns the drag handle that sets
	// that number, and nothing else about the chat.
	//
	// Scope: shell, canvas, honest status, the design activity panel (UX-2), the render
	// filmstrip (UX-3), and the context panels (UX-4). The panels are not reimplemented
	// here — they are CadContextPanels, the same component the full studio route mounts,
	// so a part can be edited from either surface and there is only one implementation of
	// Parameters, Validate and Compare to keep honest.
	//
	// UX-C made it three panels rather than two. The left column is the explorer:
	// hierarchy, project files, revision history. The centre is the viewport. The right
	// is Design Activity and the editing panels, with the conversation strip beyond it.
	// The state behind all three comes from ONE read — the workspace snapshot — so the
	// three cannot disagree about which revision is on screen, and the activity comes
	// from the project's durable event stream rather than a poll, so a refresh restores
	// the same timeline instead of restarting a fake one.
	import { getContext, onDestroy, onMount, tick } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { cadSelection } from '$lib/stores';
	import {
		acceptCadRevision,
		cadArtifactUrl,
		CadApiError,
		cadNodeColors,
		cancelCadJob,
		createCadRevision,
		downloadCadArtifact,
		fetchCadRenderObjectUrl,
		getCadCapability,
		getCadJob,
		getCadRenderRecipes,
		getCadRenders,
		getCadWorkspace,
		streamCadJob,
		streamCadProjectEvents,
		uploadCadRender,
		type CadActivityEvent,
		type CadArtifact,
		type CadCapability,
		type CadFormat,
		type CadJob,
		type CadJobEvent,
		type CadProject,
		type CadRender,
		type CadRenderPreset,
		type CadRenderRecipe,
		type CadRevision,
		type CadWorkspace
	} from '$lib/apis/cad';
	import CadContextPanels, { CAD_PANELS, type CadPanelId } from '$lib/cad/CadContextPanels.svelte';
	import CadConceptSketch from '$lib/cad/CadConceptSketch.svelte';
	import CadExplorer, { type CadExplorerTab } from '$lib/cad/CadExplorer.svelte';
	import CadViewer from '$lib/cad/CadViewer.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	// The rail's glyphs, from the app's own set: a cube here and a cube anywhere else in
	// Harvis mean the same thing, which is the whole reason an icon rail can be read at a
	// glance where a column of six labels cannot.
	import AdjustmentsHorizontal from '$lib/components/icons/AdjustmentsHorizontal.svelte';
	import ArrowLeft from '$lib/components/icons/ArrowLeft.svelte';
	import ChartBar from '$lib/components/icons/ChartBar.svelte';
	import ClockRotateRight from '$lib/components/icons/ClockRotateRight.svelte';
	import CodeBracket from '$lib/components/icons/CodeBracket.svelte';
	import Cube from '$lib/components/icons/Cube.svelte';
	import DocumentCheck from '$lib/components/icons/DocumentCheck.svelte';
	import Folder from '$lib/components/icons/Folder.svelte';
	import Knobs from '$lib/components/icons/Knobs.svelte';
	import PhotoSolid from '$lib/components/icons/PhotoSolid.svelte';
	import TaskList from '$lib/components/icons/TaskList.svelte';
	// DE-10. The timeline's stops are icons, not dots: a row that shows a wrench, a
	// lightbulb or a camera says what KIND of thing happened before its words are read.
	// These are the app's own icon set — the same glyphs the rest of Harvis uses, so a
	// wrench here and a wrench in the toolbar mean the same thing.
	// One definition for both surfaces — the card in chat draws the same stops.

	const i18n: any = getContext('i18n');

	export let projectId = '';
	/** The authoring turn, when this was opened from a card whose model is still
	 *  working. Empty for a project opened after the fact. */
	export let jobId = '';
	/** Width of the conversation strip, in pixels. Bound by Chat.svelte. */
	export let chatWidth = 420;
	/** Strip hidden entirely. The chat keeps running; it is display:none, not gone. */
	export let chatCollapsed = false;
	export let onClose: () => void = () => {};
	/** Mounted as a page rather than as an overlay over a chat (CS-4).
	 *
	 *  The difference is not cosmetic. As an overlay this component leaves a strip on the
	 *  right for Chat.svelte's own pane and owns the handle that sizes it; on a route
	 *  there is no such pane, so the strip, its width and its drag handle would all be
	 *  reserving space for something that will never arrive. Standalone also drops
	 *  Parameters, because the session spec removes manual parameter editing from the
	 *  first version — the part changes by asking. */
	export let standalone = false;
	/** What the back button says. A route goes back to the conversation that opened it;
	 *  the overlay just closes over the one it is already sitting on. */
	export let closeLabel = '';

	// The spec asks for 380–460px. The floor is enforced because a narrower column
	// makes the composer unusable; the ceiling is looser, because on a wide display
	// a 460px cap makes "resizable" a word without a behaviour.
	const MIN_W = 380;
	const MAX_W = 620;

	// The right column shows the panels that CHANGE the part. History and Artifacts moved
	// to the left explorer in UX-C, where they are the Project and History tabs — leaving
	// them here as well would put two revision lists on one screen, and sooner or later
	// they would disagree about which revision is selected. The studio route still mounts
	// all six, because it has no explorer beside it.
	const WORKSPACE_PANELS: CadPanelId[] = ['design', 'parameters', 'validate', 'compare'];
	// Both modes now show the same four. Standalone used to drop Parameters because the
	// explorer beside it already had a section by that name and two identical labels in
	// two different strips is a guessing game — but they were never the same surface: the
	// explorer's is the dependency graph, this one is the sliders that change the part.
	// One rail, two distinct names, and the route stops being the mode where the part
	// cannot be adjusted by hand.
	$: PANELS = CAD_PANELS.filter(([id]) => WORKSPACE_PANELS.includes(id));

	/** One rail for every surface this workspace can dock beside the viewport.
	 *
	 *  `kind` says which component draws it: a section of the explorer's stack, or one of
	 *  the context panels. Pressing an icon adds its surface to the pane *under* whatever
	 *  is already there rather than replacing it, so a reader can watch the feature tree
	 *  and the parameters at the same time the way the old accordion allowed. Pressing it
	 *  again takes that surface back out; taking the last one out gives the viewport the
	 *  whole window. */
	type RailItem = {
		kind: 'explorer' | 'panel';
		target: string;
		icon: any;
		label: string;
		group: number;
	};
	const RAIL: RailItem[] = [
		{ kind: 'explorer', target: 'hierarchy', icon: Cube, label: 'Feature tree', group: 0 },
		{ kind: 'explorer', target: 'parameters', icon: Knobs, label: 'Parameter graph', group: 0 },
		{ kind: 'explorer', target: 'code', icon: CodeBracket, label: 'Code', group: 0 },
		{ kind: 'explorer', target: 'files', icon: Folder, label: 'Project files', group: 0 },
		{ kind: 'explorer', target: 'history', icon: ClockRotateRight, label: 'History', group: 1 },
		{ kind: 'explorer', target: 'project', icon: PhotoSolid, label: 'Renders and exports', group: 1 },
		{ kind: 'panel', target: 'design', icon: TaskList, label: 'Design', group: 2 },
		{ kind: 'panel', target: 'parameters', icon: AdjustmentsHorizontal, label: 'Parameters', group: 2 },
		{ kind: 'panel', target: 'validate', icon: DocumentCheck, label: 'Validate', group: 2 },
		{ kind: 'panel', target: 'compare', icon: ChartBar, label: 'Compare', group: 2 }
	];
	const railKey = (r: RailItem) => `${r.kind}:${r.target}`;
	/** Which surfaces are in the stack. The tree and the code to start with, which is what
	 *  the explorer opened with before the rail existed. */
	let railOpen: Record<string, boolean> = {
		'explorer:hierarchy': true,
		'explorer:code': true
	};
	$: railItems = RAIL.filter(
		(r) => r.kind === 'explorer' || PANELS.some(([id]) => id === r.target)
	);
	/** The explorer's own open map, derived from the rail. It keeps drawing the stack,
	 *  the headers and the drag grips; only the control over what is in it moved out. */
	$: explorerOpen = Object.fromEntries(
		RAIL.filter((r) => r.kind === 'explorer').map((r) => [r.target, !!railOpen[railKey(r)]])
	) as Record<CadExplorerTab, boolean>;
	$: openPanels = PANELS.filter(([id]) => railOpen[`panel:${id}`]);
	$: explorerShown = Object.values(explorerOpen).some(Boolean);
	$: paneOpen = explorerShown || openPanels.length > 0;

	/** The one read the three panels share. Everything below is derived from it, so the
	 *  explorer, the viewport and the panels cannot end up describing different
	 *  revisions of the same part. */
	let ws: CadWorkspace | null = null;
	let job: CadJob | null = null;
	// Design activity, keyed by event id. Three sources write into this one map — the
	// snapshot, the project's durable event stream, and the live job stream — and the
	// shared id is what makes a streamed event and its persisted twin the same row
	// rather than two.
	let events: Record<string, CadActivityEvent> = {};
	/** Where the durable stream resumes from. Advanced by the snapshot and by the
	 *  stream itself; a reconnect hands it straight back, so a dropped connection
	 *  replays nothing and misses nothing. */
	let eventCursor = 0;
	let explorerTab: CadExplorerTab = 'hierarchy';
	/** Bound so the Validate panel can ask the tree to reveal the operation that broke a
	 *  build. A prop would not do: the same node may need revealing twice, and an
	 *  unchanged prop fires nothing. */
	let explorer: CadExplorer | null = null;
	/** Which tree node the user picked. Held here rather than in the explorer because
	 *  UX-D binds it to the viewport, and a selection that lived in one panel could not
	 *  be shared with the other two. */
	let selectedNodeId = '';
	// Which context panel the side column is showing. Activity leads because it is the
	// only one with anything to say while the model is still working; the rest are the
	// shared panels, and they are the same component the studio route mounts.
	let capability: CadCapability | null = null;
	/** Busy, per panel, because several panels can be in the stack at once and a single
	 *  flag would let a hidden one clear a visible one's. */
	let panelBusy: Record<string, boolean> = {};
	$: panelsBusy = Object.values(panelBusy).some(Boolean);
	let loadError = '';
	let selectedRevisionId = '';
	let canvasBox: HTMLDivElement;
	let canvasH = 420;
	let accepting = false;
	let abort: AbortController | null = null;
	let streamAbort: AbortController | null = null;
	let streamRunning = false;
	let stopped = false;
	let reloadTimer: any = null;

	// Renders. The pictures come from this viewport, which is the only renderer there is —
	// there is no server-side one. The strip of manual re-take buttons that used to sit
	// under the canvas is gone: `autoCapture` takes all six presets the moment a build
	// succeeds, so the strip was a row of buttons for work already done, and it cost the
	// part 64px of the window it is the whole point of. The pictures themselves are still
	// here — the explorer's Renders and exports section shows them.
	let viewer: any = null;
	let renders: CadRender[] = [];
	let renderUrls: Record<string, string> = {}; // artifact id → object URL
	let capturing = '';
	let renderError = '';
	// One auto-capture per build, tracked by build id: a re-render on every reactive
	// pass would upload the same picture repeatedly and burn the user's quota.
	let autoCaptured: Record<string, boolean> = {};
	// The server's own answer to "which views is this build worth photographing" (HE-7).
	// Empty for a build with no named bodies, and empty is a real answer.
	let recipes: CadRenderRecipe[] = [];

	$: revisions = ws?.history ?? [];
	// The context panels take a project with its revisions attached; the snapshot keeps
	// the two apart. Recomposing here rather than fetching the project a second time is
	// what keeps every panel on one read.
	$: project = (ws ? { ...ws.project, revisions } : null) as CadProject | null;
	// Newest first is what the project read returns and what the studio panel
	// assumes; picking by seq rather than by position survives either order.
	$: newest = revisions.reduce<CadRevision | null>(
		(a, r) => (!a || (r.seq ?? 0) > (a.seq ?? 0) ? r : a),
		null
	);
	// What is on screen: the user's pick if they made one, otherwise the server's
	// `displayed` — the newest revision that actually BUILT. Following `displayed`
	// rather than `newest` is the whole of §3's promise: a newer revision that failed
	// or is still building never blanks a viewport that was showing good geometry.
	$: displayedRevision = ws?.displayed
		? (revisions.find((r) => r.id === ws.displayed?.revision_id) ?? null)
		: null;
	$: current = revisions.find((r) => r.id === selectedRevisionId) ?? displayedRevision ?? newest;
	$: build = current?.latest_build ?? null;
	// The tree of whatever revision is being looked at, straight from that build. A
	// failed build carries one too, which is what lets the explorer point at the
	// operation that went wrong instead of emptying.
	$: manifest = build?.scene_manifest ?? null;
	// The same palette the explorer paints its swatches from, so a part is one colour in
	// both places (CS-2). It is the engine's choice, not this component's.
	$: nodeColors = cadNodeColors(manifest);
	$: capabilities = ws?.capabilities ?? null;
	// The one gate both panels obey, written once. It is deliberately the same three
	// conditions `CadExplorer.canSelect` applies — a body the engine built, whose id
	// actually landed in the GLB, on a lane where the server allows body selection.
	$: pickable = new Set(
		(manifest?.nodes ?? [])
			.filter((n) => n.selectable && n.glb_pick_key && capabilities?.select_bodies !== false)
			.map((n) => n.glb_pick_key as string)
	);
	$: selectedNode = (manifest?.nodes ?? []).find((n) => n.node_id === selectedNodeId) ?? null;
	// A selection belongs to the revision whose manifest named it. Anything else — a
	// revision switch that raced a click, a manifest that arrived without the node —
	// drops it rather than leaving a chip pointing at nothing. Written as a call
	// rather than an inline test because reading `selectedNode` here and assigning
	// `selectedNodeId` would be a reactive cycle the compiler refuses.
	const dropStaleSelection = (m: typeof manifest) => {
		if (!selectedNodeId || !m) return;
		if (!(m.nodes ?? []).some((n) => n.node_id === selectedNodeId)) selectedNodeId = '';
	};
	$: dropStaleSelection(manifest);
	// Publish to the composer. The revision travels with the node because a node id
	// only means something inside the manifest that named it — sending the project
	// alone would let the server resolve the id against whatever happened to be head
	// by the time the message arrived, which is a different part.
	$: cadSelection.set(
		selectedNode && current
			? {
					project_id: projectId,
					revision_id: current.id,
					node_id: selectedNode.node_id,
					label: selectedNode.label,
					kind: selectedNode.kind
				}
			: null
	);
	// …and follow it back. The composer's chip has its own clear button, and without
	// this the next reactive pass would simply republish the selection the user just
	// dismissed.
	$: if ($cadSelection === null) selectedNodeId = '';
	$: artifacts = (build?.artifacts ?? []) as CadArtifact[];
	$: viewable =
		build?.status === 'succeeded'
			? (artifacts.find((a) => a.format === 'glb') ??
				artifacts.find((a) => a.format === 'stl') ??
				null)
			: null;
	$: viewUrl = build && viewable ? cadArtifactUrl(build.id, viewable.id) : '';
	$: validation = (build?.validation ?? null) as Record<string, any> | null;
	// Two verdicts that are never merged: `validation` says the solid is well-formed,
	// `conformance` says it is the part that was asked for. A build can pass the first
	// and fail the second, and this bar shows both rather than one green light.
	$: conformance = build?.conformance ?? null;
	// `queued` counts as running here on purpose: the turn exists, it is going to happen,
	// and it can still be stopped — treating it as finished would take the Stop button off
	// a turn the user can call off for free. `job === null` is the moment before the first
	// poll lands, when the id is all we have.
	$: jobRunning =
		!!jobId && (job === null || job.status === 'running' || job.status === 'queued');
	$: jobWaiting = job?.status === 'queued';
	$: building = !!build && (build.status === 'queued' || build.status === 'running');
	$: modelBadge = job?.model ?? '';
	$: timeline = Object.values(events).sort(
		(a, b) => Date.parse(a.at) - Date.parse(b.at) || a.id.localeCompare(b.id)
	);
	// `timeline` still feeds the concept sketch below — the rows themselves are drawn by
	// the card in the conversation now, so nothing here re-parents or renders them.

	// DE-8e: what the request pinned down, read by the server before the model was asked
	// anything — the only thing that exists while the viewport is still empty. The newest
	// `spec` row wins, so a second turn's request replaces the first one's sketch rather
	// than leaving the earlier drawing under a newer build. `design_spec` on the current
	// revision is the fallback for a workspace opened cold, where the job rows the sketch
	// came from belong to a turn that finished before this page did.
	$: specRow = [...timeline].reverse().find((e) => e.kind === 'spec');
	$: conceptSpec = specRow
		? { stated: specRow.stated ?? {}, unknowns: specRow.unknowns ?? [], units: specRow.units }
		: {
				stated: (current?.design_spec?.stated as Record<string, any>) ?? {},
				unknowns: (current?.design_spec?.unknowns as string[]) ?? [],
				units: (current?.design_spec?.units as string) ?? 'mm'
			};

	// The strip follows the build, not the revision: renders belong to the geometry
	// that was actually made, and a revision that has been rebuilt has two of them.
	let renderedBuildId = '';
	$: if (build?.id && build.id !== renderedBuildId) {
		renderedBuildId = build.id;
		revokeRenderUrls();
		renders = [];
		loadRenders(build.id);
	}
	// Kept separate from the line above because a build arrives here `running` and
	// becomes `succeeded` without its id changing — folding the two would mean the
	// automatic view is only ever taken for builds that were already finished when the
	// workspace opened.
	$: if (build?.status === 'succeeded' && viewable && !autoCaptured[build.id]) {
		autoCapture(build.id);
	}

	const phaseLabel = () => {
		// A waiting turn has no phase to report — nothing has run yet — so it says what is
		// actually true of it rather than borrowing the running turn's language.
		if (jobWaiting) return $i18n.t('Waiting for the current turn to finish…');
		if (job?.phase === 'building') return $i18n.t('Building the geometry…');
		return $i18n.t('Designing the part…');
	};

	let cancelling = false;
	let cancelNote = '';

	/** Stop the authoring turn — the model loop, the repair rounds and the geometry.
	 *  What is reported is what the server says it managed to stop, not what was
	 *  asked for: a turn running in another process cannot be interrupted from here,
	 *  and saying "cancelled" over something still running would be the one thing a
	 *  stop button must never do. The accepted model stays on screen throughout. */
	const stopJob = async () => {
		if (!jobId || cancelling) return;
		cancelling = true;
		cancelNote = '';
		try {
			const res = await cancelCadJob(jobId);
			if (!res.cancelled && res.reason === 'already_finished') {
				cancelNote = $i18n.t('That turn had already finished.');
			} else if (!res.cancelled) {
				cancelNote = $i18n.t(
					'Marked cancelled, but the turn is running elsewhere and could not be stopped from here.'
				);
			}
			job = await getCadJob(jobId);
		} catch (e) {
			cancelNote = `${e}`;
		} finally {
			cancelling = false;
		}
	};

	/** Merge a row into the timeline. Rows arriving from the snapshot and from the
	 *  stream share their id, so the second one updates the first in place instead of
	 *  appearing beside it. */
	const mergeRow = (r: CadActivityEvent) => {
		events = { ...events, [r.id]: { ...(events[r.id] ?? {}), ...r } };
	};

	/** One read for all three panels. Replaces the old project fetch, the separate
	 *  activity fetch and the 2.5 s poll: the state comes back consistent, and the
	 *  stream below keeps it that way. */
	const load = async () => {
		if (!projectId) return;
		try {
			const snap = await getCadWorkspace(projectId);
			ws = snap;
			for (const r of snap.activity ?? []) mergeRow(r);
			if (typeof snap.event_cursor === 'number' && snap.event_cursor > eventCursor) {
				eventCursor = snap.event_cursor;
			}
			loadError = '';
		} catch (e: any) {
			loadError = e?.message ?? String(e);
		}
	};

	/** Reload the snapshot shortly after something durable happened. Debounced because
	 *  a finished build arrives as several rows at once and each one would otherwise
	 *  ask for the same read. */
	const scheduleReload = () => {
		clearTimeout(reloadTimer);
		reloadTimer = setTimeout(load, 250);
	};

	/** The project's durable timeline, resumed from the cursor rather than replayed.
	 *
	 *  This is what makes a refresh restore the same activity instead of restarting an
	 *  animation: every row already exists on the server, and reconnecting asks for the
	 *  rows after the last one seen. A stream that ends without delivering anything is a
	 *  connection that failed, so the retry waits — a dead endpoint must not become a
	 *  request loop. */
	const runEventStream = async () => {
		if (streamRunning || !projectId) return;
		streamRunning = true;
		while (!stopped) {
			const before = eventCursor;
			streamAbort = new AbortController();
			await streamCadProjectEvents(projectId, eventCursor, {
				onActivity: (ev) => {
					mergeRow(ev);
					// A revision, a build or an acceptance changes what the panels should be
					// showing. A tool row changes only the timeline it just landed in.
					if (
						ev.kind === 'revision' ||
						ev.kind === 'build' ||
						ev.kind === 'accepted' ||
						ev.kind === 'project'
					) {
						scheduleReload();
					}
				},
				onCursor: (s) => {
					if (s > eventCursor) eventCursor = s;
				},
				onReconnect: (s) => {
					if (s > eventCursor) eventCursor = s;
				},
				signal: streamAbort.signal
			});
			if (stopped) break;
			await new Promise((r) => setTimeout(r, eventCursor > before ? 500 : 4000));
		}
		streamRunning = false;
	};

	const record = (ev: CadJobEvent) => {
		// Same id the server gives this event once it is persisted, so the durable
		// stream replaces it in place instead of duplicating it.
		const id = `job:${jobId}:${ev.seq}`;
		if (events[id]) return;
		events = { ...events, [id]: { ...ev, id, job_id: jobId } as CadActivityEvent };
		// A new project, revision or build means the geometry the canvas is showing is
		// out of date. Everything else is a tool call and changes nothing on screen.
		if (ev.kind === 'project' || ev.kind === 'build') scheduleReload();
	};

	/** UX-G: wait out the turn in front of this one, reading the row rather than a stream
	 *  that does not exist yet. Ends when the turn starts, when it ends without ever
	 *  starting (stopped or reaped), or when the workspace closes. */
	const waitForStart = () =>
		new Promise<void>((resolve) => {
			const tick = setInterval(async () => {
				if (abort?.signal.aborted) {
					clearInterval(tick);
					resolve();
					return;
				}
				try {
					const fresh = await getCadJob(jobId);
					(fresh.activity ?? []).forEach(record);
					job = fresh;
					if (fresh.status !== 'queued') {
						clearInterval(tick);
						resolve();
					}
				} catch {
					// Leave the last good read standing; the next tick tries again.
				}
			}, 2000);
		});

	const watchJob = async () => {
		abort = new AbortController();
		try {
			const snap = await getCadJob(jobId);
			(snap.activity ?? []).forEach(record);
			job = snap;
			// UX-G: a queued turn has no stream to join — nothing is producing events for
			// it yet — so poll the row until it starts or ends, then carry on as usual.
			if (snap.status === 'queued') {
				await waitForStart();
				if (abort.signal.aborted) return;
			}
			if (job?.status !== 'running') return;
			const final = await streamCadJob(jobId, {
				onActivity: record,
				onStatus: (j) => (job = j),
				signal: abort.signal
			});
			if (final) job = final;
		} catch {
			// The job stream is an optimisation — it carries the phase line while a model
			// is working. Everything durable arrives on the project stream anyway, so a
			// browser that cannot hold this one open loses the spinner's wording and
			// nothing else.
		}
		await load();
	};

	const measureCanvas = () => {
		if (canvasBox) canvasH = Math.max(200, Math.round(canvasBox.clientHeight));
	};

	const clamp = (n: number) => Math.min(MAX_W, Math.max(MIN_W, n));

	// The docked pane, in pixels. There used to be two side columns; the part rail on the
	// right is gone and everything it held now heads the top bar or foots the status bar,
	// so this is the only width left to size. It is measured from the icon rail's right
	// edge, which is why the drag reads `e.clientX - box.left - RAIL_ICON_W`.
	let railW = 300;
	const RAIL_MIN = 200;
	const RAIL_MAX = 560;
	/** The icon rail itself. Fixed: it holds one glyph per row and nothing that wraps. */
	const RAIL_ICON_W = 44;

	/** Drag state for the pane handle; it doubles as the "no drag in progress" flag. */
	let sizing: 'rail' | null = null;
	let rootEl: HTMLDivElement;
	const onSizeDown = (side: 'rail') => (e: PointerEvent) => {
		sizing = side;
		(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
	};
	const onSizeMove = (e: PointerEvent) => {
		if (!sizing || !rootEl) return;
		const box = rootEl.getBoundingClientRect();
		railW = Math.min(
			RAIL_MAX,
			Math.max(RAIL_MIN, Math.round(e.clientX - box.left - RAIL_ICON_W))
		);
	};
	const onSizeUp = (e: PointerEvent) => {
		if (!sizing) return;
		sizing = null;
		try {
			localStorage.cadRailWidth = String(railW);
		} catch {
			/* private mode; the defaults are fine */
		}
		try {
			(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
		} catch {
			/* capture was never granted */
		}
		measureCanvas();
	};

	let dragging = false;
	const onHandleDown = (e: PointerEvent) => {
		if (chatCollapsed) return;
		dragging = true;
		(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
	};
	const onHandleMove = (e: PointerEvent) => {
		if (!dragging) return;
		const host = document.getElementById('chat-container');
		if (!host) return;
		chatWidth = clamp(host.getBoundingClientRect().right - e.clientX);
	};
	const onHandleUp = (e: PointerEvent) => {
		if (!dragging) return;
		dragging = false;
		// Save the width first. Releasing a capture that was never granted throws,
		// and losing the drag the user just finished over that is not a trade worth
		// making.
		try {
			localStorage.cadChatWidth = String(chatWidth);
		} catch {
			/* private mode; the default is fine */
		}
		try {
			(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
		} catch {
			/* no capture to release */
		}
	};

	// Set when the server refuses an accept because the geometry missed the frozen
	// DesignSpec. Overriding that is a person's decision and is never made for them — but
	// it is made HERE. The button used to send the user "to the studio", a surface they
	// were not on and had no link to, which is a dead end dressed up as guidance.
	let acceptOverride = false;
	// The offer belongs to ONE revision. Clicking back through history with it still armed
	// would put "Accept anyway" over a revision the server never refused.
	let overrideArmedFor = '';
	$: if ((current?.id ?? '') !== overrideArmedFor) {
		overrideArmedFor = current?.id ?? '';
		acceptOverride = false;
	}

	const acceptCurrent = async (acknowledge = false) => {
		if (!project || !current || accepting) return;
		accepting = true;
		try {
			await acceptCadRevision(project.id, current.id, acknowledge);
			acceptOverride = false;
			await load();
		} catch (e: any) {
			if (e instanceof CadApiError && e.code === 'conformance_failed' && !acknowledge) {
				acceptOverride = true;
				toast.error(
					$i18n.t('This revision does not match what was asked for. Check Validate before accepting.')
				);
			} else {
				toast.error(e?.message ?? String(e));
			}
		} finally {
			accepting = false;
		}
	};

	/** Reveal the operation that broke a build in the hierarchy tree (UX-E). The tab has
	 *  to change before the row exists, hence the tick. Never a selection: the failed
	 *  operation is not selectable and must not become an edit chip. */
	const revealNode = async (nodeId: string) => {
		explorerTab = 'hierarchy';
		openRail('explorer:hierarchy');
		await tick();
		explorer?.revealNode(nodeId);
	};

	/** Selection → code (CS-6). Same tick dance as `revealNode`: the explorer's Code
	 *  section is not mounted on the Hierarchy tab, so the tab has to change before the
	 *  request has anywhere to land. */
	const openCode = async (nodeId: string) => {
		if (!nodeId) return;
		openRail('explorer:code');
		await tick();
		explorer?.openCode(nodeId);
	};

	/** "Edit selected with Harvis" (CS-7). The composer is not in this component — a
	 *  selection already publishes itself as a chip through the `cadSelection` store, so
	 *  the honest action is to make the selection and put the cursor where the sentence
	 *  gets typed. Nothing is written into the box on the user's behalf. */
	const editSelected = (nodeId: string) => {
		if (nodeId) selectedNodeId = nodeId;
		const box = document.getElementById('chat-input');
		if (box) {
			box.focus();
			return;
		}
		// On the session route there is no composer on this page at all — the conversation
		// that opened the session owns it. The chip has already been published, so going
		// back lands the person in front of a box with the part attached. Without this the
		// button looked live and did nothing, which is worse than not offering it.
		onClose();
	};

	// ------------------------------------------------------------------
	// Move / rotate as a proposal (CS-8)
	//
	// The viewport's drag is a preview and nothing else. It arrives here as a placement —
	// millimetres and degrees in the document's own frame — and this is where it becomes
	// a real revision: a copy of the current CadIR with one `placements` entry merged in,
	// appended to the head and rebuilt by the engine. The operations that built the body
	// are never rewritten, so an author's `at: [wall_t + bore/2, 0, 0]` survives the drag
	// and still moves with the next parameter change.
	//
	// Everything below throws rather than toasting-and-returning. The viewport keeps the
	// preview standing on a rejected promise, so a refusal here costs the user a message,
	// not their drag.
	// ------------------------------------------------------------------
	const FORMATS: CadFormat[] = ['stl', 'step', 'glb', '3mf'];

	/** Whether a drag on this revision could become a revision at all. Three conditions,
	 *  and each one disables the tool honestly rather than letting a drag fail on Apply:
	 *  a recipe-built part has no document to carry placements; an older revision cannot
	 *  be appended to without forking; and a body with no `component` name has nothing for
	 *  a placement to name. */
	$: placeable =
		!!current?.cadir &&
		current.source_kind === 'cadir' &&
		!!project?.head_revision &&
		current.id === project.head_revision;
	$: gizmoNote = !current?.cadir
		? $i18n.t('This part was built from a recipe, so it has no document to place parts in.')
		: current.id !== project?.head_revision
			? $i18n.t('Moving a part needs the newest revision. Restore this one first.')
			: '';

	const proposePlacement = async (p: {
		nodeId: string;
		translate: [number, number, number];
		rotate: [number, number, number];
	}) => {
		if (!project || !current?.cadir) throw new Error($i18n.t('This revision has no document to edit.'));
		const node = (manifest?.nodes ?? []).find((n) => n.node_id === p.nodeId);
		const component = node?.component;
		if (!component) throw new Error($i18n.t('This part has no name for a placement to refer to.'));

		const doc = JSON.parse(JSON.stringify(current.cadir)) as Record<string, any>;
		const existing = (doc.placements ?? []).find((x: any) => x.component === component) ?? null;
		const t1: number[] = existing?.translate ?? [0, 0, 0];
		const r1: number[] = existing?.rotate ?? [0, 0, 0];
		const turnedBefore = r1.some((v) => Math.abs(v) > 1e-6);
		const turnedNow = p.rotate.some((v) => Math.abs(v) > 1e-6);

		// Composing two placements is exact in every case but one. The engine's transform
		// is `translate ∘ rotate-about-the-body's-own-centre`, so composing a second drag
		// (t₂, R₂) on top of (t₁, R₁) gives R = R₂·R₁ and
		// t = t₂ + R₂(t₁ + c₀ − c₁) + c₁ − c₀, where c₀ is the *raw* body's bbox centre and
		// c₁ the placed one. When either rotation is the identity that whole middle term
		// collapses and t = t₁ + t₂ exactly. When both are real rotations it does not, and
		// c₀ is not something the browser can measure — the geometry it has already has
		// the first placement baked in. Refusing is the honest answer; guessing would put
		// the part somewhere neither the preview nor the user asked for.
		if (turnedBefore && turnedNow)
			throw new Error(
				$i18n.t('This part is already rotated. Ask Harvis to turn it instead of dragging it again.')
			);

		const merged = {
			component,
			translate: [0, 1, 2].map((i) => Math.round((t1[i] + p.translate[i]) * 1000) / 1000),
			rotate: turnedNow ? p.rotate : r1
		};
		doc.placements = [
			...(doc.placements ?? []).filter((x: any) => x.component !== component),
			merged
		];

		try {
			const accepted = await createCadRevision(project.id, {
				base_revision_id: current.id,
				document: doc,
				params: current.parameters ?? {},
				formats: FORMATS
			});
			selectedRevisionId = accepted.revision_id;
			await load();
			toast.success($i18n.t('Revision {{seq}} — rebuilding with the new placement.', { seq: accepted.seq }));
		} catch (e: any) {
			if (e instanceof CadApiError && e.status === 409) {
				// Someone else moved the head. Reloading is right, and the preview is now
				// against geometry that no longer exists, so this is a real refusal.
				await load();
				throw new Error($i18n.t('This project changed elsewhere — reloaded it.'));
			}
			throw e;
		}
	};

	const exportArtifact = async (a: CadArtifact) => {
		if (!build) return;
		// Same name the full studio gives it, so a file exported from either surface
		// lands in the download folder under one predictable name.
		const name = `${(project?.title ?? 'part').replace(/[^\w.-]+/g, '_')}-rev${current?.seq ?? 0}.${a.format}`;
		try {
			await downloadCadArtifact(build.id, a, name);
		} catch (e: any) {
			toast.error(e?.message ?? String(e));
		}
	};

	// ------------------------------------------------------------------
	// Renders (UX-3)
	//
	// A render is a picture of the solid at a camera angle, taken from this viewport
	// and stored beside the exports. It is a rendered inspection view and not
	// dimensional proof — the measurements bar above is where a number comes from —
	// and the strip says so rather than leaving it implied.
	//
	// The upload carries the sha256 of the export the viewer loaded, so a render can
	// never quietly end up attached to a different solid: the server refuses any
	// digest that does not match an artifact of that build.
	// ------------------------------------------------------------------
	const PRESETS: { id: CadRenderPreset; label: string }[] = [
		{ id: 'iso', label: 'Iso' },
		{ id: 'front', label: 'Front' },
		{ id: 'rear', label: 'Rear' },
		{ id: 'right', label: 'Side' },
		{ id: 'top', label: 'Top' },
		{ id: 'four_view', label: 'Four-view' }
	];

	const revokeRenderUrls = () => {
		for (const u of Object.values(renderUrls)) URL.revokeObjectURL(u);
		renderUrls = {};
	};

	const loadRenders = async (buildId: string) => {
		if (!buildId) {
			revokeRenderUrls();
			renders = [];
			return;
		}
		try {
			const rows = await getCadRenders(buildId);
			renders = rows;
			renderError = '';
			// Thumbnails need the Authorization header, so each one is fetched and held
			// as an object URL. Only new ids are fetched; the rest are already in hand.
			for (const r of rows) {
				if (renderUrls[r.id]) continue;
				try {
					const u = await fetchCadRenderObjectUrl(buildId, r.id);
					renderUrls = { ...renderUrls, [r.id]: u };
				} catch {
					/* one thumbnail failing is not the strip failing */
				}
			}
		} catch (e: any) {
			renderError = e?.message ?? String(e);
		}
	};

	/** Capture one view and store it. Returns true when a render was actually made —
	 *  a viewport with nothing loaded produces nothing, and saying so is the point. */
	const captureView = async (preset: CadRenderPreset): Promise<boolean> => {
		if (!build || !viewable || build.status !== 'succeeded' || capturing) return false;
		capturing = preset;
		try {
			const blob = await viewer?.capture?.(preset);
			if (!blob) return false;
			await uploadCadRender(build.id, preset, blob, viewable.sha256, `rev ${current?.seq ?? 0}`);
			await loadRenders(build.id);
			renderError = '';
			return true;
		} catch (e: any) {
			renderError = e?.message ?? String(e);
			return false;
		} finally {
			capturing = '';
		}
	};

	/** Capture one server-issued recipe: the beauty pass people see, plus the object-mask
	 *  pass the backend measures and discards.
	 *
	 *  The mask goes up with the picture rather than after it, because the one finding
	 *  that rejects a render — a mask with no body in it at all — has to stop the write.
	 *  A picture of an empty scene is not a render of the part, and storing it and then
	 *  complaining about it would leave the gallery showing the thing being complained
	 *  about. */
	const captureRecipeView = async (recipe: CadRenderRecipe): Promise<boolean> => {
		if (!build || !viewable || build.status !== 'succeeded' || capturing) return false;
		capturing = recipe.recipe_id;
		try {
			const shot = await viewer?.captureRecipe?.({
				view: recipe.view,
				section: recipe.section
					? {
							axis: recipe.section.axis,
							offset: recipe.section.offset,
							flipped: recipe.section.flipped
						}
					: null,
				mask_palette: recipe.mask_palette
			});
			if (!shot?.beauty) return false;
			await uploadCadRender(
				build.id,
				recipe.recipe_id,
				shot.beauty,
				viewable.sha256,
				recipe.label,
				shot.mask
			);
			await loadRenders(build.id);
			renderError = '';
			return true;
		} catch (e: any) {
			renderError = e?.message ?? String(e);
			return false;
		} finally {
			capturing = '';
		}
	};

	/** Fill the strip for a freshly built part, so a build the user watched finish has
	 *  pictures of itself without anyone asking.
	 *
	 *  The server decides which views those are: a build that stated a cavity gets a cut
	 *  view, one with a second body gets a separation view, and one that stated neither
	 *  gets neither rather than a picture arguing about something nobody claimed. A build
	 *  with no named bodies — an STL import, or a build predating the scene manifest —
	 *  gets no recipes at all, and falls back to the camera presets so it still ends up
	 *  with a gallery.
	 *
	 *  Every one of these is corroborating evidence. A build with no pictures records
	 *  nothing and grades exactly as it would have; renders need an open browser, and
	 *  nothing here may be allowed to decide a verdict. */
	const autoCapture = async (buildId: string) => {
		if (autoCaptured[buildId]) return;
		autoCaptured = { ...autoCaptured, [buildId]: true };

		try {
			recipes = await getCadRenderRecipes(buildId);
		} catch {
			// A recipe list we could not fetch is not a build we refuse to photograph.
			recipes = [];
		}
		if (build?.id !== buildId) return;

		const plan: (CadRenderRecipe | CadRenderPreset)[] = recipes.length
			? recipes
			: PRESETS.map((p) => p.id);
		const idOf = (item: CadRenderRecipe | CadRenderPreset) =>
			typeof item === 'string' ? item : item.recipe_id;
		const take = (item: CadRenderRecipe | CadRenderPreset) =>
			typeof item === 'string' ? captureView(item) : captureRecipeView(item);

		// The viewer loads its geometry asynchronously and a capture returns null until
		// it has. Retrying the first view briefly is what makes "after a successful
		// build" true rather than "whenever the fetch happened to be quick".
		let ready = false;
		for (let i = 0; i < 12 && !ready; i++) {
			if (build?.id !== buildId) return;
			ready = await take(plan[0]);
			if (!ready) await new Promise((r) => setTimeout(r, 500));
		}
		if (!ready) return;

		// Each capture restores the camera, the section and the animation loop in its own
		// `finally`, so these run back to back and the viewport ends where the user left
		// it. A view already on file is skipped rather than retaken: a shot someone
		// framed themselves outranks one taken automatically.
		for (const item of plan.slice(1)) {
			if (build?.id !== buildId) return;
			if (renders.some((r) => r.variant === idOf(item))) continue;
			await take(item);
		}
	};

	const onKey = (e: KeyboardEvent) => {
		// Escape dismisses an overlay, which is what it is for. On the standalone route
		// it would navigate away from the page instead — a much larger action for the
		// same keystroke — so there it does nothing and the header button is the way out.
		if (e.key === 'Escape' && !dragging && !sizing && !standalone) onClose();
	};

	onMount(async () => {
		try {
			const saved = Number(localStorage.cadChatWidth);
			if (Number.isFinite(saved) && saved > 0) chatWidth = clamp(saved);
			const savedRail = Number(localStorage.cadRailWidth);
			if (Number.isFinite(savedRail) && savedRail > 0) {
				railW = Math.min(RAIL_MAX, Math.max(RAIL_MIN, savedRail));
			}
			// Merged rather than assigned: a rail item added in a later version would read
			// as `undefined` out of a map saved before it existed, and its icon would come
			// back dark for anyone who had ever opened this workspace.
			const savedOpen = JSON.parse(localStorage.cadRailOpen || 'null');
			if (savedOpen && typeof savedOpen === 'object') railOpen = { ...railOpen, ...savedOpen };
			// The saved section is deliberately NOT restored into `explorerTab`. `tab` means
			// "bring this one forward now" — arriving here after the rail has mounted, a
			// restored value reads as a fresh request and reopens a section the reader had
			// closed. What is in the stack is `cadRailOpen`'s business, above.
		} catch {
			/* default */
		}
		// Fetched once here rather than by the panels, which would refetch on every
		// switch back from Activity. Its absence costs the sliders their bounds and
		// nothing else, so a failure is not worth surfacing.
		getCadCapability()
			.then((c) => (capability = c))
			.catch(() => {});
		await load();
		await tick();
		measureCanvas();
		// The durable stream replaces the old 2.5 s poll entirely. It carries every row
		// this workspace cares about, resumes from a cursor, and costs one open
		// connection rather than a request every two and a half seconds forever.
		runEventStream();
		if (jobId) watchJob();
	});

	/** Written on every change rather than on unload: this workspace is usually left by a
	 *  navigation the page never sees. */
	const persistRail = () => {
		try {
			localStorage.cadRailOpen = JSON.stringify(railOpen);
		} catch {
			/* private mode; the session default is fine */
		}
	};

	/** Put a surface in the stack. Idempotent, so the callers that only need to be sure a
	 *  section is on screen — revealing the operation that broke a build, showing where a
	 *  viewport click landed — do not have to know whether it was already open. */
	const openRail = (key: string) => {
		if (railOpen[key]) return;
		railOpen = { ...railOpen, [key]: true };
		persistRail();
	};

	const selectExplorerTab = (t: CadExplorerTab) => {
		explorerTab = t;
		openRail(`explorer:${t}`);
		try {
			localStorage.cadExplorerTab = t;
		} catch {
			/* private mode; the session default is fine */
		}
	};

	const selectPanel = (t: CadPanelId) => openRail(`panel:${t}`);

	/** A click on the icon rail. It puts that surface in the pane *under* whatever is
	 *  already there, and a second click takes it back out; taking the last one out leaves
	 *  the viewport the whole window. */
	const selectRail = (r: RailItem) => {
		const key = railKey(r);
		if (railOpen[key]) {
			railOpen = { ...railOpen, [key]: false };
			persistRail();
			return;
		}
		if (r.kind === 'explorer') selectExplorerTab(r.target as CadExplorerTab);
		else selectPanel(r.target as CadPanelId);
	};

	/** Picking a revision switches all three panels at once, because all three read the
	 *  same `current`. Clearing the pick hands the choice back to the server's
	 *  `displayed`, so "follow the build" is reachable and is not a reload. */
	const selectRevision = (id: string) => {
		selectedRevisionId = id === selectedRevisionId ? '' : id;
		// A tree node belongs to one revision's manifest. Carrying the selection across
		// would leave a chip naming a node that is not in the tree on screen.
		selectedNodeId = '';
	};

	/** A click in the viewport. The id arrives from the GLB, so it is checked against
	 *  this revision's manifest before it becomes a selection — the viewport must not be
	 *  able to select something the tree renders as unpickable, and a stale GLB node
	 *  from an earlier build would otherwise slip through. */
	const pickNode = (id: string) => {
		if (id && !pickable.has(id)) return;
		selectedNodeId = id;
		if (!id) return;
		// Show the user where the selection landed. Neither of these is persisted: they
		// are a response to this click, not a change to the layout they chose.
		openRail('explorer:hierarchy');
		explorerTab = 'hierarchy';
	};

	onDestroy(() => {
		stopped = true;
		// The chip outlives this component otherwise, and would offer to edit a part
		// nothing on screen is showing.
		cadSelection.set(null);
		abort?.abort();
		streamAbort?.abort();
		clearTimeout(reloadTimer);
		revokeRenderUrls();
	});

	$: if (canvasBox) measureCanvas();
</script>

<svelte:window on:keydown={onKey} on:resize={measureCanvas} />

<!-- The shell, rebuilt to the reference the user asked it to match: a thin bar across
     the top, a thin status line across the bottom, and between them an icon rail, one
     docked pane, and the part.

     This partly reverses the pass that folded both bars into a single right-hand column.
     The reason that pass gave still holds — twelve controls in one h-11 row, with the
     facts that qualify them at the far edge of the screen, was unreadable — but the fix
     was the crowding, not the bars. These two are one row each and carry nothing that
     scrolls: identity and the actions on the part along the top, the measurements along
     the bottom. The column between them is now a rail of icons rather than a stack of
     six labelled sections, so one surface at a time gets the whole height instead of
     six sharing it.

     Design activity is still not here. It is drawn by the card in the conversation,
     directly under the request that started it; see `CadResultCard.svelte`. -->
<div
	bind:this={rootEl}
	class="{standalone
		? 'relative w-full h-full'
		: 'absolute inset-y-0 left-0 z-30'} flex flex-col bg-gray-50 dark:bg-gray-900"
	style={standalone ? '' : `right:${chatCollapsed ? 0 : chatWidth}px`}
	aria-label={$i18n.t('CAD workspace')}
>
	<!-- Top bar. Which part, which revision, what state it is in — then, past the gap,
	     what is happening to it and what can be done about it. -->
	<div
		class="shrink-0 h-11 flex items-center gap-2 px-2 border-b border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-900"
	>
		<button
			class="shrink-0 flex items-center gap-1 text-[11px] px-1.5 py-1 rounded-md text-gray-500 hover:text-gray-900 dark:hover:text-gray-100 hover:bg-gray-100 dark:hover:bg-gray-850 transition"
			on:click={onClose}
			title={$i18n.t('Close and return to the conversation')}
		>
			<ArrowLeft className="size-3.5" />
			<span class="max-w-[9rem] truncate">{closeLabel || $i18n.t('Close')}</span>
		</button>

		<span class="shrink-0 w-px h-5 bg-gray-100 dark:bg-gray-850"></span>

		<span class="min-w-0 truncate text-sm font-medium text-gray-800 dark:text-gray-100">
			{project?.title || job?.title || $i18n.t('Untitled part')}
		</span>

		{#if current}
			<span class="shrink-0 text-[11px] text-gray-400 tabular-nums">rev {current.seq}</span>
			<!-- Proposal vs accepted, not a synonym for pass vs fail. A model's revision lands
			     as a proposal whatever its grade, and stays one until a person says otherwise. -->
			<span
				class="shrink-0 text-[10px] px-1.5 py-0.5 rounded-md {current.state === 'accepted'
					? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
					: 'bg-amber-500/10 text-amber-600 dark:text-amber-400'}"
			>
				{current.state === 'accepted' ? $i18n.t('Accepted') : $i18n.t('Proposal')}
			</span>
		{/if}
		{#if conformance}
			<span
				class="shrink-0 text-[10px] px-1.5 py-0.5 rounded-md {conformance.status === 'passed'
					? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
					: conformance.status === 'failed'
						? 'bg-red-500/10 text-red-600 dark:text-red-400'
						: 'bg-gray-500/10 text-gray-500 dark:text-gray-400'}"
				title={conformance.summary}
			>
				{conformance.status === 'passed'
					? $i18n.t('Matches the request')
					: conformance.status === 'failed'
						? $i18n.t("Doesn't match the request")
						: (conformance.counts?.passed ?? 0) + (conformance.counts?.unverified ?? 0) === 0
							? $i18n.t('Nothing checkable was stated')
							: (conformance.counts?.passed ?? 0) > 0
								? $i18n.t('Partly checked')
								: $i18n.t('Could not be checked')}
			</span>
		{/if}
		{#if modelBadge}
			<span
				class="shrink-0 text-[10px] px-1.5 py-0.5 rounded-md bg-gray-100 dark:bg-gray-850 text-gray-500 dark:text-gray-400 max-w-[10rem] truncate"
				>{modelBadge}</span
			>
		{/if}

		<div class="flex-1 min-w-0"></div>

		{#if jobRunning}
			<span
				class="shrink-0 flex items-center gap-1.5 text-[11px] text-gray-500"
				title={jobWaiting
					? $i18n.t(
							'It starts on its own when the turn ahead of it ends. Stopping that one starts this one immediately.'
						)
					: ''}
			>
				<!-- No spinner while waiting: nothing is running yet, and a spinner on a turn
				     that has not begun claims work that is not happening. -->
				{#if !jobWaiting}<Spinner className="size-3" />{/if}
				<span class="max-w-[12rem] truncate">{phaseLabel()}</span>
			</span>
			<button
				class="shrink-0 text-[11px] px-2 py-0.5 rounded-md border border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-850 disabled:opacity-50"
				disabled={cancelling}
				on:click={stopJob}
			>
				{cancelling ? $i18n.t('Stopping…') : $i18n.t('Stop')}
			</button>
		{/if}

		{#if current?.state === 'proposal' && build?.status === 'succeeded'}
			{#if acceptOverride}
				<!-- Two clicks, not one, and the second says what it overrides. The server refused
				     this accept because the part missed the frozen DesignSpec; the override is the
				     user's to make, and it is made here rather than by sending them to a surface
				     they are not on. -->
				<button
					class="shrink-0 text-[11px] px-2 py-0.5 rounded-lg border border-amber-500/50 text-amber-600 dark:text-amber-400 hover:bg-amber-500/10 transition disabled:opacity-50"
					disabled={accepting || panelsBusy}
					on:click={() => acceptCurrent(true)}
					title={$i18n.t(
						'The geometry built, but it does not match the request. Accepting makes it the head revision anyway.'
					)}
				>
					{$i18n.t('Accept anyway')}
				</button>
				<button
					class="shrink-0 text-[11px] px-2 py-0.5 rounded-lg text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 transition"
					on:click={() => {
						acceptOverride = false;
						selectPanel('validate');
					}}
				>
					{$i18n.t('See what failed')}
				</button>
			{:else}
				<button
					class="shrink-0 text-[11px] px-2 py-0.5 rounded-lg border border-emerald-500/40 text-emerald-600 dark:text-emerald-400 hover:bg-emerald-500/10 transition disabled:opacity-50"
					disabled={accepting || panelsBusy}
					on:click={() => acceptCurrent(false)}
				>
					{$i18n.t('Accept')}
				</button>
			{/if}
		{/if}

		<!-- One button per artifact, because a single "Export" that opens a menu hides which
		     formats this build actually produced. -->
		{#each artifacts as a (a.id)}
			<button
				class="shrink-0 text-[11px] px-2 py-0.5 rounded-lg border border-gray-100 dark:border-gray-850 text-gray-600 dark:text-gray-300 hover:border-emerald-500/40 hover:bg-emerald-500/5 transition"
				on:click={() => exportArtifact(a)}
			>
				{a.format.toUpperCase()}
			</button>
		{/each}
	</div>

	{#if cancelNote}
		<div
			class="shrink-0 px-3 py-1 border-b border-gray-100 dark:border-gray-850 text-[11px] text-amber-600 dark:text-amber-400"
		>
			{cancelNote}
		</div>
	{/if}

	<div class="flex-1 min-h-0 flex">
		<!-- The icon rail. Six explorer sections and four editing panels used to be two
		     separate strips at opposite edges of the screen, one a stack of collapsible
		     headers and one a row of tabs. They are one list here, grouped by what they are
		     for, and each icon puts its surface into the pane beside it, under whatever is
		     already there. Pressing a lit icon takes that surface back out; taking the last
		     one out gives the part the whole window. -->
		<nav
			class="shrink-0 flex flex-col items-center gap-0.5 py-2 border-r border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-900"
			style="width:{RAIL_ICON_W}px"
			aria-label={$i18n.t('Workspace sections')}
		>
			{#each railItems as r, i (r.kind + ':' + r.target)}
				{@const on = !!railOpen[r.kind + ':' + r.target]}
				{#if i > 0 && r.group !== railItems[i - 1].group}
					<span class="my-1 w-5 h-px bg-gray-100 dark:bg-gray-850"></span>
				{/if}
				<button
					class="size-8 shrink-0 flex items-center justify-center rounded-lg transition {on
						? 'bg-gray-900 text-white dark:bg-white dark:text-gray-900'
						: 'text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-850'}"
					aria-pressed={on}
					aria-label={$i18n.t(r.label)}
					title={$i18n.t(r.label)}
					on:click={() => selectRail(r)}
				>
					<svelte:component this={r.icon} className="size-4" />
				</button>
			{/each}
		</nav>

		{#if paneOpen}
			<aside
				class="shrink-0 flex flex-col border-r border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-900"
				style="width:{railW}px"
				aria-label={$i18n.t('Workspace panel')}
			>
				<!-- The explorer stays mounted even with none of its sections in the stack. Its
				     Code section owns the single revision fetch that its Parameters and Project
				     Files sections are drawn from, so tearing it down to show a panel would leave
				     two other sections loading forever the next time they were opened. -->
				<div class="flex-1 min-h-0" class:hidden={!explorerShown}>
					<CadExplorer
						bind:this={explorer}
						openOverride={explorerOpen}
						onRequestOpen={(id) => openRail(`explorer:${id}`)}
						tab={explorerTab}
						onSelectTab={selectExplorerTab}
						{manifest}
						{capabilities}
						{selectedNodeId}
						onSelectNode={(id) => (selectedNodeId = id)}
						projectTitle={project?.title ?? ''}
						{artifacts}
						{renders}
						{renderUrls}
						onExport={exportArtifact}
						{revisions}
						selectedRevisionId={current?.id ?? ''}
						onSelectRevision={selectRevision}
						headRevisionId={project?.head_revision ?? ''}
						displayedRevisionId={ws?.displayed?.revision_id ?? ''}
						projectId={project?.id ?? ''}
						onRevealNode={revealNode}
					/>
				</div>

				<!-- One block per panel the rail has put in the stack, below the explorer's own
				     sections, so pressing Parameters while the feature tree is open leaves both on
				     screen. Each carries its own heading because a stack of unlabelled surfaces
				     gives a reader no way to tell which icon produced which. -->
				{#each openPanels as [id, label] (id)}
					<div
						class="flex-1 min-h-0 flex flex-col border-t border-gray-100 dark:border-gray-850"
					>
						<h3
							class="shrink-0 px-3 pt-2 pb-1 text-[10px] uppercase tracking-wider text-gray-400 dark:text-gray-500"
						>
							{$i18n.t(label)}
						</h3>
						<div class="flex-1 min-h-0 overflow-y-auto scrollbar-hidden px-3 pb-2">
							<CadContextPanels
								tab={id}
								{project}
								{capability}
								selectedRevisionId={current?.id ?? ''}
								onSelectRevision={selectRevision}
								onChanged={load}
								bind:busy={panelBusy[id]}
								showStatusLine={false}
								onRevealNode={revealNode}
							/>
						</div>
					</div>
				{/each}
			</aside>

			<!-- Drawn in both modes now. There is one pane left to size, so this handle can no
			     longer be confused with the one that sizes the conversation. -->
			<div
				class="w-1 shrink-0 cursor-col-resize bg-transparent hover:bg-emerald-500/40 transition"
				role="separator"
				aria-label={$i18n.t('Resize the panel')}
				on:pointerdown={onSizeDown('rail')}
				on:pointermove={onSizeMove}
				on:pointerup={onSizeUp}
				on:pointercancel={onSizeUp}
			></div>
		{/if}

		<!-- The viewport column. The strip of capture buttons that used to sit under it is
		     gone: all six views are taken automatically the moment a build succeeds, so the
		     strip was a row of buttons for work already done, and it cost the part 64px of
		     the window it is the whole point of. -->
		<div class="flex-1 min-w-0 min-h-0 flex flex-col">
			<!-- The revision rail that used to sit here is gone: the explorer's History section
			     is the same list with the build status and the conformance grade attached, and
			     two revision pickers on one screen would eventually disagree about the
			     selection. One line survives it — the reminder that the viewport is following
			     the server while nothing is picked, which is the state a rail could not
			     express. -->
			{#if selectedRevisionId && ws?.displayed && selectedRevisionId !== ws.displayed.revision_id}
				<div
					class="shrink-0 flex items-center gap-2 px-3 py-1 border-b border-gray-100 dark:border-gray-850 bg-amber-500/5 text-[10px] text-amber-700 dark:text-amber-400"
				>
					<span
						>{$i18n.t('Looking at an earlier revision. New builds will not change this view.')}</span
					>
					<button
						class="underline underline-offset-2 hover:text-amber-900 dark:hover:text-amber-200"
						on:click={() => selectRevision(selectedRevisionId)}
					>
						{$i18n.t('Follow the latest build')}
					</button>
				</div>
			{/if}

			<div bind:this={canvasBox} class="flex-1 min-w-0 min-h-0 relative p-3">
				{#if loadError}
					<div class="absolute inset-0 flex items-center justify-center px-8 text-center">
						<span class="text-xs text-red-500">{loadError}</span>
					</div>
				{:else if viewUrl}
					<CadViewer
						bind:this={viewer}
						url={viewUrl}
						format={viewable?.format === 'stl' ? 'stl' : 'glb'}
						height={canvasH - 24}
						{selectedNodeId}
						{nodeColors}
						onPick={viewable?.format === 'stl' ? null : pickNode}
						toolbar={true}
						bboxMm={validation?.bbox_mm ?? null}
						onSnapshot={build?.status === 'succeeded' && !capturing ? () => captureView('iso') : null}
						onEditSelected={editSelected}
						onPropose={placeable ? proposePlacement : null}
						{gizmoNote}
					/>
				{:else}
					<div
						class="absolute inset-0 flex flex-col items-center justify-center gap-2 text-xs text-gray-500 dark:text-gray-400"
					>
						{#if jobRunning || building}
							<!-- DE-8e: the requirement, drawn, instead of a spinner over nothing.
							     It is the server's own reading of the request — the same one
							     conformance grades the finished part against — so a misread is
							     visible now rather than after the build. -->
							<CadConceptSketch
								stated={conceptSpec.stated}
								unknowns={conceptSpec.unknowns}
								units={conceptSpec.units}
							/>
							<div class="flex items-center gap-2">
								<Spinner className="size-3.5" />
								<span>{building ? $i18n.t('Building the geometry…') : phaseLabel()}</span>
							</div>
						{:else if build?.status === 'failed'}
							<span class="text-red-500">
								{build.error_detail || $i18n.t('The build failed.')}
							</span>
						{:else if build?.status === 'cancelled'}
							<span>{$i18n.t('This build was cancelled.')}</span>
						{:else}
							<span>{$i18n.t('No geometry for this revision yet.')}</span>
						{/if}
					</div>
				{/if}
			</div>
		</div>
	</div>

	<!-- The status line. Still separate facts, deliberately not folded into one another: a
	     solid can be well-formed and still not be the part that was asked for, and a
	     selection the engine cannot make is not the same as nothing being selected. -->
	<div
		class="shrink-0 h-7 flex items-center gap-3 px-3 border-t border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-900 text-[10px] text-gray-500 dark:text-gray-400 tabular-nums overflow-x-auto scrollbar-hidden whitespace-nowrap"
	>
		<span>{$i18n.t('Units')}: {capabilities?.units ?? 'mm'}</span>

		<!-- What can be picked is the server's answer, not this component's opinion: the
		     naming spike could not carry a stable feature id through a boolean, and the
		     engine is where that stays recorded. -->
		<span title={capabilities?.selection_reason ?? ''}>
			{$i18n.t('Selection')}: {capabilities?.select_faces
				? $i18n.t('faces')
				: capabilities?.select_bodies
					? $i18n.t('whole body')
					: $i18n.t('none')}
		</span>

		<span>
			{$i18n.t('Geometry')}:
			{#if validation?.brep_valid === true}
				<span class="text-emerald-600 dark:text-emerald-400">{$i18n.t('B-Rep valid')}</span>
			{:else if validation?.brep_valid === false}
				<span class="text-amber-600">{$i18n.t('B-Rep not valid')}</span>
			{:else}
				{$i18n.t('not checked')}
			{/if}
		</span>

		<span>
			{$i18n.t('Conformance')}:
			{#if conformance?.status === 'passed'}
				<span class="text-emerald-600 dark:text-emerald-400">{$i18n.t('passed')}</span>
			{:else if conformance?.status === 'failed'}
				<span class="text-red-600 dark:text-red-400">{$i18n.t('failed')}</span>
			{:else}
				{$i18n.t('unverified')}
			{/if}
		</span>

		{#if validation?.bbox_mm}
			<span>
				{$i18n.t('Size')}: {Number(validation.bbox_mm.x).toFixed(1)} × {Number(
					validation.bbox_mm.y
				).toFixed(1)} × {Number(validation.bbox_mm.z).toFixed(1)} mm
			</span>
		{/if}

		<div class="flex-1 min-w-0"></div>

		{#if capturing}
			<span>{$i18n.t('Capturing a view…')}</span>
		{:else if renderError}
			<span class="text-red-500 max-w-[20rem] truncate" title={renderError}>{renderError}</span>
		{/if}

		{#if selectedNode}
			<!-- The label is the manifest's, never one this component composed: what the user
			     reads here has to be the same string the server will rehydrate when the
			     selection is sent with a message. -->
			<span class="flex items-center gap-1.5 text-emerald-700 dark:text-emerald-400">
				<span class="max-w-[14rem] truncate">{$i18n.t('Selected')}: {selectedNode.label}</span>
				<button
					class="shrink-0 opacity-70 hover:opacity-100 underline underline-offset-2"
					on:click={() => openCode(selectedNodeId)}
					title={$i18n.t('Open the operations that build this part')}>{$i18n.t('code')}</button
				>
				<button
					class="shrink-0 opacity-70 hover:opacity-100 underline underline-offset-2"
					on:click={() => (selectedNodeId = '')}
					title={$i18n.t('Clear selection')}>{$i18n.t('clear')}</button
				>
			</span>
		{/if}
	</div>

	<!-- Divider between the workspace and the conversation. Drag to resize, double-click
	     or the chevron to collapse the strip out of the way. Standalone has no
	     conversation strip beside it to size, so a handle here would drag a width nothing
	     reads. -->
	{#if !standalone}
		<div
			class="absolute top-0 bottom-0 -right-1.5 w-3 z-40 flex items-center justify-center group {chatCollapsed
				? 'cursor-pointer'
				: 'cursor-col-resize'}"
			role="separator"
			aria-label={$i18n.t('Resize the conversation panel')}
			on:pointerdown={onHandleDown}
			on:pointermove={onHandleMove}
			on:pointerup={onHandleUp}
			on:pointercancel={onHandleUp}
			on:dblclick={() => (chatCollapsed = !chatCollapsed)}
		>
			<div
				class="w-px h-full bg-gray-100 dark:bg-gray-850 group-hover:bg-emerald-500/40 transition"
			></div>
			<button
				class="absolute top-1/2 -translate-y-1/2 size-5 rounded-full border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-850 text-gray-400 hover:text-emerald-500 text-[10px] leading-none opacity-0 group-hover:opacity-100 transition"
				on:click|stopPropagation={() => (chatCollapsed = !chatCollapsed)}
				title={chatCollapsed ? $i18n.t('Show the conversation') : $i18n.t('Hide the conversation')}
			>
				{chatCollapsed ? '‹' : '›'}
			</button>
		</div>
	{/if}
</div>
