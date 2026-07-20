<script lang="ts" context="module">
	export type MascotState =
		| 'idle'
		| 'thinking'
		| 'working'
		| 'needs_approval'
		| 'success'
		| 'error'
		| 'cancelled'
		| 'sleeping';

	// One-shots must NOT loop. A mascot still waving over a finished run implies
	// live activity — that exact bug already shipped once with the SVG mascots and
	// had to be fixed, so it is enforced here in the player rather than left to
	// each call site to remember.
	const ONE_SHOT: MascotState[] = ['success', 'error', 'cancelled'];

	// Clips worth having in cache before they're needed. Deliberately small: idle
	// is near-permanent and working is the most common transition out of it.
	const PRELOAD: MascotState[] = ['idle', 'working'];
</script>

<script lang="ts">
	import { onMount, onDestroy } from 'svelte';

	export let state: MascotState = 'idle';
	export let size = 96;
	export let label = 'Harvis';
	/** true = purely decorative; hidden from screen readers. */
	export let decorative = false;
	/** Where the clips live. Overridable so the same component works in the prototype. */
	export let basePath = '/mascot';

	const FILES: Record<MascotState, string> = {
		idle: 'harvis-idle.webm',
		thinking: 'harvis-thinking.webm',
		working: 'harvis-working.webm',
		needs_approval: 'harvis-approval.webm',
		success: 'harvis-success.webm',
		error: 'harvis-error.webm',
		cancelled: 'harvis-cancelled.webm',
		sleeping: 'harvis-sleeping.webm'
	};

	let video: HTMLVideoElement | null = null;
	let reduceMotion = false;
	let motionQuery: MediaQueryList | null = null;
	/** After a one-shot finishes we settle back to idle rather than freezing. */
	let settled: MascotState | null = null;
	/** A clip that 404s (pack not generated yet) falls back to idle, then to nothing. */
	let failed = new Set<string>();

	$: effective = settled ?? state;
	$: src = `${basePath}/${FILES[effective] ?? FILES.idle}`;
	$: loops = !ONE_SHOT.includes(effective);
	$: unavailable = failed.has(src);

	// Restart on every state change — without this, switching between two looping
	// clips can leave the new one paused at the old one's currentTime.
	$: if (video && src) restart(src);

	const restart = (_src: string) => {
		if (!video) return;
		try {
			video.currentTime = 0;
			if (!reduceMotion && !document.hidden) void video.play().catch(() => {});
		} catch {
			/* a not-yet-loaded element throws on currentTime; the load event covers it */
		}
	};

	// Leaving a one-shot state cancels any pending settle, so a fast
	// success → working transition doesn't get yanked back to idle afterwards.
	$: if (!ONE_SHOT.includes(state)) settled = null;

	const onEnded = () => {
		// Only one-shots settle. Looping clips never fire this.
		if (ONE_SHOT.includes(effective)) settled = 'idle';
	};

	const onError = () => {
		failed = new Set([...failed, src]);
		// Missing clip → fall back to idle so a partial pack still animates.
		if (effective !== 'idle' && !failed.has(`${basePath}/${FILES.idle}`)) settled = 'idle';
	};

	const applyMotion = (e: MediaQueryListEvent | MediaQueryList) => {
		reduceMotion = e.matches;
		if (!video) return;
		if (reduceMotion) {
			// Hold frame 0: the character is still *present* and readable, it just
			// doesn't move. Better than hiding it — the mascot carries run state.
			video.pause();
			try {
				video.currentTime = 0;
			} catch {
				/* not loaded yet */
			}
		} else {
			void video.play().catch(() => {});
		}
	};

	// A background tab should not decode video frames.
	const onVisibility = () => {
		if (!video) return;
		if (document.hidden) video.pause();
		else if (!reduceMotion) void video.play().catch(() => {});
	};

	onMount(() => {
		motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
		applyMotion(motionQuery);
		motionQuery.addEventListener('change', applyMotion);
		document.addEventListener('visibilitychange', onVisibility);

		// Warm the cache for the clips we'll almost certainly need.
		for (const s of PRELOAD) {
			const l = document.createElement('link');
			l.rel = 'prefetch';
			l.as = 'video';
			l.href = `${basePath}/${FILES[s]}`;
			document.head.appendChild(l);
		}
	});

	onDestroy(() => {
		motionQuery?.removeEventListener('change', applyMotion);
		if (typeof document !== 'undefined')
			document.removeEventListener('visibilitychange', onVisibility);
	});
</script>

{#if !unavailable}
	<video
		bind:this={video}
		{src}
		width={size}
		height={size}
		style="width:{size}px;height:{size}px;image-rendering:pixelated;"
		autoplay={!reduceMotion}
		muted
		playsinline
		loop={loops}
		preload="auto"
		on:ended={onEnded}
		on:error={onError}
		on:loadeddata={() => restart(src)}
		aria-hidden={decorative ? 'true' : undefined}
		aria-label={decorative ? undefined : label}
		role={decorative ? undefined : 'img'}
	/>
{/if}
