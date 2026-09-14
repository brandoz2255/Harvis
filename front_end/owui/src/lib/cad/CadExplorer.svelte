<script context="module" lang="ts">
	export type CadExplorerTab =
		| 'hierarchy'
		| 'parameters'
		| 'code'
		| 'files'
		| 'history'
		| 'project';

	/** The rail's sections, in the order the design environment spec lists them: feature
	 *  tree, parameters, code, project files. History and Renders follow, because they
	 *  live nowhere else — UX-C moved them here, and dropping them to honour a list of
	 *  four would delete two working surfaces to satisfy an ordering.
	 *
	 *  `hierarchy` and `project` keep their internal ids while reading as their spec
	 *  names: a host has already persisted these ids in a session's view state, and
	 *  renaming them would reset every saved rail for nothing the user can see. */
	export const CAD_EXPLORER_TABS: [CadExplorerTab, string][] = [
		['hierarchy', 'Feature Tree'],
		['parameters', 'Parameters'],
		['code', 'Code'],
		['files', 'Project Files'],
		['history', 'History'],
		['project', 'Renders and Exports']
	];

	export const isCadExplorerTab = (v: unknown): v is CadExplorerTab =>
		typeof v === 'string' && CAD_EXPLORER_TABS.some(([id]) => id === v);
</script>

