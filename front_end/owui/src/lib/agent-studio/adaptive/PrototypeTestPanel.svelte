<script lang="ts">
	// Physical Prototype Test — Stage 1a-core: the numbers are now REAL.
	// The concept geometry is still a procedural mock (Stage 2 makes it real), but
	// the load test runs a server-side closed-form cantilever + bolt-group estimate
	// (/analyze → manifest.analysis): real sigma (MPa) + factor of safety vs. a
	// material allowable. The SAFETY VERDICT is decided by the backend
	// (verdict_code); this component only RENDERS the phrasing it is handed — it
	// never composes "looks safe" itself. Criteria (load/material/geometry/screws)
	// are gathered as chips, persisted to manifest.meta, and re-run the analysis.
	import { getContext, onMount } from 'svelte';
	import { fade, fly } from 'svelte/transition';
	import HelmetHangerMockViewer from './HelmetHangerMockViewer.svelte';

	const i18n: any = getContext('i18n');

	export let space: any = null;

	const hdrs = () => ({ Authorization: `Bearer ${localStorage.token}`, 'Content-Type': 'application/json' });
	const meta = (): Record<string, string> => space?.manifest?.meta ?? {};

	// ── Analysis result (real, from the backend) ──
	let analysis: any = space?.manifest?.analysis ?? null;
	let analyzing = false;

	// ── Stage 2: real parametric geometry (build123d CAD engine) ──
	let cadMeshRid: string = space?.manifest?.cad?.mesh_rid ?? '';
	let building = false;
	$: cadTool = (space?.manifest?.tools ?? []).find((t: any) => t.key === 'cad_build123d');
	$: cadReady = cadTool?.status === 'ready';
	$: meshUrl = cadMeshRid && space?.id ? `/api/adaptive/spaces/${space.id}/resource/${cadMeshRid}` : '';
	const buildReal = async () => {
		if (!space?.id || building) return;
		building = true;
		try {
			const r = await fetch(`/api/adaptive/spaces/${space.id}/cad/execute`, {
				method: 'POST', headers: hdrs(), credentials: 'include', body: JSON.stringify({})
			});
			if (r.ok) cadMeshRid = (await r.json()).mesh_rid;
		} catch {
			/* honest failure — the viewer stays on whatever it had */
		}
		building = false;
	};

	// ── Criteria (chips) — read from meta, fall back to assumptions ──
	const nOr = (v: any, d: number) => (Number.isFinite(parseFloat(v)) ? parseFloat(v) : d);
	const metaW = parseFloat(meta().crit_load_lb ?? '');
	let assumed: number | null = Number.isFinite(metaW) ? metaW : null;
	let popupOpen = assumed == null;
	// provenance ('assumed' tags) is single-sourced from the backend's
	// analysis.input_sources via srcOf(); no client-side default flag.

	let critMaterial = (meta().crit_material ?? 'pla').toLowerCase();
	let critArmLen = nOr(meta().crit_arm_length_mm, 100);
	let critW = nOr(meta().crit_arm_width_mm, 12);
	let critH = nOr(meta().crit_arm_height_mm, 8);
	let critScrews = parseInt(meta().crit_screw_count ?? '') || 0;

	const LOADS = [
		{ lb: 2, label: '2 lb · light helmet' },
		{ lb: 4, label: '4 lb · motorcycle helmet' },
		{ lb: 6, label: '6 lb · heavy helmet' }
	];
	const MATERIALS = [
		['pla', 'PLA'],
		['petg', 'PETG'],
		['abs', 'ABS']
	];
	const ARM_LENS = [70, 100, 140];
	const SECTIONS: [string, string, number, number][] = [
		['slim', 'Slim 10×6', 10, 6],
		['medium', 'Medium 12×8', 12, 8],
		['chunky', 'Chunky 16×10', 16, 10]
	];
	const SCREW_OPTS: [number, string][] = [
		[0, 'Not specified'],
		[2, '2 screws'],
		[3, '3 screws']
	];

	$: w = assumed ?? 5;
	$: sectionKey = critW === 10 && critH === 6 ? 'slim' : critW === 16 && critH === 10 ? 'chunky' : 'medium';

	const persist = async (patch: Record<string, string>) => {
		try {
			await fetch(`/api/adaptive/spaces/${space?.id}/meta`, {
				method: 'POST', headers: hdrs(), credentials: 'include', body: JSON.stringify({ meta: patch })
			});
		} catch {
			/* session-local only */
		}
	};

	// Recompute the REAL analysis from the persisted criteria. A monotonic
	// request id makes rapid chip changes settle on the LAST issued request, not
	// whichever resolves last (avoids stale-number flicker).
	let analyzeReq = 0;
	const runAnalyze = async () => {
		if (!space?.id) return;
		const myReq = ++analyzeReq;
		analyzing = true;
		try {
			const r = await fetch(`/api/adaptive/spaces/${space.id}/analyze`, {
				method: 'POST', headers: hdrs(), credentials: 'include', body: JSON.stringify({})
			});
			if (r.ok) {
				const data = await r.json();
				if (myReq === analyzeReq) analysis = data.analysis;
			}
		} catch {
			/* keep last analysis */
		} finally {
			if (myReq === analyzeReq) analyzing = false;
		}
	};

	const setCriterion = async (patch: Record<string, string>) => {
		await persist(patch);
		await runAnalyze();
	};

	const answerLoad = async (lb: number, isDefault = false) => {
		assumed = lb;
		popupOpen = false;
		await setCriterion({ crit_load_lb: String(lb), crit_load_src: isDefault ? 'default' : 'user' });
	};
	const setMaterial = (m: string) => {
		critMaterial = m;
		setCriterion({ crit_material: m });
	};
	const setArmLen = (l: number) => {
		critArmLen = l;
		setCriterion({ crit_arm_length_mm: String(l) });
	};
	const setSection = (key: string, bw: number, bh: number) => {
		critW = bw;
		critH = bh;
		setCriterion({ crit_arm_width_mm: String(bw), crit_arm_height_mm: String(bh) });
	};
	const setScrews = (n: number) => {
		critScrews = n;
		// pull-out check needs a spacing too — assume 60 mm when screws are specified
		setCriterion({ crit_screw_count: String(n), crit_screw_spacing_mm: n >= 2 ? '60' : '' });
	};

	onMount(() => {
		if (assumed != null && !analysis) runAnalyze();
	});

	// ── Derived rendering off the REAL analysis ──
	$: res = analysis?.results ?? null;
	$: zones = analysis?.zones ?? [];
	$: govSf = res?.governing_safety_factor ?? null;
	$: verdictCode = analysis?.verdict_code ?? null;
	$: verdictText = analysis?.verdict_text ?? '';
	$: srcOf = (k: string) => analysis?.input_sources?.[k] ?? 'default';

	const sfColor = (sf: number | null | undefined) =>
		sf == null ? '#94a3b8' : sf >= 2.5 ? '#34d399' : sf >= 2.0 ? '#fcd34d' : '#f87171';
	// utilization = sigma/allowable = 1/SF, as a bar %
	const util = (sf: number | null | undefined) => (sf == null ? 0 : Math.min(100, Math.round(100 / sf)));
	const verdictChip = (code: string | null) =>
		code === 'adequate_analytical'
			? { bg: 'rgba(52,211,153,0.14)', fg: '#34d399', label: 'Adequate (analytical)' }
			: code === 'marginal_recommend_test'
				? { bg: 'rgba(252,211,77,0.14)', fg: '#fcd34d', label: 'Marginal — recommend test' }
				: code === 'inadequate'
					? { bg: 'rgba(248,113,113,0.14)', fg: '#f87171', label: 'Inadequate' }
					: { bg: 'rgba(148,163,184,0.14)', fg: '#94a3b8', label: 'Not computed' };
	$: chip = verdictChip(verdictCode);
