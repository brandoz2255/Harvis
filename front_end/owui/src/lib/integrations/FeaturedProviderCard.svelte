<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';
	import BrandGlyph from './BrandGlyph.svelte';
	import type { IntegrationDefinition } from './catalog';
	import { NORM_META, normalizeStatus, tileTint, type EngineReadiness } from './status';

	const i18n: any = getContext('i18n');

	export let def: IntegrationDefinition;
	export let engineReadiness: EngineReadiness = {};

	const dispatch = createEventDispatcher();

	$: norm = normalizeStatus(def, engineReadiness);
	$: meta = NORM_META[norm];
	$: tint = tileTint(def);
	$: connected = norm === 'connected' || norm === 'ready';
</script>

<!-- The lead card for a section: the one provider we actively recommend, opened up so the
     whole path from "no key" to "chatting" is visible without clicking into anything. Its
     siblings render as compact rows underneath. The key itself is NEVER typed here — the
     buttons hand off to the Connection panel, which is the only place that touches it. -->
<section
	class="rounded-2xl border border-blue-500/25 bg-blue-500/[0.04] dark:bg-blue-400/[0.05] p-4 sm:p-5"
	aria-labelledby="featured-{def.id}-name"
>
	<div class="flex items-start gap-3.5">
		<div class="shrink-0 size-12 rounded-xl grid place-items-center {tint}">
			<BrandGlyph name={def.brandKey} className="size-6" />
		</div>

		<div class="min-w-0 flex-1">
			<div class="flex flex-wrap items-center gap-x-2 gap-y-1">
				<h3
					id="featured-{def.id}-name"
					class="text-base font-semibold text-gray-900 dark:text-gray-50"
				>
					{def.name}
				</h3>
				<span
					class="text-[10px] font-medium px-1.5 py-px rounded-md bg-blue-600 text-white uppercase tracking-wide"
					>{$i18n.t('Start here')}</span
				>
				<span class="inline-flex items-center gap-1.5 text-[11px] text-gray-500 dark:text-gray-400">
					<span class="size-1.5 rounded-full {meta.dot}"></span>{meta.label}
				</span>
			</div>
			<p class="mt-1 text-sm text-gray-600 dark:text-gray-300">
				{$i18n.t(def.longDescription ?? def.description)}
			</p>

			{#if def.freeLimits?.length}
				<div class="mt-2 flex flex-wrap gap-1.5">
					{#each def.freeLimits as lim}
						<span
							class="text-[11px] px-2 py-0.5 rounded-md border border-gray-200 dark:border-white/10 text-gray-600 dark:text-gray-300"
							>{$i18n.t(lim)}</span
						>
					{/each}
				</div>
			{/if}
		</div>
	</div>

	{#if def.setupSteps?.length}
		<div
			class="mt-4 rounded-xl border border-gray-200 dark:border-white/10 bg-white/70 dark:bg-white/[0.03] p-3.5"
		>
			<div class="flex items-center gap-2">
				<svg
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="1.8"
					stroke-linecap="round"
					stroke-linejoin="round"
					class="size-4 text-blue-600 dark:text-blue-300 shrink-0"
					aria-hidden="true"
					><circle cx="12" cy="12" r="9" /><path d="M12 16v-4M12 8h.01" /></svg
				>
				<h4 class="text-xs font-semibold text-gray-800 dark:text-gray-100">
					{$i18n.t('How to add your API key')}
				</h4>
			</div>
			<ol
				class="mt-2 ml-4 list-decimal space-y-1.5 text-[12px] leading-relaxed text-gray-600 dark:text-gray-300 marker:text-gray-400"
			>
				{#each def.setupSteps as step}
					<li>{$i18n.t(step)}</li>
				{/each}
			</ol>
			{#if def.keyHelp}
				<p class="mt-2.5 pt-2.5 border-t border-gray-100 dark:border-white/8 text-[11px] text-gray-500 dark:text-gray-400">
					{$i18n.t(def.keyHelp)}
				</p>
			{/if}
		</div>
	{/if}

	<div class="mt-4 flex flex-wrap items-center gap-2">
		<button
			type="button"
			class="text-xs font-medium px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white transition"
			on:click={() => dispatch('open', def.id)}
		>
			{connected ? $i18n.t('Manage API key') : $i18n.t('Add API key')}
		</button>
		{#if def.keyConsoleUrl}
			<a
				href={def.keyConsoleUrl}
				target="_blank"
				rel="noopener noreferrer"
				class="text-xs font-medium px-3 py-1.5 rounded-lg border border-gray-200 dark:border-white/10 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/5 transition"
			>
				{def.freeTier ? $i18n.t('Get a free key') : $i18n.t('Get a key')} ↗
			</a>
		{/if}
		{#if def.signupRequires}
			<span class="text-[11px] text-gray-400 dark:text-gray-500"
				>{$i18n.t('Sign-up needs')}: {$i18n.t(def.signupRequires)}</span
			>
		{/if}
	</div>
</section>
