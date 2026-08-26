<script lang="ts">
	// Rendered from a <details type="cad_build" jobid=… buildid=… projectid=…
	// revisionid=… recipe=… recipelabel=…> marker emitted by owui_compat/cad_bridge.py.
	//
	// The token carries ids and a display label — nothing else. Every claim about
	// the geometry (status, validity, measurements, artifacts) is fetched from
	// /api/cad/builds/{id}, which is ownership-checked. A card that rendered
	// measurements out of the chat text would be showing whatever the message said,
	// which is exactly the thing this lane must never do.
	//
	// Two shapes arrive here. The recipe lane knows the build before it answers, so
	// `buildid` is set from the first byte and this card polls it, as it always has.
	// The authoring lane cannot: the model creates the project itself, several seconds
	// in, so the card is handed a `jobid` and nothing else, and it watches that turn
	// happen — which tool ran, when the project appeared, when geometry was built —
	// filling in the build view the moment a build id exists.
	import { getContext, onDestroy, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import {
		cadArtifactUrl,
		cadNodeColors,
		cancelCadJob,
		downloadCadArtifact,
		fetchCadRenderObjectUrl,
		getCadBuild,
		getCadJob,
		getCadProjectActivity,
		getCadRenderRecipes,
		getCadRenders,
		streamCadJob,
		uploadCadRender,
		type CadActivityEvent,
		type CadArtifact,
		type CadBuild,
		type CadJob,
		type CadJobEvent,
		type CadRenderPreset,
		type CadRenderRecipe
	} from '$lib/apis/cad';
	import { cadFocus } from '$lib/stores';
	import { buildActivityTree, flattenActivityTree } from '$lib/cad/activityTree';
	import { activityIcon, activityTint, formatDuration } from '$lib/cad/activityIcons';
	import CadViewer from '$lib/cad/CadViewer.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	const i18n: any = getContext('i18n');

	export let id = '';
	export let attributes: Record<string, string> = {};
	export let className = 'w-full';

	let job: CadJob | null = null;
	let activity: CadJobEvent[] = [];

	// The project's own timeline, once there is a project. It is a superset of the rows
	// above — it carries this turn's activity AND everything the turn is not the author
	// of: the revision, the build, and every view captured of the result. The job stream
	// alone stopped at the model's last tool call, which is why the card used to show the
	// beginning of the process and never the end of it.
	let projectRows: CadActivityEvent[] = [];
	let projectActivityPoll: any = null;

	// A job event is a project row minus its identity — same fields, keyed by position in
	// one turn rather than by id. Giving it one lets a single tree, a single key function
	// and a single set of stops render either source.
	const asRow = (e: CadJobEvent): CadActivityEvent =>
		({ ...e, id: `job:${e.seq}` }) as CadActivityEvent;

	// Project rows win whenever they exist, because they are the same rows plus the ones
	// the job never had. Before the model has created a project — the first seconds of an
	// authoring turn — there is genuinely nothing else, and the live stream is it.
	$: rows = projectRows.length ? projectRows : activity.map(asRow);

	// DE-8d: the flat row list re-parented into turn → step → tool. Nothing is folded
	// here, so this is the same rows in the same order, each carrying a depth.
	$: activityNodes = flattenActivityTree(
		buildActivityTree(rows, (e) => e.id),
		{}
	);

	// The branch lines. `activityNodes` already carries the nesting; this works out, for
	// each row, which vertical rules to draw beside it so the nesting is something a
	// reader can SEE rather than infer from indentation.
	//
	// One rule, applied at every level: the rule at level L continues upward from this
	// row if the row before it is at least that deep, and downward if the row after it
	// is. Flattening is depth-first, so "at least that deep" is exactly "still inside
	// that branch" — which is why the last row of a branch has no line trailing below it
	// and the first row of one has none above.
	$: activityRails = activityNodes.map((node, i) => {
		const prev = activityNodes[i - 1];
		const next = activityNodes[i + 1];
		return Array.from({ length: node.depth + 1 }, (_, level) => ({
			up: !!prev && prev.depth >= level,
			down: !!next && next.depth >= level
		}));
	});

	// The geometry the rails and the row share. A rung is one nesting level; the stop
	// icon sits centred on its own rule, so the line reads as passing through it.
	const RUNG = 16;
	const STOP = 14;

	$: jobId = attributes?.jobid ?? '';
	// The token's ids win when present; on the authoring lane they are empty and the
	// job supplies them as the model discovers them.
	$: buildId = attributes?.buildid || job?.build_id || '';
	$: projectId = attributes?.projectid || job?.project_id || '';
	$: recipeLabel = attributes?.recipelabel || attributes?.recipe || '';
	// Present only on the authoring lane, which opens a room; the recipe path builds in
	// place and leaves this empty.
	$: sessionId = attributes?.sessionid ?? '';
	$: heading = job?.title || recipeLabel;

	let build: CadBuild | null = null;
	let errMsg = '';
	let elapsed = 0;
	let stopped = false;
	let timer: any = null;
	let poll: any = null;
	let jobPoll: any = null;
	let watching = false;
	let abort: AbortController | null = null;

	const TERMINAL = ['succeeded', 'failed', 'cancelled'];

	/** Open the focus workspace over this chat page — the viewport takes the surface
	 *  and this same conversation moves to a strip on the right, so nothing is lost
	 *  and nothing is duplicated. A card rendered outside the chat page has no
	 *  container to overlay, so it falls back to the full studio route. */
	const openWorkspace = () => {
		// CS-1: a request typed in an ordinary chat opened its own room, and the part
		// lives there. Overlaying the workspace on *this* conversation would show the
		// part beside a thread that is not the one making it — and the follow-up the
		// user then types would land in the wrong place. The card is the way back in;
		// the door goes to the room.
		if (sessionId) {
			goto(`/harvis/cad/session/${sessionId}`);
			return;
		}
		if (!projectId) return;
		if (document.getElementById('chat-container')) {
			cadFocus.set({ projectId, jobId: jobId || undefined });
		} else {
			goto(`/harvis/cad/${projectId}`);
		}
	};

	let cancelling = false;
	let cancelNote = '';

	/** Stop the authoring turn. The card reports what the server says it managed to
	 *  stop, not what was asked for: a cancel that reached nothing leaves the note
	 *  behind so the user does not read a still-running turn as stopped. */
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
					'The turn was marked cancelled, but it is running elsewhere and could not be stopped from here.'
				);
			}
			job = await getCadJob(jobId);
		} catch (e) {
			cancelNote = `${e}`;
		} finally {
			cancelling = false;
		}
	};

	// `queued` counts as running here on purpose: the turn exists and will happen, and it
	// is stoppable for free — dropping it out of this flag would take the Stop button off
	// the one turn that costs nothing to call off.
	$: jobRunning =
		!!jobId && (job === null || job.status === 'running' || job.status === 'queued');
	$: jobWaiting = job?.status === 'queued';
	// A job that ended without a build is the authoring lane's real failure mode:
	// the model was reached, ran, and could not produce geometry. It gets said, not
	// hidden behind a spinner that never resolves. A queued turn has not been reached at
	// all, so it is excluded — calling it failed would be a verdict on work never done.
	$: jobFailed =
		!!job &&
		job.status !== 'running' &&
		job.status !== 'queued' &&
		job.status !== 'succeeded' &&
		!buildId;
	$: status = build?.status ?? 'queued';
	$: done = TERMINAL.includes(status);

	// GLB is the display format; STL is the fallback for a build whose formats did
	// not include it. Anything else is download-only — there is no STEP loader.
	$: artifacts = (build?.artifacts ?? []) as CadArtifact[];
	$: viewable =
		artifacts.find((a) => a.format === 'glb') ?? artifacts.find((a) => a.format === 'stl') ?? null;
	$: viewerUrl = build && viewable ? cadArtifactUrl(build.id, viewable.id) : '';
	// The card is a small preview, but it is the same part: colouring it from the same
	// manifest is what stops the thumbnail in chat from disagreeing with the workspace.
	$: nodeColors = cadNodeColors(build?.scene_manifest);

	$: v = build?.validation ?? null;
	$: bbox = v?.bbox_mm ?? null;
	// The engine nests the mesh report; `parsed: false` is an honest "unknown" and
	// must never render as a pass.
	$: mesh = v?.mesh ?? null;
	// The other verdict. `validation` is about the solid; this is about the request.
	// Null on an older build, and on a recipe build whose DesignSpec stated nothing
	// checkable — neither of which is a pass, so nothing here claims one.
	$: conformance = build?.conformance ?? null;

	const fmtMm = (n: number) => (Math.round(n * 100) / 100).toString();
	const fmtBytes = (n: number) =>
		n >= 1_048_576
			? `${(n / 1_048_576).toFixed(1)} MB`
			: n >= 1024
				? `${Math.round(n / 1024)} KB`
				: `${n} B`;

	// DE-9. Which reasoning rows the reader has opened, by seq. The card's other rows
	// deliberately have no per-row fold — they are already short enough to read at a
	// glance inside the outer disclosure. A thought is the one row whose body cannot
	// be shown inline without burying the turn, and folding it is the whole point of
	// recording it, so it gets the exception.
	let openThoughts: Record<string, boolean> = {};

	// With the studio open, this conversation IS the activity panel. The workspace used to
	// draw its own copy of the timeline in a right-hand column; it gave that column over to
	// the part itself, so the process is read here — directly under the request that started
	// it — and there is only ever one copy of it on screen.
	//
	// Back out of the studio and the card goes back to being about the result: the finished
	// product, its measurements, its exports, with the process folded away behind its own
	// heading for anyone who wants it.
	$: inStudio = !!$cadFocus && !!projectId && $cadFocus.projectId === projectId;
	// `null` means "follow the surface". A reader who opens or closes it has said something
	// about this card, and that outranks the default until the page is left.
	let activityOpen: boolean | null = null;
	$: showActivity = activityOpen ?? (inStudio || jobRunning);

	// Derived, not a function called from the template: Svelte tracks the
	// identifier it sees, so a `statusDot()` call would be evaluated once and
	// never again — the dot would sit on "queued" blue for a finished build.
	// A waiting turn gets a still dot, not a pulsing one: a pulse reads as work in
	// progress, and nothing is running on this turn yet.
	$: dotClass = jobFailed
		? 'bg-red-500'
		: jobWaiting
			? 'bg-gray-300 dark:bg-gray-600'
			: !buildId && jobRunning
				? 'bg-blue-500 animate-pulse'
				: status === 'succeeded'
					? 'bg-emerald-500'
					: status === 'failed'
						? 'bg-red-500'
						: status === 'cancelled'
							? 'bg-gray-400 dark:bg-gray-600'
							: 'bg-blue-500 animate-pulse';

	// The phase a person would name, not the column value. `job.phase` is the runner's
	// word for where the turn is; this is what that means to whoever is waiting.
	$: phaseLabel =
		job?.phase === 'building'
			? $i18n.t('Building the geometry…')
			: job?.phase === 'authoring' || job?.phase === 'starting' || !job?.phase
				? $i18n.t('Designing the part…')
				: '';

	const load = async () => {
		try {
			build = await getCadBuild(buildId);
			errMsg = '';
		} catch (e: any) {
			// A 404 here means the lane was switched off or the build is not this
			// user's. Either way the honest card is "can't read it", not a spinner
			// that never resolves.
			errMsg = e?.detail?.message ?? e?.message ?? `${e}`;
			stopped = true;
		}
	};

	// Started once, the moment a build id exists — which on the authoring lane is
	// partway through the turn, not at mount.
	const watchBuild = () => {
		if (watching || !buildId) return;
		watching = true;
		load();
		poll = setInterval(async () => {
			if (done || stopped) return;
			if (elapsed > 180) {
				// Give up polling, keep whatever the last read said. A build that has
				// not finished in three minutes is a thing to report, not to hide
				// behind a spinner that runs until the tab closes.
				stopped = true;
				return;
			}
			await load();
		}, 1200);
	};

	$: if (buildId && !watching) watchBuild();

	/** The pictures this timeline is showing, keyed by render id. Read through the same
	 *  ownership-checked artifact route as every export — a plain `<img src>` there
	 *  carries no Authorization header and would 401. */
	let timelineShots: Record<string, string> = {};
	let loadingShots = false;

	const revokeTimelineShots = () => {
		for (const u of Object.values(timelineShots)) URL.revokeObjectURL(u);
		timelineShots = {};
	};

	const loadTimelineShots = async (list: CadActivityEvent[]) => {
		if (loadingShots) return;
		const missing = list.filter(
			(e) => e.kind === 'render' && e.render_id && e.build_id && !timelineShots[e.render_id]
		);
		if (!missing.length) return;
		loadingShots = true;
		try {
			for (const e of missing) {
				try {
					const u = await fetchCadRenderObjectUrl(e.build_id!, e.render_id!);
					timelineShots = { ...timelineShots, [e.render_id!]: u };
				} catch {
					/* one picture failing leaves its row as a labelled stop, not a broken card */
				}
			}
		} finally {
			loadingShots = false;
		}
	};

	$: if (activityNodes.length) loadTimelineShots(activityNodes.map((n) => n.row));

	/** Read the project's timeline. Failure is silent on purpose: the live job rows are
	 *  still standing, and replacing a working partial view with an error would be a
	 *  worse card than the one that just shows less. */
	const loadProjectActivity = async () => {
		if (!projectId) return;
		try {
			const fresh = await getCadProjectActivity(projectId);
			if (fresh.length) projectRows = fresh;
		} catch {
			/* keep whatever the last read said */
		}
	};

	// ------------------------------------------------------------------
	// Taking the pictures, not just showing them.
	//
	// A render can only come from a 3D viewport — there is no server-side renderer, and
	// `cad_render_views` says so to the model's face. The only viewport that had ever
	// taken one was the studio's, so a part whose studio nobody opened had no pictures at
	// all and this timeline ended at the model's last tool call. This card has the same
	// viewer, showing the same build, so it takes the six views itself.
	//
	// Not while the studio is open: the workspace is already capturing there, and two
	// capturers racing for one row is a way to get half a strip twice.
	// ------------------------------------------------------------------
	// Which views: the server's own recipe list (HE-7), which is derived from what the
	// request stated and what the build produced — so a part that claimed a cavity gets a
	// cut view and one that claimed nothing gets neither. A build with no named bodies
	// gets no recipes and falls back to the camera presets, which is the case an STL
	// import lands in.
	const CAPTURE_PRESETS: CadRenderPreset[] = [
		'iso',
		'front',
		'rear',
		'right',
		'top',
		'four_view'
	];
	let viewer: any = null;
	let capturedFor = '';

	/** One picture, from a recipe or from a bare camera preset. Recipes also ask for the
	 *  object-mask pass, which goes up alongside the picture: the backend measures it,
	 *  keeps the findings on the render, and discards the bytes. */
	const shoot = async (item: CadRenderRecipe | CadRenderPreset) => {
		if (typeof item === 'string') {
			const beauty = (await viewer?.capture?.(item)) ?? null;
			return { beauty, mask: null, variant: item, label: '' };
		}
		const shot = await viewer?.captureRecipe?.({
			view: item.view,
			section: item.section
				? {
						axis: item.section.axis,
						offset: item.section.offset,
						flipped: item.section.flipped
					}
				: null,
			mask_palette: item.mask_palette
		});
		return {
			beauty: shot?.beauty ?? null,
			mask: shot?.mask ?? null,
			variant: item.recipe_id,
			label: item.label
		};
	};

	const captureViews = async (b: CadBuild, sha: string) => {
		if (capturedFor === b.id) return;
		capturedFor = b.id;
		let have: Set<string>;
		try {
			have = new Set((await getCadRenders(b.id)).map((r) => r.variant));
		} catch {
			// Could not read what exists; capturing blind would overwrite views someone
			// framed themselves. Clear the latch so a later tick can try again.
			capturedFor = '';
			return;
		}

		let plan: (CadRenderRecipe | CadRenderPreset)[];
		try {
			plan = await getCadRenderRecipes(b.id);
		} catch {
			// A recipe list we could not fetch is not a build we refuse to photograph.
			plan = [];
		}
		if (!plan.length) plan = CAPTURE_PRESETS;

		// A view already on file is skipped rather than retaken: a shot a person aimed
		// outranks one taken automatically.
		const missing = plan.filter((item) =>
			typeof item === 'string' ? !have.has(item) : !have.has(item.recipe_id)
		);
		if (!missing.length) return;

		for (const item of missing) {
			// The viewer loads its mesh asynchronously and a capture returns null until it
			// has. Retrying briefly is what makes this "after the build" rather than
			// "whenever the fetch happened to be quick".
			let shot: Awaited<ReturnType<typeof shoot>> | null = null;
			for (let i = 0; i < 12 && !shot?.beauty; i++) {
				// Moved on to another build: stop rather than file a picture of one part
				// under another one's id.
				if (build?.id !== b.id) return;
				shot = await shoot(item);
				if (!shot?.beauty) await new Promise((r) => setTimeout(r, 500));
			}
			// The viewport never came up. A partial strip is where this stops — it is not
			// worth spinning through five more views that will fail the same way.
			if (!shot?.beauty) return;
			try {
				await uploadCadRender(b.id, shot.variant, shot.beauty, sha, shot.label, shot.mask);
				// Re-read after each one so the pictures appear as they are taken instead
				// of all at once at the end.
				await loadProjectActivity();
			} catch {
				/* one view failing is not the strip failing */
			}
		}
	};

	$: if (!inStudio && done && status === 'succeeded' && build && viewable && viewer) {
		captureViews(build, viewable.sha256);
	}

	// Once while the turn runs — so the build and the first captures appear as they
	// happen — and once more after it ends, because the last rows land after the stream
	// has already closed.
	let projectActivitySettled = false;
	$: if (projectId && !projectActivityPoll && !projectActivitySettled) {
		loadProjectActivity();
		projectActivityPoll = setInterval(loadProjectActivity, 4000);
	}
	// `settled` and not just a cleared handle: without it, clearing the interval would
	// satisfy the start condition again and the poll would restart forever.
	$: if (projectActivityPoll && !jobRunning && done) {
		clearInterval(projectActivityPoll);
		projectActivityPoll = null;
		projectActivitySettled = true;
		loadProjectActivity();
	}

	const record = (ev: CadJobEvent) => {
		// The stream de-duplicates on `seq` already; the poll fallback below does not,
		// so the card holds the invariant itself rather than trusting its source.
		if (activity.some((e) => e.seq === ev.seq)) return;
		activity = [...activity, ev].sort((a, b) => a.seq - b.seq);
	};

	/** Poll the job when the stream is unavailable — a proxy that buffers or a browser
	 *  that dropped the connection. Same rows, slower; never a different answer. */
	const pollJob = () => {
		if (jobPoll) return;
		jobPoll = setInterval(async () => {
			if (!jobRunning || stopped) return;
			try {
				const fresh = await getCadJob(jobId);
				(fresh.activity ?? []).forEach(record);
				job = fresh;
			} catch {
				// Leave the last good read standing; the next tick tries again.
			}
		}, 2000);
	};

	/** UX-G: wait out the turn in front. A queued turn has no stream to join — nothing is
	 *  producing events for it yet — so the card polls the row until it starts, or until
	 *  it ends without ever starting (the user stopped it, or the server reaped it). */
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
			const snapshot = await getCadJob(jobId);
			(snapshot.activity ?? []).forEach(record);
			job = snapshot;
		} catch (e: any) {
			errMsg = e?.detail?.message ?? e?.message ?? `${e}`;
			stopped = true;
			return;
		}
		if (job.status === 'queued') {
			await waitForStart();
			if (abort.signal.aborted) return;
		}
		if (job?.status !== 'running') return;
		try {
			const final = await streamCadJob(jobId, {
				onActivity: record,
				onStatus: (j) => (job = j),
				signal: abort.signal
			});
			if (final) job = final;
			// A stream that ended without a terminal frame (a proxy closing an idle
			// connection) leaves the row as the authority — read it once more.
			if (job?.status === 'running') job = await getCadJob(jobId);
		} catch {
			if (!abort.signal.aborted) pollJob();
		}
	};

	onMount(async () => {
		if (!jobId && !buildId) {
			errMsg = $i18n.t('This card is missing its build id.');
			return;
		}
		timer = setInterval(() => {
			if ((jobRunning || !done) && !stopped) elapsed += 1;
		}, 1000);
		if (jobId) watchJob();
	});

	onDestroy(() => {
		if (timer) clearInterval(timer);
		if (poll) clearInterval(poll);
		if (jobPoll) clearInterval(jobPoll);
		if (projectActivityPoll) clearInterval(projectActivityPoll);
		revokeTimelineShots();
		abort?.abort();
	});

	const download = async (a: CadArtifact) => {
		if (!build) return;
		try {
			await downloadCadArtifact(build.id, a, `${attributes?.recipe || 'part'}.${a.format}`);
		} catch (e: any) {
			errMsg = e?.detail?.message ?? e?.message ?? `${e}`;
		}
	};
