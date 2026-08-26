<script lang="ts">
	// "Get free API keys" — the onboarding a new user actually needs.
	//
	// Harvis ships no models and no keys. A fresh install with no GPU and no Ollama can still
	// have a working chat in about two minutes, because several vendors publish a real free tier
	// on an OpenAI-compatible API. The blocker is never the wiring — it's that a new user doesn't
	// know these tiers exist, or which one to start with, or where the key comes from.
	//
	// So this is a guide, not a wizard: it names the vendors, states each free allowance plainly,
	// links the console, and hands off to the normal connect flow. It never opens a browser tab
	// on its own and never asks for a key here — the credential is typed into the card's own
	// ConnectionPanel, which is the one place that encrypts and verifies it.
	//
	// The list is DERIVED from the catalog (`freeTier` present + `keyConsoleUrl`), so adding a
	// sixth provider is still one catalog row. Nothing to keep in sync here.
	//
	// Where the allowances come from: each was read off the vendor's own pricing page when this
	// build shipped. The community-maintained index below is the place to check whether they've
	// moved since — it is LINKED, never vendored: cheahjs/free-llm-api-resources publishes no
	// licence at all, so copying its table into this repo would not be ours to copy.
	import { createEventDispatcher, getContext } from 'svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import BrandGlyph from './BrandGlyph.svelte';
	import { CATALOG, toneFor, type IntegrationDefinition } from '$lib/integrations/catalog';
	import { normalizeStatus, NORM_META, type EngineReadiness } from '$lib/integrations/status';

	const i18n: any = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let show = false;
	/** Live-merged defs from the page, so the "Connected" ticks are real and not the static baseline. */
	export let merged: IntegrationDefinition[] = [];
	export let engineReadiness: EngineReadiness = {};

	// Prefer the page's live copy of each card; fall back to the static catalog entry so the
	// guide still renders (with everything unconnected) if the status fetch failed.
	$: providers = CATALOG.filter((d) => d.freeTier && d.keyConsoleUrl).map(
		(d) => merged.find((m) => m.id === d.id) ?? d
	);
	$: connectedCount = providers.filter(
		(d) => normalizeStatus(d, engineReadiness) === 'connected'
	).length;

	const connect = (id: string) => {
		show = false;
		dispatch('connect', id); // the page opens that card's detail modal
	};

	const SOURCE_REPO = 'https://github.com/cheahjs/free-llm-api-resources';
</script>

