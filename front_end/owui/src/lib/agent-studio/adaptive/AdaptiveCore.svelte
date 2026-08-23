<script lang="ts">
	// Adaptive Core — ringed HUD centerpiece. Motion policy:
	//   • CHROME (always, except reduced-motion): the tick/segment/dashed orbits
	//     drift slowly. This is instrument chrome — "the system is on" — and never
	//     encodes progress.
	//   • WORK (sweep): the radar sweep spins ONLY while real work is reported
	//     (busy request in flight, planning, executing). It stops the moment the
	//     state settles — it is a readout, not decoration.
	//   • TRUTH (arc): the determinate arc is the REAL fraction of steps done;
	//     color encodes the derived state; the amber pulse marks "waiting on your
	//     approval". Progress is never timer-faked.
	// prefers-reduced-motion disables all motion; state stays legible via color+fill.
	import { getContext } from 'svelte';

	const i18n: any = getContext('i18n');

	export let state: 'idle' | 'listening' | 'planning' | 'executing' | 'waiting' | 'error' | 'done' = 'idle';
	export let progress = 0; // 0..1 — real fraction of steps complete
	export let steps = 0;
	export let gates = 0;
	export let label = '';
	export let size = 150;
	// busy = a REAL request in flight (e.g. creating the space) — brief soft
	// blink + sweep, stops the moment the request settles. Not a fake loop.
	export let busy = false;

	$: compact = size < 118; // small instances keep only the arc + glow + readout

	// Fixed 200×200 HUD frame, scaled by `size` (geometry stays crisp at any size).
	const R_PROG = 58;
	const CIRC = 2 * Math.PI * R_PROG;
	const SEG_R = 84;
	const SEG_C = 2 * Math.PI * SEG_R;
	const SEG_DASH = `${((SEG_C / 8) * 0.68).toFixed(2)} ${((SEG_C / 8) * 0.32).toFixed(2)}`;
	const TICKS = Array.from({ length: 72 }, (_, i) => i);

	$: clamped = Math.max(0, Math.min(1, progress || 0));
	$: dashoffset = CIRC * (1 - clamped);
	$: pct = Math.round(clamped * 100);
	$: ambient = state === 'idle' || state === 'listening';
	$: sweeping = busy || state === 'planning' || state === 'executing';

	const META: Record<string, { color: string; word: string }> = {
		idle: { color: '#38bdf8', word: 'System ready' },
		listening: { color: '#38bdf8', word: 'Listening' },
		planning: { color: '#38bdf8', word: 'Planning' },
		executing: { color: '#22d3ee', word: 'Executing' },
		waiting: { color: '#fcd34d', word: 'Waiting for approval' },
		error: { color: '#f87171', word: 'Attention' },
		done: { color: '#34d399', word: 'Done' }
	};
	$: meta = META[state] ?? META.idle;
	$: glowRgb =
		state === 'waiting' ? '252,211,77' : state === 'error' ? '248,113,113' : state === 'done' ? '52,211,153' : '34,211,238';
</script>

<div
	class="hud relative shrink-0 select-none"
	style="width:{size}px;height:{size}px;"
	role="img"
	aria-label="{$i18n.t('Adaptive core')}: {$i18n.t(meta.word)}{steps ? `, ${pct}% ${$i18n.t('complete')}` : ''}"
