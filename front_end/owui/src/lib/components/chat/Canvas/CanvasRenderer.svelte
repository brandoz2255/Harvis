<script lang="ts">
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';
	import { canvasChartToVegaLite, renderVegaVisualization } from '$lib/utils';

	const i18n = getContext<Writable<i18nType>>('i18n');

	// The typed ```canvas panel — a JSON spec of blocks (stat/table/chart/callout/
	// diff/heading/text) rendered as a rich card, both INLINE in the message
	// (mode='inline', via CodeBlock) and in the Artifacts rail (mode='panel').
	// `spec` may be a parsed object OR a raw JSON string; parsing is DEFENSIVE —
	// malformed input renders an honest error card, it never throws into the chat.
	export let spec: any = null;
	export let mode: 'inline' | 'panel' = 'inline';
	// Inline-only affordance: push this canvas to the right-side Artifacts rail.
	export let onOpen: (() => void) | null = null;

	type CanvasBlock = Record<string, any>;

	let title = '';
	let blocks: CanvasBlock[] = [];
	let parseError: string | null = null;

	const TONE_CLASSES: Record<string, string> = {
		info: 'border-blue-500/20 bg-blue-500/10 text-blue-700 dark:text-blue-300',
		good: 'border-green-500/20 bg-green-500/10 text-green-700 dark:text-green-300',
		warning: 'border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-300',
		danger: 'border-red-500/20 bg-red-500/10 text-red-700 dark:text-red-300'
	};

	const DELTA_TONE: Record<string, string> = {
		info: 'text-blue-600 dark:text-blue-400',
		good: 'text-green-600 dark:text-green-400',
		warning: 'text-amber-600 dark:text-amber-400',
		danger: 'text-red-600 dark:text-red-400'
	};

	const str = (v: any): string => (v === null || v === undefined ? '' : String(v));
	const headersOf = (block: CanvasBlock): any[] =>
		Array.isArray(block?.headers) ? block.headers : [];
	const rowsOf = (block: CanvasBlock): any[][] =>
		Array.isArray(block?.rows) ? block.rows.filter((r: any) => Array.isArray(r)) : [];

	const parse = (s: any) => {
		parseError = null;
		title = '';
		blocks = [];
		try {
			const obj = typeof s === 'string' ? JSON.parse(s) : s;
			if (!obj || typeof obj !== 'object' || Array.isArray(obj)) {
				parseError = 'Canvas spec must be a JSON object with a "blocks" array.';
				return;
			}
			title = typeof obj.title === 'string' ? obj.title : '';
			blocks = Array.isArray(obj.blocks)
				? obj.blocks.filter((b: any) => b && typeof b === 'object' && !Array.isArray(b))
				: [];
			if (blocks.length === 0 && !title) {
				parseError = 'Canvas spec has no renderable blocks.';
			}
		} catch (e) {
			parseError = `Invalid canvas JSON: ${e instanceof Error ? e.message : e}`;
		}
	};

	$: parse(spec);

	// Consecutive stat cards share one responsive row; everything else is full-width.
	$: groups = blocks.reduce(
		(acc: Array<{ stat: boolean; items: CanvasBlock[] }>, b: CanvasBlock) => {
			const isStat = b?.kind === 'stat';
			const last = acc[acc.length - 1];
			if (isStat && last?.stat) {
				last.items.push(b);
			} else {
				acc.push({ stat: isStat, items: [b] });
			}
			return acc;
		},
		[]
	);

	// Charts reuse the EXISTING Vega path (renderVegaVisualization) — the simple
	// {chartType, categories, series} shape is translated to Vega-Lite in utils.
	const renderChart = async (block: CanvasBlock): Promise<string> => {
		const vlSpec = canvasChartToVegaLite(block, {
			dark:
				typeof document !== 'undefined' && document.documentElement.classList.contains('dark')
		});
		if (!vlSpec) {
			throw new Error(
				'chart block needs chartType (bar|line|pie), categories[] and series[{name,data}]'
			);
		}
		return await renderVegaVisualization(JSON.stringify(vlSpec));
	};
</script>

<div
	class="harvis-canvas w-full flex flex-col gap-2.5 text-gray-800 dark:text-gray-100 {mode ===
	'panel'
		? 'p-4 max-w-3xl mx-auto'
		: 'p-3.5'}"
