<script lang="ts">
	// The parameter graph of one revision, read-only (DE-2/DE-5).
	//
	// Every field here is the engine's: the value, the unit, whether it is an input or
	// derived from a formula, the bounds and where it sits against them, the file and
	// line that declare it, and the operations that read it. Nothing is recomputed on
	// this side — a formula evaluated twice is a formula that can disagree with itself,
	// and the whole point of the panel is that it and the code are the same source.
	//
	// It selects, it does not edit. A slider that writes straight into geometry would be
	// changing an accepted part without a revision to show for it; parameter changes go
	// through the conversation, which produces a revision the engine actually built.
	import { getContext } from 'svelte';

	import type { CadParameter, CadSourceGraph } from '$lib/apis/cad';

	const i18n: any = getContext('i18n');

	export let graph: CadSourceGraph | null = null;
	/** The design's own name, drawn as the root of the tree so the parameters read as
	 *  belonging to something rather than floating. */
	export let title = '';
	export let selected = '';
	export let onSelect: (name: string) => void = () => {};

	/** The accepted revision's input values, when the revision on screen is a proposal.
	 *  Null when it *is* the accepted one, or when the accepted revision's values cannot
	 *  be read — in which case no comparison is drawn rather than a guessed one. Only
	 *  inputs are compared: a derived value would have to be re-evaluated over there, and
	 *  this component evaluates nothing. */
	export let acceptedValues: Record<string, number> | null = null;

	/** Said instead of the tree when there is no graph. The backend's own sentence when
	 *  it has one, because it knows why. */
	export let note = '';
	export let loading = false;

	const num = (v: number | null) =>
		v === null || v === undefined || !Number.isFinite(v)
			? '—'
			: Number.isInteger(v)
				? `${v}`
				: `${Math.round(v * 1000) / 1000}`;

	const statusText = (p: CadParameter) =>
		p.status === 'at_min'
			? $i18n.t('at minimum')
			: p.status === 'at_max'
				? $i18n.t('at maximum')
				: p.status === 'out_of_range'
					? $i18n.t('outside its range')
					: '';

	const statusClass = (p: CadParameter) =>
		p.status === 'out_of_range'
			? 'text-red-600 dark:text-red-400 bg-red-500/10'
			: 'text-amber-600 dark:text-amber-400 bg-amber-500/10';

	const boundsText = (p: CadParameter) =>
		p.min === null && p.max === null
			? ''
			: `${num(p.min)}–${num(p.max)}${p.unit ? ` ${p.unit}` : ''}`;

	/** What changed against the accepted revision, or ''. Compared as numbers and printed
	 *  from the accepted side, so "was" always names a value a build actually used. */
	const wasText = (p: CadParameter) => {
		if (!acceptedValues || p.kind !== 'input') return '';
		const before = acceptedValues[p.name];
		if (typeof before !== 'number' || !Number.isFinite(before)) return '';
		if (p.value !== null && Math.abs(before - p.value) < 1e-9) return '';
		return `${num(before)}${p.unit ? ` ${p.unit}` : ''}`;
	};

	const usedBy = (p: CadParameter) => {
		// Distinct labels, in the order the operations run. A parameter read three times
		// by one feature is that feature once — the slot detail is in the title.
		const seen: string[] = [];
		for (const u of p.used_by) if (u.label && !seen.includes(u.label)) seen.push(u.label);
		return seen;
	};

	const slotsOf = (p: CadParameter) =>
		p.used_by.map((u) => `${u.label} · ${u.location}`).join('\n');

	$: params = graph?.parameters ?? [];
</script>

