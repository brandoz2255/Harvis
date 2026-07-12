<script lang="ts">
	// "Effort" popover panel: a wide Faster ⟷ Smarter slider with a textured track + white thumb.
	// Rendered as Dropdown content (a popover above the composer effort button — NOT a modal). Sets the
	// model's reasoning effort (Low→Faster … Max→Smarter); saves ONLY the effort (partial profile update).
	import { createEventDispatcher, getContext } from 'svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import { saveModelProfile } from '$lib/apis/model-profiles';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let model: any = {};

	const LEVELS = ['low', 'medium', 'high', 'max'];
	const LABELS: Record<string, string> = { low: 'Low', medium: 'Medium', high: 'High', max: 'Max' };

	let trackEl: HTMLDivElement;
	let dragging = false;
	let liveLevel: string | null = null;

	$: current = liveLevel ?? model?.info?.meta?.profile_effort ?? 'medium';
	$: idx = Math.max(0, LEVELS.indexOf(current));
	$: pct = (idx / (LEVELS.length - 1)) * 100;

	const levelFromX = (clientX: number): string => {
		if (!trackEl) return 'medium';
		const r = trackEl.getBoundingClientRect();
		const frac = Math.min(1, Math.max(0, (clientX - r.left) / r.width));
		return LEVELS[Math.round(frac * (LEVELS.length - 1))];
	};

	const commit = async (lvl: string) => {
		liveLevel = null;
		model.info = model.info ?? {};
		model.info.meta = { ...(model.info.meta ?? {}), profile_effort: lvl };
		model = model;
		try {
			await saveModelProfile(localStorage.token, model.id, { effort: lvl });
			dispatch('changed', { id: model.id, effort: lvl });
		} catch (_) {
			/* keep optimistic value */
		}
	};

	const onDown = (e: PointerEvent) => {
		e.preventDefault();
		e.stopPropagation();
		dragging = true;
		trackEl?.setPointerCapture?.(e.pointerId);
		liveLevel = levelFromX(e.clientX);
	};
	const onMove = (e: PointerEvent) => {
		if (!dragging) return;
		liveLevel = levelFromX(e.clientX);
	};
	const onUp = (e: PointerEvent) => {
		if (!dragging) return;
		dragging = false;
		trackEl?.releasePointerCapture?.(e.pointerId);
		commit(levelFromX(e.clientX));
	};
</script>

<div class="px-3.5 py-3 text-gray-800 dark:text-gray-100">
	<!-- header -->
	<div class="flex items-center justify-between mb-2.5">
		<div class="text-sm">
			<span class="text-gray-500 dark:text-gray-400">{$i18n.t('Effort')}</span>
			<span class="font-medium text-indigo-500 dark:text-indigo-400 ml-1">{LABELS[current]}</span>
		</div>
		<Tooltip content={$i18n.t('Faster = quicker, less thinking. Smarter = deeper reasoning, slower. Applied on API-key Claude; best-effort on subscription.')}>
			<svg class="size-4 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/></svg>
		</Tooltip>
	</div>

	<div class="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400 mb-1.5">
		<span>{$i18n.t('Faster')}</span>
		<span>{$i18n.t('Smarter')}</span>
	</div>

	<!-- slider track -->
	<div
		bind:this={trackEl}
		class="effort-track relative h-7 rounded-lg cursor-ew-resize select-none touch-none"
		role="slider"
		tabindex="-1"
		aria-label={$i18n.t('Reasoning effort')}
		aria-valuemin="0"
		aria-valuemax={LEVELS.length - 1}
		aria-valuenow={idx}
		on:pointerdown={onDown}
		on:pointermove={onMove}
		on:pointerup={onUp}
	>
		<div
			class="absolute inset-y-0 left-0 rounded-lg bg-indigo-500/20 dark:bg-indigo-400/20 pointer-events-none"
			style="width: {pct}%"
		/>
		<div
			class="absolute size-5 rounded-full bg-white shadow-md ring-1 ring-black/10 pointer-events-none transition-all duration-75"
			style="top: 50%; left: calc(10px + {pct} * (100% - 20px) / 100); transform: translate(-50%, -50%);"
		/>
	</div>

	<!-- footer: model + current level -->
	<div class="flex items-center justify-between mt-3">
		<span class="text-sm truncate mr-2">{model?.name ?? model?.id}</span>
		<span
			class="shrink-0 px-2 py-0.5 rounded-md text-xs font-medium bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-200"
			>{LABELS[current]}</span
		>
	</div>
</div>

<style>
	.effort-track {
		background-image:
			radial-gradient(circle at 1px 1px, rgba(255, 255, 255, 0.18) 1px, transparent 1.4px),
			linear-gradient(90deg, rgba(120, 120, 135, 0.35), rgba(99, 102, 241, 0.45));
		background-size:
			6px 6px,
			100% 100%;
	}
	:global(.dark) .effort-track {
		background-image:
			radial-gradient(circle at 1px 1px, rgba(255, 255, 255, 0.12) 1px, transparent 1.4px),
			linear-gradient(90deg, rgba(80, 80, 95, 0.5), rgba(99, 102, 241, 0.5));
		background-size:
			6px 6px,
			100% 100%;
	}
</style>
