<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import StatusBadge from './StatusBadge.svelte';
	import CommandBlock from './CommandBlock.svelte';
	import BrandGlyph from './BrandGlyph.svelte';
	import {
		type IntegrationDefinition,
		type IntegrationAction,
		CATEGORY_LABEL,
		ENGINE_LABEL,
		AUTH_LABEL,
		actionsFor,
		applyTemplate,
		toneFor
	} from '$lib/integrations/catalog';
	import { CAPABILITY_LABEL, SURFACE_LABEL, formatSourceLine } from '$lib/integrations/capabilities';
	import ConnectionPanel from './ConnectionPanel.svelte';

	const i18n: any = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let show = false;
	export let def: IntegrationDefinition | null = null;

	// ── Connect-mode variants (Kimi: membership key vs Moonshot platform key) ──
	// One tile, several ways in. `variantKey` resets whenever the modal switches to a different
	// integration so the toggle can never carry a stale selection from the previous card. The
	// guard is on def.id, not on `def` itself: the page re-merges live status every 7s, handing
	// us a NEW object for the same integration, and keying on identity would reset the user's
	// pick mid-typing.
	let lastDefId = '';
	let variantKey = '';
	$: if (def && def.id !== lastDefId) {
		lastDefId = def.id;
		variantKey = def.variants?.[0]?.key ?? '';
	}
	$: variant = def?.variants?.find((v) => v.key === variantKey) ?? null;
	// The def handed to ConnectionPanel (and to the sections a variant can override). Only fields
	// the variant actually declares are replaced — everything else stays the tile's.
	$: viewDef = (
		def && variant
			? {
					...def,
					connect: variant.connect,
					providerKey: variant.providerKey,
					runtimeNote: variant.runtimeNote ?? def.runtimeNote,
					// ?? not ||: a variant's empty array means "this mode grants nothing", and || would
					// fall through to the tile's list and claim shell access the mode doesn't have.
					permissions: variant.permissions ?? def.permissions,
					auth: variant.auth ?? def.auth,
					engine: variant.engine ?? def.engine,
					links: variant.links ?? def.links
				}
			: def
	) as IntegrationDefinition | null;

	$: tone = def ? toneFor(def.brandKey) : { icon: '', tile: '' };
	$: actions = def ? actionsFor(def) : [];
	$: engineTone =
		viewDef?.engine?.support === 'candidate'
			? 'text-emerald-500 dark:text-emerald-400'
			: viewDef?.engine?.support === 'supported'
				? 'text-green-500 dark:text-green-400'
				: 'text-amber-500 dark:text-amber-400'; // planned
	const onAction = (a: IntegrationAction) => def && dispatch('action', { def, action: a });
</script>

