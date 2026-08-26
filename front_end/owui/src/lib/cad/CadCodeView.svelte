<script lang="ts">
	// A revision as a read-only project (CS-3), in one implementation.
	//
	// Two surfaces show these files — the studio's Code panel and the session workspace's
	// left rail, where the spec splits them into a Files section and a Code section. They
	// are the same tree over the same revision, so this component owns the fetch, the
	// open-file selection and the "generated, not authored" wording, and the hosts choose
	// which halves to draw. A second copy would drift, and the thing it would drift on is
	// the sentence that tells someone these files cannot be edited.
	//
	// Everything here is derived by the server on each read: there is no file table and no
	// writer, which is why there is no save control and why `read_only` is read from the
	// response rather than assumed. Harvis does not invent a source language — what a
	// revision has is what is shown, and what it does not have is said in a sentence.
	import { getContext } from 'svelte';

	import { getCadRevisionFiles, type CadFile, type CadFileTree } from '$lib/apis/cad';

	const i18n: any = getContext('i18n');

	export let projectId = '';
	export let revisionId = '';
	/** Reveal the body a part file builds. Absent on a host with no scene to point at,
	 *  and the button is then not drawn rather than drawn dead. */
	export let onRevealNode: ((nodeId: string) => void) | null = null;

	/** `tree` draws the file list, `document` the open file. The session rail draws them
	 *  as two separate sections; the studio panel draws both in one column. */
	export let show: 'tree' | 'document' | 'both' = 'both';
	/** Which file is open. Bindable so a host that draws the list and the document as two
	 *  separate sections keeps one answer between them — the rail switches this component
	 *  from `tree` to `document` rather than mounting a second copy, and the open path has
	 *  to survive that switch. */
	export let openFile = '';
	/** Fired when a row is clicked, so a rail that hides the document behind another
	 *  section can bring it forward. The path is already in `openFile` by then. */
	export let onOpenFile: (path: string) => void = () => {};

	/** The body the rest of the workspace is pointed at (CS-6). Set it and the file that
	 *  builds that body opens; the host clears it through `onFocusApplied`, which is what
	 *  stops a hand-picked file from being overridden the next time this mounts. */
	export let focusNodeId = '';
	export let onFocusApplied: () => void = () => {};

	/** Handed the tree each time one lands, so a host can draw the parameter graph beside
	 *  the code without asking for the same revision twice. One fetch, one answer: the
	 *  panels are supposed to be projections of a single source, and two requests could
	 *  return two revisions' worth of it. */
	export let onTree: (tree: CadFileTree) => void = () => {};

	/** Which lines to mark, as `[first, last]` — a parameter's declaration, or the slot a
	 *  feature reads it in. Null when nothing is selected. Lines are 1-based, matching
	 *  the engine's `spans`, because the marks exist to point at what those spans name. */
	export let highlight: [number, number] | null = null;

	/** Keyed by revision, so switching revisions never shows the previous revision's
	 *  files while the new ones are still in flight. */
	let trees: Record<string, CadFileTree> = {};
	let loading = '';
	let failed: Record<string, string> = {};

	const load = async (pid: string, rid: string) => {
		loading = rid;
		const { [rid]: _cleared, ...rest } = failed;
		failed = rest;
		try {
			const t = await getCadRevisionFiles(pid, rid);
			trees = { ...trees, [rid]: t };
			onTree(t);
		} catch (e: any) {
			failed = { ...failed, [rid]: e?.message ?? `${e}` };
		} finally {
			loading = '';
		}
	};

	$: if (projectId && revisionId && !trees[revisionId] && !failed[revisionId] && loading !== revisionId) {
		load(projectId, revisionId);
	}
	$: tree = revisionId ? (trees[revisionId] ?? null) : null;
	$: error = revisionId ? (failed[revisionId] ?? '') : '';
	// An open file that is not in this revision's tree is a leftover from the previous
	// one; falling back to the first file beats showing a body that is no longer there.
	$: if (tree && !tree.files.some((f) => f.path === openFile)) {
		openFile = tree.files[0]?.path ?? '';
	}
	// Tree/viewport selection → code (CS-6). A body whose component has its own slice
	// opens that slice; a single-body design has no per-part file and its part *is*
	// model.cadir.json, so that is the honest answer rather than leaving whatever was
	// open. Applied once and reported, because the host clears the request — otherwise
	// this would fight a file the user picked by hand every time the tab came back.
	$: if (tree && focusNodeId) {
		const hit =
			tree.files.find((f) => f.node_id === focusNodeId) ??
			tree.files.find((f) => f.kind === 'main');
		if (hit) openFile = hit.path;
		onFocusApplied();
	}
	$: shown = (tree?.files.find((f) => f.path === openFile) ?? null) as CadFile | null;

	// Split once per file rather than per line: the document is re-rendered whenever the
	// highlight moves, and re-splitting a 70-line file on every parameter click is work
	// nobody asked for.
	$: lines = shown ? shown.content.split('\n') : [];
	$: marked = (n: number) => !!highlight && n >= highlight[0] && n <= highlight[1];

	/** Bring a mark below the fold into view. An action rather than a binding because only
	 *  the *first* marked line should be scrolled to, and `bind:this` inside an each block
	 *  keeps whichever line rendered last. `nearest` so a mark already on screen does not
	 *  jump the panel under a reader who is looking at it. */
	const followMark = (node: HTMLElement, first: boolean) => {
		const run = (f: boolean) => f && node.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
		run(first);
		return { update: run };
	};

	const size = (n: number) => (n >= 1024 ? `${(n / 1024).toFixed(1)} kB` : `${n} B`);
