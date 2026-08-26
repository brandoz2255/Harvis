<script lang="ts">
	// Animated workspace mascot — the "little guy": light-blue Harvis buddy
	// with grabber claws. Ported from
	// newjfrontend/components/mascots/HarvisClawMascot.tsx (red OpenClaw
	// variant), re-hued to the blue family. Claws animate continuously while
	// state === 'working'.
	import { onMount, onDestroy } from 'svelte';

	export let state: 'idle' | 'lookLeft' | 'lookRight' | 'wave' | 'working' | 'angry' = 'idle';
	export let size = 60;
	export let className = '';
	export let interactive = false;
	// Ambient look-around/wave cycle while idle. Turn OFF where "idle" means *finished*
	// rather than *waiting* — a mascot waving over a completed run implies live activity.
	export let idleCycle = true;

	let currentState: string = state;
	let bobOffset = 0;
	let antennaWiggle = 0;
	let clawOpenLeft = 0;
	let clawOpenRight = 0;
	let clickCount = 0;
	let isAngry = false;
	let isStartled = false;

	let rafId: number | null = null;
	let cycleTimer: ReturnType<typeof setInterval> | null = null;
	let clickTimer: ReturnType<typeof setTimeout> | null = null;
	let angryTimer: ReturnType<typeof setTimeout> | null = null;
	let startleTimer: ReturnType<typeof setTimeout> | null = null;
	let burst = false;
	let burstFrame = 0;

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
			clawOpenLeft = 0;
			clawOpenRight = 0;
			burst = false;
		} else {
			startLoop();
		}
		syncState(state, isAngry, idleCycle);
	};

	$: eyeOffset = currentState === 'lookLeft' ? -4 : currentState === 'lookRight' ? 4 : 0;
	$: isSmiling = currentState === 'idle' || currentState === 'wave' || currentState === 'working';

	$: syncState(state, isAngry, idleCycle);

	const syncState = (s: string, angry: boolean, cycle = true) => {
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
		// Static idle pose — no auto look/wave cycle — when the caller opted out, or the
		// user asked for reduced motion.
		if (!cycle || reduceMotion) return;
		let i = 0;
		cycleTimer = setInterval(() => {
			i = (i + 1) % CYCLE.length;
			currentState = CYCLE[i];
		}, 2000);
	};

	$: onCurrentState(currentState);
	const onCurrentState = (cs: string) => {
		if (cs === 'wave') {
			burst = true;
			burstFrame = 0;
		}
	};

	let frame = 0;
	const loop = () => {
		frame++;
		bobOffset = Math.sin(frame * 0.05) * 2;
		antennaWiggle = Math.sin(frame * 0.08) * 3;
		if (state === 'working') {
			clawOpenLeft = Math.sin(frame * 0.2) * 12;
			clawOpenRight = Math.sin(frame * 0.2 + Math.PI) * 12;
		} else if (burst) {
			burstFrame++;
			if (burstFrame < 60) {
				clawOpenLeft = Math.sin(burstFrame * 0.4) * 15;
				clawOpenRight = Math.sin(burstFrame * 0.4 + Math.PI) * 15;
			} else {
				burst = false;
				clawOpenLeft = 0;
				clawOpenRight = 0;
			}
		} else if (clawOpenLeft !== 0 || clawOpenRight !== 0) {
			clawOpenLeft = 0;
			clawOpenRight = 0;
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
		if (rafId !== null) cancelAnimationFrame(rafId);
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
	viewBox="-7 -3 94 82"
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
		<filter id="clawGlow" x="-50%" y="-50%" width="200%" height="200%">
			<feGaussianBlur stdDeviation="1.5" result="coloredBlur" />
			<feMerge>
				<feMergeNode in="coloredBlur" />
				<feMergeNode in="SourceGraphic" />
			</feMerge>
		</filter>
		<linearGradient id="clawHeadGradient" x1="0%" y1="0%" x2="0%" y2="100%">
			<stop offset="0%" stop-color="var(--harvis-mark-accent)" />
			<stop offset="100%" stop-color="var(--color-blue-600)" />
		</linearGradient>
		<linearGradient id="clawScreenGradient" x1="0%" y1="0%" x2="0%" y2="100%">
			<stop offset="0%" stop-color="var(--color-gray-800)" />
			<stop offset="100%" stop-color="var(--color-gray-950)" />
		</linearGradient>
		<linearGradient id="clawGradient" x1="0%" y1="0%" x2="0%" y2="100%">
			<stop offset="0%" stop-color="var(--harvis-mark-accent)" />
			<stop offset="100%" stop-color="var(--color-blue-600)" />
		</linearGradient>
		<linearGradient id="clawBodyGradient" x1="0%" y1="0%" x2="0%" y2="100%">
			<stop offset="0%" stop-color="var(--color-blue-500)" />
			<stop offset="100%" stop-color="var(--color-blue-700)" />
		</linearGradient>
		<linearGradient id="clawAngryGradient" x1="0%" y1="0%" x2="0%" y2="100%">
			<stop offset="0%" stop-color="#FC8181" />
			<stop offset="100%" stop-color="#E53E3E" />
		</linearGradient>
	</defs>

	<!-- antennae -->
	<g style="transform-origin: 30px 8px; transform: rotate({antennaWiggle}deg)">
		<line x1="30" y1="8" x2="26" y2="0" stroke={accent} stroke-width="2" stroke-linecap="round" />
		<circle cx="26" cy="2" r="3" fill={accent} filter="url(#clawGlow)" />
	</g>
	<g style="transform-origin: 50px 8px; transform: rotate({-antennaWiggle}deg)">
		<line x1="50" y1="8" x2="54" y2="0" stroke={accent} stroke-width="2" stroke-linecap="round" />
		<circle cx="54" cy="2" r="3" fill={accent} filter="url(#clawGlow)" />
	</g>

	<!-- head + screen -->
	<rect
		x="22"
		y="8"
		width="36"
		height="30"
		rx="6"
		fill={isAngry ? 'url(#clawAngryGradient)' : 'url(#clawHeadGradient)'}
	/>
	<rect x="26" y="12" width="28" height="22" rx="3" fill="url(#clawScreenGradient)" />

	<!-- eyes -->
	<g style="transform: translateX({eyeOffset}px); transition: transform 0.3s ease">
		{#if isAngry}
			<line x1="29" y1="15" x2="38" y2="18" stroke={ANGRY} stroke-width="2.5" stroke-linecap="round" />
			<line x1="51" y1="15" x2="42" y2="18" stroke={ANGRY} stroke-width="2.5" stroke-linecap="round" />
			<ellipse cx="34" cy="22" rx="4" ry="2" fill={ANGRY} />
			<ellipse cx="34" cy="22" rx="2" ry="1" fill="#FED7D7" />
			<ellipse cx="46" cy="22" rx="4" ry="2" fill={ANGRY} />
			<ellipse cx="46" cy="22" rx="2" ry="1" fill="#FED7D7" />
		{:else if isStartled}
			<circle cx="34" cy="20" r="5" fill={ACCENT} filter="url(#clawGlow)" />
			<circle cx="34" cy="20" r="2.5" fill="var(--color-gray-50)" />
			<circle cx="34" cy="19" r="1" fill="#ffffff" />
			<circle cx="46" cy="20" r="5" fill={ACCENT} filter="url(#clawGlow)" />
			<circle cx="46" cy="20" r="2.5" fill="var(--color-gray-50)" />
			<circle cx="46" cy="19" r="1" fill="#ffffff" />
		{:else if isSmiling}
			<path
				d="M31 21 Q34 17 37 21"
				stroke={ACCENT}
				stroke-width="2.5"
				stroke-linecap="round"
				fill="none"
				filter="url(#clawGlow)"
			/>
			<path
				d="M43 21 Q46 17 49 21"
				stroke={ACCENT}
				stroke-width="2.5"
				stroke-linecap="round"
				fill="none"
				filter="url(#clawGlow)"
			/>
		{:else}
			<ellipse cx="34" cy="20" rx="3" ry="4" fill={ACCENT} filter="url(#clawGlow)" />
			<ellipse cx="34" cy="20" rx="1.5" ry="2" fill="var(--color-gray-50)" />
			<ellipse cx="46" cy="20" rx="3" ry="4" fill={ACCENT} filter="url(#clawGlow)" />
			<ellipse cx="46" cy="20" rx="1.5" ry="2" fill="var(--color-gray-50)" />
		{/if}
	</g>

	<!-- mouth -->
	{#if isAngry}
		<path d="M34 30 Q40 26 46 30" stroke={ANGRY} stroke-width="2" stroke-linecap="round" fill="none" />
	{:else if isSmiling && !isStartled}
		<path
			d="M34 28 Q40 33 46 28"
			stroke={ACCENT}
			stroke-width="2"
			stroke-linecap="round"
			fill="none"
			filter="url(#clawGlow)"
		/>
	{/if}

	<!-- legs + base + H chest -->
	<rect x="24" y="38" width="10" height="24" rx="3" fill="url(#clawBodyGradient)" />
	<rect x="46" y="38" width="10" height="24" rx="3" fill="url(#clawBodyGradient)" />
	<rect x="24" y="46" width="32" height="10" rx="2" fill="url(#clawBodyGradient)" />
	<text x="40" y="55" text-anchor="middle" font-size="10" font-weight="bold" fill="var(--color-gray-50)">H</text>

	<!-- left claw arm -->
	<g style="transform-origin: 16px 45px">
		<ellipse cx="12" cy="42" rx="8" ry="6" fill="url(#clawGradient)" />
		<g style="transform-origin: 8px 50px">
			<path
				d={`M3 ${44 - clawOpenLeft * 0.3} Q8 ${40 - clawOpenLeft * 0.3} 10 ${46 - clawOpenLeft * 0.2}`}
				fill="url(#clawGradient)"
				stroke="var(--color-blue-700)"
				stroke-width="1"
			/>
			<ellipse cx="3" cy={44 - clawOpenLeft * 0.3} rx="4" ry="5" fill="url(#clawGradient)" />
			<path
				d={`M3 ${52 + clawOpenLeft * 0.3} Q8 ${56 + clawOpenLeft * 0.3} 10 ${50 + clawOpenLeft * 0.2}`}
				fill="url(#clawGradient)"
				stroke="var(--color-blue-700)"
				stroke-width="1"
			/>
			<ellipse cx="3" cy={52 + clawOpenLeft * 0.3} rx="4" ry="5" fill="url(#clawGradient)" />
		</g>
	</g>

	<!-- right claw arm -->
	<g style="transform-origin: 64px 45px">
		<ellipse cx="68" cy="42" rx="8" ry="6" fill="url(#clawGradient)" />
		<g style="transform-origin: 72px 50px">
			<path
				d={`M77 ${44 - clawOpenRight * 0.3} Q72 ${40 - clawOpenRight * 0.3} 70 ${46 - clawOpenRight * 0.2}`}
				fill="url(#clawGradient)"
				stroke="var(--color-blue-700)"
				stroke-width="1"
			/>
			<ellipse cx="77" cy={44 - clawOpenRight * 0.3} rx="4" ry="5" fill="url(#clawGradient)" />
			<path
				d={`M77 ${52 + clawOpenRight * 0.3} Q72 ${56 + clawOpenRight * 0.3} 70 ${50 + clawOpenRight * 0.2}`}
				fill="url(#clawGradient)"
				stroke="var(--color-blue-700)"
				stroke-width="1"
			/>
			<ellipse cx="77" cy={52 + clawOpenRight * 0.3} rx="4" ry="5" fill="url(#clawGradient)" />
		</g>
	</g>
</svg>
