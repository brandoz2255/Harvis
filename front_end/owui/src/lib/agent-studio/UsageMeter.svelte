<script lang="ts">
	// Reusable context / token / cost meter — a compact gauge that opens an
	// image-style popup. Props-driven so any surface (the VibeCode composer, the
	// run view) can feed it the model's context window + price and the run's
	// token totals. Extracted from the VibeCode composer meter.
	import { getContext } from 'svelte';
	const i18n: any = getContext('i18n');

	export let ctxUsed = 0; // input tokens (+ live output while running)
	export let ctxWindow = 24576; // the model's context window
	export let sessionTokens = 0; // total tokens this run (in + out, + live)
	export let costUsd = 0; // estimated $ this run
	export let modelName = '';
	export let isFree = true; // local model → no cost
	export let live = false; // animate the bar while the run is active
	export let lastIn = 0; // last-turn input tokens
	export let lastOut = 0; // last-turn output tokens
	export let atApiRates = false; // subscription → "at API rates"
	export let align: 'left' | 'right' = 'right';
	// Which way the popup opens. The default keeps every existing call site unchanged; the
	// chat composer sits at the bottom of the viewport, where a downward panel is off-screen.
	export let placement: 'top' | 'bottom' = 'bottom';
	// What "free" reads as in the popup. Defaults to the local-model wording this meter was
	// built for; a connected free-tier vendor key is free but not local, so that caller
	// overrides it rather than having the meter claim something untrue about where it ran.
	export let freeLabel = '';

	let open = false;
	$: ctxPct = ctxWindow ? Math.min(100, Math.round((ctxUsed / ctxWindow) * 100)) : 0;
	$: ctxAvail = Math.max(0, ctxWindow - ctxUsed);

	const fmtTok = (n: number) =>
		n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1) + 'k' : String(Math.round(n || 0));
	const fmtCost = (n: number) =>
		n >= 1 ? '$' + n.toFixed(2) : n > 0 ? '$' + n.toFixed(3) : '$0';
</script>

<div class="relative">
	<button
		type="button"
		class="flex items-center gap-2 px-2 py-1 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-850 transition"
		on:click={() => (open = !open)}
		title={$i18n.t('Context & usage')}
	>
		<div class="flex flex-col items-end leading-tight">
			<span class="tabular-nums text-[11px] text-gray-500 dark:text-gray-400"
				>{fmtTok(ctxUsed)} / {fmtTok(ctxWindow)} · {ctxPct}%</span
			>
			<span class="tabular-nums text-[10px] text-gray-400 dark:text-gray-500">
				{#if isFree}{$i18n.t('Free')}{:else}{fmtCost(costUsd)}{/if} · {fmtTok(sessionTokens)} tok
			</span>
		</div>
		<div class="w-14 h-1.5 rounded-full bg-gray-200 dark:bg-gray-800 overflow-hidden">
			<div
				class="h-full rounded-full transition-all {live ? 'animate-pulse ' : ''}{ctxPct > 85
					? 'bg-red-500'
					: 'bg-blue-500'}"
				style="width: {ctxPct}%"
			></div>
		</div>
	</button>

	{#if open}
		<button
			type="button"
			class="fixed inset-0 z-40 cursor-default"
			on:click={() => (open = false)}
			aria-label="Close usage panel"
		></button>
		<div
			class="absolute {align === 'right' ? 'right-0' : 'left-0'} {placement === 'top'
				? 'bottom-full mb-2'
				: 'top-full mt-2'} z-50 w-64 rounded-xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-900 shadow-xl p-3 text-xs space-y-2"
		>
			<div class="flex justify-between text-gray-700 dark:text-gray-200 font-medium">
				<span>{$i18n.t('Context window')}</span>
				<span class="tabular-nums">{ctxUsed.toLocaleString()} / {ctxWindow.toLocaleString()}</span>
			</div>
			<div class="h-1.5 rounded-full bg-gray-200 dark:bg-gray-800 overflow-hidden">
				<div
					class="h-full rounded-full {ctxPct > 85 ? 'bg-red-500' : 'bg-blue-500'}"
					style="width: {ctxPct}%"
				></div>
			</div>
			<div class="flex justify-between text-gray-500">
				<span>{$i18n.t('Used')}</span><span class="tabular-nums">{ctxPct}%</span>
			</div>
			<div class="flex justify-between text-gray-500">
				<span>{$i18n.t('Available')}</span
				><span class="tabular-nums">{ctxAvail.toLocaleString()} {$i18n.t('tokens')}</span>
			</div>
			{#if lastIn || lastOut}
				<div class="flex justify-between text-gray-500">
					<span>{$i18n.t('Last turn')}</span>
					<span class="tabular-nums">↑ {fmtTok(lastIn)} · ↓ {fmtTok(lastOut)}</span>
				</div>
			{/if}
			<div class="flex justify-between text-gray-500">
				<span>{$i18n.t('Session total')}</span
				><span class="tabular-nums">{sessionTokens.toLocaleString()} {$i18n.t('tokens')}</span>
			</div>
			<div class="flex justify-between text-gray-700 dark:text-gray-200 font-medium pt-1 border-t border-gray-100 dark:border-gray-850">
				<span>{$i18n.t('Est. cost')}</span>
				<span class="tabular-nums">
					{#if isFree}{freeLabel || $i18n.t('Free · local')}{:else}{fmtCost(costUsd)}{#if atApiRates}
							<span class="text-gray-400 font-normal">· {$i18n.t('at API rates')}</span>{/if}{/if}
				</span>
			</div>
			{#if modelName}
				<div class="flex justify-between text-gray-400 text-[11px]">
					<span>{$i18n.t('Model')}</span><span class="truncate ml-2 font-mono">{modelName}</span>
				</div>
			{/if}
		</div>
	{/if}
</div>