>
	<svg viewBox="0 0 200 200" width={size} height={size} class="absolute inset-0 overflow-visible">
		<defs>
			<linearGradient id="hvSweep" gradientUnits="userSpaceOnUse" x1="100" y1="100" x2="100" y2="44">
				<stop offset="0%" stop-color="rgba(125,211,252,0)" />
				<stop offset="100%" stop-color="rgba(125,211,252,0.9)" />
			</linearGradient>
		</defs>

		{#if !compact}
			<!-- cardinal markers -->
			{#each [0, 90, 180, 270] as a (a)}
				<line x1="100" y1="2" x2="100" y2="9" stroke={meta.color} stroke-width="2" opacity="0.55" transform="rotate({a} 100 100)" />
			{/each}

			<!-- outer tick ring (static instrument scale) -->
			<g opacity="0.6">
				{#each TICKS as i (i)}
					<line
						x1="100"
						y1="5"
						x2="100"
						y2={i % 6 === 0 ? 11.5 : 8.5}
						stroke="#38bdf8"
						stroke-width={i % 6 === 0 ? 1.1 : 0.7}
						opacity={i % 6 === 0 ? 0.5 : 0.24}
						transform="rotate({i * 5} 100 100)"
					/>
				{/each}
			</g>

			<!-- segmented ring — slow chrome drift -->
			<g class="rotA">
				<circle cx="100" cy="100" r={SEG_R} fill="none" stroke="#38bdf8" stroke-width="5" stroke-dasharray={SEG_DASH} opacity="0.26" />
			</g>

			<!-- fine dashed orbit — counter-drift -->
			<g class="rotB">
				<circle cx="100" cy="100" r="74" fill="none" stroke="#7dd3fc" stroke-width="1.4" stroke-dasharray="2.5 6" opacity="0.35" />
			</g>

			<!-- inner hairline -->
			<circle cx="100" cy="100" r="67" fill="none" stroke="#38bdf8" stroke-width="0.6" opacity="0.14" />

			<!-- radar sweep — spins ONLY while real work is in flight -->
			{#if sweeping}
				<g class="sweep">
					<path d="M100 100 L100 44 A56 56 0 0 1 121 48.1 Z" fill="rgba(56,189,248,0.10)" />
					<line x1="100" y1="100" x2="100" y2="44" stroke="url(#hvSweep)" stroke-width="1.6" />
				</g>
			{/if}
		{/if}

		<!-- determinate progress: track + REAL arc -->
		<g transform="rotate(-90 100 100)">
			<circle cx="100" cy="100" r={R_PROG} fill="none" stroke="rgba(148,163,184,0.16)" stroke-width={compact ? 5 : 4} />
			<circle
				class="arc"
				cx="100"
				cy="100"
				r={R_PROG}
				fill="none"
				stroke={meta.color}
				stroke-width={compact ? 5 : 4}
				stroke-linecap="round"
				stroke-dasharray={CIRC}
				stroke-dashoffset={dashoffset}
			/>
		</g>
		{#if state === 'waiting' && steps}
			<circle class="waitdot" cx="100" cy="42" r="4.5" fill="#fcd34d" />
		{/if}
	</svg>

	<!-- core glow — breathing = readiness (ambient) · quick blink = request in flight -->
	<div
		class="glow absolute rounded-lg {busy ? 'shaping' : ambient ? 'breathe' : ''}"
		style="inset:{size * (compact ? 0.24 : 0.31)}px;background:rgba({glowRgb},{state === 'idle' ? 0.06 : 0.1});box-shadow:0 0 {compact ? 14 : 40}px {compact ? 3 : 8}px rgba({glowRgb},{state === 'idle' ? 0.18 : 0.32}), inset 0 0 {compact ? 10 : 24}px rgba({glowRgb},0.3);"
	></div>

	<!-- center readout -->
	<div class="absolute inset-0 flex flex-col items-center justify-center text-center px-3">
		{#if !compact}
			<span class="text-[9px] uppercase tracking-[0.24em]" style="color:{meta.color};">{label || $i18n.t(meta.word)}</span>
		{/if}
		{#if steps}
			<span class="font-semibold text-gray-50 tabular-nums leading-tight" style="font-size:{compact ? 15 : size * 0.14}px;"
				>{pct}<span class="text-[10px] text-gray-400">%</span></span
			>
			{#if !compact}<span class="text-[10px] text-gray-400">{steps} {$i18n.t('steps')} · {gates} {$i18n.t('gates')}</span>{/if}
		{:else}
			<span class="font-semibold text-cyan-200/70 leading-tight" style="font-size:{compact ? 14 : 20}px;">◈</span>
			{#if !compact}<span class="text-[10px] text-gray-500 mt-0.5">{$i18n.t('no task shaping yet')}</span>{/if}
		{/if}
	</div>
</div>

<style>
	/* Assemble once when the core materializes. */
	.hud {
		animation: hv-assemble 0.5s cubic-bezier(0.22, 1, 0.36, 1);
	}
	/* TRUTH — the arc moves only when real progress changes. */
	.arc {
		transition:
			stroke-dashoffset 500ms cubic-bezier(0.22, 1, 0.36, 1),
			stroke 300ms ease;
	}
	.glow {
		transition:
			background 300ms ease,
			box-shadow 300ms ease;
	}
	/* AMBIENT — readiness/listening, never progress. */
	.glow.breathe {
		animation: hv-breathe 4.5s ease-in-out infinite;
	}
	/* SHAPING — soft quick blink while a real request is in flight. */
	.glow.shaping {
		animation: hv-breathe 0.8s ease-in-out infinite;
	}
	/* CHROME — instrument drift ("system on"), not progress. */
	.rotA {
		transform-origin: 100px 100px;
		animation: hv-rot 60s linear infinite;
	}
	.rotB {
		transform-origin: 100px 100px;
		animation: hv-rot-rev 42s linear infinite;
	}
	/* WORK — sweep only exists while busy/planning/executing (see markup). */
	.sweep {
		transform-origin: 100px 100px;
		animation: hv-rot 2.6s linear infinite;
	}
	/* WAITING — persistent gentle pulse: a real "needs your approval" state. */
	.waitdot {
		animation: hv-pulse 1.6s ease-in-out infinite;
	}

	@keyframes hv-assemble {
		from {
			opacity: 0;
			transform: scale(0.92);
		}
		to {
			opacity: 1;
			transform: scale(1);
		}
	}
	@keyframes hv-breathe {
		0%,
		100% {
			opacity: 0.55;
			transform: scale(0.985);
		}
		50% {
			opacity: 1;
			transform: scale(1.015);
		}
	}
	@keyframes hv-rot {
		from {
			transform: rotate(0deg);
		}
		to {
			transform: rotate(360deg);
		}
	}
	@keyframes hv-rot-rev {
		from {
			transform: rotate(0deg);
		}
		to {
			transform: rotate(-360deg);
		}
	}
	@keyframes hv-pulse {
		0%,
		100% {
			opacity: 1;
		}
		50% {
			opacity: 0.3;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.arc,
		.glow {
			transition: none;
		}
		.hud,
		.glow.breathe,
		.glow.shaping,
		.rotA,
		.rotB,
		.sweep,
		.waitdot {
			animation: none;
		}
	}
</style>
