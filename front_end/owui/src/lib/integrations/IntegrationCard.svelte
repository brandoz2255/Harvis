<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import StatusBadge from './StatusBadge.svelte';
	import BrandGlyph from './BrandGlyph.svelte';
	import CommandBlock from './CommandBlock.svelte';
	import {
		type IntegrationDefinition,
		type IntegrationAction,
		CATEGORY_LABEL,
		actionsFor,
		applyTemplate,
		toneFor
	} from '$lib/integrations/catalog';
	import { CAPABILITY_LABEL, SURFACE_LABEL, formatSourceLine } from '$lib/integrations/capabilities';

	export let def: IntegrationDefinition;
	const dispatch = createEventDispatcher();

	$: tone = toneFor(def.brandKey);
	$: cmd = applyTemplate(def.commands?.launch ?? def.commands?.install, def.model?.preferred);
	// the inline command block already provides copy → drop the redundant copy action on cards
	$: actions = actionsFor(def).filter((a) => a.kind !== 'copy');

	const onAction = (a: IntegrationAction) => dispatch('action', { def, action: a });
</script>

<div
	class="group flex flex-col rounded-xl border border-gray-100 dark:border-white/8 bg-gray-50 dark:bg-[#121a2e] hover:bg-gray-100 dark:hover:bg-white/[0.04] transition overflow-hidden"
>
	<button type="button" class="flex flex-col text-left p-4 gap-2.5" on:click={() => dispatch('open', def.id)}>
		<div class="flex items-start justify-between gap-2">
			<div class="flex items-center gap-2.5 min-w-0">
				<span class="shrink-0 size-9 flex items-center justify-center rounded-lg border {tone.tile} {tone.icon}">
					<BrandGlyph name={def.brandKey} className="size-5" />
				</span>
				<div class="min-w-0">
					<div class="text-sm font-semibold text-gray-800 dark:text-gray-100 truncate">{def.name}</div>
					<div class="text-[10px] uppercase tracking-wide text-gray-500 dark:text-gray-400">{CATEGORY_LABEL[def.category]}</div>
				</div>
			</div>
			<StatusBadge status={def.status} />
		</div>
		<p class="text-xs text-gray-500 dark:text-gray-400 leading-relaxed line-clamp-2">{def.description}</p>
		{#if def.provides?.length}
			<div class="flex flex-wrap items-center gap-1">
				{#each def.provides as c}
					<span class="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/5 text-blue-600/80 dark:text-blue-300/70">{CAPABILITY_LABEL[c]}</span>
				{/each}
			</div>
		{/if}
		{#if def.usedBy?.length}
			<span class="text-[10px] text-gray-500 dark:text-gray-400">Used by {def.usedBy.map((s) => SURFACE_LABEL[s]).join(', ')}</span>
		{/if}
		<span class="text-[10px] text-gray-500 dark:text-gray-400">{formatSourceLine(def)}</span>
		{#if def.runtimeNote}<span class="text-[10px] text-amber-500/80 line-clamp-1">{def.runtimeNote}</span>{/if}
	</button>

	{#if cmd}
		<div class="px-4 -mt-0.5"><CommandBlock command={cmd} /></div>
	{/if}

	{#if actions.length}
		<div class="px-4 py-3 flex flex-wrap items-center gap-2">
			{#each actions as a}
				<button
					type="button"
					title={a.title ?? ''}
					class="text-xs px-2.5 py-1 rounded-lg border transition {a.primary
						? 'border-blue-500/30 text-blue-600 dark:text-blue-300 bg-blue-500/10 hover:bg-blue-500/15'
						: 'border-gray-200 dark:border-white/10 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/5'}"
					on:click={() => onAction(a)}
				>
					{a.label}
				</button>
			{/each}
		</div>
	{/if}
</div>
