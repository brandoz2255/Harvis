<script lang="ts">
	// Animated Harvis mascot (blue robot). Ported from
	// newjfrontend/components/mascots/HarvisMascot.tsx — same states and
	// rAF-driven bob/antenna/wave animation, re-hued teal → blue.
	import { onMount, onDestroy } from 'svelte';

	export let state: 'idle' | 'lookLeft' | 'lookRight' | 'wave' | 'talking' | 'angry' = 'idle';
	export let size = 60;
	export let className = '';
	export let interactive = false;

	let currentState: string = state;
	let bobOffset = 0;
	let antennaWiggle = 0;
	let armRotation = 0;
	let clickCount = 0;
	let isAngry = false;
	let isStartled = false;

	let rafId: number | null = null;
	let cycleTimer: ReturnType<typeof setInterval> | null = null;
	let clickTimer: ReturnType<typeof setTimeout> | null = null;
	let angryTimer: ReturnType<typeof setTimeout> | null = null;
	let startleTimer: ReturnType<typeof setTimeout> | null = null;
	let waving = false;
	let waveFrame = 0;

	const CYCLE = ['idle', 'lookLeft', 'idle', 'lookRight', 'idle', 'wave'];

	// Accessibility + battery: honour prefers-reduced-motion (WCAG 2.3.3). When the user
	// asks for less motion we hold a static pose — no rAF, no idle look/wave cycle — and
	// we re-evaluate live so toggling the OS setting takes effect without a reload.
	let reduceMotion = false;
	let motionQuery: MediaQueryList | null = null;
	const onMotionChange = (e: MediaQueryListEvent | MediaQueryList) => {
		reduceMotion = e.matches;
		if (reduceMotion) {
			stopLoop();
			bobOffset = 0;
			antennaWiggle = 0;
			armRotation = 0;
			waving = false;
		} else {
			startLoop();
		}
		syncState(state, isAngry);
	};

	$: eyeOffset = currentState === 'lookLeft' ? -4 : currentState === 'lookRight' ? 4 : 0;
	$: isSmiling = currentState === 'idle' || currentState === 'wave';

	$: syncState(state, isAngry);

	const syncState = (s: string, angry: boolean) => {
		if (cycleTimer) {
			clearInterval(cycleTimer);
			cycleTimer = null;
		}
		if (angry) {
			currentState = 'angry';
			return;
		}
		if (s !== 'idle') {
			currentState = s;
			return;
		}
		currentState = 'idle';
		// Reduced motion: stay in the static idle pose — no auto look/wave cycle.
		if (reduceMotion) return;
		let i = 0;
		cycleTimer = setInterval(() => {
			i = (i + 1) % CYCLE.length;
			currentState = CYCLE[i];
		}, 2000);
	};

	$: onCurrentState(currentState);
	const onCurrentState = (cs: string) => {
		if (cs === 'wave') {
			waving = true;
			waveFrame = 0;
		} else {
			waving = false;
			armRotation = 0;
		}
	};

	let frame = 0;
	const loop = () => {
		frame++;
		bobOffset = Math.sin(frame * 0.05) * 2;
		antennaWiggle = Math.sin(frame * 0.08) * 3;
		if (waving) {
			waveFrame++;
			if (waveFrame < 40) {
				armRotation = Math.sin(waveFrame * 0.3) * 30;
			} else {
				armRotation = 0;
				waving = false;
			}
		}
		rafId = requestAnimationFrame(loop);
	};

	const startLoop = () => {
		if (rafId !== null || reduceMotion) return;
		rafId = requestAnimationFrame(loop);
	};
	const stopLoop = () => {
		if (rafId !== null) cancelAnimationFrame(rafId);
		rafId = null;
	};
	// A background tab should not burn frames (or battery) animating something nobody sees.
	const onVisibility = () => (document.hidden ? stopLoop() : startLoop());

	onMount(() => {
		motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
		onMotionChange(motionQuery);
		motionQuery.addEventListener('change', onMotionChange);
		document.addEventListener('visibilitychange', onVisibility);
		startLoop();
	});

	onDestroy(() => {
		stopLoop();
		motionQuery?.removeEventListener('change', onMotionChange);
		if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisibility);
		if (cycleTimer) clearInterval(cycleTimer);
		if (clickTimer) clearTimeout(clickTimer);
		if (angryTimer) clearTimeout(angryTimer);
		if (startleTimer) clearTimeout(startleTimer);
	});

	const handleClick = () => {
		if (!interactive) return;
		clickCount++;
		if (clickCount >= 4) {
			isAngry = true;
			isStartled = false;
			clickCount = 0;
			if (angryTimer) clearTimeout(angryTimer);
			angryTimer = setTimeout(() => {
				isAngry = false;
			}, 1000);
		} else {
			isStartled = true;
			if (startleTimer) clearTimeout(startleTimer);
			startleTimer = setTimeout(() => {
				isStartled = false;
			}, 300);
		}
		if (clickTimer) clearTimeout(clickTimer);
		clickTimer = setTimeout(() => {
			clickCount = 0;
		}, 2000);
	};

	// Theme accent — --color-blue-* re-hues per theme (Midnight cyan-blue,
	// Airy indigo, Warm coral). ANGRY stays hardcoded red: semantic state color.
	const ACCENT = 'var(--harvis-mark-accent)';
	const ANGRY = '#E53E3E';
	$: accent = isAngry ? ANGRY : ACCENT;
