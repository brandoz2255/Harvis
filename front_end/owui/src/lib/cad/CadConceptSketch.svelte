<script lang="ts">
	/**
	 * DE-8e — the picture that exists before the geometry does.
	 *
	 * While a turn is authoring there is nothing to render: the viewport sits empty
	 * behind a spinner for as long as the model takes, and a reader has no way to tell
	 * a working request from a misread one until the part arrives. This draws the one
	 * thing that is already known at that point — what the *request* pinned down.
	 *
	 * Its source is `cad_designspec.extract`, a regular-expression pass the server runs
	 * before the model is asked anything. That matters twice over:
	 *
	 *  - it is not a picture of the part, and never claims to be. It is a scale outline
	 *    of the stated envelope — the requirement, drawn — so a wrong reading is visible
	 *    in a second rather than after a two-minute build.
	 *  - it is the same answer key `cad_conformance` grades the finished part against,
	 *    so the sketch and the verdict can never be two opinions. If the sketch is
	 *    wrong here, the grade was going to be wrong too, and now you know first.
	 *
	 * Nothing on this canvas is drawn by a model, and nothing is inferred. The
	 * extractor's own rule is that a pattern which does not match unambiguously
	 * produces nothing rather than a guess; this mirrors it exactly and declines to
	 * draw at all when the request pinned nothing down.
	 */
	import { getContext } from 'svelte';

	const i18n: any = getContext('i18n');

	/** The extractor's `stated` map, verbatim. Server-owned; never model-authored. */
	export let stated: Record<string, any> | null | undefined = undefined;
	export let unknowns: string[] | null | undefined = undefined;
	/** `'mm'`, or `'unsupported'` when the sentence used units the extractor refuses to
	 *  convert. Foreign units are declined rather than silently turned into millimetres. */
	export let units: string | null | undefined = 'mm';

	const num = (v: any): number | null =>
		typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : null;

	const fmt = (v: number) => (Number.isInteger(v) ? `${v}` : `${Math.round(v * 100) / 100}`);

	$: s = stated ?? {};

	// The envelope, in the order the extractor could supply it. `overall_mm` arrives
	// SORTED — the extractor discards which dimension is which axis — so a triple can
	// only ever be drawn as "these three numbers", never as an orientation. That is
	// said in words below rather than implied by the drawing.
	$: triple = Array.isArray(s.overall_mm) && s.overall_mm.length === 3 ? [...s.overall_mm] : null;
	$: cube = num(s.cube_edge_mm);
	$: flats = num(s.across_flats_mm);
	$: corners = num(s.across_corners_mm);
	$: bore = num(s.bore_diameter_mm);

	$: named = {
		length: num(s.length_mm),
		width: num(s.width_mm),
		height: num(s.height_mm),
		depth: num(s.depth_mm),
		thickness: num(s.thickness_mm)
	};

	type Shape =
		| { kind: 'rect'; w: number; h: number; wLabel: string; hLabel: string; hStated: boolean }
		| { kind: 'hex'; across: number; byFlats: boolean; h: number | null }
		| { kind: 'none' };

	/** Pick what can honestly be drawn, most specific first. A hexagon is only drawn
	 *  when the sentence actually said "across flats" or "across corners" — the two
	 *  phrases nothing but a hexagon uses. */
	const pickShape = (
		t: number[] | null,
		c: number | null,
		f: number | null,
		k: number | null,
		n: typeof named
	): Shape => {
		if (f || k) {
			return {
				kind: 'hex',
				across: (f ?? k) as number,
				byFlats: !!f,
				h: n.height ?? n.thickness ?? null
			};
		}
		if (t) {
			const sorted = [...t].sort((a, b) => b - a);
			return {
				kind: 'rect',
				w: sorted[0],
				h: sorted[1],
				wLabel: fmt(sorted[0]),
				hLabel: fmt(sorted[1]),
				hStated: true
			};
		}
		if (c) {
			return { kind: 'rect', w: c, h: c, wLabel: fmt(c), hLabel: fmt(c), hStated: true };
		}
		const across = n.width ?? n.length ?? n.depth ?? n.thickness;
		const up = n.height ?? n.thickness ?? n.length;
		if (across && up && across !== up) {
			return { kind: 'rect', w: across, h: up, wLabel: fmt(across), hLabel: fmt(up), hStated: true };
		}
		// Only one dimension was stated. Drawing a square would invent the other, so the
		// square is drawn as explicitly unknown: one edge carries its number, the other
		// says it has none. Which edge gets the number matters — a lone `thickness` or
		// `height` is a vertical measurement, and putting it on the horizontal edge would
		// state a width the request never gave.
		const only = across ?? up;
		if (only) {
			const verticalOnly = !n.width && !n.length && !n.depth && !!(n.height ?? n.thickness);
			return {
				kind: 'rect',
				w: only,
				h: only,
				wLabel: verticalOnly ? '?' : fmt(only),
				hLabel: verticalOnly ? fmt(only) : '?',
				hStated: false
			};
		}
		return { kind: 'none' };
	};

	$: shape = pickShape(triple, cube, flats, corners, named);
	$: drawable = shape.kind !== 'none';

	// Geometry, in a 220×150 viewBox. The scale is shared by the outline and the bore
	// so the hole is the size the sentence asked for relative to the body, not a
	// decorative circle — a 9 mm bore in a 10 mm cube should look alarming.
	const W = 220;
	const H = 150;
	const PAD = 34;

	// The bore counts toward the extent even when it is larger than the body it is in.
	// Leaving it out let a Ø10 bore in a 4 mm outline scale straight off the canvas —
	// the one case where the drawing has the most to say gets no picture at all.
	$: extent =
		shape.kind === 'rect'
			? Math.max(shape.w, shape.h, bore ?? 0)
			: shape.kind === 'hex'
				? Math.max(shape.across, shape.h ?? shape.across, bore ?? 0)
				: 1;
	$: scale = Math.min((W - PAD * 2) / extent, (H - PAD * 2) / extent);
	$: cx = W / 2;
	$: cy = H / 2;

	$: rectW = shape.kind === 'rect' ? shape.w * scale : 0;
	$: rectH = shape.kind === 'rect' ? shape.h * scale : 0;

	$: hexPoints =
		shape.kind === 'hex'
			? Array.from({ length: 6 }, (_, i) => {
					// `across corners` is the full diagonal, `across flats` the short width;
					// the circumradius differs by the usual √3/2, and using the wrong one
					// would draw a hexagon the stated size did not describe.
					const r = flats ? shape.across / Math.sqrt(3) : shape.across / 2;
					const a = (Math.PI / 180) * (60 * i - 30);
					return `${cx + r * scale * Math.cos(a)},${cy + r * scale * Math.sin(a)}`;
				}).join(' ')
			: '';

	$: boreR = bore ? (bore / 2) * scale : 0;
	$: holes = typeof s.hole_count === 'number' && s.hole_count > 1 ? s.hole_count : 0;
	$: unsupportedUnits = units === 'unsupported';
