<script lang="ts">
	// CAD Studio — the Gate 4 vertical slice: pick or create a project, look at the
	// built part, change a parameter, get a new revision, restore an older one, and
	// export the four formats.
	//
	// Two things here are worth knowing before reading the code.
	//
	// A project is created with revision 1 and NO build — that is the store's
	// contract, not an oversight. So the first geometry comes from appending a
	// revision, and "Build" on an unbuilt revision means "append a revision carrying
	// these parameters and build that". Every build in this lane belongs to the
	// revision that produced it; nothing is ever rebuilt in place.
	//
	// Parameter bounds come from `/api/cad/capability`, which reads them from the
	// engine. There is no copy of them in this file: a slider that disagreed with the
	// engine would offer values the engine refuses.
	//
	// This component is host-independent — it lives in `$lib/cad`, not under
	// ChatControls, because the CAD workspace is a place of its own (`/harvis/cad`)
	// and chat is only one of the things that can point at it.
	import { getContext, onMount, onDestroy } from 'svelte';
	import { toast } from 'svelte-sonner';

	import CadViewer from './CadViewer.svelte';
	import {
		CadApiError,
		cadArtifactUrl,
		createCadProject,
		createCadRevision,
		downloadCadArtifact,
		getCadCapability,
		getCadProject,
		getCadRecipeSource,
		listCadProjects,
		pollCadBuild,
		restoreCadRevision,
		type CadArtifact,
		type CadCapability,
		type CadFormat,
		type CadProject,
		type CadRecipeSource,
		type CadRevision
	} from '$lib/apis/cad';

	const i18n: any = getContext('i18n');

	/** Open this project on mount instead of the most recently updated one. This is
	 *  what makes `/harvis/cad/{id}` a real deep link rather than a decorative URL. An
	 *  id the caller does not own 404s in `getCadProject`, so a guessed id leaks
	 *  nothing — the route layer, not this component, is what enforces that. */
	export let initialProjectId = '';

	/** Viewport height in pixels. The chat rail is narrow and short; the dedicated
	 *  route has a whole page, and 300px there wastes most of it. */
	export let viewerHeight = 300;

	const FORMATS: CadFormat[] = ['stl', 'step', 'glb', '3mf'];

	let capability: CadCapability | null = null;
	let projects: CadProject[] = [];
	let project: CadProject | null = null;
	let selectedRevisionId = '';

	type Tab = 'parameters' | 'features' | 'inspect' | 'validate' | 'versions' | 'source' | 'files';
	const TABS: [Tab, string][] = [
		['parameters', 'Parameters'],
		['features', 'Features'],
		['inspect', 'Inspect'],
		['validate', 'Validate'],
		['versions', 'Versions'],
		['source', 'Source'],
		['files', 'Files']
	];
	let tab: Tab = 'parameters';

	// The CadIR document behind a recipe, fetched once per recipe and only when a tab
	// that shows it is opened. Keyed by recipe name because that is what the document
	// belongs to — every revision built from `studded_brick_v1` shows the same one.
	let recipeSources: Record<string, CadRecipeSource> = {};
	let sourceLoading = false;
	let sourceError = '';

	let loading = true;
	let busy = false;
	let statusLine = '';
	let newTitle = '';
	let newRecipe = '';
	let params: Record<string, number> = {};
	let creating = false;

	let abort: AbortController | null = null;

	$: revisions = project?.revisions ?? [];
	$: selectedRevision =
		revisions.find((r) => r.id === selectedRevisionId) ?? revisions[0] ?? null;
	$: latestBuild = selectedRevision?.latest_build ?? null;
	$: artifacts = (latestBuild?.artifacts ?? []) as CadArtifact[];
	$: viewable =
		latestBuild?.status === 'succeeded'
			? (artifacts.find((a) => a.format === 'glb') ??
				artifacts.find((a) => a.format === 'stl') ??
				null)
			: null;
	$: viewUrl = latestBuild && viewable ? cadArtifactUrl(latestBuild.id, viewable.id) : '';
	$: paramSpec =
		(selectedRevision?.recipe_name &&
			capability?.recipe_params?.[selectedRevision.recipe_name]?.parameters) ||
		[];
	$: measurements = (latestBuild?.validation ?? null) as Record<string, any> | null;
	// The triangle-level report is nested under `mesh`, and `parsed: false` is a real
	// state: the engine refuses to give a watertight/manifold verdict on a file it could
	// not read, and this panel must not turn that silence into a pass.
	$: mesh = (measurements?.mesh ?? null) as Record<string, any> | null;
	$: recipeName = selectedRevision?.recipe_name ?? '';
	$: recipeSource = recipeName ? (recipeSources[recipeName] ?? null) : null;

	// Fetch the CadIR document the first time a tab that needs it is opened. Guarded on
	// both the cache and the in-flight flag so re-running this statement — which Svelte
	// does on every `tab` or revision change — cannot start a second request.
	$: if (
		(tab === 'features' || tab === 'source') &&
		recipeName &&
		!recipeSources[recipeName] &&
		!sourceLoading
	) {
		loadRecipeSource(recipeName);
	}

	const fmt = (n: number | null | undefined, digits = 1) =>
		typeof n === 'number' && isFinite(n) ? n.toFixed(digits) : '—';

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

	// Seed the editor from the revision being looked at, falling back to the engine's
	// declared defaults. Never from the previous revision's edits — the sliders must
	// show what this revision actually is.
	const seedParams = (rev: CadRevision | null) => {
		const spec =
			(rev?.recipe_name && capability?.recipe_params?.[rev.recipe_name]?.parameters) || [];
		const next: Record<string, number> = {};
		for (const p of spec) {
			const v = rev?.parameters?.[p.name];
			next[p.name] = typeof v === 'number' ? v : p.default;
		}
		params = next;
	};

	const loadRecipeSource = async (recipe: string) => {
		sourceLoading = true;
		sourceError = '';
		try {
			const doc = await getCadRecipeSource(recipe);
			recipeSources = { ...recipeSources, [recipe]: doc };
		} catch (e: any) {
			// Shown in place rather than raised as a toast: the rest of the studio still
			// works, and a part whose source cannot be read is a fact about one tab.
			sourceError = e?.message ?? `${e}`;
		} finally {
			sourceLoading = false;
		}
	};

	const loadCapability = async () => {
		capability = await getCadCapability();
		if (capability?.recipes?.length && !newRecipe) newRecipe = capability.recipes[0];
	};

	const loadProjects = async () => {
		try {
			projects = await listCadProjects();
		} catch (e: any) {
			projects = [];
			if (!(e instanceof CadApiError && e.status === 404)) {
				toast.error(e?.message ?? `${e}`);
			}
		}
	};

	/** Re-reads a project and returns it. The return value matters: reactive
	 *  derivations do not update inside an in-flight async function, so callers that
	 *  need a revision right after a reload must take it from here. */
	const openProject = async (id: string): Promise<CadProject | null> => {
		try {
			const p = await getCadProject(id);
			project = p;
			const revs = p.revisions ?? [];
			if (!revs.some((r) => r.id === selectedRevisionId)) {
				selectedRevisionId = revs[0]?.id ?? '';
			}
			seedParams(revs.find((r) => r.id === selectedRevisionId) ?? null);
			return p;
		} catch (e: any) {
			toast.error(e?.message ?? `${e}`);
			return null;
		}
	};

	const selectRevision = (id: string) => {
		selectedRevisionId = id;
		seedParams(revisions.find((r) => r.id === id) ?? null);
	};

	/** Wait for a build to finish, then re-read the project so the version list and
	 *  the viewport agree with the store rather than with an optimistic guess. */
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
			if (project) await openProject(project.id);
		}
	};

	const createProject = async () => {
		if (!newRecipe) return;
		creating = true;
		try {
			const p = await createCadProject({
				title: newTitle.trim() || $i18n.t('Untitled part'),
				recipe: newRecipe,
				formats: FORMATS
			});
			newTitle = '';
			await loadProjects();
			const opened = await openProject(p.id);
			// Revision 1 exists with no geometry — the store creates projects without a
			// build on purpose. Build it straight away; a part that opens on an empty
			// viewport reads as broken.
			//
			// `params` and not `{}`: openProject has just seeded it from the engine's
			// declared defaults, and sending them makes the revision record what it was
			// actually built with. An empty map builds the identical part but leaves a row
			// that cannot say which values produced it.
			await buildFrom(opened?.revisions?.[0] ?? null, params);
		} catch (e: any) {
			toast.error(e?.message ?? `${e}`);
		} finally {
			creating = false;
		}
	};

	/** Append a revision carrying `overrides` on top of `rev`'s parameters, and build
	 *  it. A 409 means someone else moved the head — say so instead of forking. */
	const buildFrom = async (rev: CadRevision | null, overrides: Record<string, number>) => {
		if (!project || !rev) return;
		try {
			const accepted = await createCadRevision(project.id, {
				base_revision_id: rev.id,
				recipe: rev.recipe_name ?? newRecipe,
				params: { ...(rev.parameters ?? {}), ...overrides },
				formats: FORMATS
			});
			selectedRevisionId = accepted.revision_id;
			await followBuild(accepted.build_id, $i18n.t('Revision {{seq}}', { seq: accepted.seq }));
		} catch (e: any) {
			if (e instanceof CadApiError && e.status === 409) {
				toast.error($i18n.t('This project changed elsewhere — reloading it.'));
				await openProject(project.id);
			} else {
				toast.error(e?.message ?? `${e}`);
			}
		}
	};

	const applyParameters = async () => {
		if (!selectedRevision) return;
		// Build from the head, not from the revision on screen: appending to an older
		// revision is what the 409 exists to prevent.
		const head = revisions.find((r) => r.id === project?.head_revision) ?? revisions[0];
		await buildFrom(head, params);
	};

	const restore = async (rev: CadRevision) => {
		if (!project) return;
		try {
			const accepted = await restoreCadRevision(project.id, rev.id);
			selectedRevisionId = accepted.revision_id;
			await followBuild(
				accepted.build_id,
				$i18n.t('Restored revision {{seq}}', { seq: rev.seq })
			);
		} catch (e: any) {
			toast.error(e?.message ?? `${e}`);
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

	onMount(async () => {
		await loadCapability();
		if (capability?.enabled) {
			await loadProjects();
			// A deep link wins over "the most recent one" even when the id is not in the
			// list — the list is this user's projects, and openProject is what decides
			// whether the id is theirs.
			const target = initialProjectId || projects[0]?.id;
			if (target) await openProject(target);
		}
		loading = false;
	});

	onDestroy(() => abort?.abort());
</script>

<div class="flex flex-col w-full h-full text-sm">
	{#if loading}
		<div class="p-4 text-xs text-gray-500 dark:text-gray-400">{$i18n.t('Loading…')}</div>
	{:else if !capability || !capability.enabled}
		<div class="p-4 text-xs text-gray-500 dark:text-gray-400">
			{$i18n.t('Local CAD is not enabled on this server.')}
		</div>
	{:else}
		<!-- Top bar: which project, which revision, and what the engine is doing. -->
		<div
			class="flex flex-wrap items-center gap-2 px-3 py-2 border-b border-gray-100 dark:border-gray-850"
		>
			<select
				class="text-xs bg-transparent outline-none max-w-[45%] truncate"
				value={project?.id ?? ''}
				on:change={(e) => {
					const id = (e.target as HTMLSelectElement).value;
					if (id) openProject(id);
				}}
			>
				{#if !projects.length}
					<option value="">{$i18n.t('No parts yet')}</option>
				{:else if !project}
					<!-- Nothing open, but parts exist — a deep link that 404'd lands here.
					     Without this the select's value matches no option and the browser
					     renders an empty box, which reads as "you have no parts". -->
					<option value="">{$i18n.t('Select a part')}</option>
				{/if}
				{#each projects as p}
					<option value={p.id}>{p.title}</option>
				{/each}
			</select>

			{#if selectedRevision}
				<span class="text-[11px] text-gray-500 dark:text-gray-400"
					>rev {selectedRevision.seq}</span
				>
			{/if}
			{#if latestBuild}
				<span class="text-[11px] {statusTone(latestBuild.status)}">{latestBuild.status}</span>
			{/if}
			{#if statusLine}
				<span class="text-[11px] text-gray-500 dark:text-gray-400">{statusLine}</span>
			{/if}
			{#if !capability.engine_reachable}
				<span class="text-[11px] text-amber-600 dark:text-amber-400"
					>{$i18n.t('engine unreachable')}</span
				>
			{/if}
		</div>

		<div class="flex-1 overflow-y-auto px-3 py-3 flex flex-col gap-3">
			{#if !project}
				<!-- New part -->
				<div class="flex flex-col gap-2">
					<div class="text-xs text-gray-500 dark:text-gray-400">
						{$i18n.t('Start a part from a trusted template. Every dimension stays editable.')}
					</div>
					<input
						class="w-full text-sm px-2.5 py-1.5 rounded-lg bg-gray-50 dark:bg-gray-850 outline-none"
						placeholder={$i18n.t('Part name')}
						bind:value={newTitle}
					/>
					<select
						class="w-full text-sm px-2.5 py-1.5 rounded-lg bg-gray-50 dark:bg-gray-850 outline-none"
						bind:value={newRecipe}
					>
						{#each capability.recipes as r}
							<option value={r}>{r}</option>
						{/each}
					</select>
					<button
						class="self-start text-xs px-3 py-1.5 rounded-lg bg-gray-900 text-white dark:bg-white dark:text-gray-900 disabled:opacity-50"
						disabled={creating || !capability.engine_reachable}
						on:click={createProject}
						>{creating ? $i18n.t('Creating…') : $i18n.t('Create part')}</button
					>
				</div>
			{:else}
				<CadViewer
					url={viewUrl}
					format={viewable?.format === 'stl' ? 'stl' : 'glb'}
					height={viewerHeight}
				/>

				{#if latestBuild?.status === 'failed'}
					<div class="text-xs text-red-500 dark:text-red-400">
						{latestBuild.error_detail || latestBuild.error_code}
					</div>
				{/if}

				{#if measurements}
					<!-- Measured by the engine after the build, not predicted before it. -->
					<div class="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-gray-500 dark:text-gray-400">
						<span
							>{$i18n.t('Bounding box')}: {fmt(measurements.bbox_mm?.x)} × {fmt(
								measurements.bbox_mm?.y
							)} × {fmt(measurements.bbox_mm?.z)} mm</span
						>
						<span>{$i18n.t('Volume')}: {fmt(measurements.volume_mm3, 0)} mm³</span>
						<span>{$i18n.t('Solids')}: {measurements.solid_count ?? '—'}</span>
						<span
							>{$i18n.t('Watertight')}: {mesh?.watertight === true
								? $i18n.t('yes')
								: mesh?.watertight === false
									? $i18n.t('no')
									: '—'}</span
						>
					</div>
				{/if}

				<!-- Seven tabs is more than fits a narrow rail, which is part of why the
				     studio moved to its own route. It scrolls rather than wrapping so the
				     strip stays one line at any width. -->
				<div
					class="flex gap-1 border-b border-gray-100 dark:border-gray-850 overflow-x-auto scrollbar-none"
				>
					{#each TABS as [t, label]}
						<button
							class="px-2.5 py-1 text-xs rounded-t-lg transition shrink-0 {tab === t
								? 'font-medium text-gray-900 dark:text-white border-b-2 border-gray-900 dark:border-white'
								: 'text-gray-500 dark:text-gray-400'}"
							on:click={() => (tab = t)}>{$i18n.t(label)}</button
						>
					{/each}
				</div>

				{#if tab === 'parameters'}
					{#if !paramSpec.length}
						<div class="text-xs text-gray-500 dark:text-gray-400">
							{$i18n.t('Parameter ranges are unavailable while the engine is unreachable.')}
						</div>
					{:else}
						<div class="flex flex-col gap-2.5">
							{#each paramSpec as p}
								<div class="flex flex-col gap-1">
									<div class="flex items-center justify-between text-[11px]">
										<span class="text-gray-600 dark:text-gray-300">{p.name}</span>
										<span class="text-gray-500 dark:text-gray-400 tabular-nums"
											>{params[p.name]}</span
										>
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
									disabled={busy || !capability.engine_reachable}
									on:click={applyParameters}
									>{busy ? $i18n.t('Building…') : $i18n.t('Build revision')}</button
								>
								<button
									class="text-xs px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300"
									disabled={busy}
									on:click={() => seedParams(selectedRevision)}>{$i18n.t('Reset')}</button
								>
							</div>
						</div>
					{/if}
				{:else if tab === 'versions'}
					<div class="flex flex-col gap-1">
						{#each revisions as rev}
							<div
								class="flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs {rev.id ===
								selectedRevision?.id
									? 'bg-gray-100 dark:bg-gray-850'
									: 'hover:bg-gray-50 dark:hover:bg-gray-900'}"
							>
								<button class="flex-1 text-left" on:click={() => selectRevision(rev.id)}>
									<span class="font-medium">rev {rev.seq}</span>
									<span class="text-gray-500 dark:text-gray-400"> · {rev.created_by}</span>
									{#if rev.latest_build}
										<span class="{statusTone(rev.latest_build.status)}">
											· {rev.latest_build.status}</span
										>
									{:else}
										<span class="text-gray-400 dark:text-gray-500"> · {$i18n.t('not built')}</span
										>
									{/if}
								</button>
								{#if rev.id !== project.head_revision}
									<button
										class="text-[11px] px-2 py-0.5 rounded-md border border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300 disabled:opacity-50"
										disabled={busy}
										on:click={() => restore(rev)}>{$i18n.t('Restore')}</button
									>
								{:else if !rev.latest_build}
									<button
										class="text-[11px] px-2 py-0.5 rounded-md border border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300 disabled:opacity-50"
										disabled={busy}
										on:click={() => buildFrom(rev, {})}>{$i18n.t('Build')}</button
									>
								{/if}
							</div>
						{/each}
					</div>
				{:else if tab === 'features'}
					{#if sourceLoading}
						<div class="text-xs text-gray-500 dark:text-gray-400">{$i18n.t('Loading…')}</div>
					{:else if sourceError}
						<div class="text-xs text-amber-600 dark:text-amber-400">{sourceError}</div>
					{:else if !recipeSource}
						<div class="text-xs text-gray-500 dark:text-gray-400">
							{$i18n.t('This part has no feature list — it was not built from a template.')}
						</div>
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
						<!-- Said plainly rather than left to be discovered by clicking. The spike
						     behind Gate 5 showed the mapping is possible — one glTF primitive per
						     B-Rep face — but nothing emits the manifest yet, so every feature here
						     reports selectable: false and the viewport selects whole bodies. -->
						<div class="text-[11px] text-gray-400 dark:text-gray-500">
							{$i18n.t(
								'Selecting an individual face in the viewport is not available yet — selection is whole-body.'
							)}
						</div>
					{/if}
				{:else if tab === 'inspect'}
					{#if !measurements}
						<div class="text-xs text-gray-500 dark:text-gray-400">
							{$i18n.t('Nothing to measure — this revision has not been built.')}
						</div>
					{:else}
						<!-- Every number here was measured by the engine off the built solid.
						     None of it is predicted, and none of it comes from the model. -->
						<div class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
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
						<!-- The two identities Gate 2 settled on. `source_hash` is what two
						     revisions are compared on; `mesh_signature` is what proves two builds
						     of the same input produced the same shape. Neither is a file hash —
						     STEP embeds a wall-clock timestamp and 3MF is a ZIP. -->
						{#if measurements.source_hash || measurements.mesh_signature}
							<div class="flex flex-col gap-0.5 text-[11px] text-gray-400 dark:text-gray-500">
								{#if measurements.source_hash}
									<span class="font-mono truncate"
										>{$i18n.t('source')} {measurements.source_hash}</span
									>
								{/if}
								{#if measurements.mesh_signature}
									<span class="font-mono truncate"
										>{$i18n.t('shape')} {measurements.mesh_signature}</span
									>
								{/if}
							</div>
						{/if}
					{/if}
				{:else if tab === 'validate'}
					{#if !measurements}
						<div class="text-xs text-gray-500 dark:text-gray-400">
							{$i18n.t('Nothing to check — this revision has not been built.')}
						</div>
					{:else}
						{@const expected =
							(recipeName && capability.recipe_params?.[recipeName]?.expected_solids) ?? null}
						<div class="flex flex-col gap-1 text-xs">
							<div class="flex items-center gap-2">
								<span
									class={measurements.brep_valid
										? 'text-green-600 dark:text-green-400'
										: 'text-red-500 dark:text-red-400'}
									>{measurements.brep_valid ? '✓' : '✕'}</span
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
									<span
										>{$i18n.t('Mesh not checked')}{mesh.reason ? ` — ${mesh.reason}` : ''}</span
									>
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
										<span
											>{mesh.degenerate_triangles}
											{$i18n.t('degenerate triangles')}</span
										>
									</div>
								{/if}
							{/if}
						</div>
						<!-- Three separate statements, never merged. -->
						<div class="text-[11px] text-gray-400 dark:text-gray-500">
							{$i18n.t(
								'These checks say the geometry is well-formed. They do not say the part is printable, strong, or safe.'
							)}
						</div>
					{/if}
				{:else if tab === 'source'}
					{#if sourceLoading}
						<div class="text-xs text-gray-500 dark:text-gray-400">{$i18n.t('Loading…')}</div>
					{:else if sourceError}
						<div class="text-xs text-amber-600 dark:text-amber-400">{sourceError}</div>
					{:else if !recipeSource}
						<div class="text-xs text-gray-500 dark:text-gray-400">
							{$i18n.t('This part has no source document — it was not built from a template.')}
						</div>
					{:else}
						<div class="flex flex-col gap-2">
							<div class="text-[11px] text-gray-500 dark:text-gray-400">
								{recipeSource.recipe} · CadIR {recipeSource.schema_version} · {recipeSource.units}
							</div>
							{#if selectedRevision && Object.keys(selectedRevision.parameters ?? {}).length}
								<!-- The document is shared by every revision of this recipe; these are
								     the values THIS revision resolved it with. -->
								<div class="grid grid-cols-[auto_1fr] gap-x-3 text-[11px]">
									{#each Object.entries(selectedRevision.parameters ?? {}) as [k, v]}
										<span class="text-gray-500 dark:text-gray-400">{k}</span>
										<span class="tabular-nums">{v}</span>
									{/each}
								</div>
							{:else}
								<!-- Revisions built before the studio started sending resolved defaults
								     recorded an empty map. Naming the values used would be a guess; an
								     empty map means exactly "the defaults in the document below". -->
								<div class="text-[11px] text-gray-500 dark:text-gray-400">
									{$i18n.t(
										'This revision recorded no explicit values — it was built with the defaults below.'
									)}
								</div>
							{/if}
							<pre
								class="text-[11px] font-mono whitespace-pre overflow-x-auto p-2 rounded-lg bg-gray-50 dark:bg-gray-900">{JSON.stringify(
									recipeSource.document,
									null,
									2
								)}</pre>
						</div>
					{/if}
				{:else if tab === 'files'}
					{#if !artifacts.length}
						<div class="text-xs text-gray-500 dark:text-gray-400">
							{$i18n.t('No files — this revision has not been built.')}
						</div>
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

				{#if artifacts.length && tab !== 'files'}
					<div class="flex flex-wrap items-center gap-1 pt-1">
						<span class="text-[11px] text-gray-500 dark:text-gray-400 mr-1"
							>{$i18n.t('Export')}</span
						>
						{#each artifacts as a}
							<button
								class="text-[11px] px-2 py-0.5 rounded-md border border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-850"
								on:click={() => download(a)}
								title={`${a.size_bytes} bytes · sha256 ${a.sha256.slice(0, 12)}…`}
								>{a.format.toUpperCase()}</button
							>
						{/each}
					</div>
				{/if}

				<button
					class="self-start text-[11px] text-gray-500 dark:text-gray-400 hover:underline"
					on:click={() => {
						project = null;
						selectedRevisionId = '';
					}}>{$i18n.t('New part')}</button
				>
			{/if}

			<div class="mt-auto pt-2 text-[10px] text-gray-400 dark:text-gray-500">
				{$i18n.t('Storage')}: {mb(capability.quota.user_used_bytes)} / {mb(
					capability.quota.user_limit_bytes
				)}
			</div>
		</div>
	{/if}
</div>