<script lang="ts">
	// The left rail of the CAD workspace — stacked, collapsible, drag-resizable sections
	// over one revision (DE-5).
	//
	// It used to be a tab strip, which meant the parameters, the code and the tree could
	// never be read against each other: seeing where a dimension is used cost two clicks
	// and a lost place. Sections stack instead, each with its own scroll and its own
	// share of the column, and both the open/closed state and the shares persist.
	//
	// Every section is a projection of ONE revision fetch. `CadCodeView` owns that fetch
	// and hands the tree up through `onTree`; Parameters and Project Files draw from the
	// same object. Two fetches could return two revisions' worth of the same design, and
	// then the panel that is supposed to prove the source is single would be the thing
	// disproving it.
	//
	// It is a reader — it selects, it does not edit. Validation and compare stay in the
	// context panels on the right, because those change the part and this column has to
	// stay trustworthy while a build is running.
	//
	// Everything the tree shows comes from the engine's own scene manifest. Nothing here
	// is reconstructed from GLB triangles, and no node is invented: a build that produced
	// no manifest shows no tree, which is the honest answer rather than a fabricated one.
	import { getContext, onDestroy, onMount, tick } from 'svelte';

	import CadCodeView from './CadCodeView.svelte';
	import CadParametersPanel from './CadParametersPanel.svelte';
	import type {
		CadArtifact,
		CadFileTree,
		CadRender,
		CadRevision,
		CadSceneManifest,
		CadSceneNode,
		CadWorkspaceCapabilities
	} from '$lib/apis/cad';

	const i18n: any = getContext('i18n');

	/** The section the host wants brought forward. It no longer hides the others — it
	 *  opens this one, which is what "show me the code for that body" has to mean once
	 *  every section is on screen at once. */
	export let tab: CadExplorerTab = 'hierarchy';
	export let onSelectTab: (t: CadExplorerTab) => void = () => {};

	/** Which sections are open, when something outside this component decides that.
	 *
	 *  The studio's icon rail is that something: pressing an icon adds its section to the
	 *  stack and pressing it again takes it out, so the same accordion is driven from a
	 *  column of glyphs instead of six headers competing for one narrow column. The
	 *  sections still stack and still share the height by weight — only the control moved.
	 *
	 *  Null means this component owns its own open state, which is what every other host
	 *  wants. A section that is closed stays MOUNTED and hidden rather than torn down:
	 *  `code` owns the one revision fetch that Parameters and Project Files are drawn
	 *  from, so unmounting it would leave those two loading forever. */
	export let openOverride: Partial<Record<CadExplorerTab, boolean>> | null = null;
	/** Called instead of opening a section directly, when the host owns that state. */
	export let onRequestOpen: ((id: CadExplorerTab) => void) | null = null;
	$: railDriven = openOverride !== null;

	/** The tree of the revision currently on screen. Null when that revision has no
	 *  build, or when its build predates the manifest column. */
	export let manifest: CadSceneManifest | null = null;
	/** What this workspace can actually select, decided by the server. The explorer
	 *  gates its rows on this rather than on its own opinion of what a body is. */
	export let capabilities: CadWorkspaceCapabilities | null = null;
	export let selectedNodeId = '';
	export let onSelectNode: (id: string, node: CadSceneNode) => void = () => {};

	/** Names the export files, and titles the parameter tree. */
	export let projectTitle = '';

	/** The project the source sections read from. Empty until the host has one, and
	 *  CadCodeView draws nothing rather than guessing. */
	export let projectId = '';
	/** Point the viewport at the body a part file builds. Null on a host with no scene
	 *  to point at, and the offer is then not made. */
	export let onRevealNode: ((nodeId: string) => void) | null = null;

	/** The open file, held here rather than inside CadCodeView so it survives a section
	 *  being collapsed and reopened. */
	let openFile = '';

	/** A body whose code has been asked for but not yet shown (CS-6). Holding the request
	 *  here and clearing it on arrival is what keeps a file the user opened by hand from
	 *  being replaced every time the section comes back. */
	let pendingCodeNode = '';
	// Selection is the request. Assigning inside a reactive block that only reads
	// `selectedNodeId` means a re-selection of the same body does not re-fire, which is
	// correct: the file is already open.
	$: pendingCodeNode = selectedNodeId;

	export let artifacts: CadArtifact[] = [];
	export let renders: CadRender[] = [];
	/** Object URLs for the render thumbnails, keyed by artifact id. Fetched by the host
	 *  because they need the Authorization header. */
	export let renderUrls: Record<string, string> = {};
	export let onExport: (a: CadArtifact) => void = () => {};

	export let revisions: CadRevision[] = [];
	export let selectedRevisionId = '';
	export let onSelectRevision: (id: string) => void = () => {};
	/** The accepted revision, so History can mark it. Distinct from whichever revision
	 *  is being looked at. */
	export let headRevisionId = '';
	/** The revision the server says should be on screen. Marked so a user who has
	 *  clicked back through history can see where "live" is. */
	export let displayedRevisionId = '';

	let collapsed: Record<string, boolean> = {};

	$: nodes = manifest?.nodes ?? [];
	$: byId = Object.fromEntries(nodes.map((n) => [n.node_id, n]));

	// --- Sections: open state and vertical shares -----------------------------------
	// Three open by default — the tree, the parameters and the code — because those are
	// the three the environment is for. Files, History and Renders open on a click and
	// stay open once chosen.
	let open: Record<CadExplorerTab, boolean> = {
		hierarchy: true,
		parameters: true,
		code: true,
		files: false,
		history: false,
		project: false
	};
	/** `flex-grow` per open section. Relative, not pixels: the rail is resizable and a
	 *  saved pixel height would be wrong on the next window. */
	let weight: Record<CadExplorerTab, number> = {
		hierarchy: 1.1,
		parameters: 1.2,
		code: 1.4,
		files: 0.8,
		history: 1,
		project: 1
	};

	const persistLayout = () => {
		try {
			localStorage.cadExplorerOpen = JSON.stringify(open);
			localStorage.cadExplorerWeights = JSON.stringify(weight);
		} catch {
			/* private mode; the session default is fine */
		}
	};

	onMount(() => {
		try {
			const savedOpen = JSON.parse(localStorage.cadExplorerOpen ?? 'null');
			if (savedOpen && typeof savedOpen === 'object') {
				// Merged rather than assigned: a rail saved before a section existed would
				// otherwise come back with that section undefined, which renders as closed
				// with no header a user could click to find it.
				for (const [id] of CAD_EXPLORER_TABS)
					if (typeof savedOpen[id] === 'boolean') open[id] = savedOpen[id];
				open = { ...open };
			}
			const savedW = JSON.parse(localStorage.cadExplorerWeights ?? 'null');
			if (savedW && typeof savedW === 'object') {
				for (const [id] of CAD_EXPLORER_TABS) {
					const v = Number(savedW[id]);
					if (Number.isFinite(v) && v > 0.05 && v < 20) weight[id] = v;
				}
				weight = { ...weight };
			}
		} catch {
			/* defaults */
		}
		// The saved layout wins over the saved `tab`, and there is deliberately no
		// force-open here: `tab` only records where the rail was last brought forward,
		// which says nothing about whether the reader then closed it. Re-asserting it
		// would make one section impossible to keep shut across a reload.
		applied = isCadExplorerTab(tab) ? tab : '';
	});

	const toggleSection = (id: CadExplorerTab) => {
		open = { ...open, [id]: !open[id] };
		persistLayout();
		// Only an opening is reported: `tab` is "the section to bring forward", and
		// closing one does not nominate another.
		if (open[id]) onSelectTab(id);
	};

	const show = (id: CadExplorerTab) => {
		if (railDriven) {
			// The host's rail is the authority; opening it here would be overwritten on the
			// next tick and the section would flicker open and shut.
			onRequestOpen?.(id);
			onSelectTab(id);
			return;
		}
		if (!open[id]) {
			open = { ...open, [id]: true };
			persistLayout();
		}
		onSelectTab(id);
	};

	// The host still drives the rail through `tab`. Opening rather than switching, so a
	// request to look at the code does not hide the tree the request came from.
	//
	// Guarded on the value having *changed*: without `applied`, the block re-runs whenever
	// `open` does, and collapsing the section the host last nominated reopened it on the
	// same tick — the one section in the rail that could not be closed.
	let applied: CadExplorerTab | '' = '';
	$: if (isCadExplorerTab(tab) && tab !== applied) {
		applied = tab;
		if (!railDriven && !open[tab]) open = { ...open, [tab]: true };
	}

	// Derived from what is on screen, not from the internal map, so the drag grips sit
	// between the sections a reader can actually see in either mode.
	$: openIds = CAD_EXPLORER_TABS.map(([id]) => id).filter((id) => shown[id]);
	const nextOpen = (id: CadExplorerTab): CadExplorerTab | null => {
		const i = openIds.indexOf(id);
		return i >= 0 && i < openIds.length - 1 ? openIds[i + 1] : null;
	};

	// --- Dragging the divider between two open sections -----------------------------
	// Weights are recomputed from the two sections' measured heights, so a drag moves the
	// boundary by exactly the pointer's travel however many other sections are open.
	let secEls: Record<string, HTMLElement | null> = {};
	const MIN_SECTION_PX = 56;
	let drag: {
		a: CadExplorerTab;
		b: CadExplorerTab;
		y: number;
		ha: number;
		hb: number;
		wa: number;
		wb: number;
	} | null = null;

	const gripMove = (e: PointerEvent) => {
		if (!drag) return;
		const total = drag.ha + drag.hb;
		if (total < MIN_SECTION_PX * 2) return;
		const ha = Math.min(
			total - MIN_SECTION_PX,
			Math.max(MIN_SECTION_PX, drag.ha + (e.clientY - drag.y))
		);
		const sum = drag.wa + drag.wb;
		weight = {
			...weight,
			[drag.a]: (sum * ha) / total,
			[drag.b]: (sum * (total - ha)) / total
		};
	};

	const gripUp = () => {
		window.removeEventListener('pointermove', gripMove);
		window.removeEventListener('pointerup', gripUp);
		window.removeEventListener('pointercancel', gripUp);
		if (!drag) return;
		drag = null;
		persistLayout();
	};
	onDestroy(gripUp);

	// The move and up listeners go on the window rather than staying on the handle with
	// `setPointerCapture`: the pointer leaves a 4px strip on the first frame of any real
	// drag, and capture is the only thing that would keep the events coming — one that
	// silently does nothing when the pointer id is synthetic. The window always hears them.
	const gripDown = (a: CadExplorerTab) => (e: PointerEvent) => {
		const b = nextOpen(a);
		const ea = secEls[a];
		const eb = b ? secEls[b] : null;
		if (!b || !ea || !eb) return;
		e.preventDefault(); // otherwise the drag selects the text it passes over
		drag = {
			a,
			b,
			y: e.clientY,
			ha: ea.getBoundingClientRect().height,
			hb: eb.getBoundingClientRect().height,
			wa: weight[a],
			wb: weight[b]
		};
		window.addEventListener('pointermove', gripMove);
		window.addEventListener('pointerup', gripUp);
		window.addEventListener('pointercancel', gripUp);
	};

	// --- The one source read ---------------------------------------------------------
	/** The revision's files and parameter graph, as CadCodeView fetched them. Cleared the
	 *  moment the revision changes, so Parameters never describes a design the viewport
	 *  has already replaced. */
	let fileTree: CadFileTree | null = null;
	$: if (fileTree && selectedRevisionId && fileTree.revision_id !== selectedRevisionId) {
		fileTree = null;
	}
	$: sourceGraph = fileTree?.source_graph ?? null;
	/** The backend's own sentence about a missing graph, when it sent one. */
	$: graphNote = sourceGraph ? '' : (fileTree?.notes ?? []).join(' ');

	let selectedParam = '';
	// A parameter belongs to one revision's graph. Carrying the name across would leave a
	// highlight pointing at a line number from a different document.
	$: if (!sourceGraph?.parameters.some((p) => p.name === selectedParam)) selectedParam = '';
	$: param = sourceGraph?.parameters.find((p) => p.name === selectedParam) ?? null;

	/** The lines that declare the selected parameter, for the code section's marks. */
	$: codeHighlight = (
		param?.defined_in.line
			? [param.defined_in.line, param.defined_in.line_end ?? param.defined_in.line]
			: null
	) as [number, number] | null;

	/** The operations that read the selected parameter, so the tree can mark them. The
	 *  graph's `op_id` and the manifest's `cadir_operation_id` are the same id — that is
	 *  what makes "features that use it" a highlight rather than a list. */
	$: consumerOps = new Set(
		(param?.used_by ?? []).map((u) => u.op_id).filter((x): x is string => !!x)
	);

	const pickParam = (name: string) => {
		selectedParam = name;
		if (!name) return;
		const p = sourceGraph?.parameters.find((x) => x.name === name);
		if (p?.defined_in.path) openFile = p.defined_in.path;
		show('code');
	};

	/** The accepted revision's input values, read from the document it already carries.
	 *  Only the head is consulted, and only when the revision on screen is not it: a
	 *  proposal is the only thing there is a "was" for. Derived values are left out — the
	 *  panel does not evaluate formulas, and a re-evaluated one could disagree with the
	 *  engine that built the part. */
	const inputsOf = (r: CadRevision | undefined): Record<string, number> | null => {
		if (!r) return null;
		const out: Record<string, number> = {};
		for (const p of (r.cadir?.parameters ?? []) as any[]) {
			if (typeof p?.name === 'string' && typeof p?.value === 'number') out[p.name] = p.value;
		}
		// The revision's own overrides win: they are what the build was actually given.
		for (const [k, v] of Object.entries(r.parameters ?? {})) {
			if (typeof v === 'number') out[k] = v;
		}
		return Object.keys(out).length ? out : null;
	};
	$: acceptedValues =
		headRevisionId && selectedRevisionId && headRevisionId !== selectedRevisionId
			? inputsOf(revisions.find((r) => r.id === headRevisionId))
			: null;

	/** Depth-first order with a depth per row, computed once per manifest.
	 *
	 *  A flat list rather than a recursive component: the tree is small, and flattening
	 *  keeps collapse, keyboard order and the selected-row highlight in one place instead
	 *  of spread across a component that mounts itself. */
	const flatten = (m: CadSceneManifest | null, hidden: Record<string, boolean>) => {
		if (!m) return [] as { node: CadSceneNode; depth: number; kids: number }[];
		const kids: Record<string, CadSceneNode[]> = {};
		for (const n of m.nodes) {
			const p = n.parent_id ?? '';
			(kids[p] ??= []).push(n);
		}
		const out: { node: CadSceneNode; depth: number; kids: number }[] = [];
		const seen = new Set<string>();
		const walk = (id: string, depth: number) => {
			const n = m.nodes.find((x) => x.node_id === id);
			if (!n || seen.has(id)) return; // a cycle would otherwise hang the panel
			seen.add(id);
			const children = kids[id] ?? [];
			out.push({ node: n, depth, kids: children.length });
			if (hidden[id]) return;
			for (const c of children) walk(c.node_id, depth + 1);
		};
		walk(m.root_id, 0);
		// Anything the root could not reach still gets shown, at the top level. A node
		// that is missing from the tree is a bug worth seeing, not one worth hiding.
		for (const n of m.nodes) if (!seen.has(n.node_id)) walk(n.node_id, 0);
		return out;
	};

	$: rows = flatten(manifest, collapsed);

	$: selectedSeq = revisions.find((r) => r.id === selectedRevisionId)?.seq ?? 0;

	/** The name the download will land under, built by the same recipe the panels use.
	 *  The row used to print `a.media_type` — `model/gltf-binary` next to a GLB badge that
	 *  already said the format, which told the user nothing they could not see. */
	const fileNameOf = (a: CadArtifact) =>
		`${(projectTitle || 'part').replace(/[^\w.-]+/g, '_')}-rev${selectedSeq}.${a.format}`;

	/** A row can be clicked only when the engine put its id into the GLB. `selectable`
	 *  alone is not enough — a body whose pick key never landed would highlight nothing,
	 *  and offering the click anyway is how a viewport and a tree start disagreeing. */
	const canSelect = (n: CadSceneNode) =>
		!!n.selectable && !!n.glb_pick_key && capabilities?.select_bodies !== false;

	const statusDot = (n: CadSceneNode) =>
		n.status === 'valid'
			? 'bg-emerald-500'
			: n.status === 'error'
				? 'bg-red-500'
				: n.status === 'building'
					? 'bg-sky-500'
					: n.status === 'suppressed'
						? 'bg-gray-300 dark:bg-gray-700'
						: 'bg-gray-400';

	/** The part's viewport colour, or '' when the manifest named none (CS-2).
	 *
	 *  Shape-checked before it reaches a `style` attribute: the value is the engine's,
	 *  not a user's, but a colour is the one manifest field this component writes
	 *  straight into CSS, and a six-digit hex is the whole contract. */
	const swatch = (n: CadSceneNode) =>
		n.kind === 'body' && /^#[0-9a-fA-F]{6}$/.test(n.color ?? '') ? (n.color as string) : '';

	const kindLabel = (n: CadSceneNode) =>
		n.kind === 'assembly'
			? $i18n.t('Assembly')
			: n.kind === 'body'
				? $i18n.t('Body')
				: n.kind === 'reference'
					? $i18n.t('Reference')
					: (n.op ?? $i18n.t('Feature'));

	const toggle = (id: string) => {
		collapsed = { ...collapsed, [id]: !collapsed[id] };
	};

	// --- Reveal (UX-E error→feature) -----------------------------------------------
	// Exposed as a method rather than a prop, because the same node may need revealing
	// twice in a row and a prop that has not changed fires nothing. The host binds the
	// component and calls this.
	//
	// Revealing is deliberately NOT selecting. The operation that broke a build has no
	// `glb_pick_key` and is not selectable; highlighting it here points at the failure
	// without turning it into an edit target the model would then be told about.
	let rowEls: Record<string, HTMLElement | null> = {};
	let revealed = '';
	let revealTimer: ReturnType<typeof setTimeout> | null = null;
	onDestroy(() => revealTimer && clearTimeout(revealTimer));

	export const revealNode = async (id: string) => {
		if (!id || !byId[id]) return;
		show('hierarchy');
		// Expand every ancestor first — a row inside a collapsed branch is not in `rows`
		// at all, so there would be nothing to scroll to.
		const openBranches = { ...collapsed };
		const guard = new Set<string>();
		let cur = byId[id].parent_id ?? null;
		while (cur && !guard.has(cur)) {
			guard.add(cur);
			delete openBranches[cur];
			cur = byId[cur]?.parent_id ?? null;
		}
		collapsed = openBranches;
		revealed = id;
		await tick();
		rowEls[id]?.scrollIntoView({ block: 'center', behavior: 'smooth' });
		if (revealTimer) clearTimeout(revealTimer);
		revealTimer = setTimeout(() => (revealed = ''), 2600);
	};

	/** Show the code that builds a body. A method rather than a prop for the same reason
	 *  as `revealNode`: asking twice for the same body has to work, and a prop that has
	 *  not changed fires nothing. */
	export const openCode = (id: string) => {
		if (!id) return;
		pendingCodeNode = id;
		show('code');
	};

	const sizeOf = (b: number) =>
		b < 1024
			? `${b} B`
			: b < 1024 * 1024
				? `${(b / 1024).toFixed(0)} KB`
				: `${(b / 1048576).toFixed(1)} MB`;

	const timeOf = (at?: string | null) => {
		if (!at) return '';
		const d = new Date(at);
		return Number.isNaN(d.getTime())
			? ''
			: d.toLocaleString(undefined, {
					month: 'short',
					day: 'numeric',
					hour: '2-digit',
					minute: '2-digit'
				});
	};

	// Newest first, by seq rather than by position: the project read and the workspace
	// snapshot do not promise the same order, and picking by seq survives either.
	$: ordered = [...revisions].sort((a, b) => (b.seq ?? 0) - (a.seq ?? 0));

	/** The count beside each section header. A header that says how much is behind it is
	 *  the whole reason a closed section is not a hidden one.
	 *
	 *  Derived rather than a function the markup calls with only a section id: such a call
	 *  does not re-run when the tree or the graph changes, so the header would go on
	 *  printing a count from a revision ago. */
	/** Which section bodies are on screen. A derived record rather than a helper function
	 *  because Svelte tracks the names a markup expression reads: `isOpen(id)` would only
	 *  re-run when `isOpen` itself changed, which is never. */
	$: shown = Object.fromEntries(
		CAD_EXPLORER_TABS.map(([id]) => [id, openOverride ? !!openOverride[id] : !!open[id]])
	) as Record<CadExplorerTab, boolean>;

	$: counts = {
		hierarchy: rows.length,
		parameters: sourceGraph?.parameters.length ?? 0,
		code: 0,
		files: fileTree?.files.length ?? 0,
		history: ordered.length,
		project: artifacts.length + renders.length
	} as Record<CadExplorerTab, number>;