<Modal bind:show size="lg">
	<div class="p-5 sm:p-6 space-y-5">
		<div class="flex items-start justify-between gap-4">
			<div>
				<h2 class="text-lg font-semibold text-gray-800 dark:text-gray-100">
					{$i18n.t('Get free API keys')}
				</h2>
				<p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
					{$i18n.t(
						'Harvis ships no models of its own. These providers publish a genuinely free tier — connect any one of them and you have a working chat, no GPU and no credit card.'
					)}
				</p>
			</div>
			<button
				type="button"
				class="shrink-0 rounded-lg p-1.5 text-gray-500 dark:text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
				on:click={() => (show = false)}
				aria-label={$i18n.t('Close')}
			>
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="size-4" aria-hidden="true">
					<path d="M6 6l12 12M18 6L6 18" />
				</svg>
			</button>
		</div>

		<!-- How it goes, in the order it actually happens. Three steps because there are three. -->
		<ol
			class="grid gap-2 sm:grid-cols-3 text-xs text-gray-600 dark:text-gray-300"
			aria-label={$i18n.t('Steps')}
		>
			{#each [$i18n.t('Pick a provider below and open its console.'), $i18n.t('Sign in there and create an API key.'), $i18n.t('Come back, press Connect, and paste it.')] as step, i}
				<li class="rounded-xl border border-gray-100 dark:border-white/10 bg-gray-50 dark:bg-white/5 px-3 py-2.5">
					<span class="font-semibold text-gray-800 dark:text-gray-100">{i + 1}.</span>
					{step}
				</li>
			{/each}
		</ol>

		<div class="space-y-2.5">
			{#each providers as def (def.id)}
				{@const norm = normalizeStatus(def, engineReadiness)}
				{@const tone = toneFor(def.brandKey)}
				<div
					class="flex flex-col sm:flex-row sm:items-center gap-3 rounded-xl border border-gray-100 dark:border-white/10 px-3.5 py-3"
				>
					<div class="flex items-start gap-3 min-w-0 flex-1">
						<div class="shrink-0 grid place-items-center size-9 rounded-lg border {tone.tile} {tone.icon}">
							<BrandGlyph name={def.brandKey} className="size-5" />
						</div>
						<div class="min-w-0">
							<div class="flex items-center gap-2">
								<span class="text-sm font-medium text-gray-800 dark:text-gray-100">{def.name}</span>
								{#if norm === 'connected'}
									<span class="inline-flex items-center gap-1 text-[11px] {NORM_META.connected.text}">
										<span class="size-1.5 rounded-full {NORM_META.connected.dot}"></span>
										{$i18n.t('Connected')}
									</span>
								{/if}
							</div>
							<p class="mt-0.5 text-xs text-gray-500 dark:text-gray-400">{$i18n.t(def.freeTier ?? '')}</p>

							<!-- The numbers you actually compare, as chips. Scanning three of these across five
							     rows is what picking a provider consists of; reading five paragraphs is not. -->
							{#if def.freeLimits?.length}
								<ul class="mt-1.5 flex flex-wrap gap-1" aria-label={$i18n.t('Free tier limits')}>
									{#each def.freeLimits as limit}
										<li
											class="rounded-md px-1.5 py-0.5 text-[10.5px] leading-tight border border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-white/5 text-gray-600 dark:text-gray-300 tabular-nums"
										>
											{$i18n.t(limit)}
										</li>
									{/each}
								</ul>
							{/if}

							<!-- Stated here rather than discovered on the vendor's signup form. Phone
							     verification is the one that makes people give up halfway. -->
							{#if def.signupRequires}
								<p class="mt-1.5 flex items-start gap-1.5 text-[11px] text-gray-500 dark:text-gray-400">
									<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="size-3 mt-0.5 shrink-0" aria-hidden="true">
										<path d="M12 3l7.5 3.5v5c0 4.2-3.1 7.8-7.5 9-4.4-1.2-7.5-4.8-7.5-9v-5z" />
									</svg>
									<span>{$i18n.t('Signup needs')}: {$i18n.t(def.signupRequires)}</span>
								</p>
							{/if}
						</div>
					</div>

					<div class="flex items-center gap-2 shrink-0 sm:justify-end sm:self-start sm:pt-0.5">
						{#if def.links?.docs}
							<a
								href={def.links.docs}
								target="_blank"
								rel="noopener noreferrer"
								class="rounded-lg px-2 py-1.5 text-xs text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200 hover:bg-gray-50 dark:hover:bg-white/5"
								title={$i18n.t('Vendor documentation')}
							>
								{$i18n.t('Docs')}
							</a>
						{/if}
						<a
							href={def.keyConsoleUrl}
							target="_blank"
							rel="noopener noreferrer"
							class="rounded-lg px-2.5 py-1.5 text-xs border border-gray-200 dark:border-white/10 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-white/5"
						>
							{$i18n.t('Open console')}
						</a>
						<button
							type="button"
							class="rounded-lg px-2.5 py-1.5 text-xs bg-gray-900 dark:bg-white text-white dark:text-gray-900 hover:opacity-90"
							on:click={() => connect(def.id)}
						>
							{norm === 'connected' ? $i18n.t('Manage') : $i18n.t('Connect')}
						</button>
					</div>
				</div>
			{/each}
		</div>

		<div class="space-y-2 border-t border-gray-100 dark:border-white/10 pt-3.5">
			<p class="text-[11px] text-gray-500 dark:text-gray-400">
				{$i18n.t(
					'Free tiers have rate limits and change without notice — the allowances above are what each vendor advertised when this build shipped, not a guarantee. Keys are stored encrypted per-user, never shown again, and sent only to the vendor they belong to.'
				)}
				{#if connectedCount}
					<span class="ml-1 text-gray-500 dark:text-gray-400">
						{$i18n.t('{{count}} connected.', { count: connectedCount })}
					</span>
				{/if}
			</p>

			<!-- Where to check whether any of the above has moved. Named in full rather than hidden
			     behind "learn more" so it's usable from a screenshot or a copy-paste. -->
			<p class="text-[11px] text-gray-500 dark:text-gray-400">
				{$i18n.t('Looking for more, or checking whether a limit has changed?')}
				<a
					href={SOURCE_REPO}
					target="_blank"
					rel="noopener noreferrer"
					class="inline-flex items-center gap-1 font-medium text-gray-600 dark:text-gray-300 underline decoration-gray-300 dark:decoration-white/25 underline-offset-2 hover:text-gray-900 dark:hover:text-white"
				>
					github.com/cheahjs/free-llm-api-resources
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="size-2.5" aria-hidden="true">
						<path d="M7 17L17 7M9 7h8v8" />
					</svg>
				</a>
				{$i18n.t(
					'is a community-maintained index of every free LLM API tier. Harvis links to it rather than copying it, so what you read there is always current.'
				)}
			</p>
		</div>
	</div>
</Modal>