</script>

{#if !revisionId}
	<p class="text-xs text-gray-500 dark:text-gray-400">{$i18n.t('No revision selected.')}</p>
{:else if error}
	<div class="flex flex-col items-start gap-1.5">
		<p class="text-xs text-amber-600 dark:text-amber-400">{error}</p>
		<button
			class="text-[11px] px-2 py-0.5 rounded-md border border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300 disabled:opacity-50"
			disabled={!!loading}
			on:click={() => load(projectId, revisionId)}>{$i18n.t('Retry')}</button
		>
	</div>
{:else if !tree}
	<p class="text-xs text-gray-500 dark:text-gray-400">{$i18n.t('Loading…')}</p>
{:else}
	<div class="flex flex-col gap-2">
		{#if show !== 'document'}
			<div class="flex flex-col">
				{#each tree.files as f}
					<button
						class="flex items-baseline gap-2 px-2 py-1 rounded-md text-left text-xs {f.path ===
						openFile
							? 'bg-gray-100 dark:bg-gray-850 text-gray-900 dark:text-gray-100'
							: 'text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-900'}"
						on:click={() => {
							openFile = f.path;
							onOpenFile(f.path);
						}}
					>
						<span class="font-mono truncate {f.kind === 'part' ? 'pl-3' : ''}">{f.path}</span>
						<span
							class="ml-auto shrink-0 text-[11px] text-gray-400 dark:text-gray-500 tabular-nums"
							>{size(f.bytes)}</span
						>
					</button>
				{/each}
			</div>
		{/if}

		{#if show !== 'tree' && shown}
			<div class="flex items-baseline gap-2">
				<p class="text-[11px] text-gray-500 dark:text-gray-400">{shown.description}</p>
				{#if shown.node_id && onRevealNode}
					<!-- Reveal, not select: this scrolls the hierarchy to the body this file builds.
					     Making it a selection would put a chip on the composer that the user never
					     picked in the viewport. The label says "tree" for the same reason — it does
					     not touch the viewport, and "Show in scene" promised that it did. -->
					<button
						class="ml-auto shrink-0 text-[11px] px-2 py-0.5 rounded-md border border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300"
						on:click={() => onRevealNode?.(shown.node_id ?? '')}
						>{$i18n.t('Show in tree')}</button
					>
				{/if}
			</div>
			<!-- Rendered line by line rather than as one text node, so a span the engine's
			     source map names can actually be marked, and so the gutter carries the number
			     that map speaks in — a location reading `main.cadir.json:15` is only useful
			     next to a 15. The tags run together on purpose: inside a `pre`, a newline in
			     the template is a newline on screen. -->
			<pre
				class="text-[11px] font-mono whitespace-pre overflow-x-auto scrollbar-hidden p-2 rounded-lg bg-gray-50 dark:bg-gray-900"
			>{#each lines as ln, i (i)}<span class="block w-fit min-w-full {marked(i + 1) ? 'bg-amber-400/25 dark:bg-amber-400/20' : ''}" use:followMark={marked(i + 1) && i + 1 === highlight?.[0]}><span class="inline-block w-7 pr-2 text-right select-none text-gray-400 dark:text-gray-600 tabular-nums" aria-hidden="true">{i + 1}</span>{ln}</span>{/each}</pre>
		{/if}

		{#if show !== 'tree'}
			{#each tree.notes as n}
				<p class="text-[11px] text-gray-500 dark:text-gray-400">{n}</p>
			{/each}

			{#if tree.read_only}
				<!-- Said, not merely implied by the absence of a save button. These files are
				     generated from the revision on every read, so editing the text would have to be
				     mapped back into the document — and a mapping that is slightly wrong rewrites
				     someone's part without saying so. Changes go through the conversation, which
				     produces a revision the engine actually built. -->
				<p class="text-[11px] text-gray-400 dark:text-gray-500">
					{$i18n.t(
						'These files are generated from the revision and cannot be edited here — change the design by asking, or with Parameters.'
					)}
				</p>
			{/if}
		{/if}
	</div>
{/if}