</script>

<div
	{id}
	class="{className} my-1 rounded-2xl border border-gray-100 dark:border-gray-850 overflow-hidden"
>
	<div class="flex items-center gap-2 px-4 py-2.5 bg-gray-50/60 dark:bg-gray-850/40">
		<span class="size-2 rounded-full shrink-0 {dotClass}"></span>
		<span class="text-sm font-medium text-gray-800 dark:text-gray-100 truncate">
			{heading || $i18n.t('Local CAD build')}
		</span>
		<span class="text-[11px] text-gray-400 shrink-0">{$i18n.t('Local CAD · millimetres')}</span>
		<!-- Which model authored this. It is the answer to "is that really Opus?", and
		     the lane refuses to substitute a different one silently, so the badge can be
		     taken at face value. -->
		{#if job?.model}
			<span
				class="text-[11px] px-1.5 py-0.5 rounded-md bg-gray-100 dark:bg-gray-800 text-gray-500 shrink-0 truncate max-w-[10rem]"
			>
				{job.model}
			</span>
		{/if}
		<span class="ml-auto text-[11px] text-gray-400 tabular-nums shrink-0">
			{#if build?.duration_ms != null}
				{build.duration_ms} ms
			{:else if !done}
				{elapsed}s
			{/if}
		</span>
	</div>

	<div class="px-4 py-3">
		{#if errMsg}
			<div class="text-xs text-red-500">{errMsg}</div>
		{:else if jobFailed}
			<!-- The lane that was asked is the lane that is named. There is no quiet
			     hand-off to a smaller local model, so this really is the chosen model
			     saying it could not do it. -->
			<div class="text-xs text-red-500">
				{job?.error_detail ||
					$i18n.t('{{model}} could not build that.', { model: job?.model ?? 'The model' })}
				{#if job?.error_code}
					<span class="text-gray-400"> ({job.error_code})</span>
				{/if}
			</div>
		{:else if jobWaiting}
			<!-- No spinner: nothing is running on this turn yet, and a spinner would claim
			     work that is not happening. The second line is there because the first one
			     otherwise reads as "stuck" — waiting is a choice the lane made, and the way
			     out of it is the Stop button on the turn ahead. -->
			<div class="text-xs text-gray-600 dark:text-gray-300">
				{$i18n.t('Waiting for the current turn to finish.')}
			</div>
			<div class="mt-0.5 text-[11px] text-gray-400">
				{$i18n.t(
					'It starts on its own when that one ends. Stopping the running turn starts this one immediately.'
				)}
			</div>
		{:else if !buildId}
			<div class="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-300">
				<Spinner className="size-3.5" />
				{phaseLabel}
			</div>
		{:else if status === 'failed'}
			<div class="text-xs text-red-500">
				{build?.error_detail || $i18n.t('The build failed.')}
				{#if build?.error_code}
					<span class="text-gray-400"> ({build.error_code})</span>
				{/if}
			</div>
		{:else if status === 'cancelled'}
			<div class="text-xs text-gray-500">{$i18n.t('This build was cancelled.')}</div>
		{:else if !done}
			<div class="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-300">
				<Spinner className="size-3.5" />
				{stopped
					? $i18n.t('Still building — reopen CAD Studio to check on it.')
					: $i18n.t('Building the geometry locally…')}
			</div>
		{:else}
			{#if viewerUrl}
				<div class="rounded-xl overflow-hidden border border-gray-100 dark:border-gray-850 mb-3">
					<CadViewer
						bind:this={viewer}
						url={viewerUrl}
						format={viewable?.format === 'stl' ? 'stl' : 'glb'}
						height={240}
						{nodeColors}
					/>
				</div>
			{:else}
				<div class="text-[11px] text-gray-400 mb-3">
					{$i18n.t('This build produced no viewable mesh.')}
				</div>
			{/if}

			{#if v}
				<div class="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-gray-500 mb-3 tabular-nums">
					{#if bbox}
						<span>{fmtMm(bbox.x)} × {fmtMm(bbox.y)} × {fmtMm(bbox.z)} mm</span>
					{/if}
					{#if v.volume_mm3 != null}
						<span>{fmtMm(v.volume_mm3)} mm³</span>
					{/if}
					{#if v.solid_count != null}
						<span>{v.solid_count} {v.solid_count === 1 ? $i18n.t('solid') : $i18n.t('solids')}</span>
					{/if}
					<span class={v.brep_valid ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600'}>
						{v.brep_valid ? $i18n.t('B-Rep valid') : $i18n.t('B-Rep not valid')}
					</span>
					<!-- parsed === false is "unknown", and says so. Only a parsed report
					     can claim watertight either way. -->
					{#if mesh?.parsed === true}
						<span
							class={mesh.watertight
								? 'text-emerald-600 dark:text-emerald-400'
								: 'text-amber-600'}
						>
							{mesh.watertight ? $i18n.t('Watertight') : $i18n.t('Not watertight')}
						</span>
					{:else if mesh}
						<span class="text-gray-400">{$i18n.t('Mesh check unavailable')}</span>
					{/if}
				</div>
			{/if}

			<!-- Every metric above describes a solid that is well-formed. This says
			     whether it is the part that was asked for, and the two are not the same
			     question: the 30 mm cube that came out 35 mm with no hole in it satisfied
			     all of them. A failed proposal is not the project, so the card says so
			     rather than letting a green dot stand for both answers. -->
			{#if conformance?.status === 'failed'}
				<div
					class="mb-3 px-3 py-2 rounded-xl bg-red-500/5 border border-red-500/20 text-[11px] text-red-600 dark:text-red-400"
				>
					<div class="font-medium">{$i18n.t("This doesn't match what was asked for")}</div>
					<div class="mt-0.5 text-gray-600 dark:text-gray-300">{conformance.summary}</div>
					<div class="mt-1 text-gray-500">
						{$i18n.t(
							'It was kept as a proposal — open CAD Studio to repair it, or accept it anyway.'
						)}
					</div>
				</div>
			{:else if conformance?.status === 'passed'}
				<div class="mb-3 text-[11px] text-emerald-600 dark:text-emerald-400">
					{$i18n.t('Matches the requested dimensions')} · {conformance.summary}
				</div>
			{/if}

			<div class="flex flex-wrap items-center gap-2">
				{#each artifacts as a (a.id)}
					<button
						class="text-[11px] px-2 py-1 rounded-lg border border-gray-100 dark:border-gray-850 text-gray-600 dark:text-gray-300 hover:border-emerald-500/40 hover:bg-emerald-500/5 transition"
						on:click={() => download(a)}
					>
						{a.format.toUpperCase()} · {fmtBytes(a.size_bytes)}
					</button>
				{/each}
			</div>
		{/if}

		<!-- Design activity: what the model DID, and — on `say` rows — what it wrote for
		     the reader while doing it. Tool names, verdicts, durations and that narration
		     are public; prompts, credentials, paths and storage keys are not, and none of
		     them are in these rows. Still not chain-of-thought: a `say` row is the model's
		     own visible text, quoted, never a paraphrase of what it thought. The private
		     reasoning is dropped in `cad_agent` and has no route to this list. -->
		{#if rows.length}
			<div class="mt-3">
				<!-- A button rather than a <details>, because the open state is not the reader's
				     alone: opening the studio opens this, and closing it puts the card back to the
				     product. A native disclosure would fight that, and a second copy of the body
				     under a second branch would be one timeline too many to keep in step. -->
				<button
					class="text-[11px] text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition"
					on:click={() => (activityOpen = !showActivity)}
					aria-expanded={showActivity}
				>
					{$i18n.t('Design activity')} · {rows.length}
				</button>
				<!-- The same timeline the studio used to draw, from the same rows and the same
					     stops — see `activityIcons.ts`. It reads the PROJECT's activity once a project
					     exists, not just this turn's: the turn's own stream ends at the model's last
					     tool call, so on its own the card showed the beginning of the work and never
					     the revision, the build, or the views captured of the result. -->
				{#if showActivity}
					<!-- No `gap` between the rows: the branch lines are drawn per row, top edge to
					     bottom edge, and a gap would chop the spine into dashes. The breathing room
					     is `py-0.5` INSIDE each row, which the lines span. -->
					<div class="mt-2 flex flex-col">
						{#each activityNodes as node, i (node.row.id)}
							{@const ev = node.row}
							{@const rails = activityRails[i] ?? []}
							<div class="relative py-0.5" style="padding-left:{node.depth * RUNG + STOP + 6}px">
								{#each rails as rail, level}
									{#if level < node.depth}
										<!-- An ancestor's spine, running the full height of a row nested under it.
										     This is the line that makes a branch read as one thing. -->
										{#if rail.up || rail.down}
											<span
												class="absolute top-0 bottom-0 w-px bg-gray-200 dark:bg-gray-700"
												style="left:{level * RUNG + STOP / 2}px"
												aria-hidden="true"
											></span>
										{/if}
									{:else}
										<!-- This row's own spine, split around its stop so the icon sits ON the line
										     rather than beside it. It is missing above on the first row of a branch
										     and missing below on the last, which is how the shape of the work shows
										     without anything being asserted about it. -->
										{#if rail.up}
											<span
												class="absolute top-0 w-px bg-gray-200 dark:bg-gray-700"
												style="left:{level * RUNG + STOP / 2}px;height:5px"
												aria-hidden="true"
											></span>
										{/if}
										{#if rail.down}
											<span
												class="absolute bottom-0 w-px bg-gray-200 dark:bg-gray-700"
												style="left:{level * RUNG + STOP / 2}px;top:19px"
												aria-hidden="true"
											></span>
										{/if}
									{/if}
								{/each}
								{#if node.depth > 0}
									<!-- The elbow off the parent spine. It draws a nesting the rows already carry;
									     it asserts nothing `activityTree` did not derive. -->
									<span
										class="absolute h-px bg-gray-200 dark:bg-gray-700"
										style="left:{(node.depth - 1) * RUNG + STOP / 2}px;top:12px;width:{RUNG - STOP / 2}px"
										aria-hidden="true"
									></span>
								{/if}
								<!-- The stop. A wrench, a lightbulb, a camera — what KIND of thing happened,
								     readable before the row itself is. It sits centred on its own rule, over the
								     card's background, so the line reads as running through it. -->
								<span
									class="absolute flex items-center justify-center {activityTint(
										ev
									)}"
									style="left:{node.depth * RUNG}px;top:5px;width:{STOP}px;height:{STOP}px"
								>
									<svelte:component this={activityIcon(ev)} className="size-3.5" />
								</span>
								<div class="flex items-start gap-1 text-[11px]">
									<span class="min-w-0 flex-1">
										{#if ev.kind === 'think'}
											<!-- The heading, and the body only when asked for. The whole row is the
												     press target because a 6px chevron in a chat bubble is not one. -->
											<button
												class="block w-full text-left"
												on:click={() =>
													(openThoughts = { ...openThoughts, [ev.id]: !openThoughts[ev.id] })}
												aria-expanded={!!openThoughts[ev.id]}
											>
												<!-- A reasoning row names itself, because the line under it is the
													     model's own words and would otherwise read as narration. -->
												<span
													class="block text-[9px] uppercase tracking-wider text-violet-500/80 dark:text-violet-400/70"
												>
													{$i18n.t('Thinking')}
												</span>
												<span class="block leading-snug text-gray-600 dark:text-gray-300">{ev.label}</span>
												<span class="block text-[10px] text-violet-500/70 dark:text-violet-400/60">
													{openThoughts[ev.id] ? $i18n.t('Collapse') : $i18n.t('+ Expand')}
												</span>
											</button>
											{#if openThoughts[ev.id]}
												<span
													class="mt-1 block px-2 py-1.5 rounded-md bg-violet-500/5 border-l-2 border-violet-400/40 text-[10px] leading-relaxed text-gray-600 dark:text-gray-300 whitespace-pre-wrap break-words"
												>
													{ev.thinking ??
														$i18n.t(
															'This turn recorded more reasoning than it can keep. The step happened; its text was not stored.'
														)}
												</span>
												{#if ev.clipped}
													<!-- The clip lands mid-word, so without this line the panel reads
														     as broken rather than as bounded. -->
													<span class="mt-1 block italic text-gray-400">
														{$i18n.t('This thought ran longer than the panel keeps. The rest was not stored.')}
													</span>
												{/if}
											{/if}
										{:else}
											<span
												class="block leading-snug text-gray-600 dark:text-gray-300 {ev.kind === 'say'
													? 'whitespace-pre-wrap'
													: ''}">{ev.label}</span
											>
										{/if}
										{#if ev.error_code}
											<span class="block text-amber-600 dark:text-amber-500">{ev.error_code}</span>
										{/if}
									</span>
									{#if ev.duration_ms != null}
										<span class="mt-0.5 text-gray-400 tabular-nums shrink-0">
											{formatDuration(ev.duration_ms)}
										</span>
									{/if}
								</div>

								<!-- The picture, in the timeline, at the moment the shutter fired. Same
									     authorized bytes the studio's filmstrip shows — fetched through the
									     artifact route with the auth header, which is why this is an object URL
									     and not an `src` pointed at the endpoint. A row whose fetch failed keeps
									     its label and shows no image, rather than a broken frame. -->
								{#if ev.kind === 'render' && ev.render_id && timelineShots[ev.render_id]}
									<div class="mt-1 mb-1.5 mr-1">
										<img
											src={timelineShots[ev.render_id]}
											alt={ev.label}
											class="w-full max-h-56 object-contain rounded-md border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900"
										/>
										<!-- The disclaimer belongs to the picture, not to every row label: a render
											     is what the viewport was showing, never a measurement. -->
										<span class="block mt-0.5 text-[10px] text-gray-400 whitespace-normal">
											{`${ev.filename ?? ''} · ${$i18n.t('An inspection view. Not dimensional proof.')}`}
										</span>
									</div>
								{/if}
							</div>
						{/each}
					</div>
				{/if}
			</div>
		{/if}

		<div class="mt-3 flex items-center gap-3">
			<!-- No door when the reader is already through it: this card is drawn in the
			     studio's own conversation as well as in the chat the request came from, and
			     offering "Open the studio" to someone standing in it is the thing UX-C set
			     out to stop doing. -->
			{#if inStudio}
				<!-- nothing: the workspace is on screen beside this -->
			{:else if sessionId}
				<button
					class="text-[11px] text-gray-500 hover:text-emerald-500 transition"
					on:click={openWorkspace}
				>
					<!-- Offered from the first frame, before there is a project: the room exists
					     the moment the request was made, and it is where the work is visible. -->
					{$i18n.t('Open CAD session')} →
				</button>
			{:else if projectId}
				<button
					class="text-[11px] text-gray-500 hover:text-emerald-500 transition"
					on:click={openWorkspace}
				>
					<!-- Live while the turn is still running: the project exists the moment the
					     model created it, and waiting for the build to finish before offering
					     the door is the thing UX-0 exists to stop doing. -->
					{jobRunning ? $i18n.t('Open CAD Workspace') : $i18n.t('Open in CAD Studio')} →
				</button>
			{/if}

			{#if jobRunning && jobId}
				<button
					class="text-[11px] text-gray-500 hover:text-red-500 transition disabled:opacity-50"
					disabled={cancelling}
					on:click={stopJob}
				>
					{cancelling ? $i18n.t('Stopping…') : $i18n.t('Stop')}
				</button>
			{/if}
		</div>

		<!-- Said only when it is true. A cancel that could not reach the turn leaves it
		     running, and reporting that as "Cancelled" would be the exact dishonesty the
		     rest of this card is built to avoid. -->
		{#if cancelNote}
			<div class="mt-1 text-[11px] text-amber-500">{cancelNote}</div>
		{/if}
	</div>
</div>