</script>

<div class="flex flex-col items-center justify-center gap-2 text-center px-6">
	{#if unsupportedUnits}
		<p class="text-xs text-amber-600 dark:text-amber-500 max-w-xs">
			{$i18n.t(
				'The request used units this reader does not convert, so nothing was read from it. Everything downstream works in millimetres.'
			)}
		</p>
	{:else if drawable}
		<svg
			viewBox="0 0 {W} {H}"
			class="w-full max-w-[15rem] text-gray-400 dark:text-gray-500"
			role="img"
			aria-label={$i18n.t('Scale outline of the dimensions stated in the request')}
		>
			<!-- The ground line: it is a drawing of a requirement, so it gets drawn like
			     one rather than like a rendered part. -->
			<defs>
				<pattern id="cs-hatch" width="6" height="6" patternUnits="userSpaceOnUse">
					<path d="M0,6 L6,0" stroke="currentColor" stroke-width="0.5" opacity="0.35" />
				</pattern>
			</defs>

			{#if shape.kind === 'rect'}
				<rect
					x={cx - rectW / 2}
					y={cy - rectH / 2}
					width={rectW}
					height={rectH}
					fill="url(#cs-hatch)"
					stroke="currentColor"
					stroke-width="1.5"
				/>
				<!-- Width witness + dimension line, below the shape. -->
				<line
					x1={cx - rectW / 2}
					y1={cy + rectH / 2 + 6}
					x2={cx - rectW / 2}
					y2={cy + rectH / 2 + 16}
					stroke="currentColor"
					stroke-width="0.5"
				/>
				<line
					x1={cx + rectW / 2}
					y1={cy + rectH / 2 + 6}
					x2={cx + rectW / 2}
					y2={cy + rectH / 2 + 16}
					stroke="currentColor"
					stroke-width="0.5"
				/>
				<line
					x1={cx - rectW / 2}
					y1={cy + rectH / 2 + 12}
					x2={cx + rectW / 2}
					y2={cy + rectH / 2 + 12}
					stroke="currentColor"
					stroke-width="0.75"
				/>
				<text x={cx} y={cy + rectH / 2 + 25} text-anchor="middle" font-size="9" fill="currentColor">
					{shape.wLabel}
				</text>

				<!-- Height witness + dimension line, to the left. -->
				<line
					x1={cx - rectW / 2 - 6}
					y1={cy - rectH / 2}
					x2={cx - rectW / 2 - 16}
					y2={cy - rectH / 2}
					stroke="currentColor"
					stroke-width="0.5"
				/>
				<line
					x1={cx - rectW / 2 - 6}
					y1={cy + rectH / 2}
					x2={cx - rectW / 2 - 16}
					y2={cy + rectH / 2}
					stroke="currentColor"
					stroke-width="0.5"
				/>
				<line
					x1={cx - rectW / 2 - 12}
					y1={cy - rectH / 2}
					x2={cx - rectW / 2 - 12}
					y2={cy + rectH / 2}
					stroke="currentColor"
					stroke-width="0.75"
				/>
				<text
					x={cx - rectW / 2 - 16}
					y={cy}
					text-anchor="middle"
					font-size="9"
					fill="currentColor"
					transform="rotate(-90 {cx - rectW / 2 - 16} {cy})"
				>
					{shape.hLabel}
				</text>
			{:else if shape.kind === 'hex'}
				<polygon
					points={hexPoints}
					fill="url(#cs-hatch)"
					stroke="currentColor"
					stroke-width="1.5"
				/>
				<text x={cx} y={H - 14} text-anchor="middle" font-size="9" fill="currentColor">
					{fmt(shape.across)}
					{shape.byFlats ? $i18n.t('across flats') : $i18n.t('across corners')}
				</text>
			{/if}

			{#if boreR > 0.5}
				<circle
					cx={cx}
					cy={cy}
					r={boreR}
					class="fill-white dark:fill-gray-900"
					stroke="currentColor"
					stroke-width="1.25"
					stroke-dasharray={s.bore_through ? '' : '3 2'}
				/>
				<line
					x1={cx - boreR}
					y1={cy}
					x2={cx + boreR}
					y2={cy}
					stroke="currentColor"
					stroke-width="0.5"
				/>
				<text x={cx} y={cy - boreR - 4} text-anchor="middle" font-size="8" fill="currentColor">
					Ø{fmt(bore ?? 0)}
				</text>
			{/if}
		</svg>

		<p class="text-[11px] text-gray-500 dark:text-gray-400 max-w-xs leading-snug">
			{$i18n.t('The request, drawn to scale in millimetres — not the part.')}
		</p>

		<!-- Every caveat the extractor's own output implies, said rather than drawn. -->
		<div class="text-[10px] text-gray-400 dark:text-gray-500 max-w-xs leading-snug space-y-0.5">
			{#if triple}
				<p>{$i18n.t('Three sizes were stated, but not which is which axis.')}</p>
			{/if}
			{#if shape.kind === 'rect' && !shape.hStated}
				<p>{$i18n.t('Only one dimension was stated; the other is the model’s to choose.')}</p>
			{/if}
			{#if bore && !s.bore_through}
				<p>{$i18n.t('The bore was not stated as going all the way through.')}</p>
			{/if}
			{#if holes}
				<p>{$i18n.t('{{count}} holes were asked for; one is drawn.', { count: holes })}</p>
			{/if}
			{#if unknowns?.length}
				<p>{$i18n.t('Still open: {{list}}', { list: unknowns.join(', ') })}</p>
			{/if}
		</div>
	{:else}
		<p class="text-[11px] text-gray-400 dark:text-gray-500 max-w-xs leading-snug">
			{$i18n.t(
				'Nothing in the request fixed a dimension, so there is nothing to draw yet. The part appears here when the first build finishes.'
			)}
		</p>
	{/if}
</div>
