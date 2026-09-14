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
	// What this file still owns is the *page*: which project is open, the viewport, the
	// measured summary, creating a part from a template, and importing a file. The six
	// editing panels underneath — Design, Parameters, Validate, History, Compare,
	// Artifacts — are CadContextPanels, the same component the in-chat focus workspace
	// mounts. They were duplicated once and drifted; there is one copy now.
	//
	// This component is host-independent — it lives in `$lib/cad`, not under
	// ChatControls, because the CAD workspace is a place of its own (`/harvis/cad`)
	// and chat is only one of the things that can point at it.
	import { getContext, onMount, onDestroy } from 'svelte';
	import { toast } from 'svelte-sonner';

	import CadContextPanels, { CAD_PANELS, type CadPanelId } from './CadContextPanels.svelte';
	import CadViewer from './CadViewer.svelte';
	import {
		CadApiError,
		cadArtifactUrl,
		cadNodeColors,
		createCadProject,
		createCadRevision,
		downloadCadArtifact,
		getCadCapability,
		getCadProject,
		importCadAsset,
		listCadProjects,
		pollCadBuild,
		type CadArtifact,
		type CadCapability,
		type CadFormat,
		type CadProject,
		type CadRevision
	} from '$lib/apis/cad';
	import { uploadFile } from '$lib/apis/files';

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

	// The panels themselves live in CadContextPanels, which the in-chat focus workspace
	// mounts too. This route keeps the strip because it also has a New-part flow and an
	// import control, neither of which belongs in a shared panel component.
	let tab: CadPanelId = 'parameters';

	let loading = true;
	let busy = false;
	let statusLine = '';
	let newTitle = '';
	let newRecipe = '';
	let params: Record<string, number> = {};
	let creating = false;

	// Import lives behind the server's own list of readable kinds rather than a constant
	// here. `FORMATS` is what the engine WRITES, and it includes GLB — build123d exports
	// glTF and ships no reader for it, so a picker built from `FORMATS` would offer a
	// kind every choice of which the server refuses. An older backend that publishes no
	// `import_kinds` shows no Import control at all, which is the honest reading of
	// "this server cannot do that".
	let importInput: HTMLInputElement;
	let importing = false;
	$: importKinds = capability?.import_kinds ?? [];
	$: importAccept = importKinds.map((k) => `.${k}`).join(',');

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
	// Per-part colours come from the build's own manifest (CS-2), so this panel and the
	// focus workspace paint the same part the same colour.
	$: nodeColors = cadNodeColors(latestBuild?.scene_manifest);
	/** A body the Code panel or a build error asked the viewport to point at. This is a
	 *  highlight, not a selection: this surface has no composer, so revealing a part must
	 *  not manufacture a chip the user never clicked. Cleared when the revision changes,
	 *  because node ids belong to the build that produced them. */
	let revealedNodeId = '';
	$: if (latestBuild?.id) revealedNodeId = '';
	$: measurements = (latestBuild?.validation ?? null) as Record<string, any> | null;
	// The triangle-level report is nested under `mesh`, and `parsed: false` is a real
	// state: the engine refuses to give a watertight/manifold verdict on a file it could
	// not read, and this panel must not turn that silence into a pass.
	$: mesh = (measurements?.mesh ?? null) as Record<string, any> | null;

	const fmt = (n: number | null | undefined, digits = 1) =>
		typeof n === 'number' && isFinite(n) ? n.toFixed(digits) : '—';

	const mb = (n: number) => `${(n / 1024 / 1024).toFixed(1)} MB`;

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

	/** Upload a STEP/STL/3MF/BREP file and turn it into a part of its own.
	 *
	 *  The bytes go to OWUI's file store first and the CAD route is given only the id it
	 *  gets back, which the backend resolves through the ownership-checked attachment
	 *  path. The browser never hands geometry to the CAD lane directly, and the id is
	 *  useless to anyone who does not own the upload.
	 *
	 *  `process: false` on the upload is deliberate: the processing pass is RAG text
	 *  extraction, and running it over a binary solid model does nothing but burn time
	 *  and log a parse failure.
	 *
	 *  An import always creates its own project rather than appending to the open one. An
	 *  imported body has no parameters and cannot be rebuilt — dropping one into the
	 *  middle of a parametric part's history would leave a head that the Parameters tab
	 *  cannot edit and Restore cannot reproduce. */
	const importAsset = async (event: Event) => {
		const input = event.target as HTMLInputElement;
		const file = input.files?.[0];
		// Reset immediately: picking the same file twice in a row fires no `change` event
		// otherwise, and a failed import is exactly when someone retries the same file.
		input.value = '';
		if (!file) return;

		const ext = file.name.includes('.') ? file.name.split('.').pop()!.toLowerCase() : '';
		if (!importKinds.includes(ext)) {
			toast.error(
				$i18n.t('Harvis cannot read that file — supported: {{kinds}}', {
					kinds: importKinds.map((k) => `.${k}`).join(', ')
				})
			);
			return;
		}
		const cap = capability?.import_max_bytes ?? 0;
		if (cap && file.size > cap) {
			toast.error(
				$i18n.t('That file is {{mb}} MB, over the {{cap}} MB limit.', {
					mb: (file.size / 1048576).toFixed(1),
					cap: Math.floor(cap / 1048576)
				})
			);
			return;
		}

		importing = true;
		statusLine = $i18n.t('Uploading…');
		try {
			const uploaded = await uploadFile(localStorage.token, file, null, false);
			if (!uploaded?.id) throw new Error($i18n.t('The upload did not return a file id.'));
			const accepted = await importCadAsset({
				attachment: {
					name: file.name,
					file_id: uploaded.id,
					mime_type: file.type || undefined
				},
				// No `formats`: which exports an imported body may claim is the server's
				// call, not this panel's. It withholds STEP from a mesh import on purpose,
				// and restating that rule here would give it two places to drift.
				title: file.name.replace(/\.[^.]+$/, '') || file.name
			});
			await loadProjects();
			await openProject(accepted.project_id);
			selectedRevisionId = accepted.revision_id;
			await followBuild(accepted.build_id, $i18n.t('Imported {{name}}', { name: file.name }));
		} catch (e: any) {
			statusLine = '';
			toast.error(e?.message ?? `${e}`);
		} finally {
			importing = false;
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
			{#if selectedRevision?.state === 'proposal'}
				<!-- Said here, at the top, because it changes what every other control on
				     this panel means: a proposal is not the project, and a parameter edit
				     will not build from it until someone accepts it. -->
				<span
					class="text-[11px] px-1.5 py-0.5 rounded-md bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300"
					>{$i18n.t('proposal')}</span
				>
			{/if}
			{#if latestBuild}
				<span class="text-[11px] {statusTone(latestBuild.status)}">{latestBuild.status}</span>
			{/if}
			{#if latestBuild?.conformance_status === 'failed'}
				<span class="text-[11px] text-red-500 dark:text-red-400"
					>{$i18n.t("doesn't match the request")}</span
				>
			{/if}
			{#if statusLine}
				<span class="text-[11px] text-gray-500 dark:text-gray-400">{statusLine}</span>
			{/if}
			{#if !capability.engine_reachable}
				<span class="text-[11px] text-amber-600 dark:text-amber-400"
					>{$i18n.t('engine unreachable')}</span
				>
			{/if}

			{#if importKinds.length}
				<!-- Always reachable, unlike the new-part block, which only exists while
				     nothing is open. Importing a file is not "starting from a template" and
				     should not be hidden behind having no part open. -->
				<button
					class="ml-auto text-[11px] px-2 py-1 rounded-lg bg-gray-50 dark:bg-gray-850 text-gray-600 dark:text-gray-300 disabled:opacity-50"
					disabled={importing || busy || !capability.engine_reachable}
					title={$i18n.t('Import {{kinds}}', {
						kinds: importKinds.map((k) => `.${k}`).join(' ')
					})}
					on:click={() => importInput?.click()}
					>{importing ? $i18n.t('Importing…') : $i18n.t('Import file')}</button
				>
			{/if}
		</div>

		<!-- One input for both entry points. `accept` comes from the server's readable
		     kinds, and the same list is re-checked in `importAsset` — `accept` is a picker
		     filter a user can defeat by typing a name, not a validation. -->
		<input
			bind:this={importInput}
			class="hidden"
			type="file"
			accept={importAccept}
			on:change={importAsset}
		/>

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

					{#if importKinds.length}
						<div class="pt-1 text-xs text-gray-500 dark:text-gray-400">
							{$i18n.t(
								'Or import a file you already have. It opens as reference geometry — measurable and exportable, with no editable dimensions recovered from it.'
							)}
						</div>
						<button
							class="self-start text-xs px-3 py-1.5 rounded-lg bg-gray-50 dark:bg-gray-850 text-gray-700 dark:text-gray-200 disabled:opacity-50"
							disabled={importing || !capability.engine_reachable}
							on:click={() => importInput?.click()}
							>{importing
								? $i18n.t('Importing…')
								: $i18n.t('Import {{kinds}}', {
										kinds: importKinds.map((k) => `.${k}`).join(' ')
									})}</button
						>
					{/if}
				</div>
			{:else}
				<CadViewer
					url={viewUrl}
					format={viewable?.format === 'stl' ? 'stl' : 'glb'}
					height={viewerHeight}
					{nodeColors}
					selectedNodeId={revealedNodeId}
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

				<!-- Six panels is more than fits a narrow rail, which is part of why the
				     studio moved to its own route. The strip scrolls rather than wrapping so
				     it stays one line at any width. The panels themselves are the shared
				     component — the in-chat focus workspace renders the same six. -->
				<div
					class="flex gap-1 border-b border-gray-100 dark:border-gray-850 overflow-x-auto scrollbar-none"
					role="tablist"
				>
					{#each CAD_PANELS as [t, label]}
						<button
							role="tab"
							aria-selected={tab === t}
							class="px-2.5 py-1 text-xs rounded-t-lg transition shrink-0 {tab === t
								? 'font-medium text-gray-900 dark:text-white border-b-2 border-gray-900 dark:border-white'
								: 'text-gray-500 dark:text-gray-400'}"
							on:click={() => (tab = t)}>{$i18n.t(label)}</button
						>
					{/each}
				</div>

				<CadContextPanels
					{tab}
					{project}
					{capability}
					{selectedRevisionId}
					onSelectRevision={selectRevision}
					onRevealNode={(nodeId) => (revealedNodeId = nodeId)}
					onChanged={async () => {
						if (project) await openProject(project.id);
					}}
					bind:busy
				/>

				{#if artifacts.length && tab !== 'artifacts'}
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
