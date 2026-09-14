<script context="module" lang="ts">
	export type CadPanelId =
		| 'design'
		| 'code'
		| 'parameters'
		| 'validate'
		| 'history'
		| 'compare'
		| 'artifacts';

	/** The panel set, in the order the spec lists it. Exported because the tab strip
	 *  belongs to whichever surface is hosting these panels — the focus workspace puts
	 *  Activity in front of them, the studio route does not — and a strip rendered here
	 *  would have to grow a slot to accommodate that. */
	export const CAD_PANELS: [CadPanelId, string][] = [
		['design', 'Design'],
		['code', 'Code'],
		['parameters', 'Parameters'],
		['validate', 'Validate'],
		['history', 'History'],
		['compare', 'Compare'],
		['artifacts', 'Artifacts']
	];
</script>

<script lang="ts">
	// The CAD context panels (UX-4).
	//
	// One implementation of the controls, mounted by both surfaces that need them: the
	// focus workspace's side column and the full studio route. Before this they lived
	// only in CadStudioPanel, which meant the workspace could show a part but not change
	// one — and copying the markup across would have left two Parameters tabs to drift
	// apart, which is the failure the file-level comments in this directory keep warning
	// about.
	//
	// This component owns the editing state (slider values, the fetched CadIR document,
	// the compare selection) and the actions that change the project. It does NOT own the
	// project: the host loads it, polls it, and reloads it through `onChanged` after a
	// build. That split is what lets the workspace keep its own live job stream driving
	// the same data.
	//
	// The panel names come from the spec, and two studio tabs were folded rather than
	// dropped: Features and Source are both "what this part is made of", so they are one
	// Design panel; Inspect and Validate are both read off the build, so they are one
	// Validate panel with the measurements and the verdicts kept visibly apart. Renders
	// is not here — it is the filmstrip under the viewport, where the pictures are taken.
	import { getContext, onDestroy, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import {
		CadApiError,
		acceptCadRevision,
		compareCadRevisions,
		createCadRevision,
		downloadCadArtifact,
		getCadCapability,
		getCadRecipeSource,
		pollCadBuild,
		restoreCadRevision,
		type CadArtifact,
		type CadCapability,
		type CadFormat,
		type CadParamSpec,
		type CadProject,
		type CadRecipeSource,
		type CadRevision
	} from '$lib/apis/cad';
	import CadCodeView from './CadCodeView.svelte';

	const i18n: any = getContext('i18n');

	export let tab: CadPanelId = 'design';
	export let project: CadProject | null = null;
	/** Passed in by a host that already has it; fetched here otherwise. The bounds on
	 *  every slider come from this, never from a constant in the frontend — a slider that
	 *  disagreed with the engine would offer values the engine refuses. */
	export let capability: CadCapability | null = null;
	export let selectedRevisionId = '';
	export let onSelectRevision: (id: string) => void = () => {};
	/** Reload the project. Awaited, so the panels re-derive from the store rather than
	 *  from an optimistic guess about what the build did. */
	export let onChanged: () => any = () => {};
	/** True while a build this panel started is running. Bindable so the host can
	 *  disable its own controls for the same reason. */
	export let busy = false;
	/** Short single-line report of the last action. The workspace has a status bar of
	 *  its own and hides this; the studio shows it. */
	export let showStatusLine = true;
	/** Reveal a scene node in the host's hierarchy tree (UX-E error→feature). Only the
	 *  workspace has an explorer to reveal it in, so this stays null on the studio route
	 *  and the offer is simply not made there — a button that scrolled nothing would be
	 *  worse than no button. Revealing is NOT selecting: a broken operation has no
	 *  `glb_pick_key`, is not selectable, and must never become an edit chip. */
	export let onRevealNode: ((nodeId: string) => void) | null = null;

	const FORMATS: CadFormat[] = ['stl', 'step', 'glb', '3mf'];

	let params: Record<string, number> = {};
	let statusLine = '';
	let abort: AbortController | null = null;

	// The CadIR document behind a recipe, fetched once per recipe and only when the
	// Design panel is open. Keyed by recipe because that is what the document belongs
	// to — every revision built from `studded_brick_v1` shows the same one.
	let recipeSources: Record<string, CadRecipeSource> = {};
	let sourceLoading = false;
	// Failures are remembered per recipe rather than held in one resettable string. The
	// fetch below is driven by a reactive statement, and a flag that cleared on the next
	// attempt gave that statement no memory of having already failed — a dead engine
	// produced an unbounded 503 loop. One failed recipe stays failed until it is retried.
	let sourceFailed: Record<string, string> = {};

	let compareA = '';
	let compareB = '';
	let comparing = false;
	let compareResult: any = null;
	let compareError = '';

	$: revisions = project?.revisions ?? [];
	$: selectedRevision = revisions.find((r) => r.id === selectedRevisionId) ?? revisions[0] ?? null;
	$: latestBuild = selectedRevision?.latest_build ?? null;
	$: artifacts = (latestBuild?.artifacts ?? []) as CadArtifact[];
	$: measurements = (latestBuild?.validation ?? null) as Record<string, any> | null;
	// The second verdict, never folded into the first. `measurements` says the solid is
	// sound; this says it is the part that was asked for. `unverified` is its own answer.
	$: conformance = latestBuild?.conformance ?? null;
	$: mesh = (measurements?.mesh ?? null) as Record<string, any> | null;
	// A failed build still carries its scene tree, with the operation that broke marked
	// `error` by the engine (it derives the op id from the runtime error and validates it
	// against the declared ops, so an unparseable message marks nothing rather than
	// guessing). These are the rows the Validate panel offers to reveal.
	//
	// `error` propagates up the tree — a broken fillet marks its own node, the body that
	// contains it, and the assembly above that. Measured on a real failed build: three
	// error nodes, only one of which broke. Offering all three would give two buttons
	// reading "Broke at <the document's name>", pointing at containers that did nothing
	// wrong, so this is the nodes that actually name an operation.
	$: errorNodes = (latestBuild?.scene_manifest?.nodes ?? []).filter(
		(n) => n.status === 'error' && n.cadir_operation_id
	);
	// Null when nothing has been accepted yet — the correct state for a project whose
	// only revision is a model's proposal, not a gap to paper over.
	$: head = revisions.find((r) => r.id === project?.head_revision) ?? null;
	$: imported = selectedRevision?.source_kind === 'import';
	$: provenance = selectedRevision?.provenance ?? null;
	$: parsed = (measurements?.provenance ?? null) as Record<string, any> | null;
	$: recipeName = selectedRevision?.recipe_name ?? '';
	$: authored = selectedRevision?.source_kind === 'cadir';
	// An authored revision carries its own document, so there is nothing to fetch — and
	// nothing that *could* be fetched: `/recipes/{name}/source` answers from the engine's
	// registry, and an authored part's name was never registered there. Shaping the
	// carried document like the route's response keeps the Design panel one renderer.
	$: revisionDocument =
		authored && selectedRevision?.cadir
			? ({
					schema_version: selectedRevision.cadir.schema_version ?? '0.1',
					recipe: selectedRevision.recipe_name ?? 'design',
					units: selectedRevision.cadir.units ?? 'mm',
					document: selectedRevision.cadir,
					features: (selectedRevision.cadir.operations ?? []).map((op: any, i: number) => ({
						op_id: op.op_id || `${op.op}#${i}`,
						op: op.op,
						mode: op.mode ?? 'add',
						when: op.when ?? null,
						optional: !!op.optional,
						selectable: false
					}))
				} as CadRecipeSource)
			: null;
	$: recipeSource = revisionDocument ?? (recipeName ? (recipeSources[recipeName] ?? null) : null);
	$: sourceError = revisionDocument ? '' : recipeName ? (sourceFailed[recipeName] ?? '') : '';
	// Same split for the sliders: an authored revision declares its own parameters with
	// their own bounds, and `capability.recipe_params` only ever knows the registered
	// recipes. Reading only the latter left every authored part with no sliders at all.
	$: paramSpec = (
		authored
			? (selectedRevision?.cadir?.parameters ?? [])
			: (selectedRevision?.recipe_name &&
					capability?.recipe_params?.[selectedRevision.recipe_name]?.parameters) ||
				[]
	) as CadParamSpec[];

	// Re-seed whenever the revision on screen changes. The sliders must show what this
	// revision actually is, never the previous one's edits.
	let seededFor = '';
	$: if (selectedRevision && selectedRevision.id !== seededFor && capability) {
		seededFor = selectedRevision.id;
		seedParams(selectedRevision);
	}

	// Fetch the CadIR document the first time the Design panel is opened. Three guards,
	// stopping three different things: the cache stops a refetch, the in-flight flag
	// stops a second concurrent request, and the failure record stops the retry loop.
	// Never for an import — its `recipe_name` is the uploaded file's stem, so the request
	// could only 404, and the panel would report a missing recipe for a part that never
	// had one. Never for an authored revision either, for the same reason: it already
	// has its document, and its name is not in the engine's recipe registry.
	$: if (
		tab === 'design' &&
		recipeName &&
		!imported &&
		!revisionDocument &&
		!recipeSources[recipeName] &&
		!sourceFailed[recipeName] &&
		!sourceLoading
	) {
		loadRecipeSource(recipeName);
	}

	// Two revisions to compare, defaulted to the one on screen against whatever came
	// before it — the comparison someone opening this panel almost always wants.
	$: if (tab === 'compare' && revisions.length > 1 && !compareA && !compareB) {
		const sorted = [...revisions].sort((x, y) => (y.seq ?? 0) - (x.seq ?? 0));
		compareB = selectedRevision?.id ?? sorted[0].id;
		compareA = (sorted.find((r) => r.id !== compareB) ?? sorted[0]).id;
	}

	const fmt = (n: number | null | undefined, digits = 1) =>
		typeof n === 'number' && isFinite(n) ? n.toFixed(digits) : '—';

	/** A conformance check states `expected` and `measured` as whatever it could say — a
	 *  count, a millimetre value, a list of them, or null when there was nothing to
	 *  measure. Printed raw, a list reads "10,20,30" and a null reads "null". */
	const quantity = (v: any): string =>
		v === null || v === undefined
			? '—'
			: Array.isArray(v)
				? v.map(quantity).join(', ')
				: typeof v === 'number'
					? Number.isInteger(v)
						? `${v}`
						: v.toFixed(2)
					: `${v}`;

	const mb = (n: number) => `${(n / 1024 / 1024).toFixed(1)} MB`;

	/** Artifact sizes, unlike the storage quota, are usually kilobytes — a GLB of a
	 *  bracket is a few KB, and `mb()` renders every one of them as "0.0 MB". */
	const size = (n: number) =>
		n >= 1024 * 1024 ? mb(n) : n >= 1024 ? `${(n / 1024).toFixed(1)} KB` : `${n} B`;

	const statusTone = (s?: string) =>
		s === 'succeeded'
			? 'text-green-600 dark:text-green-400'
			: s === 'failed'
				? 'text-red-500 dark:text-red-400'
				: s === 'cancelled'
					? 'text-gray-500 dark:text-gray-400'
					: 'text-blue-500 dark:text-blue-400';

	const seedParams = (rev: CadRevision | null) => {
		// Same two sources as `paramSpec`, and for the same reason: an authored part's
		// bounds are in the document it carries, a recipe's are in the capability read.
		// Seeding from the capability alone left every authored part's sliders unbound.
		const spec = (
			rev?.source_kind === 'cadir'
				? (rev?.cadir?.parameters ?? [])
				: (rev?.recipe_name && capability?.recipe_params?.[rev.recipe_name]?.parameters) || []
		) as CadParamSpec[];
		const next: Record<string, number> = {};
		for (const p of spec) {
			const v = rev?.parameters?.[p.name];
			next[p.name] = typeof v === 'number' ? v : p.default;
		}
		params = next;
	};

	const loadRecipeSource = async (recipe: string) => {
		sourceLoading = true;
		// Drop any prior failure up front, so the retry button only has to clear the key.
		const { [recipe]: _cleared, ...rest } = sourceFailed;
		sourceFailed = rest;
		try {
			recipeSources = { ...recipeSources, [recipe]: await getCadRecipeSource(recipe) };
		} catch (e: any) {
			// Shown in place rather than raised as a toast: the rest of the workspace still
			// works, and a part whose source cannot be read is a fact about one panel.
			sourceFailed = { ...sourceFailed, [recipe]: e?.message ?? `${e}` };
		} finally {
			sourceLoading = false;
		}
	};

	/** Wait for a build to finish, then let the host re-read the project so the version
	 *  list and the viewport agree with the store. */
	const followBuild = async (buildId: string, label: string) => {
		abort?.abort();
		abort = new AbortController();
		busy = true;
		statusLine = $i18n.t('Building…');
		try {
			const build = await pollCadBuild(buildId, { signal: abort.signal });
			if (build.status === 'succeeded') {
				statusLine = `${label} · ${fmt(build.duration_ms, 0)} ms`;
			} else if (build.status === 'failed') {
				statusLine = '';
				toast.error(build.error_detail || build.error_code || $i18n.t('The build failed.'));
			} else {
				statusLine = $i18n.t('Build {{status}}.', { status: build.status });
			}
		} catch (e: any) {
			statusLine = '';
			toast.error(e?.message ?? `${e}`);
		} finally {
			busy = false;
			await onChanged();
		}
	};

	/** Append a revision carrying `overrides` on top of `rev`'s parameters, and build it.
	 *  A 409 means someone else moved the head — say so instead of forking. */
	const buildFrom = async (rev: CadRevision | null, overrides: Record<string, number>) => {
		if (!project || !rev) return;
		try {
			// Which source the new revision is built from has to match what the base
			// actually is. Sending `recipe` for an authored part named a recipe the engine
			// has never heard of, so every slider edit on a generated part could only come
			// back `unknown_recipe`. The document travels with the request instead — the
			// engine resolves the same overrides against the bounds it declares.
			const source =
				rev.source_kind === 'cadir' && rev.cadir
					? { document: rev.cadir }
					: { recipe: rev.recipe_name ?? '' };
			const accepted = await createCadRevision(project.id, {
				base_revision_id: rev.id,
				...source,
				params: { ...(rev.parameters ?? {}), ...overrides },
				formats: FORMATS
			});
			onSelectRevision(accepted.revision_id);
			await followBuild(accepted.build_id, $i18n.t('Revision {{seq}}', { seq: accepted.seq }));
		} catch (e: any) {
			if (e instanceof CadApiError && e.status === 409) {
				toast.error($i18n.t('This project changed elsewhere — reloading it.'));
				await onChanged();
			} else {
				toast.error(e?.message ?? `${e}`);
			}
		}
	};

	const applyParameters = async () => {
		if (!selectedRevision) return;
		// Build from the head, not from the revision on screen: appending to an older
		// revision is what the 409 exists to prevent. And when there is no head at all,
		// say so rather than sending a request whose only possible answer is that 409.
		if (!head) {
			toast.error(
				$i18n.t('Accept a version first — nothing in this project has been accepted yet.')
			);
			return;
		}
		await buildFrom(head, params);
	};

	const restore = async (rev: CadRevision) => {
		if (!project) return;
		try {
			const accepted = await restoreCadRevision(project.id, rev.id);
			onSelectRevision(accepted.revision_id);
			await followBuild(accepted.build_id, $i18n.t('Restored revision {{seq}}', { seq: rev.seq }));
		} catch (e: any) {
			toast.error(e?.message ?? `${e}`);
		}
	};

	/** Accept a proposal, which is the only thing that moves the project head.
	 *
	 *  A `conformance_failed` 409 is answered with a confirm rather than a retry: the
	 *  build measured wrong against the DesignSpec, and overriding that is a judgement
	 *  only the person looking at it can make. */
	const accept = async (rev: CadRevision) => {
		if (!project) return;
		busy = true;
		try {
			await acceptCadRevision(project.id, rev.id);
			statusLine = $i18n.t('Accepted revision {{seq}}', { seq: rev.seq });
		} catch (e: any) {
			if (e instanceof CadApiError && e.code === 'conformance_failed') {
				const ok = confirm(`${e.message}\n\n${$i18n.t('Accept it anyway?')}`);
				if (!ok) {
					busy = false;
					return;
				}
				try {
					await acceptCadRevision(project.id, rev.id, true);
					statusLine = $i18n.t('Accepted revision {{seq}} despite the mismatch', { seq: rev.seq });
				} catch (e2: any) {
					toast.error(e2?.message ?? `${e2}`);
				}
			} else {
				toast.error(e?.message ?? `${e}`);
			}
		} finally {
			busy = false;
			await onChanged();
		}
	};

	const download = async (a: CadArtifact) => {
		if (!latestBuild || !project) return;
		const name = `${project.title.replace(/[^\w.-]+/g, '_')}-rev${selectedRevision?.seq ?? 0}.${a.format}`;
		try {
			await downloadCadArtifact(latestBuild.id, a, name);
		} catch (e: any) {
			toast.error(e?.message ?? `${e}`);
		}
	};

	/** The diff is the server's, not this panel's. Two revisions can differ in ways the
	 *  browser cannot see — a measurement is read from each revision's most recently
	 *  SUCCEEDED build, which is not always the build attached to the revision here. */
	const runCompare = async () => {
		if (!project || !compareA || !compareB || compareA === compareB) return;
		comparing = true;
		compareError = '';
		try {
			compareResult = await compareCadRevisions(project.id, compareA, compareB);
		} catch (e: any) {
			compareResult = null;
			compareError = e?.message ?? `${e}`;
		} finally {
			comparing = false;
		}
	};

	// Re-run whenever either side changes, so the panel never shows a diff labelled with
	// revisions it was not computed from.
	$: if (tab === 'compare' && compareA && compareB && compareA !== compareB) {
		void compareA;
		void compareB;
		runCompare();
	}

	const seqOf = (id: string) => revisions.find((r) => r.id === id)?.seq ?? '?';

	/** One measurement value, rendered without inventing a unit it does not have.
	 *  Vectors arrive as `{x, y, z}` and read as three numbers; anything else that is not
	 *  a number is shown as its own JSON rather than as `[object Object]`. */
	const value = (v: any): string => {
		if (v === null || v === undefined) return '—';
		if (typeof v === 'number') return isFinite(v) ? String(Number(v.toFixed(3))) : '—';
		if (typeof v === 'boolean') return v ? 'yes' : 'no';
		if (typeof v === 'object' && 'x' in v && 'y' in v && 'z' in v) {
			return `${fmt(v.x, 2)}, ${fmt(v.y, 2)}, ${fmt(v.z, 2)}`;
		}
		return typeof v === 'string' ? v : JSON.stringify(v);
	};

	onMount(async () => {
		if (!capability) {
			try {
				capability = await getCadCapability();
			} catch {
				// A missing capability read costs the sliders their bounds and nothing else;
				// every panel below says so in place rather than failing to render.
			}
		}
		if (selectedRevision) {
			seededFor = selectedRevision.id;
			seedParams(selectedRevision);
		}
	});

	onDestroy(() => abort?.abort());
</script>

<div class="flex flex-col gap-3 text-sm">
	{#if !project}
		<p class="text-xs text-gray-500 dark:text-gray-400">{$i18n.t('No part is open.')}</p>
	{:else if tab === 'parameters'}
		{#if imported}
			<!-- Checked before the engine-unreachable message, which would otherwise blame
			     the engine for the absence of dimensions nobody ever stated. An imported
			     solid is geometry, not a recipe: no reader recovers the sketch and the
			     feature history that produced it. -->
			<p class="text-xs text-gray-500 dark:text-gray-400">
				{$i18n.t(
					'An imported part has no editable dimensions — the file carries geometry, not the steps that made it. Measure it in Validate, or export it from Artifacts.'
				)}
			</p>
		{:else if !paramSpec.length}
			<!-- Three separate reasons a part can have no sliders, and only one of them is
			     the engine's fault. Collapsing them into the unreachable message told a
			     user the engine was down while it was plainly answering — the ranges were
			     simply somewhere this panel was not looking. -->
			<p class="text-xs text-gray-500 dark:text-gray-400">
				{#if !capability}
					{$i18n.t('Parameter ranges could not be read from the server.')}
				{:else if !capability.engine_reachable}
					{$i18n.t('Parameter ranges are unavailable while the engine is unreachable.')}
				{:else if authored}
					{$i18n.t(
						'This part declares no adjustable parameters — its dimensions are written directly into the design. Ask for a change in the conversation instead.'
					)}
				{:else}
					{$i18n.t('This part declares no adjustable parameters.')}
				{/if}
			</p>
		{:else}
			<div class="flex flex-col gap-2.5">
				{#each paramSpec as p}
					<div class="flex flex-col gap-1">
						<div class="flex items-center justify-between text-[11px]">
							<span class="text-gray-600 dark:text-gray-300">{p.name}</span>
							<span class="text-gray-500 dark:text-gray-400 tabular-nums">{params[p.name]}</span>
						</div>
						<input
							type="range"
							class="w-full accent-gray-900 dark:accent-white"
							min={p.min}
							max={p.max}
							step={p.kind === 'int' ? 1 : (p.max - p.min) / 100}
							bind:value={params[p.name]}
							disabled={busy}
						/>
					</div>
				{/each}
				<div class="flex items-center gap-2">
					<button
						class="text-xs px-3 py-1.5 rounded-lg bg-gray-900 text-white dark:bg-white dark:text-gray-900 disabled:opacity-50"
						disabled={busy || capability?.engine_reachable === false}
						on:click={applyParameters}
						>{busy ? $i18n.t('Building…') : $i18n.t('Build revision')}</button
					>
					<button
						class="text-xs px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300"
						disabled={busy}
						on:click={() => seedParams(selectedRevision)}>{$i18n.t('Reset')}</button
					>
				</div>
				<!-- Said here because it changes what the button above does: a new revision is
				     appended to the accepted head, so an edit made while looking at an older
				     revision does not fork from it. -->
				<p class="text-[11px] text-gray-400 dark:text-gray-500">
					{head
						? $i18n.t('A build appends a new revision on top of rev {{seq}}.', { seq: head.seq })
						: $i18n.t('Nothing has been accepted yet — accept a version in History first.')}
				</p>
			</div>
		{/if}
	{:else if tab === 'design'}
		{#if imported}
			<div class="flex flex-col gap-1 text-xs text-gray-500 dark:text-gray-400">
				<p>
					{$i18n.t('This part was imported. It has no feature list and no source document.')}
				</p>
				{#if provenance}
					<p class="truncate">
						{$i18n.t('From')}
						<span class="font-mono">{provenance.name}</span> · {provenance.kind.toUpperCase()} · {mb(
							provenance.bytes
						)}
					</p>
				{/if}
			</div>
		{:else if sourceLoading}
			<p class="text-xs text-gray-500 dark:text-gray-400">{$i18n.t('Loading…')}</p>
		{:else if sourceError}
			<!-- The retry is the only way back: a remembered failure is what stops the
			     reactive fetch from re-firing, so nothing reloads this on its own. -->
			<div class="flex flex-col items-start gap-1.5">
				<p class="text-xs text-amber-600 dark:text-amber-400">{sourceError}</p>
				<button
					class="text-[11px] px-2 py-0.5 rounded-md border border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300 disabled:opacity-50"
					disabled={sourceLoading}
					on:click={() => loadRecipeSource(recipeName)}>{$i18n.t('Retry')}</button
				>
			</div>
		{:else if !recipeSource}
			<p class="text-xs text-gray-500 dark:text-gray-400">
				{$i18n.t('This part has no feature list — it was not built from a template.')}
			</p>
		{:else}
			<div class="flex flex-col gap-1">
				{#each recipeSource.features as f}
					<div
						class="flex items-baseline gap-2 px-2 py-1.5 rounded-lg text-xs bg-gray-50 dark:bg-gray-900"
					>
						<span class="font-medium text-gray-800 dark:text-gray-100">{f.op_id}</span>
						<span class="text-[11px] text-gray-500 dark:text-gray-400">{f.op}</span>
						{#if f.mode && f.mode !== 'add'}
							<span class="text-[11px] text-gray-500 dark:text-gray-400">· {f.mode}</span>
						{/if}
						{#if f.when}
							<span class="text-[11px] text-gray-400 dark:text-gray-500 truncate"
								>· {$i18n.t('when')} {f.when}</span
							>
						{/if}
					</div>
				{/each}
			</div>
			<!-- Said plainly rather than left to be discovered by clicking. The Gate 5a spike
			     showed the mapping is possible — one glTF primitive per B-Rep face — but
			     nothing emits the manifest yet, so every feature reports selectable: false
			     and the viewport selects whole bodies. -->
			<p class="text-[11px] text-gray-400 dark:text-gray-500">
				{$i18n.t(
					'Selecting an individual face in the viewport is not available yet — selection is whole-body.'
				)}
			</p>

			<details class="text-xs">
				<summary class="cursor-pointer text-gray-500 dark:text-gray-400">
					{$i18n.t('Source document')}
					<span class="text-[11px] text-gray-400 dark:text-gray-500">
						· {recipeSource.recipe} · CadIR {recipeSource.schema_version} · {recipeSource.units}
					</span>
				</summary>
				{#if selectedRevision && Object.keys(selectedRevision.parameters ?? {}).length}
					<!-- The document is shared by every revision of this recipe; these are the
					     values THIS revision resolved it with. -->
					<div class="grid grid-cols-[auto_1fr] gap-x-3 mt-1.5 text-[11px]">
						{#each Object.entries(selectedRevision.parameters ?? {}) as [k, v]}
							<span class="text-gray-500 dark:text-gray-400">{k}</span>
							<span class="tabular-nums">{v}</span>
						{/each}
					</div>
				{:else}
					<!-- Revisions built before the studio started sending resolved defaults
					     recorded an empty map. Naming the values used would be a guess; an empty
					     map means exactly "the defaults in the document below". -->
					<p class="mt-1.5 text-[11px] text-gray-500 dark:text-gray-400">
						{$i18n.t(
							'This revision recorded no explicit values — it was built with the defaults below.'
						)}
					</p>
				{/if}
				<pre
					class="mt-1.5 text-[11px] font-mono whitespace-pre overflow-x-auto scrollbar-hidden p-2 rounded-lg bg-gray-50 dark:bg-gray-900">{JSON.stringify(
						recipeSource.document,
						null,
						2
					)}</pre>
			</details>
		{/if}
	{:else if tab === 'code'}
		<!-- The design as a project (CS-3). The view itself is CadCodeView, shared with the
		     session workspace's left rail so there is one implementation of the tree, the
		     open document and the sentence that says these files are generated rather than
		     authored. -->
		<CadCodeView
			projectId={project?.id ?? ''}
			revisionId={selectedRevision?.id ?? ''}
			{onRevealNode}
		/>
	{:else if tab === 'validate'}
		{#if !measurements}
			<!-- Three different reasons there is nothing to measure, and they are not
			     interchangeable. A build that RAN and broke has no `validation` either, so
			     the single "has not been built" line used to report every real failure as
			     though nothing had ever happened. -->
			{#if latestBuild?.status === 'failed' || latestBuild?.status === 'cancelled'}
				<div class="flex flex-col gap-1 text-xs">
					<span class={statusTone(latestBuild.status)}>
						{latestBuild.status === 'cancelled'
							? $i18n.t('This build was cancelled — nothing was measured.')
							: $i18n.t('This build failed — nothing was measured.')}
					</span>
					{#if latestBuild.error_detail}
						<!-- Safe text by contract: the engine strips paths, argv and host names
						     before this ever reaches a response body. -->
						<span class="text-gray-600 dark:text-gray-300">{latestBuild.error_detail}</span>
					{/if}
					{#if latestBuild.error_code}
						<span class="font-mono text-[11px] text-gray-400 dark:text-gray-500"
							>{latestBuild.error_code}</span
						>
					{/if}
					{#if errorNodes.length && onRevealNode}
						<!-- The engine already marked which operation broke (UX-A). Naming it here
						     and offering to reveal it is the whole of the error→feature path. -->
						<div class="pt-1 flex flex-col gap-1">
							{#each errorNodes as n}
								<button
									class="text-left text-red-500 dark:text-red-400 hover:underline"
									on:click={() => onRevealNode(n.node_id)}
								>
									{$i18n.t('Broke at')}
									{n.label}
									{#if n.cadir_operation_id}<span class="font-mono text-[11px] opacity-70"
											>· {n.cadir_operation_id}</span
										>{/if}
								</button>
							{/each}
						</div>
					{/if}
				</div>
			{:else if latestBuild}
				<p class="text-xs text-gray-500 dark:text-gray-400">
					{$i18n.t('This build is still running — nothing has been measured yet.')}
				</p>
			{:else}
				<p class="text-xs text-gray-500 dark:text-gray-400">
					{$i18n.t('Nothing to check — this revision has not been built.')}
				</p>
			{/if}
		{:else}
			{@const expected =
				(recipeName && capability?.recipe_params?.[recipeName]?.expected_solids) ?? null}
			<!-- Measured by the engine off the built solid. None of it is predicted, and
			     none of it comes from the model. -->
			<div class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
				<span class="text-gray-500 dark:text-gray-400">{$i18n.t('Bounding box')}</span>
				<span class="tabular-nums"
					>{fmt(measurements.bbox_mm?.x, 2)} × {fmt(measurements.bbox_mm?.y, 2)} × {fmt(
						measurements.bbox_mm?.z,
						2
					)} mm</span
				>
				<span class="text-gray-500 dark:text-gray-400">{$i18n.t('Volume')}</span>
				<span class="tabular-nums">{fmt(measurements.volume_mm3, 1)} mm³</span>
				<span class="text-gray-500 dark:text-gray-400">{$i18n.t('Surface area')}</span>
				<span class="tabular-nums">{fmt(measurements.surface_area_mm2, 1)} mm²</span>
				<span class="text-gray-500 dark:text-gray-400">{$i18n.t('Center of mass')}</span>
				<span class="tabular-nums"
					>{fmt(measurements.center_of_mass_mm?.x, 2)}, {fmt(
						measurements.center_of_mass_mm?.y,
						2
					)}, {fmt(measurements.center_of_mass_mm?.z, 2)} mm</span
				>
				<span class="text-gray-500 dark:text-gray-400">{$i18n.t('Solids')}</span>
				<span class="tabular-nums">{measurements.solid_count ?? '—'}</span>
				<span class="text-gray-500 dark:text-gray-400">{$i18n.t('Triangles')}</span>
				<span class="tabular-nums">{mesh?.triangle_count ?? '—'}</span>
				<span class="text-gray-500 dark:text-gray-400">{$i18n.t('Build time')}</span>
				<span class="tabular-nums">{fmt(measurements.duration_ms, 0)} ms</span>
				{#if measurements.peak_rss_bytes}
					<span class="text-gray-500 dark:text-gray-400">{$i18n.t('Peak memory')}</span>
					<span class="tabular-nums">{mb(measurements.peak_rss_bytes)}</span>
				{/if}
			</div>

			<!-- The two identities Gate 2 settled on. `source_hash` is what two revisions are
			     compared on; `mesh_signature` is what proves two builds of the same input
			     produced the same shape. Neither is a file hash — STEP embeds a wall-clock
			     timestamp and 3MF is a ZIP. -->
			{#if measurements.source_hash || measurements.mesh_signature}
				<div class="flex flex-col gap-0.5 text-[11px] text-gray-400 dark:text-gray-500">
					{#if measurements.source_hash}
						<span class="font-mono truncate">{$i18n.t('source')} {measurements.source_hash}</span>
					{/if}
					{#if measurements.mesh_signature}
						<span class="font-mono truncate">{$i18n.t('shape')} {measurements.mesh_signature}</span>
					{/if}
				</div>
			{/if}

			{#if provenance}
				<!-- Where the geometry came from, kept separate from what it measures. `exact`
				     is the load-bearing word: a STEP read gives real B-Rep solids, an STL read
				     gives a triangle shell that only looks like one, and every downstream claim
				     about tolerance depends on which. -->
				<div class="flex flex-col gap-0.5 text-[11px] text-gray-500 dark:text-gray-400">
					<span class="truncate"
						>{$i18n.t('Imported from')} <span class="font-mono">{provenance.name}</span> ·
						{provenance.kind.toUpperCase()} · {mb(provenance.bytes)}</span
					>
					{#if parsed}
						<span>
							{parsed.exact === true
								? $i18n.t('Read as exact solids — dimensions are the file’s own.')
								: parsed.exact === false
									? $i18n.t('Read as a triangle mesh — measurements are approximate.')
									: $i18n.t('The engine did not report how this file was read.')}
							{#if parsed.parser}· {parsed.parser}{/if}
						</span>
					{/if}
					<span class="font-mono truncate">sha256 {provenance.sha256.slice(0, 16)}…</span>
				</div>
			{/if}

			<div class="pt-1 border-t border-gray-100 dark:border-gray-850">
				<div class="text-xs font-medium mb-1.5 mt-2">{$i18n.t('Checks')}</div>
				<div class="flex flex-col gap-1 text-xs">
					<div class="flex items-center gap-2">
						<span
							class={measurements.brep_valid
								? 'text-green-600 dark:text-green-400'
								: 'text-red-500 dark:text-red-400'}>{measurements.brep_valid ? '✓' : '✕'}</span
						>
						<span
							>{$i18n.t('B-Rep valid')}{measurements.brep_valid
								? ''
								: ` — ${$i18n.t('the solid failed OpenCascade’s validity check')}`}</span
						>
					</div>
					<div class="flex items-center gap-2">
						<span
							class={expected === null || measurements.solid_count === expected
								? 'text-green-600 dark:text-green-400'
								: 'text-amber-600 dark:text-amber-400'}
							>{expected === null || measurements.solid_count === expected ? '✓' : '!'}</span
						>
						<span
							>{$i18n.t('Solids')}: {measurements.solid_count}{expected === null
								? ''
								: ` / ${expected} ${$i18n.t('expected')}`}</span
						>
					</div>
					{#if mesh?.parsed === false}
						<!-- The engine declined to give a verdict because it could not read the
						     exported mesh. That is not a pass, and it must not look like one. -->
						<div class="flex items-center gap-2 text-amber-600 dark:text-amber-400">
							<span>?</span>
							<span>{$i18n.t('Mesh not checked')}{mesh.reason ? ` — ${mesh.reason}` : ''}</span>
						</div>
					{:else if mesh}
						<div class="flex items-center gap-2">
							<span
								class={mesh.watertight
									? 'text-green-600 dark:text-green-400'
									: 'text-amber-600 dark:text-amber-400'}>{mesh.watertight ? '✓' : '!'}</span
							>
							<span
								>{$i18n.t('Watertight')}{mesh.watertight
									? ''
									: ` — ${mesh.open_edges} ${$i18n.t('open edges')}`}</span
							>
						</div>
						<div class="flex items-center gap-2">
							<span
								class={mesh.manifold
									? 'text-green-600 dark:text-green-400'
									: 'text-amber-600 dark:text-amber-400'}>{mesh.manifold ? '✓' : '!'}</span
							>
							<span
								>{$i18n.t('Manifold')}{mesh.manifold
									? ''
									: ` — ${mesh.non_manifold_edges} ${$i18n.t('edges shared by three or more triangles')}`}</span
							>
						</div>
						{#if mesh.degenerate_triangles}
							<div class="flex items-center gap-2 text-amber-600 dark:text-amber-400">
								<span>!</span>
								<span>{mesh.degenerate_triangles} {$i18n.t('degenerate triangles')}</span>
							</div>
						{/if}
					{/if}
				</div>
				<!-- Three separate statements, never merged. -->
				<p class="mt-1.5 text-[11px] text-gray-400 dark:text-gray-500">
					{$i18n.t(
						'These checks say the geometry is well-formed. They do not say the part is printable, strong, or safe.'
					)}
				</p>
			</div>

			<!-- The second question, kept visibly separate from the first. Everything above
			     asks whether the solid is sound; this asks whether it is the part that was
			     requested, measured against the DesignSpec frozen before the model ran. The
			     wrong 30 mm cube passed every check above. -->
			{#if conformance}
				<div class="pt-2 border-t border-gray-100 dark:border-gray-850">
					<div class="text-xs font-medium mb-1.5">
						{$i18n.t('Matches the request')}
						<span
							class={conformance.status === 'passed'
								? 'text-green-600 dark:text-green-400'
								: conformance.status === 'failed'
									? 'text-red-500 dark:text-red-400'
									: 'text-gray-500 dark:text-gray-400'}>· {conformance.status}</span
						>
					</div>
					<p class="text-[11px] text-gray-500 dark:text-gray-400 mb-1.5">{conformance.summary}</p>
					<div class="flex flex-col gap-1 text-xs">
						{#each conformance.checks as c}
							<!-- `ok` is tri-state and each state is a different answer: true passed,
							     false FAILED, null could not be measured. They must not look alike —
							     one grey glyph for all three is what hid every failed requirement. -->
							<div class="flex items-start gap-2">
								<span
									class={c.ok === true
										? 'text-green-600 dark:text-green-400'
										: c.ok === false
											? 'text-red-500 dark:text-red-400'
											: 'text-gray-400 dark:text-gray-500'}
									>{c.ok === true ? '✓' : c.ok === false ? '✕' : '?'}</span
								>
								<span class="min-w-0">
									{c.requirement || c.id}
									<span class="text-gray-500 dark:text-gray-400">
										— {c.ok === null
											? $i18n.t('not measured')
											: `${$i18n.t('measured')} ${quantity(c.measured)}`}{c.expected ===
											null || c.expected === undefined
											? ''
											: `, ${$i18n.t('asked for')} ${quantity(c.expected)}`}{c.tolerance_mm
											? ` ±${c.tolerance_mm} mm`
											: ''}</span
									>
									{#if c.detail && c.ok !== true}
										<!-- The grader's own words about what it saw. On a failure this is
										     the only line that says why, so it is never folded away. -->
										<span class="block text-[11px] text-gray-600 dark:text-gray-300"
											>{c.detail}</span
										>
									{/if}
									{#if c.note}
										<!-- Assumptions are shown, not hidden: a check written from a value
										     Harvis chose rather than one the user stated says so here. -->
										<span class="block text-[11px] text-gray-400 dark:text-gray-500"
											>{c.note}</span
										>
									{/if}
								</span>
							</div>
						{/each}
					</div>
				</div>
			{/if}
		{/if}
	{:else if tab === 'history'}
		<div class="flex flex-col gap-1">
			{#each revisions as rev}
				<div
					class="flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs {rev.id ===
					selectedRevision?.id
						? 'bg-gray-100 dark:bg-gray-850'
						: 'hover:bg-gray-50 dark:hover:bg-gray-900'}"
				>
					<button class="flex-1 text-left min-w-0" on:click={() => onSelectRevision(rev.id)}>
						<span class="font-medium">rev {rev.seq}</span>
						<span class="text-gray-500 dark:text-gray-400"> · {rev.created_by}</span>
						{#if rev.latest_build}
							<span class={statusTone(rev.latest_build.status)}> · {rev.latest_build.status}</span>
						{:else}
							<span class="text-gray-400 dark:text-gray-500"> · {$i18n.t('not built')}</span>
						{/if}
						<!-- Two separate facts, shown separately. A build can be `succeeded` and
						     still not be the requested part, and merging them into one word is how
						     the wrong cube came to be reported as a working one. -->
						{#if rev.latest_build?.conformance_status === 'failed'}
							<span class="text-red-500 dark:text-red-400">
								· {$i18n.t("doesn't match the request")}</span
							>
						{/if}
						{#if rev.state === 'proposal'}
							<span
								class="ml-1 px-1.5 py-0.5 rounded-md bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300"
								>{$i18n.t('proposal')}</span
							>
						{/if}
						{#if rev.provenance}
							<span class="text-gray-500 dark:text-gray-400 truncate">
								· {$i18n.t('imported')} {rev.provenance.name}</span
							>
						{/if}
					</button>
					{#if rev.source_kind === 'import'}
						<!-- No Build and no Restore, because neither is possible: the source file
						     was never kept, so there is nothing to hand the engine. The server
						     answers `import_not_rebuildable` to both, and offering a button whose
						     only outcome is that error would be a lie shaped like an affordance. -->
						<span class="text-[11px] text-gray-400 dark:text-gray-500 shrink-0"
							>{$i18n.t('import file not kept')}</span
						>
					{:else if !rev.latest_build}
						<button
							class="text-[11px] px-2 py-0.5 rounded-md border border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300 disabled:opacity-50 shrink-0"
							disabled={busy}
							on:click={() => buildFrom(rev, {})}>{$i18n.t('Build')}</button
						>
					{:else if rev.state === 'proposal'}
						<button
							class="text-[11px] px-2 py-0.5 rounded-md border border-amber-300 dark:border-amber-800 text-amber-700 dark:text-amber-300 disabled:opacity-50 shrink-0"
							disabled={busy}
							on:click={() => accept(rev)}>{$i18n.t('Accept')}</button
						>
					{:else if rev.id !== project.head_revision}
						<button
							class="text-[11px] px-2 py-0.5 rounded-md border border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300 disabled:opacity-50 shrink-0"
							disabled={busy}
							on:click={() => restore(rev)}>{$i18n.t('Restore')}</button
						>
					{/if}
				</div>
			{/each}
		</div>
	{:else if tab === 'compare'}
		{#if revisions.length < 2}
			<p class="text-xs text-gray-500 dark:text-gray-400">
				{$i18n.t('There is only one revision — nothing to compare it against yet.')}
			</p>
		{:else}
			<div class="flex items-center gap-2 text-xs">
				<select
					class="flex-1 min-w-0 px-2 py-1 rounded-lg bg-gray-50 dark:bg-gray-850 outline-none"
					bind:value={compareA}
				>
					{#each revisions as r}
						<option value={r.id}>rev {r.seq}</option>
					{/each}
				</select>
				<span class="text-gray-400">→</span>
				<select
					class="flex-1 min-w-0 px-2 py-1 rounded-lg bg-gray-50 dark:bg-gray-850 outline-none"
					bind:value={compareB}
				>
					{#each revisions as r}
						<option value={r.id}>rev {r.seq}</option>
					{/each}
				</select>
			</div>

			{#if compareA === compareB}
				<p class="text-xs text-gray-500 dark:text-gray-400">
					{$i18n.t('Pick two different revisions.')}
				</p>
			{:else if comparing}
				<p class="text-xs text-gray-500 dark:text-gray-400">{$i18n.t('Comparing…')}</p>
			{:else if compareError}
				<p class="text-xs text-amber-600 dark:text-amber-400">{compareError}</p>
			{:else if compareResult}
				<div class="flex flex-col gap-2 text-xs">
					<div>
						<div class="text-[11px] font-medium text-gray-600 dark:text-gray-300 mb-1">
							{$i18n.t('Parameters')}
						</div>
						{#if !Object.keys(compareResult.parameters ?? {}).length}
							<p class="text-[11px] text-gray-500 dark:text-gray-400">
								{$i18n.t('Identical — every parameter has the same value in both.')}
							</p>
						{:else}
							<div class="grid grid-cols-[1fr_auto_auto] gap-x-3 gap-y-0.5 text-[11px]">
								<span class="text-gray-400 dark:text-gray-500">{$i18n.t('name')}</span>
								<span class="text-gray-400 dark:text-gray-500 tabular-nums"
									>rev {seqOf(compareA)}</span
								>
								<span class="text-gray-400 dark:text-gray-500 tabular-nums"
									>rev {seqOf(compareB)}</span
								>
								{#each Object.entries(compareResult.parameters) as [k, d]}
									<span class="text-gray-600 dark:text-gray-300 truncate">{k}</span>
									<span class="tabular-nums">{value(d.a)}</span>
									<span class="tabular-nums text-emerald-600 dark:text-emerald-400"
										>{value(d.b)}</span
									>
								{/each}
							</div>
						{/if}
					</div>

					<div>
						<div class="text-[11px] font-medium text-gray-600 dark:text-gray-300 mb-1">
							{$i18n.t('Measurements')}
						</div>
						{#if compareResult.measurements === null}
							<!-- "No measurements yet" and "no change" are different answers, and the
							     server returns null rather than {} to keep them apart. -->
							<p class="text-[11px] text-gray-500 dark:text-gray-400">
								{$i18n.t('One of these revisions has never built successfully.')}
							</p>
						{:else if !Object.keys(compareResult.measurements).length}
							<p class="text-[11px] text-gray-500 dark:text-gray-400">
								{$i18n.t('Identical — the two builds measure the same.')}
							</p>
						{:else}
							<div class="grid grid-cols-[1fr_auto_auto] gap-x-3 gap-y-0.5 text-[11px]">
								{#each Object.entries(compareResult.measurements) as [k, d]}
									<span class="text-gray-600 dark:text-gray-300 truncate">{k}</span>
									<span class="tabular-nums">{value(d.a)}</span>
									<span class="tabular-nums text-emerald-600 dark:text-emerald-400"
										>{value(d.b)}</span
									>
								{/each}
							</div>
						{/if}
					</div>
				</div>
			{/if}
		{/if}
	{:else if tab === 'artifacts'}
		{#if !artifacts.length}
			<p class="text-xs text-gray-500 dark:text-gray-400">
				{$i18n.t('No files — this revision has not been built.')}
			</p>
		{:else}
			<div class="flex flex-col gap-1">
				{#each artifacts as a}
					<div
						class="flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs hover:bg-gray-50 dark:hover:bg-gray-900"
					>
						<span class="font-medium w-12 shrink-0">{a.format.toUpperCase()}</span>
						<span class="text-gray-500 dark:text-gray-400 tabular-nums shrink-0"
							>{size(a.size_bytes)}</span
						>
						<span
							class="text-[11px] font-mono text-gray-400 dark:text-gray-500 truncate flex-1"
							title={a.sha256}>{a.sha256.slice(0, 16)}…</span
						>
						<button
							class="text-[11px] px-2 py-0.5 rounded-md border border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300 shrink-0"
							on:click={() => download(a)}>{$i18n.t('Download')}</button
						>
					</div>
				{/each}
			</div>
		{/if}
	{/if}

	{#if showStatusLine && statusLine}
		<p class="text-[11px] text-gray-500 dark:text-gray-400">{statusLine}</p>
	{/if}
</div>
