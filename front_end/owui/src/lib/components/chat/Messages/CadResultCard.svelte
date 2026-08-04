<script lang="ts">
	// Rendered from a <details type="cad_build" buildid=… projectid=… revisionid=…
	// recipe=… recipelabel=…> marker emitted by owui_compat/cad_bridge.py.
	//
	// The token carries ids and a display label — nothing else. Every claim about
	// the geometry (status, validity, measurements, artifacts) is fetched from
	// /api/cad/builds/{id}, which is ownership-checked. A card that rendered
	// measurements out of the chat text would be showing whatever the message said,
	// which is exactly the thing this lane must never do.
	import { getContext, onDestroy, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import {
		cadArtifactUrl,
		downloadCadArtifact,
		getCadBuild,
		type CadArtifact,
		type CadBuild
	} from '$lib/apis/cad';
	import CadViewer from '$lib/cad/CadViewer.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	const i18n: any = getContext('i18n');

	export let id = '';
	export let attributes: Record<string, string> = {};
	export let className = 'w-full';

	$: buildId = attributes?.buildid ?? '';
	$: projectId = attributes?.projectid ?? '';
	$: recipeLabel = attributes?.recipelabel || attributes?.recipe || '';

	let build: CadBuild | null = null;
	let errMsg = '';
	let elapsed = 0;
	let stopped = false;
	let timer: any = null;
	let poll: any = null;

	const TERMINAL = ['succeeded', 'failed', 'cancelled'];

	$: status = build?.status ?? 'queued';
	$: done = TERMINAL.includes(status);

	// GLB is the display format; STL is the fallback for a build whose formats did
	// not include it. Anything else is download-only — there is no STEP loader.
	$: artifacts = (build?.artifacts ?? []) as CadArtifact[];
	$: viewable =
		artifacts.find((a) => a.format === 'glb') ?? artifacts.find((a) => a.format === 'stl') ?? null;
	$: viewerUrl = build && viewable ? cadArtifactUrl(build.id, viewable.id) : '';

	$: v = build?.validation ?? null;
	$: bbox = v?.bbox_mm ?? null;
	// The engine nests the mesh report; `parsed: false` is an honest "unknown" and
	// must never render as a pass.
	$: mesh = v?.mesh ?? null;

	const fmtMm = (n: number) => (Math.round(n * 100) / 100).toString();
	const fmtBytes = (n: number) =>
		n >= 1_048_576
			? `${(n / 1_048_576).toFixed(1)} MB`
			: n >= 1024
				? `${Math.round(n / 1024)} KB`
				: `${n} B`;

	// Derived, not a function called from the template: Svelte tracks the
	// identifier it sees, so a `statusDot()` call would be evaluated once and
	// never again — the dot would sit on "queued" blue for a finished build.
	$: dotClass =
		status === 'succeeded'
			? 'bg-emerald-500'
			: status === 'failed'
				? 'bg-red-500'
				: status === 'cancelled'
					? 'bg-gray-400 dark:bg-gray-600'
					: 'bg-blue-500 animate-pulse';

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

	onMount(async () => {
		if (!buildId) {
			errMsg = $i18n.t('This card is missing its build id.');
			return;
		}
		await load();
		timer = setInterval(() => {
			if (!done && !stopped) elapsed += 1;
		}, 1000);
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
	});

	onDestroy(() => {
		if (timer) clearInterval(timer);
		if (poll) clearInterval(poll);
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
			{recipeLabel || $i18n.t('Local CAD build')}
		</span>
		<span class="text-[11px] text-gray-400 shrink-0">{$i18n.t('Local CAD · millimetres')}</span>
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
						url={viewerUrl}
						format={viewable?.format === 'stl' ? 'stl' : 'glb'}
						height={240}
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

		{#if projectId}
			<button
				class="mt-3 text-[11px] text-gray-500 hover:text-emerald-500 transition"
				on:click={() => goto(`/harvis/cad/${projectId}`)}
			>
				{$i18n.t('Open in CAD Studio')} →
			</button>
		{/if}
	</div>
</div>