{#if loading}
	<p class="px-1.5 text-[11px] text-gray-400">{$i18n.t('Loading…')}</p>
{:else if !graph}
	<p class="px-1.5 text-[11px] text-gray-400 leading-snug">
		{note || $i18n.t('No parameter graph for this revision.')}
	</p>
{:else if params.length === 0}
	<p class="px-1.5 text-[11px] text-gray-400 leading-snug">
		{$i18n.t('This design declares no parameters — every dimension in it is a literal.')}
	</p>
{:else}
	<div class="flex flex-col">
		<p class="px-1.5 pb-0.5 text-[11px] text-gray-700 dark:text-gray-200 truncate">
			{title || $i18n.t('Design')}
		</p>
		<ul class="flex flex-col">
			{#each params as p, i (p.name)}
				{@const last = i === params.length - 1}
				{@const was = wasText(p)}
				<li>
					<button
						class="w-full text-left px-1.5 py-1 rounded-md transition {selected === p.name
							? 'bg-emerald-500/10'
							: 'hover:bg-gray-50 dark:hover:bg-gray-850'}"
						aria-current={selected === p.name}
						on:click={() => onSelect(selected === p.name ? '' : p.name)}
					>
						<span class="flex items-baseline gap-1.5">
							<span class="shrink-0 font-mono text-[11px] text-gray-300 dark:text-gray-700 select-none"
								>{last ? '└─' : '├─'}</span
							>
							<span
								class="min-w-0 truncate font-mono text-[11px] text-gray-700 dark:text-gray-200"
								title={p.name}>{p.name}</span
							>
							<span class="ml-auto shrink-0 text-[11px] text-gray-900 dark:text-gray-100 tabular-nums">
								{num(p.value)}{p.unit ? ` ${p.unit}` : ''}
							</span>
						</span>

						<span
							class="mt-0.5 flex flex-wrap items-center gap-1 pl-5 text-[9px] text-gray-400 leading-4"
						>
							{#if p.kind === 'derived'}
								<!-- Said plainly, because a derived value cannot be edited the way an
								     input can: changing it means changing the formula. -->
								<span class="px-1 rounded bg-gray-100 dark:bg-gray-850 text-gray-500 dark:text-gray-400"
									>{$i18n.t('derived')}</span
								>
							{/if}
							{#if !p.resolved}
								<!-- The engine could not evaluate this one. Shown rather than hidden: a
								     blank value with no explanation reads as a panel that failed. -->
								<span class="px-1 rounded bg-amber-500/10 text-amber-600 dark:text-amber-400"
									>{$i18n.t('not evaluated')}</span
								>
							{/if}
							{#if statusText(p)}
								<span class="px-1 rounded {statusClass(p)}">{statusText(p)}</span>
							{/if}
							{#if boundsText(p)}
								<span class="tabular-nums">{boundsText(p)}</span>
							{/if}
							{#if was}
								<!-- Against the accepted revision, not against this parameter's declared
								     default: what a reader wants to know about a proposal is what it moves
								     away from the part that was actually accepted. -->
								<span class="text-amber-600 dark:text-amber-400 tabular-nums"
									>{$i18n.t('was {{value}}', { value: was })}</span
								>
							{/if}
							{#if p.defined_in.path}
								<span class="font-mono truncate"
									>{p.defined_in.path}{p.defined_in.line ? `:${p.defined_in.line}` : ''}</span
								>
							{/if}
						</span>

						<span class="mt-0.5 block pl-5 text-[9px] leading-4 text-gray-400" title={slotsOf(p)}>
							{#if usedBy(p).length}
								{$i18n.t('Used by')}: {usedBy(p).join(', ')}
							{:else}
								<!-- A parameter nothing reads is worth seeing: it is either dead or a
								     rename that half-landed, and both are the kind of thing a silent
								     panel hides. -->
								<span class="italic">{$i18n.t('Used by nothing in this design.')}</span>
							{/if}
						</span>
					</button>
				</li>
			{/each}
		</ul>

		{#if !graph.complete}
			<!-- The engine's own flag. A partial graph looks exactly like a complete one, so
			     the difference has to be written down or the panel is quietly wrong. -->
			<p class="mt-1.5 px-1.5 pt-1.5 border-t border-gray-100 dark:border-gray-850 text-[10px] text-amber-600 dark:text-amber-400 leading-snug">
				{$i18n.t('Some operations could not be read, so this list may be missing consumers.')}
			</p>
		{/if}
		<p class="mt-1 px-1.5 text-[10px] text-gray-400 leading-snug">
			{$i18n.t('Read-only. Ask for a change and Harvis proposes a revision you can accept.')}
		</p>
	</div>
{/if}
