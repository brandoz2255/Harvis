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

	$: tone = def ? toneFor(def.brandKey) : { icon: '', tile: '' };
	$: actions = def ? actionsFor(def) : [];
	$: engineTone =
		def?.engine?.support === 'candidate'
			? 'text-emerald-500 dark:text-emerald-400'
			: def?.engine?.support === 'supported'
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

			<!-- engine support (honest planned/candidate signal) -->
			{#if def.engine}
				<div class="rounded-lg border border-gray-100 dark:border-white/8 bg-gray-50 dark:bg-white/[0.02] px-3 py-2.5">
					<div class="flex items-center gap-2 text-xs">
						<span class="font-semibold text-gray-700 dark:text-gray-200">{$i18n.t('Engine support')}:</span>
						<span class="font-medium {engineTone}">{$i18n.t(ENGINE_LABEL[def.engine.support])}</span>
					</div>
					{#if def.engine.notes}
						<p class="text-[11px] text-gray-500 dark:text-gray-400 mt-1">{def.engine.notes}</p>
					{/if}
				</div>
			{/if}

			<!-- honest runtime note -->
			{#if def.runtimeNote}
				<div class="rounded-lg border border-amber-500/20 bg-amber-500/[0.04] px-3 py-2.5 text-xs">
					<span class="font-semibold text-amber-600 dark:text-amber-300">Note:</span>
					<span class="text-gray-600 dark:text-gray-300">{def.runtimeNote}</span>
				</div>
			{/if}

			<!-- connection (Phase B) — the source of truth for per-user connection state -->
			{#if def.connect}
				<ConnectionPanel {def} on:changed />
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
			{#if def.auth && !def.connect}
				<div class="space-y-1.5">
					<div class="text-xs font-semibold text-gray-700 dark:text-gray-200">{$i18n.t('Authentication')}</div>
					{#if def.auth.required}
						<div class="flex flex-wrap items-center gap-1.5">
							{#each def.auth.modes as m}
								<span class="text-[11px] px-2 py-0.5 rounded-full bg-gray-100 dark:bg-white/5 text-gray-600 dark:text-gray-300 border border-gray-200/60 dark:border-white/8">
									{$i18n.t(AUTH_LABEL[m])}{$i18n.t(' — planned')}
								</span>
							{/each}
						</div>
					{:else}
						<p class="text-xs text-gray-500 dark:text-gray-400">{$i18n.t('No authentication required.')}</p>
					{/if}
					{#if def.auth.notes}
						<p class="text-[11px] text-gray-500 dark:text-gray-400">{def.auth.notes}</p>
					{/if}
				</div>
			{/if}

			<!-- capabilities (typed contract) -->
			{#if def.provides && def.provides.length}
				<div class="space-y-1.5">
					<div class="text-xs font-semibold text-gray-700 dark:text-gray-200">{$i18n.t('Capabilities')}</div>
					<div class="flex flex-wrap gap-1.5">
						{#each def.provides as c}
							<span class="text-[11px] px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-600/90 dark:text-blue-300/90 border border-blue-500/15">{CAPABILITY_LABEL[c]}</span>
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
							<span class="text-[11px] px-2 py-0.5 rounded-full bg-gray-100 dark:bg-white/5 text-gray-500 dark:text-gray-400 border border-gray-200/60 dark:border-white/8">{c}</span>
						{/each}
					</div>
				</div>
			{/if}

			<!-- verified links -->
			{#if def.links?.docs || def.links?.homepage}
				<div class="space-y-1.5">
					<div class="text-xs font-semibold text-gray-700 dark:text-gray-200">{$i18n.t('Verified links')}</div>
					<div class="flex flex-wrap gap-2">
						{#if def.links.docs}
							<a
								href={def.links.docs}
								target="_blank"
								rel="noreferrer"
								class="text-xs px-2.5 py-1 rounded-lg border border-gray-200 dark:border-white/10 text-blue-600 dark:text-blue-300 hover:bg-blue-500/10 transition"
								>{$i18n.t('Docs')}</a
							>
						{/if}
						{#if def.links.homepage}
							<a
								href={def.links.homepage}
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
			{#if def.permissions && def.permissions.length}
				<div class="space-y-1.5">
					<div class="text-xs font-semibold text-gray-700 dark:text-gray-200">{$i18n.t('Permissions')}</div>
					<ul class="space-y-1">
						{#each def.permissions as p}
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
