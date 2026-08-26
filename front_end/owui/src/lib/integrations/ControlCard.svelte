<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';
	import BrandGlyph from './BrandGlyph.svelte';
	import type { IntegrationDefinition } from './catalog';
	import {
		NORM_META,
		normalizeStatus,
		isDefault,
		primaryCapabilityOf,
		defaultLabelFor,
		isPack,
		tileTint,
		type EngineReadiness
	} from './status';

	const i18n: any = getContext('i18n');

	export let def: IntegrationDefinition;
	export let engineReadiness: EngineReadiness = {};
	export let prefs: Record<string, string> = {};
	/** Sibling of a featured card — same row, dialled down so the lead card carries the section. */
	export let compact = false;

	const dispatch = createEventDispatcher();

	$: pack = isPack(def);
	$: norm = pack ? null : normalizeStatus(def, engineReadiness);
	$: meta = norm ? NORM_META[norm] : null;
	$: isDef = isDefault(def, prefs);
	$: canSetDefault = !pack && !!primaryCapabilityOf(def);
	$: tint = tileTint(def);
</script>

<!-- Directory row: tinted brand tile · name · one-line purpose · ONE status · chevron.
     The whole row opens the details drawer (capabilities, runtime, source, security, setup).
     Logs / Set-default stay secondary — revealed on hover or keyboard focus at md and up,
     always visible below md where there is no hover. Never hover-only. -->
<div
	class="group relative flex items-center rounded-xl hover:bg-gray-50 dark:hover:bg-gray-850/70 transition cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-blue-500/40 {compact
		? 'gap-2.5 px-2 py-1.5'
		: 'gap-3 px-2.5 py-2.5'}"
	role="button"
	tabindex="0"
	title={def.description}
	on:click={() => dispatch('open', def.id)}
	on:keydown={(e) => (e.key === 'Enter' || e.key === ' ') && dispatch('open', def.id)}
>
	<div class="shrink-0 rounded-xl grid place-items-center {compact ? 'size-8' : 'size-10'} {tint}">
		<BrandGlyph name={def.brandKey} className={compact ? 'size-4' : 'size-5'} />
	</div>

	<div class="min-w-0 flex-1">
		<div class="flex items-center gap-1.5">
			<span
				class="font-semibold text-gray-900 dark:text-gray-50 truncate {compact
					? 'text-[13px]'
					: 'text-sm'}">{def.name}</span
			>
			{#if isDef}
				<span
					class="shrink-0 text-[10px] font-medium px-1.5 py-px rounded-md bg-blue-50 dark:bg-blue-500/15 text-blue-600 dark:text-blue-300"
					title={$i18n.t('This is the saved default for its capability')}>{$i18n.t('Default')}</span
				>
			{/if}
		</div>
		<p
			class="text-gray-500 dark:text-gray-400 truncate {compact ? 'text-[11px]' : 'text-xs'}"
		>
			{def.description}
		</p>
	</div>

	<!-- trailing cluster: secondary actions · the one status · affordance chevron -->
	<div class="shrink-0 flex items-center gap-1.5">
		<div
			class="flex items-center gap-1 opacity-100 md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100 transition"
			role="group"
			aria-label={$i18n.t('Quick actions')}
			on:click|stopPropagation
			on:keydown|stopPropagation
		>
			{#if !pack}
				<button
					type="button"
					class="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-150 dark:hover:bg-gray-800 transition"
					title={$i18n.t('Recent activity')}
					aria-label={$i18n.t('Recent activity')}
					on:click={() => dispatch('logs', def)}
				>
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="size-4"><path d="M12 8v4l3 1.5" /><circle cx="12" cy="12" r="9" /></svg>
				</button>
			{/if}
			{#if canSetDefault && !isDef}
				<button
					type="button"
					class="p-1.5 rounded-lg text-gray-400 hover:text-blue-600 dark:hover:text-blue-400 hover:bg-gray-150 dark:hover:bg-gray-800 transition"
					title={defaultLabelFor(def)}
					aria-label={defaultLabelFor(def)}
					on:click={() => dispatch('setDefault', def)}
				>
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="size-4"><path d="m5 13 4 4L19 7" /></svg>
				</button>
			{/if}
		</div>

		{#if meta}
			<span class="inline-flex items-center gap-1.5 text-xs font-medium {meta.text}">
				<span class="size-1.5 rounded-full {meta.dot}"></span>
				<span class="hidden sm:inline">{$i18n.t(meta.label)}</span>
			</span>
		{:else}
			<span class="text-xs text-gray-400">{$i18n.t('Recipe')}</span>
		{/if}

		<svg
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			stroke-width="2"
			stroke-linecap="round"
			stroke-linejoin="round"
			class="size-4 text-gray-300 dark:text-gray-600 group-hover:text-gray-500 dark:group-hover:text-gray-400 transition"
			aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg
		>
	</div>
</div>
