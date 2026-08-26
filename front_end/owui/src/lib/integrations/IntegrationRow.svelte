<script lang="ts">
	// Ollama-style catalog row: colored brand tile · name · status · one-line description ·
	// a command-first mono block with copy · actions. Full-width, sits in a divide-y section.
	import { createEventDispatcher } from 'svelte';
	import StatusBadge from './StatusBadge.svelte';
	import BrandGlyph from './BrandGlyph.svelte';
	import CommandBlock from './CommandBlock.svelte';
	import {
		type IntegrationDefinition,
		type IntegrationAction,
		actionsFor,
		applyTemplate,
		toneFor
	} from '$lib/integrations/catalog';
	import { CAPABILITY_LABEL, SURFACE_LABEL, formatSourceLine } from '$lib/integrations/capabilities';

	export let def: IntegrationDefinition;
	const dispatch = createEventDispatcher();

	$: tone = toneFor(def.brandKey);
	$: cmd = applyTemplate(def.commands?.launch ?? def.commands?.install ?? def.commands?.check, def.model?.preferred);
	$: actions = actionsFor(def).filter((a) => a.kind !== 'copy');

	const open = () => dispatch('open', def.id);
	const onAction = (a: IntegrationAction) => dispatch('action', { def, action: a });
</script>

<div class="flex items-start gap-3.5 px-4 py-3.5 hover:bg-gray-50 dark:hover:bg-white/[0.025] transition">
	<button type="button" class="shrink-0" on:click={open} aria-label={def.name}>
		<span class="size-10 flex items-center justify-center rounded-xl border {tone.tile} {tone.icon}">
			<BrandGlyph name={def.brandKey} className="size-6" />
		</span>
	</button>

	<div class="min-w-0 flex-1">
		<div class="flex items-start justify-between gap-3">
			<button type="button" class="min-w-0 text-left" on:click={open}>
				<div class="flex items-center gap-2 flex-wrap">
					<span class="text-sm font-semibold text-gray-800 dark:text-gray-100">{def.name}</span>
					<StatusBadge status={def.status} />
				</div>
				<p class="text-xs text-gray-500 dark:text-gray-400 leading-relaxed mt-0.5 max-w-2xl">{def.description}</p>
				<div class="flex flex-wrap items-center gap-x-2 gap-y-1 mt-1.5">
					{#each def.provides ?? [] as c}
						<span class="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/5 text-blue-600/80 dark:text-blue-300/70">{CAPABILITY_LABEL[c]}</span>
					{/each}
					{#if def.usedBy?.length}
						<span class="text-[10px] text-gray-500 dark:text-gray-400">Used by {def.usedBy.map((s) => SURFACE_LABEL[s]).join(', ')}</span>
					{/if}
					<span class="text-[10px] text-gray-500 dark:text-gray-400">{formatSourceLine(def)}</span>
				</div>
				{#if def.runtimeNote}
					<span class="block text-[10px] text-amber-500/80 mt-1">{def.runtimeNote}</span>
				{/if}
			</button>

			<div class="shrink-0 flex items-center gap-2">
				{#each actions as a}
					<button
						type="button"
						title={a.title ?? ''}
						class="text-xs px-2.5 py-1 rounded-lg border transition whitespace-nowrap {a.primary
							? 'border-blue-500/30 text-blue-600 dark:text-blue-300 bg-blue-500/10 hover:bg-blue-500/15'
							: 'border-gray-200 dark:border-white/10 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/5'}"
						on:click={() => onAction(a)}
					>
						{a.label}
					</button>
				{/each}
			</div>
		</div>

		{#if cmd}
			<div class="mt-2 max-w-xl"><CommandBlock command={cmd} /></div>
		{/if}
	</div>
</div>