</script>

<div class="h-full flex flex-col bg-white dark:bg-gray-900" aria-label={$i18n.t('Project explorer')}>
	{#each CAD_EXPLORER_TABS as [id, label] (id)}
		<section
			bind:this={secEls[id]}
			class="flex flex-col min-h-0 {shown[id] ? '' : 'shrink-0'}"
			class:hidden={railDriven && !shown[id]}
			style={shown[id] ? `flex:${weight[id]} 1 0px` : ''}
		>
			<h3 class="shrink-0">
				{#if railDriven}
					<!-- No chevron when the host's rail owns this: pressing the icon is what puts
					     the section in the stack and takes it out again, and a second control that
					     looks like it does the same thing would leave the reader guessing which one
					     they used. The header stays, because a stack of three needs its labels. -->
					<div
						class="w-full flex items-center gap-1.5 px-2 py-1.5 border-b border-gray-100 dark:border-gray-850"
					>
						<span
							class="min-w-0 truncate text-[10px] uppercase tracking-wide text-gray-500 dark:text-gray-400"
							>{$i18n.t(label)}</span
						>
						{#if counts[id]}
							<span class="ml-auto shrink-0 text-[10px] text-gray-400 tabular-nums">{counts[id]}</span>
						{/if}
					</div>
				{:else}
					<button
						class="w-full flex items-center gap-1.5 px-2 py-1 border-b border-gray-100 dark:border-gray-850 text-left hover:bg-gray-50 dark:hover:bg-gray-850 transition"
						aria-expanded={open[id]}
						on:click={() => toggleSection(id)}
					>
						<span class="shrink-0 text-[9px] leading-none text-gray-400 w-2"
							>{open[id] ? '▾' : '▸'}</span
						>
						<span
							class="min-w-0 truncate text-[10px] uppercase tracking-wide text-gray-500 dark:text-gray-400"
							>{$i18n.t(label)}</span
						>
						{#if counts[id]}
							<span class="ml-auto shrink-0 text-[10px] text-gray-400 tabular-nums">{counts[id]}</span>
						{/if}
					</button>
				{/if}
			</h3>

			<!-- Hidden rather than unmounted. Collapsing Code must not throw away the fetch
			     that Parameters and Project Files are drawn from, and every section keeps its
			     scroll position for the next time it is opened. -->
			<div
				class="flex-1 min-h-0 overflow-y-auto scrollbar-hidden px-1.5 py-1.5"
				class:hidden={!shown[id]}
			>
				{#if id === 'hierarchy'}
					{#if !manifest || rows.length === 0}
						<p class="px-1.5 text-[11px] text-gray-400 leading-snug">
							{$i18n.t('No scene tree for this revision. It appears once a build finishes.')}
						</p>
					{:else}
						<ul class="flex flex-col gap-px">
							{#each rows as { node, depth, kids } (node.node_id)}
								{@const consumes =
									!!node.cadir_operation_id && consumerOps.has(node.cadir_operation_id)}
								<li>
									<div
										bind:this={rowEls[node.node_id]}
										class="flex items-center gap-1 rounded-md pr-1 {selectedNodeId === node.node_id
											? 'bg-emerald-500/10'
											: ''} {revealed === node.node_id
											? 'ring-1 ring-red-400 dark:ring-red-500 bg-red-500/5'
											: ''} {consumes ? 'bg-amber-400/15' : ''}"
										style="padding-left:{depth * 12}px"
									>
										<button
											class="size-4 shrink-0 text-[9px] leading-none text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition {kids
												? ''
												: 'invisible'}"
											on:click={() => toggle(node.node_id)}
											aria-label={collapsed[node.node_id] ? $i18n.t('Expand') : $i18n.t('Collapse')}
										>
											{collapsed[node.node_id] ? '▸' : '▾'}
										</button>
										<button
											class="min-w-0 flex-1 flex items-center gap-1.5 py-1 text-left transition {canSelect(
												node
											)
												? 'cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-850 rounded-md px-1'
												: 'cursor-default px-1'}"
											disabled={!canSelect(node)}
											on:click={() => canSelect(node) && onSelectNode(node.node_id, node)}
											title={consumes
												? $i18n.t('Reads {{name}}', { name: selectedParam })
												: node.status === 'suppressed' && node.when
													? $i18n.t('Skipped because {{cond}} was not met', { cond: node.when })
													: kindLabel(node)}
										>
											<span class="size-1.5 rounded-full shrink-0 {statusDot(node)}"></span>
											{#if swatch(node)}
												<!-- The colour this part is wearing in the viewport, so a row and a
												     body identify each other before anything is clicked. Decoration
												     only: the exported STEP/STL carries no colour. -->
												<span
													class="size-2 rounded-[2px] shrink-0 ring-1 ring-black/10 dark:ring-white/15"
													style="background-color:{swatch(node)}"
													aria-hidden="true"
												></span>
											{/if}
											<span
												class="min-w-0 truncate text-[11px] {node.status === 'suppressed'
													? 'text-gray-400 dark:text-gray-500 line-through'
													: 'text-gray-700 dark:text-gray-200'}"
											>
												{node.label}
											</span>
											{#if node.kind === 'feature' && node.op}
												<span class="shrink-0 text-[9px] text-gray-400 font-mono">{node.op}</span>
											{/if}
											{#if node.instances && node.instances > 1}
												<span class="shrink-0 text-[9px] text-gray-400 tabular-nums"
													>×{node.instances}</span
												>
											{/if}
										</button>
									</div>
								</li>
							{/each}
						</ul>

						<!-- The engine's own sentence about what can be picked, printed rather than
						     paraphrased. A second explanation written here could drift from the code
						     that decides it, and then one of the two would be a lie. -->
						<p
							class="mt-2 px-1.5 pt-2 border-t border-gray-100 dark:border-gray-850 text-[10px] text-gray-400 leading-snug"
						>
							{capabilities?.selection_reason ||
								manifest.selection?.reason ||
								$i18n.t('Whole bodies only. Faces and edges are not selectable yet.')}
						</p>
					{/if}
				{:else if id === 'parameters'}
					<CadParametersPanel
						graph={sourceGraph}
						title={projectTitle}
						selected={selectedParam}
						onSelect={pickParam}
						{acceptedValues}
						note={graphNote}
						loading={!!selectedRevisionId && !fileTree}
					/>
				{:else if id === 'code'}
					<!-- The only CadCodeView in the rail, and the only fetch. It hands the tree up
					     through `onTree`, and Parameters and Project Files read that same object:
					     one request, one revision, three views of it. -->
					<div class="px-0.5">
						<CadCodeView
							{projectId}
							revisionId={selectedRevisionId}
							show="document"
							bind:openFile
							focusNodeId={pendingCodeNode}
							onFocusApplied={() => (pendingCodeNode = '')}
							onTree={(t) => (fileTree = t)}
							highlight={codeHighlight}
							{onRevealNode}
						/>
					</div>
				{:else if id === 'files'}
					<!-- Drawn here rather than by a second CadCodeView: two instances would mean
					     two fetches of the same revision, and the rail's whole claim is that its
					     sections are projections of one source. -->
					{#if !fileTree}
						<p class="px-1.5 text-[11px] text-gray-400">
							{selectedRevisionId ? $i18n.t('Loading…') : $i18n.t('No revision selected.')}
						</p>
					{:else}
						<div class="flex flex-col">
							{#each fileTree.files as f (f.path)}
								<button
									class="flex items-baseline gap-2 px-2 py-1 rounded-md text-left text-xs {f.path ===
									openFile
										? 'bg-gray-100 dark:bg-gray-850 text-gray-900 dark:text-gray-100'
										: 'text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-900'}"
									title={f.description}
									on:click={() => {
										openFile = f.path;
										show('code');
									}}
								>
									<span class="font-mono truncate {f.kind === 'part' ? 'pl-3' : ''}">{f.path}</span>
									<span
										class="ml-auto shrink-0 text-[11px] text-gray-400 dark:text-gray-500 tabular-nums"
										>{sizeOf(f.bytes)}</span
									>
								</button>
							{/each}
							{#each fileTree.notes as n}
								<p class="mt-1 px-2 text-[10px] text-gray-400 leading-snug">{n}</p>
							{/each}
						</div>
					{/if}
				{:else if id === 'history'}
					{#if ordered.length === 0}
						<p class="px-1.5 text-[11px] text-gray-400">{$i18n.t('No revisions yet.')}</p>
					{:else}
						<ul class="flex flex-col gap-px">
							{#each ordered as r (r.id)}
								{@const b = r.latest_build}
								<li>
									<button
										class="w-full text-left px-1.5 py-1.5 rounded-md transition {r.id ===
										selectedRevisionId
											? 'bg-emerald-500/10'
											: 'hover:bg-gray-50 dark:hover:bg-gray-850'}"
										on:click={() => onSelectRevision(r.id)}
										aria-current={r.id === selectedRevisionId}
									>
										<span class="flex items-center gap-1.5">
											<span
												class="shrink-0 size-1.5 rounded-full {b?.status === 'succeeded'
													? 'bg-emerald-500'
													: b?.status === 'failed'
														? 'bg-red-500'
														: b?.status === 'running' || b?.status === 'queued'
															? 'bg-sky-500'
															: 'bg-gray-300 dark:bg-gray-700'}"
											></span>
											<span class="shrink-0 text-[11px] text-gray-700 dark:text-gray-200 tabular-nums"
												>rev {r.seq}</span
											>
											<!-- Every marker is `shrink-0 whitespace-nowrap`: this column is 17rem wide and
											     a row carrying Accepted + head + on screen at once had the flexbox shrink
											     the labels until they broke mid-word into "Accepte d" and "hea d". -->
											{#if r.state === 'accepted'}
												<span
													class="shrink-0 whitespace-nowrap text-[9px] px-1 py-0.5 rounded bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
													>{$i18n.t('Accepted')}</span
												>
											{:else}
												<span
													class="shrink-0 whitespace-nowrap text-[9px] px-1 py-0.5 rounded bg-amber-500/10 text-amber-600 dark:text-amber-400"
													>{$i18n.t('Proposal')}</span
												>
											{/if}
											{#if r.id === headRevisionId}
												<span class="shrink-0 whitespace-nowrap text-[9px] text-gray-400"
													>{$i18n.t('head')}</span
												>
											{/if}
											{#if r.id === displayedRevisionId}
												<span
													class="shrink-0 whitespace-nowrap text-[9px] text-emerald-600 dark:text-emerald-400"
													>{$i18n.t('on screen')}</span
												>
											{/if}
											<span class="ml-auto shrink-0 text-[10px] text-gray-400">{timeOf(r.created_at)}</span
											>
										</span>
										<span class="mt-0.5 flex items-center gap-2 pl-3 text-[10px] text-gray-400">
											<span class="truncate">
												{r.recipe_name ?? (r.source_kind === 'cadir' ? $i18n.t('authored') : r.source_kind)}
											</span>
											{#if b}
												<span class={b.status === 'failed' ? 'text-red-500' : ''}>{b.status}</span>
											{:else}
												<span>{$i18n.t('never built')}</span>
											{/if}
											{#if b?.conformance_status}
												<span
													class={b.conformance_status === 'passed'
														? 'text-emerald-600 dark:text-emerald-400'
														: b.conformance_status === 'failed'
															? 'text-red-600 dark:text-red-400'
															: ''}
												>
													{b.conformance_status}
												</span>
											{/if}
										</span>
									</button>
								</li>
							{/each}
						</ul>
						<p
							class="mt-2 px-1.5 pt-2 border-t border-gray-100 dark:border-gray-850 text-[10px] text-gray-400 leading-snug"
						>
							{$i18n.t('Picking a revision switches the tree, the viewport, the files and the verdicts together.')}
						</p>
					{/if}
				{:else}
					<div class="flex flex-col gap-3">
						<section>
							<h4 class="px-1.5 pb-1 text-[10px] uppercase tracking-wide text-gray-400">
								{$i18n.t('Exports')}
							</h4>
							{#if artifacts.length === 0}
								<p class="px-1.5 text-[11px] text-gray-400">
									{$i18n.t('Nothing exported for this revision yet.')}
								</p>
							{:else}
								<ul class="flex flex-col gap-px">
									{#each artifacts as a (a.id)}
										<li>
											<button
												class="w-full flex items-center gap-2 px-1.5 py-1 rounded-md text-left hover:bg-gray-50 dark:hover:bg-gray-850 transition"
												on:click={() => onExport(a)}
												title={$i18n.t('Download')}
											>
												<span
													class="shrink-0 text-[9px] font-mono px-1 py-0.5 rounded bg-gray-100 dark:bg-gray-850 text-gray-500 dark:text-gray-400"
													>{a.format.toUpperCase()}</span
												>
												<span
													class="min-w-0 flex-1 truncate text-[11px] text-gray-700 dark:text-gray-200"
													title={fileNameOf(a)}
												>
													{fileNameOf(a)}
												</span>
												<span class="shrink-0 text-[10px] text-gray-400 tabular-nums"
													>{sizeOf(a.size_bytes)}</span
												>
											</button>
										</li>
									{/each}
								</ul>
							{/if}
						</section>

						<section>
							<h4 class="px-1.5 pb-1 text-[10px] uppercase tracking-wide text-gray-400">
								{$i18n.t('Renders')}
							</h4>
							{#if renders.length === 0}
								<p class="px-1.5 text-[11px] text-gray-400">
									{$i18n.t('No views captured yet. They are taken automatically once a build finishes.')}
								</p>
							{:else}
								<div class="grid grid-cols-3 gap-1 px-1">
									{#each renders as r (r.id)}
										<div
											class="relative rounded-md overflow-hidden border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-850"
											style="height:52px"
											title={[r.meta?.label || r.variant, ...(r.meta?.qc ?? []).map((f) => f.detail)].join(
												' — '
											)}
										>
											{#if renderUrls[r.id]}
												<img
													src={renderUrls[r.id]}
													alt={$i18n.t('{{view}} view', { view: r.meta?.label || r.variant })}
													class="absolute inset-0 w-full h-full object-contain"
												/>
											{/if}
											<!-- A QC finding is a note about the picture, never about the part —
											     a dot the tooltip explains, not a badge that reads as a failure.
											     The one finding that would condemn a picture stops the upload, so
											     nothing here is ever worse than a warning. -->
											{#if (r.meta?.qc ?? []).length}
												<span
													class="absolute top-1 right-1 h-1.5 w-1.5 rounded-full bg-amber-400"
												></span>
											{/if}
											<span
												class="absolute bottom-0 inset-x-0 text-[9px] leading-4 text-center truncate px-1 bg-white/75 dark:bg-gray-900/75 text-gray-600 dark:text-gray-300"
												>{r.meta?.label || r.variant}</span
											>
										</div>
									{/each}
								</div>
							{/if}
							<p class="mt-1 px-1.5 text-[10px] text-gray-400 leading-snug">
								{$i18n.t('A rendered inspection view, not dimensional proof.')}
							</p>
						</section>

						<!-- Imported references are their own section rather than mixed into Exports:
						     a file somebody uploaded and a file this engine produced are different
						     things, and a single list would blur which is which. -->
						<section>
							<h4 class="px-1.5 pb-1 text-[10px] uppercase tracking-wide text-gray-400">
								{$i18n.t('References')}
							</h4>
							{#if ordered.some((r) => r.provenance)}
								<ul class="flex flex-col gap-px">
									{#each ordered.filter((r) => r.provenance) as r (r.id)}
										<li
											class="px-1.5 py-1 text-[11px] text-gray-700 dark:text-gray-200 flex items-center gap-2"
										>
											<span class="min-w-0 truncate" title={r.provenance?.filename ?? ''}>
												{r.provenance?.filename ?? $i18n.t('Imported file')}
											</span>
											<span class="ml-auto shrink-0 text-[10px] text-gray-400 tabular-nums"
												>rev {r.seq}</span
											>
										</li>
									{/each}
								</ul>
							{:else}
								<p class="px-1.5 text-[11px] text-gray-400">
									{$i18n.t('Nothing has been imported into this project.')}
								</p>
							{/if}
						</section>
					</div>
				{/if}
			</div>

			{#if shown[id] && nextOpen(id)}
				<div
					class="h-1 shrink-0 cursor-row-resize hover:bg-emerald-500/40 transition"
					role="separator"
					aria-orientation="horizontal"
					aria-label={$i18n.t('Resize {{section}}', { section: $i18n.t(label) })}
					on:pointerdown={gripDown(id)}
				></div>
			{/if}
		</section>
	{/each}
</div>