>
	{#if title || (mode === 'inline' && onOpen)}
		<div class="flex items-start justify-between gap-2">
			<div class="font-medium text-sm pt-1.5 min-w-0 break-words">{str(title)}</div>
			{#if mode === 'inline' && onOpen}
				<button
					class="shrink-0 flex items-center justify-center min-w-[2.75rem] min-h-[2.75rem] rounded-xl text-sm text-gray-500 dark:text-gray-400 hover:bg-black/5 dark:hover:bg-white/5 hover:text-black dark:hover:text-white transition"
					title={$i18n.t('Open in panel')}
					aria-label={$i18n.t('Open in panel')}
					on:click={onOpen}
				>
					⤢
				</button>
			{/if}
		</div>
	{/if}

	{#if parseError}
		<div
			class="flex gap-2.5 border px-4 py-3 border-red-600/10 bg-red-600/10 rounded-2xl text-sm"
		>
			{parseError}
		</div>
	{:else}
		{#each groups as group}
			{#if group.stat}
				<div
					class="grid gap-2.5"
					style="grid-template-columns: repeat(auto-fit, minmax(9.5rem, 1fr));"
				>
					{#each group.items as block}
						<div
							class="rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50/50 dark:bg-gray-850/50 px-3.5 py-3"
						>
							<div class="text-xs text-gray-500 dark:text-gray-400 truncate">
								{str(block.label)}
							</div>
							<div class="flex items-baseline gap-1.5 mt-0.5 flex-wrap">
								<div class="text-xl font-semibold tabular-nums">{str(block.value)}</div>
								{#if block.delta}
									<div
										class="text-xs tabular-nums {DELTA_TONE[str(block.tone)] ??
											'text-gray-500 dark:text-gray-400'}"
									>
										{str(block.delta)}
									</div>
								{/if}
							</div>
						</div>
					{/each}
				</div>
			{:else}
				{#each group.items as block}
					{#if block.kind === 'table'}
						<div class="rounded-2xl border border-gray-100 dark:border-gray-850 overflow-hidden">
							<div class="overflow-x-auto max-h-96 overflow-y-auto">
								<table class="w-full text-sm">
									<thead
										class="sticky top-0 z-[1] bg-gray-50 dark:bg-gray-850 text-xs text-gray-500 dark:text-gray-400"
									>
										<tr>
											{#each headersOf(block) as header}
												<th class="text-left font-medium px-3.5 py-2 whitespace-nowrap">
													{str(header)}
												</th>
											{/each}
										</tr>
									</thead>
									<tbody>
										{#each rowsOf(block) as row}
											<tr class="border-t border-gray-100 dark:border-gray-850">
												{#each row as cell}
													<td class="px-3.5 py-1.5 tabular-nums whitespace-nowrap">
														{str(cell)}
													</td>
												{/each}
											</tr>
										{/each}
									</tbody>
								</table>
							</div>
						</div>
					{:else if block.kind === 'chart'}
						<div class="rounded-2xl border border-gray-100 dark:border-gray-850 p-3 overflow-x-auto">
							{#await renderChart(block)}
								<div class="text-xs text-gray-500 dark:text-gray-400">
									{$i18n.t('Rendering chart...')}
								</div>
							{:then svg}
								<div class="canvas-chart max-w-full">{@html svg}</div>
							{:catch error}
								<div class="text-xs text-red-600 dark:text-red-400">
									Chart could not be rendered: {error?.message ?? error}
								</div>
							{/await}
						</div>
					{:else if block.kind === 'callout'}
						<div
							class="border rounded-2xl px-4 py-3 text-sm {TONE_CLASSES[str(block.tone)] ??
								TONE_CLASSES.info}"
						>
							{str(block.text)}
						</div>
					{:else if block.kind === 'diff'}
						<div class="rounded-2xl border border-gray-100 dark:border-gray-850 overflow-hidden">
							<div class="grid md:grid-cols-2">
								<div class="min-w-0 bg-red-500/5">
									<div class="text-xs text-red-600 dark:text-red-400 px-3.5 pt-2">
										Before{block.language ? ` · ${str(block.language)}` : ''}
									</div>
									<pre
										class="text-xs font-mono whitespace-pre overflow-x-auto px-3.5 py-2">{str(
											block.before
										)}</pre>
								</div>
								<div
									class="min-w-0 bg-green-500/5 border-t md:border-t-0 md:border-l border-gray-100 dark:border-gray-850"
								>
									<div class="text-xs text-green-600 dark:text-green-400 px-3.5 pt-2">After</div>
									<pre
										class="text-xs font-mono whitespace-pre overflow-x-auto px-3.5 py-2">{str(
											block.after
										)}</pre>
								</div>
							</div>
						</div>
					{:else if block.kind === 'heading'}
						<div class="font-semibold text-base mt-1 break-words">{str(block.text)}</div>
					{:else if block.kind === 'text'}
						<div class="text-sm whitespace-pre-wrap break-words">{str(block.text)}</div>
					{:else}
						<!-- Unknown kind — honest note, never a crash -->
						<div
							class="text-xs text-gray-500 dark:text-gray-400 border border-dashed border-gray-200 dark:border-gray-800 rounded-2xl px-3.5 py-2"
						>
							Unsupported canvas block: "{str(block.kind) || 'unknown'}"
						</div>
					{/if}
				{/each}
			{/if}
		{/each}
	{/if}
</div>

<style>
	.canvas-chart :global(svg) {
		max-width: 100%;
		height: auto;
	}
</style>