</script>

<div class="grid lg:grid-cols-[minmax(0,1fr)_340px] gap-3 w-full items-start">
	<!-- STAGE: the rotatable 3D result is the star (concept geometry still a mock) -->
	<article class="hud-panel" in:fly={{ y: 14, duration: 300, delay: 100 }}>
		<span class="corner tl"></span><span class="corner tr"></span><span class="corner bl"></span><span class="corner br"></span>
		<div class="flex items-center justify-between gap-2">
			<h3 class="text-xs font-semibold text-gray-100">{$i18n.t('Concept preview — helmet hanger')}</h3>
			<div class="flex items-center gap-2">
				<span class="text-[8px] uppercase tracking-widest {meshUrl ? 'text-emerald-300/70' : 'text-cyan-300/60'}">{meshUrl ? $i18n.t('Parametric CAD · illustrative overlay') : $i18n.t('Mock geometry · illustrative overlay')}</span>
				{#if cadReady}
					<button
						class="text-[10px] px-2 py-0.5 rounded-lg border border-cyan-400/30 text-cyan-200 hover:bg-cyan-400/10 transition disabled:opacity-50"
						disabled={building}
						on:click={buildReal}>{building ? $i18n.t('Building…') : meshUrl ? $i18n.t('Rebuild') : $i18n.t('Build real geometry')}</button
					>
				{/if}
			</div>
		</div>
		<div class="mt-2">
			{#key meshUrl}
				<HelmetHangerMockViewer load={w} {meshUrl} />
			{/key}
		</div>
	</article>

	<!-- REFINE RAIL: criteria + real numbers + safety, beside the stage on desktop -->
	<div class="space-y-3">
	<!-- ANALYTICAL LOAD TEST — REAL closed-form numbers -->
	<article class="hud-panel" in:fly={{ y: 14, duration: 300, delay: 170 }}>
		<span class="corner tl"></span><span class="corner tr"></span><span class="corner bl"></span><span class="corner br"></span>
		<div class="flex items-center justify-between gap-2">
			<h3 class="text-xs font-semibold text-gray-100">{$i18n.t('Analytical load test')}</h3>
			<span class="text-[8px] uppercase tracking-widest text-cyan-300/60">{$i18n.t('Closed-form · not FEA')}</span>
		</div>

		<!-- criteria chips -->
		<div class="mt-2 space-y-1.5">
			<div class="flex items-center gap-1.5 flex-wrap">
				<span class="text-[9px] uppercase tracking-wide text-gray-500 w-14">{$i18n.t('Material')}</span>
				{#each MATERIALS as [key, label] (key)}
					<button class="chip {critMaterial === key ? 'on' : ''}" on:click={() => setMaterial(key)}>{label}</button>
				{/each}
			</div>
			<div class="flex items-center gap-1.5 flex-wrap">
				<span class="text-[9px] uppercase tracking-wide text-gray-500 w-14">{$i18n.t('Arm')}</span>
				{#each ARM_LENS as l (l)}
					<button class="chip {critArmLen === l ? 'on' : ''}" on:click={() => setArmLen(l)}>{l}mm</button>
				{/each}
			</div>
			<div class="flex items-center gap-1.5 flex-wrap">
				<span class="text-[9px] uppercase tracking-wide text-gray-500 w-14">{$i18n.t('Section')}</span>
				{#each SECTIONS as [key, label, bw, bh] (key)}
					<button class="chip {sectionKey === key ? 'on' : ''}" on:click={() => setSection(key, bw, bh)}>{label}</button>
				{/each}
			</div>
			<div class="flex items-center gap-1.5 flex-wrap">
				<span class="text-[9px] uppercase tracking-wide text-gray-500 w-14">{$i18n.t('Screws')}</span>
				{#each SCREW_OPTS as [n, label] (n)}
					<button class="chip {critScrews === n ? 'on' : ''}" on:click={() => setScrews(n)}>{label}</button>
				{/each}
			</div>
		</div>

		{#if res}
			<dl class="mt-3 space-y-1 text-[11px]">
				<div class="flex justify-between gap-2"><dt class="text-gray-500">{$i18n.t('Peak bending stress')}</dt><dd class="text-gray-100 tabular-nums">{res.sigma_root_mpa} MPa</dd></div>
				<div class="flex justify-between gap-2"><dt class="text-gray-500">{$i18n.t('Material allowable')}</dt><dd class="text-gray-300 tabular-nums">{res.allowable_mpa} MPa</dd></div>
				<div class="flex justify-between gap-2"><dt class="text-gray-500">{$i18n.t('Factor of safety')}</dt><dd class="tabular-nums font-semibold" style="color:{sfColor(govSf)};">{govSf ?? '—'}</dd></div>
			</dl>

			<div class="mt-3 space-y-2">
				{#each zones as z (z.key)}
					<div>
						<div class="flex justify-between text-[10px] text-gray-400">
							<span>{$i18n.t(z.label)}</span>
							{#if z.safety_factor != null}
								<span class="tabular-nums" style="color:{sfColor(z.safety_factor)};">SF {z.safety_factor} · {z.sigma_mpa} MPa</span>
							{:else if z.status === 'needs_screw_spec'}
								<span class="text-gray-500">{$i18n.t('needs screw spec')}</span>
							{:else}
								<span class="text-gray-600">{$i18n.t('not modeled')}</span>
							{/if}
						</div>
						<div class="mt-0.5 h-1.5 rounded-full bg-white/6 overflow-hidden">
							<div class="meter h-full rounded-full" style="width:{util(z.safety_factor)}%;background:{sfColor(z.safety_factor)};"></div>
						</div>
					</div>
				{/each}
			</div>

			<div class="mt-3 flex items-start gap-2">
				<span class="shrink-0 text-[8px] uppercase tracking-widest px-1.5 py-0.5 rounded" style="background:{chip.bg};color:{chip.fg};">{$i18n.t(chip.label)}</span>
			</div>
			<p class="mt-1.5 text-[11px] text-gray-300 leading-relaxed">{verdictText}</p>
		{:else}
			<p class="mt-3 text-[11px] text-gray-500">{analyzing ? $i18n.t('Computing…') : $i18n.t('Set the load to run the analysis.')}</p>
		{/if}
	</article>

	<!-- SAFETY & ASSUMPTIONS — real allowable / knockdown / not-modeled -->
	<article class="hud-panel amber" in:fly={{ y: 14, duration: 300, delay: 240 }}>
		<span class="corner tl"></span><span class="corner tr"></span><span class="corner bl"></span><span class="corner br"></span>
		<div class="flex items-center justify-between gap-2">
			<h3 class="text-xs font-semibold text-amber-200">{$i18n.t('Safety & assumptions')}</h3>
			<span class="text-[8px] uppercase tracking-widest text-amber-300/80">{$i18n.t('Prototype check')}</span>
		</div>
		<p class="mt-1.5 text-[11px] text-amber-200/90 leading-relaxed">
			{$i18n.t('First-order analytical estimate — not FEA, not certified engineering.')}
		</p>
		{#if analysis?.assumptions}
			<ul class="mt-2 space-y-1 text-[11px] text-gray-300">
				<li class="flex items-start gap-1.5"><span class="mt-1 size-1 rounded-full bg-amber-300/80 shrink-0"></span>{$i18n.t('Load')}: {w} lb{#if srcOf('load') === 'default'} <span class="text-amber-300/70">({$i18n.t('assumed')})</span>{/if}</li>
				<li class="flex items-start gap-1.5"><span class="mt-1 size-1 rounded-full bg-amber-300/80 shrink-0"></span>{$i18n.t('Material')}: {analysis.inputs.material} — {$i18n.t('yield')} {analysis.assumptions.material_yield_mpa} MPa × {analysis.assumptions.knockdown_factor} {$i18n.t('knockdown')} = {analysis.assumptions.allowable_mpa} MPa{#if srcOf('material') === 'default'} <span class="text-amber-300/70">({$i18n.t('assumed')})</span>{/if}</li>
				<li class="flex items-start gap-1.5"><span class="mt-1 size-1 rounded-full bg-amber-300/80 shrink-0"></span>{$i18n.t('Geometry')}: {analysis.inputs.arm_length_mm}×{analysis.inputs.arm_width_mm}×{analysis.inputs.arm_height_mm} mm{#if srcOf('arm_length_mm') === 'default'} <span class="text-amber-300/70">({$i18n.t('assumed — Stage 2 makes it real')})</span>{/if}</li>
			</ul>
			<div class="mt-2 text-[10px] text-gray-500">
				<span class="uppercase tracking-widest text-[9px]">{$i18n.t('Not modeled')}:</span>
				{analysis.assumptions.not_modeled.join(' · ')}
			</div>
		{/if}
		<button
			class="mt-2.5 text-[10px] px-2.5 py-1 rounded-lg border border-amber-400/30 text-amber-200 hover:bg-amber-400/10 transition"
			on:click={() => (popupOpen = true)}>{$i18n.t('Change load assumption')}</button
		>
	</article>
	</div>

	<!-- OUTPUT SUMMARY -->
	<article class="hud-panel lg:col-span-2" in:fly={{ y: 14, duration: 300, delay: 310 }}>
		<span class="corner tl"></span><span class="corner tr"></span><span class="corner bl"></span><span class="corner br"></span>
		<div class="flex items-center justify-between gap-2">
			<h3 class="text-xs font-semibold text-gray-100">{$i18n.t('Prototype test summary')}</h3>
			<span class="text-[8px] uppercase tracking-widest text-cyan-300/60">{$i18n.t('Analytical')}</span>
		</div>
		<p class="mt-1.5 text-[11px] text-gray-300 leading-relaxed">{verdictText || $i18n.t('Run the analysis to produce a summary.')}</p>
		<div class="mt-2.5 grid sm:grid-cols-2 gap-3 text-[11px]">
			<div>
				<div class="text-[9px] uppercase tracking-widest text-gray-500">{$i18n.t('Before real use, provide')}</div>
				<ul class="mt-1 space-y-0.5 text-gray-400">
					{#each ['Verified material + print settings', 'Screw type / diameter', 'Wall surface + anchors', 'Exact measured dimensions', 'A physical load test (or FEA if SF is marginal)'] as it (it)}
						<li class="flex items-center gap-1.5"><span class="size-1 rounded-full bg-cyan-400/60 shrink-0"></span>{$i18n.t(it)}</li>
					{/each}
				</ul>
			</div>
			<div>
				<div class="text-[9px] uppercase tracking-widest text-gray-500">{$i18n.t('Recommended design changes')}</div>
				<ol class="mt-1 space-y-0.5 text-gray-400 list-decimal list-inside">
					{#each ['Thicken the arm near the wall plate (raises section modulus fastest)', 'Add fillets at the arm/base joint', 'Use at least two mounting screws', 'Target a factor of safety ≥ 2.5 before fabrication'] as it (it)}
						<li>{$i18n.t(it)}</li>
					{/each}
				</ol>
			</div>
		</div>
	</article>
</div>

<!-- ONE focused question — the load is the primary driver; everything else has a safe default -->
{#if popupOpen}
	<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" transition:fade={{ duration: 150 }}>
		<div class="dark-surface w-full max-w-md rounded-2xl bg-[#0c111d] border border-cyan-400/25 shadow-xl p-4 space-y-3">
			<h3 class="text-sm font-semibold text-gray-100">{$i18n.t('What approximate weight should this hanger support?')}</h3>
			<p class="text-[11px] text-gray-500">{$i18n.t('The load drives the stress calculation. Material and geometry start from safe defaults you can tune after.')}</p>
			<div class="flex flex-wrap gap-1.5">
				{#each LOADS as o (o.lb)}
					<button
						type="button"
						class="text-[11px] px-2.5 py-1.5 rounded-lg border border-white/10 text-gray-300 hover:text-cyan-200 hover:border-cyan-400/30 transition"
						on:click={() => answerLoad(o.lb)}>{$i18n.t(o.label)}</button
					>
				{/each}
			</div>
			<div class="flex items-center justify-end gap-2 pt-1">
				<button
					class="text-xs px-3 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white transition"
					on:click={() => answerLoad(5, true)}>{$i18n.t('Use safe default: 5 lb prototype assumption')}</button
				>
			</div>
		</div>
	</div>
{/if}

<style>
	.hud-panel {
		position: relative;
		padding: 0.85rem 1rem;
		background: linear-gradient(180deg, rgba(13, 21, 36, 0.92), rgba(8, 13, 24, 0.92));
		border: 1px solid rgba(56, 189, 248, 0.16);
		transition: border-color 200ms ease;
	}
	.hud-panel:hover {
		border-color: rgba(56, 189, 248, 0.35);
	}
	.hud-panel.amber {
		border-color: rgba(252, 211, 77, 0.22);
	}
	.hud-panel.amber:hover {
		border-color: rgba(252, 211, 77, 0.4);
	}
	.corner {
		position: absolute;
		width: 10px;
		height: 10px;
		border: 0 solid rgba(125, 211, 252, 0.55);
		pointer-events: none;
	}
	.hud-panel.amber .corner {
		border-color: rgba(252, 211, 77, 0.55);
	}
	.corner.tl { top: -1px; left: -1px; border-top-width: 1.5px; border-left-width: 1.5px; }
	.corner.tr { top: -1px; right: -1px; border-top-width: 1.5px; border-right-width: 1.5px; }
	.corner.bl { bottom: -1px; left: -1px; border-bottom-width: 1.5px; border-left-width: 1.5px; }
	.corner.br { bottom: -1px; right: -1px; border-bottom-width: 1.5px; border-right-width: 1.5px; }

	.chip {
		font-size: 10px;
		padding: 2px 8px;
		border-radius: 9999px;
		border: 1px solid rgba(255, 255, 255, 0.1);
		color: #cbd5e1;
		transition: all 150ms ease;
	}
	.chip:hover {
		border-color: rgba(56, 189, 248, 0.4);
		color: #7dd3fc;
	}
	.chip.on {
		background: rgba(56, 189, 248, 0.14);
		border-color: rgba(56, 189, 248, 0.5);
		color: #bae6fd;
	}
	.meter {
		transition: width 500ms cubic-bezier(0.22, 1, 0.36, 1), background 300ms ease;
	}
	@media (prefers-reduced-motion: reduce) {
		.meter { transition: none; }
	}
</style>