</script>

<!-- svelte-ignore a11y-click-events-have-key-events a11y-no-noninteractive-element-interactions -->
<svg
	width={size}
	height={size}
	viewBox="0 0 60 70"
	class="{className} {interactive ? 'cursor-pointer' : ''}"
	style="transform: translateY({bobOffset + (isStartled ? -8 : 0)}px) scale({isStartled
		? 1.1
		: 1}); transition: {isStartled ? 'transform 0.1s ease-out' : 'transform 0.3s ease'}"
	xmlns="http://www.w3.org/2000/svg"
	role="img"
	aria-hidden="true"
	on:click={handleClick}
>
	<defs>
		<filter id="harvisGlow" x="-50%" y="-50%" width="200%" height="200%">
			<feGaussianBlur stdDeviation="1.5" result="coloredBlur" />
			<feMerge>
				<feMergeNode in="coloredBlur" />
				<feMergeNode in="SourceGraphic" />
			</feMerge>
		</filter>
		<linearGradient id="harvisBodyGradient" x1="0%" y1="0%" x2="0%" y2="100%">
			<stop offset="0%" stop-color="var(--color-blue-500)" />
			<stop offset="100%" stop-color="var(--color-blue-700)" />
		</linearGradient>
		<linearGradient id="harvisScreenGradient" x1="0%" y1="0%" x2="0%" y2="100%">
			<stop offset="0%" stop-color="var(--color-gray-800)" />
			<stop offset="100%" stop-color="var(--color-gray-950)" />
		</linearGradient>
		<linearGradient id="harvisAngryGradient" x1="0%" y1="0%" x2="0%" y2="100%">
			<stop offset="0%" stop-color="#FC8181" />
			<stop offset="100%" stop-color="#E53E3E" />
		</linearGradient>
	</defs>

	<!-- antennae -->
	<g style="transform-origin: 20px 8px; transform: rotate({antennaWiggle}deg)">
		<line x1="20" y1="8" x2="16" y2="0" stroke={accent} stroke-width="2" stroke-linecap="round" />
		<circle cx="16" cy="2" r="3" fill={accent} filter="url(#harvisGlow)" />
	</g>
	<g style="transform-origin: 40px 8px; transform: rotate({-antennaWiggle}deg)">
		<line x1="40" y1="8" x2="44" y2="0" stroke={accent} stroke-width="2" stroke-linecap="round" />
		<circle cx="44" cy="2" r="3" fill={accent} filter="url(#harvisGlow)" />
	</g>

	<!-- head + screen -->
	<rect
		x="12"
		y="8"
		width="36"
		height="30"
		rx="6"
		fill={isAngry ? 'url(#harvisAngryGradient)' : 'url(#harvisBodyGradient)'}
	/>
	<rect x="16" y="12" width="28" height="22" rx="3" fill="url(#harvisScreenGradient)" />

	<!-- eyes -->
	<g style="transform: translateX({eyeOffset}px); transition: transform 0.3s ease">
		{#if isAngry}
			<line x1="19" y1="15" x2="28" y2="18" stroke={ANGRY} stroke-width="2.5" stroke-linecap="round" />
			<line x1="41" y1="15" x2="32" y2="18" stroke={ANGRY} stroke-width="2.5" stroke-linecap="round" />
			<ellipse cx="24" cy="22" rx="4" ry="2" fill={ANGRY} />
			<ellipse cx="24" cy="22" rx="2" ry="1" fill="#FED7D7" />
			<ellipse cx="36" cy="22" rx="4" ry="2" fill={ANGRY} />
			<ellipse cx="36" cy="22" rx="2" ry="1" fill="#FED7D7" />
		{:else if isStartled}
			<circle cx="24" cy="20" r="5" fill={ACCENT} filter="url(#harvisGlow)" />
			<circle cx="24" cy="20" r="2.5" fill="var(--color-gray-50)" />
			<circle cx="24" cy="19" r="1" fill="#ffffff" />
			<circle cx="36" cy="20" r="5" fill={ACCENT} filter="url(#harvisGlow)" />
			<circle cx="36" cy="20" r="2.5" fill="var(--color-gray-50)" />
			<circle cx="36" cy="19" r="1" fill="#ffffff" />
		{:else if isSmiling}
			<path
				d="M21 21 Q24 17 27 21"
				stroke={ACCENT}
				stroke-width="2.5"
				stroke-linecap="round"
				fill="none"
				filter="url(#harvisGlow)"
			/>
			<path
				d="M33 21 Q36 17 39 21"
				stroke={ACCENT}
				stroke-width="2.5"
				stroke-linecap="round"
				fill="none"
				filter="url(#harvisGlow)"
			/>
		{:else}
			<ellipse cx="24" cy="20" rx="3" ry="4" fill={ACCENT} filter="url(#harvisGlow)" />
			<ellipse cx="24" cy="20" rx="1.5" ry="2" fill="var(--color-gray-50)" />
			<ellipse cx="36" cy="20" rx="3" ry="4" fill={ACCENT} filter="url(#harvisGlow)" />
			<ellipse cx="36" cy="20" rx="1.5" ry="2" fill="var(--color-gray-50)" />
		{/if}
	</g>

	<!-- mouth -->
	{#if isAngry}
		<path d="M24 30 Q30 26 36 30" stroke={ANGRY} stroke-width="2" stroke-linecap="round" fill="none" />
	{:else if isSmiling && !isStartled}
		<path
			d="M24 28 Q30 33 36 28"
			stroke={ACCENT}
			stroke-width="2"
			stroke-linecap="round"
			fill="none"
			filter="url(#harvisGlow)"
		/>
	{/if}

	<!-- legs + base -->
	<rect
		x="14"
		y="38"
		width="10"
		height="28"
		rx="3"
		fill={isAngry ? 'url(#harvisAngryGradient)' : 'url(#harvisBodyGradient)'}
	/>
	<rect
		x="36"
		y="38"
		width="10"
		height="28"
		rx="3"
		fill={isAngry ? 'url(#harvisAngryGradient)' : 'url(#harvisBodyGradient)'}
	/>
	<rect
		x="14"
		y="48"
		width="32"
		height="8"
		rx="2"
		fill={isAngry ? 'url(#harvisAngryGradient)' : 'url(#harvisBodyGradient)'}
	/>

	<!-- arms (right one waves) -->
	<rect x="4" y="42" width="6" height="14" rx="3" fill={accent} />
	<g
		style="transform-origin: 53px 42px; transform: rotate({armRotation}deg); transition: {currentState ===
		'wave'
			? 'none'
			: 'transform 0.3s ease'}"
	>
		<rect x="50" y="42" width="6" height="14" rx="3" fill={accent} />
	</g>
</svg>