<Modal bind:show size="lg">
	{#if def}
		<div class="p-5 sm:p-6 space-y-5 text-gray-700 dark:text-gray-200">
			<!-- header -->
			<div class="flex items-start justify-between gap-3">
				<div class="flex items-center gap-3 min-w-0">
					<span class="shrink-0 size-11 flex items-center justify-center rounded-xl border {tone.tile} {tone.icon}">
						<BrandGlyph name={def.brandKey} className="size-6" />
					</span>
					<div class="min-w-0">
						<div class="flex items-center gap-2">
							<h2 class="text-lg font-semibold text-gray-900 dark:text-white truncate">{def.name}</h2>
							<StatusBadge status={def.status} />
						</div>
						<div class="text-xs text-gray-400 mt-0.5">
							{CATEGORY_LABEL[def.category]}{#if def.provider} · {def.provider}{/if} · {formatSourceLine(def)}
						</div>
						{#if def.usedBy?.length}
							<div class="text-[11px] text-gray-400 mt-0.5">Used by {def.usedBy.map((s) => SURFACE_LABEL[s]).join(', ')}</div>
						{/if}
					</div>
				</div>
				<button
					type="button"
					class="shrink-0 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition text-xl leading-none"
					on:click={() => (show = false)}
					aria-label={$i18n.t('Close')}>×</button
				>
			</div>

			<!-- overview -->
			<p class="text-sm leading-relaxed text-gray-600 dark:text-gray-300">
				{def.longDescription ?? def.description}
			</p>

			<!-- connect-mode toggle — one tile, several credentials (see IntegrationVariant).
			     Rendered ABOVE engine support / runtime note / connection, all of which the chosen
			     mode rewrites, so the user picks first and then reads what that mode actually does. -->
			{#if def.variants && def.variants.length > 1}
				<div class="space-y-2">
					<div class="text-xs font-semibold text-gray-700 dark:text-gray-200">{$i18n.t('Choose how to connect')}</div>
					<div class="flex flex-wrap gap-2" role="radiogroup" aria-label={$i18n.t('Choose how to connect')}>
						{#each def.variants as v}
							<button
								type="button"
								role="radio"
								aria-checked={variantKey === v.key}
								class="flex-1 min-w-[13rem] text-left px-3 py-2 rounded-xl border transition {variantKey === v.key
									? 'border-blue-500/40 bg-blue-500/[0.07] ring-1 ring-blue-500/20'
									: 'border-gray-200 dark:border-white/10 hover:bg-gray-50 dark:hover:bg-white/[0.03]'}"
								on:click={() => (variantKey = v.key)}
							>
								<span class="flex items-center gap-1.5">
									<span
										class="shrink-0 size-3.5 rounded-full border grid place-items-center {variantKey === v.key
											? 'border-blue-500'
											: 'border-gray-300 dark:border-white/20'}"
									>
										{#if variantKey === v.key}<span class="size-1.5 rounded-full bg-blue-500"></span>{/if}
									</span>
									<span class="text-xs font-semibold text-gray-900 dark:text-gray-50">{v.label}</span>
								</span>
								<span class="block mt-1 text-[11px] leading-snug text-gray-500 dark:text-gray-400">{v.tagline}</span>
							</button>
						{/each}
					</div>
				</div>
			{/if}

			<!-- engine support (honest planned/candidate signal) -->
			{#if viewDef?.engine}
				<div class="rounded-lg border border-gray-100 dark:border-white/8 bg-gray-50 dark:bg-white/[0.02] px-3 py-2.5">
					<div class="flex items-center gap-2 text-xs">
						<span class="font-semibold text-gray-700 dark:text-gray-200">{$i18n.t('Engine support')}:</span>
						<span class="font-medium {engineTone}">{$i18n.t(ENGINE_LABEL[viewDef.engine.support])}</span>
					</div>
					{#if viewDef.engine.notes}
						<p class="text-[11px] text-gray-500 dark:text-gray-400 mt-1">{viewDef.engine.notes}</p>
					{/if}
				</div>
			{/if}

			<!-- honest runtime note -->
			{#if viewDef?.runtimeNote}
				<div class="rounded-lg border border-amber-500/20 bg-amber-500/[0.04] px-3 py-2.5 text-xs">
					<span class="font-semibold text-amber-600 dark:text-amber-300">Note:</span>
					<span class="text-gray-600 dark:text-gray-300">{viewDef.runtimeNote}</span>
				</div>
			{/if}

			<!-- connection (Phase B) — the source of truth for per-user connection state.
			     Keyed on variantKey: the panel loads its credential state in onMount, so switching
			     modes has to remount it or it would keep showing the previous mode's status. -->
			{#if viewDef?.connect}
				{#key variantKey}
					<ConnectionPanel def={viewDef} engineAuthKey={variant?.engineAuthKey ?? ''} on:changed />
				{/key}
			{/if}

			<!-- setup / commands -->
			{#if def.commands?.install || def.commands?.launch || def.commands?.check}
				<div class="space-y-2.5">
					<div class="text-xs font-semibold text-gray-700 dark:text-gray-200">{$i18n.t('Setup')}</div>
					{#if def.commands.install}
						<CommandBlock label={$i18n.t('Install')} command={def.commands.install} />
					{/if}
					{#if def.commands.launch}
						<CommandBlock label={$i18n.t('Launch')} command={applyTemplate(def.commands.launch, def.model?.preferred)} />
					{/if}
					{#if def.commands.check}
						<CommandBlock label={$i18n.t('Check')} command={def.commands.check} />
					{/if}
				</div>
			{/if}

			<!-- authentication (suppressed when a live Connection panel replaces it) -->
			{#if viewDef?.auth && !viewDef?.connect}
				<div class="space-y-1.5">
					<div class="text-xs font-semibold text-gray-700 dark:text-gray-200">{$i18n.t('Authentication')}</div>
					{#if viewDef.auth.required}
						<div class="flex flex-wrap items-center gap-1.5">
							{#each viewDef.auth.modes as m}
								<span class="text-[11px] px-2 py-0.5 rounded-md bg-gray-100 dark:bg-white/5 text-gray-600 dark:text-gray-300 border border-gray-200/60 dark:border-white/8">
									{$i18n.t(AUTH_LABEL[m])}{$i18n.t(' — planned')}
								</span>
							{/each}
						</div>
					{:else}
						<p class="text-xs text-gray-500 dark:text-gray-400">{$i18n.t('No authentication required.')}</p>
					{/if}
					{#if viewDef.auth.notes}
						<p class="text-[11px] text-gray-500 dark:text-gray-400">{viewDef.auth.notes}</p>
					{/if}
				</div>
			{/if}

			<!-- capabilities (typed contract) -->
			{#if def.provides && def.provides.length}
				<div class="space-y-1.5">
					<div class="text-xs font-semibold text-gray-700 dark:text-gray-200">{$i18n.t('Capabilities')}</div>
					<div class="flex flex-wrap gap-1.5">
						{#each def.provides as c}
							<span class="text-[11px] px-2 py-0.5 rounded-md bg-blue-500/10 text-blue-600/90 dark:text-blue-300/90 border border-blue-500/15">{CAPABILITY_LABEL[c]}</span>
						{/each}
					</div>
				</div>
			{/if}

			<!-- feature tags (free-form) -->
			{#if def.capabilities && def.capabilities.length}
				<div class="space-y-1.5">
					<div class="text-xs font-semibold text-gray-700 dark:text-gray-200">{$i18n.t('Feature tags')}</div>
					<div class="flex flex-wrap gap-1.5">
						{#each def.capabilities as c}
							<span class="text-[11px] px-2 py-0.5 rounded-md bg-gray-100 dark:bg-white/5 text-gray-500 dark:text-gray-400 border border-gray-200/60 dark:border-white/8">{c}</span>
						{/each}
					</div>
				</div>
			{/if}

			<!-- verified links -->
			{#if viewDef?.links?.docs || viewDef?.links?.homepage}
				<div class="space-y-1.5">
					<div class="text-xs font-semibold text-gray-700 dark:text-gray-200">{$i18n.t('Verified links')}</div>
					<div class="flex flex-wrap gap-2">
						{#if viewDef.links.docs}
							<a
								href={viewDef.links.docs}
								target="_blank"
								rel="noreferrer"
								class="text-xs px-2.5 py-1 rounded-lg border border-gray-200 dark:border-white/10 text-blue-600 dark:text-blue-300 hover:bg-blue-500/10 transition"
								>{$i18n.t('Docs')}</a
							>
						{/if}
						{#if viewDef.links.homepage}
							<a
								href={viewDef.links.homepage}
								target="_blank"
								rel="noreferrer"
								class="text-xs px-2.5 py-1 rounded-lg border border-gray-200 dark:border-white/10 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/5 transition"
								>{$i18n.t('Homepage')}</a
							>
						{/if}
					</div>
				</div>
			{/if}

			<!-- permissions -->
			{#if viewDef?.permissions && viewDef.permissions.length}
				<div class="space-y-1.5">
					<div class="text-xs font-semibold text-gray-700 dark:text-gray-200">{$i18n.t('Permissions')}</div>
					<ul class="space-y-1">
						{#each viewDef.permissions as p}
							<li class="text-xs text-gray-500 dark:text-gray-400 flex items-start gap-1.5">
								<span class="text-amber-500 mt-0.5">•</span>{p}
							</li>
						{/each}
					</ul>
				</div>
			{/if}

			<!-- actions -->
			{#if actions.length}
				<div class="flex flex-wrap items-center gap-2 pt-3 border-t border-gray-100 dark:border-white/8">
					{#each actions as a}
						<button
							type="button"
							title={a.title ?? ''}
							class="text-xs px-3 py-1.5 rounded-lg border transition {a.primary
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
	{/if}
</Modal>
