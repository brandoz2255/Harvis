<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import BrandGlyph from './BrandGlyph.svelte';
	import type { IntegrationDefinition } from './catalog';
	import {
		NORM_META,
		normalizeStatus,
		isDefault,
		primaryCapabilityOf,
		defaultLabelFor,
		isPack,
		type EngineReadiness
	} from './status';

	export let def: IntegrationDefinition;
	export let engineReadiness: EngineReadiness = {};
	export let prefs: Record<string, string> = {};

	const dispatch = createEventDispatcher();

	$: pack = isPack(def);
	$: norm = pack ? null : normalizeStatus(def, engineReadiness);
	$: meta = norm ? NORM_META[norm] : null;
	$: isDef = isDefault(def, prefs);
	$: canSetDefault = !pack && !!primaryCapabilityOf(def);
</script>

<!-- Compact control-panel card: face = icon · name · one-line purpose · ONE status · Manage · default.
     Everything else (capabilities, runtime, source, security, setup) lives in the details drawer. -->
<div
	class="group flex flex-col rounded-xl border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-900 hover:border-gray-200 dark:hover:border-gray-800 transition cursor-pointer"
	role="button"
	tabindex="0"
	on:click={() => dispatch('open', def.id)}
	on:keydown={(e) => (e.key === 'Enter' || e.key === ' ') && dispatch('open', def.id)}
>
	<div class="flex items-start gap-3 p-3">
		<BrandGlyph name={def.brandKey} className="size-5 shrink-0 mt-0.5" />
		<div class="min-w-0 flex-1">
			<div class="flex items-center gap-1.5">
				<span class="text-sm font-medium text-gray-900 dark:text-gray-50 truncate">{def.name}</span>
				{#if isDef}
					<span
						class="shrink-0 text-[10px] font-medium px-1.5 py-px rounded-full bg-blue-50 dark:bg-blue-500/15 text-blue-600 dark:text-blue-300"
						title="This is the saved default for its capability">Default</span
					>
				{/if}
			</div>
			<p class="text-xs text-gray-500 dark:text-gray-400 truncate">{def.description}</p>
		</div>
		<!-- ONE normalized status, top-right -->
		<div class="shrink-0">
			{#if meta}
				<span class="inline-flex items-center gap-1.5 text-xs font-medium {meta.text}">
					<span class="size-1.5 rounded-full {meta.dot}"></span>{meta.label}
				</span>
			{:else}
				<span class="text-xs text-gray-400">Recipe</span>
			{/if}
		</div>
	</div>

	<!-- actions row (stop propagation so a button click doesn't also open the drawer) -->
	<div class="flex items-center gap-1.5 px-3 pb-2.5" on:click|stopPropagation on:keydown|stopPropagation>
		<button
			type="button"
			class="text-xs px-2 py-1 rounded-lg bg-gray-100 dark:bg-gray-850 hover:bg-gray-200 dark:hover:bg-gray-800 text-gray-700 dark:text-gray-200 transition"
			on:click={() => dispatch('open', def.id)}>{pack ? 'View details' : 'Manage'}</button
		>
		{#if !pack}
			<button
				type="button"
				class="text-xs px-2 py-1 rounded-lg border border-gray-150 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-850 text-gray-600 dark:text-gray-300 transition"
				title="Recent activity"
				on:click={() => dispatch('logs', def)}>Logs</button
			>
		{/if}
		{#if canSetDefault}
			{#if isDef}
				<span class="text-[11px] text-gray-400 dark:text-gray-500 px-1">In use by default</span>
			{:else}
				<button
					type="button"
					class="text-xs px-2 py-1 rounded-lg border border-gray-150 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-850 text-gray-600 dark:text-gray-300 transition"
					on:click={() => dispatch('setDefault', def)}>{defaultLabelFor(def)}</button
				>
			{/if}
		{/if}
	</div>
</div>
