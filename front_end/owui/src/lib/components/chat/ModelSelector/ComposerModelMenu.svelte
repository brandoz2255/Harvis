<script lang="ts">
	// The composer model menu — the picker users actually see, lifted out of MessageInput so the
	// Build/Code tab gets the SAME one rather than a second, thinner copy that drifts. It is only
	// the dropdown's CONTENTS: each caller keeps its own trigger, because the chat composer's
	// trigger is the Auto/Chat/Agent mode pill and Build has no chat modes.
	//
	// Note for anyone reaching for the OTHER selector: ModelSelector/Selector.svelte is the navbar
	// picker and has no effort affordance. It is deliberately kept stock (see
	// docs/handoffs/2026-07-10-model-picker-effort-slider.md) — do not wire the composer through it.
	import { createEventDispatcher, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { models, settings, config } from '$lib/stores';
	import { getModels } from '$lib/apis';
	import EffortSlider from './EffortSlider.svelte';
	import ModelProfileEditor from './ModelProfileEditor.svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	// The candidate list. Chat passes the whole catalogue; Build passes its engine-filtered one,
	// which is why this is a prop and not a read of $models.
	export let items: any[] = [];
	export let selectedId = '';

	let modelSearch = '';
	let showAllModels = false;
	let showModelEditor = false;
	let editorModel: any = null;

	const isCloudModel = (m: any) => ['anthropic', 'openai'].includes(m?.owned_by);

	// Context window, shown beside each model id. Several vendor catalogues carry families that
	// differ only in the tail of the id, and the window is often what actually separates them.
	const modelContext = (m: any) => {
		const n = Number(m?.info?.meta?.context_length || 0);
		if (!n) return '';
		return n >= 1_000_000 ? `${Math.round(n / 1_000_000)}M ctx` : `${Math.round(n / 1024)}K ctx`;
	};

	// Abbreviated, because the effort rides on the model row and the row is tight. No saved effort
	// reads as "Auto": the model decides. Blank for models with no effort axis at all.
	const EFFORT_SHORT: Record<string, string> = {
		minimal: 'Min',
		low: 'Low',
		medium: 'Med',
		high: 'High',
		extra_high: 'X-High',
		max: 'Max',
		ultra: 'Ultra'
	};
	export const effortLabelOf = (m: any) => {
		const e = m?.info?.meta?.profile_effort;
		if (e) return EFFORT_SHORT[e] ?? e;
		return m?.info?.meta?.supports_effort ? 'Auto' : '';
	};

	let refreshingModels = false;
	const refreshModels = async () => {
		if (refreshingModels) return;
		refreshingModels = true;
		try {
			models.set(
				await getModels(
					localStorage.token,
					$config?.features?.enable_direct_connections && ($settings?.directConnections ?? null),
					false,
					true
				)
			);
			toast.success($i18n.t('Models refreshed'));
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			refreshingModels = false;
		}
	};

	// The effort flyout that opens beside a hovered model row. It lives OUTSIDE the scrolling list
	// — an absolutely positioned child of a scroll container is clipped by it — so the row hands
	// over its offset and the panel is placed against the list instead.
	let modelListEl: HTMLDivElement | null = null;
	let effortFlyoutModel: any = null;
	let effortFlyoutTop = 0;
	let effortFlyoutTimer: any = null;
	const openEffortFlyout = (m: any, ev: Event) => {
		clearTimeout(effortFlyoutTimer);
		const row = (ev.currentTarget as HTMLElement)?.closest('[data-model-row]') as HTMLElement;
		if (row && modelListEl) effortFlyoutTop = row.offsetTop - modelListEl.scrollTop;
		effortFlyoutModel = m;
	};
	// A small grace period so the pointer can cross the gap between the row and the panel.
	const closeEffortFlyout = () => {
		clearTimeout(effortFlyoutTimer);
		effortFlyoutTimer = setTimeout(() => (effortFlyoutModel = null), 160);
	};
	const holdEffortFlyout = () => clearTimeout(effortFlyoutTimer);

	// Reset the transient view whenever the menu is re-mounted by its caller's dropdown.
	export const resetView = () => {
		showAllModels = false;
		modelSearch = '';
		effortFlyoutModel = null;
	};

	// The "show all Claude models" gate is a persisted user setting, managed in Settings →
	// Interface (not in this dropdown). The picker just reads it.
	$: modelMenuList = (() => {
		const all = items ?? [];
		const q = modelSearch.trim().toLowerCase();
		const match = (m: any) =>
			!q || (m?.name ?? '').toLowerCase().includes(q) || (m?.id ?? '').toLowerCase().includes(q);
		// Claude is limited to the current-generation flagships (meta.primary) unless the user has
		// opted into the full catalog in settings; OpenAI + local are unaffected.
		const showAllClaude = $settings?.showAllCloudModels === true;
		const claude = all.filter((m: any) => m?.owned_by === 'anthropic');
		const claudeShown = showAllClaude ? claude : claude.filter((m: any) => m?.info?.meta?.primary);
		const openai = all.filter((m: any) => m?.owned_by === 'openai');
		const local = all.filter((m: any) => !isCloudModel(m));
		const ordered = [...claudeShown, ...openai, ...local]; // cloud-first
		const curModel = all.find((m: any) => m.id === selectedId);
		// Float the active model to the very top without disturbing the cloud-first ordering.
		const withCur = curModel ? [curModel, ...ordered.filter((m: any) => m.id !== selectedId)] : ordered;
		const filtered = withCur.filter(match);
		// Capped by default; a search OR "Show all models" expands to the full list.
		return showAllModels || q ? filtered : filtered.slice(0, 7);
	})();

	// Same list, under provider headings. Groups appear in order of first appearance, so the
	// active model's provider leads.
	$: modelMenuGroups = (() => {
		const LABELS: Record<string, string> = { anthropic: 'Anthropic', openai: 'OpenAI' };
		const groups: { label: string; models: any[] }[] = [];
		for (const m of modelMenuList) {
			const label = LABELS[m?.owned_by] ?? 'Local';
			let g = groups.find((x) => x.label === label);
			if (!g) groups.push((g = { label, models: [] }));
			g.models.push(m);
		}
		return groups;
	})();

	// What the "Edit Models…" footer opens: the active model when it has an editable profile
	// (cloud only), else nothing — the action is disabled rather than silently inert.
	$: activeModel = (items ?? []).find((m: any) => m.id === selectedId);
	$: editableModel = isCloudModel(activeModel) ? activeModel : null;
</script>

<div class="flex items-center gap-1.5 px-2 py-1 border-b border-gray-150 dark:border-gray-850 mb-0.5">
	<svg class="size-3 text-gray-400 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.35-4.35"/></svg>
	<input bind:value={modelSearch} placeholder={$i18n.t('Search models')} autocomplete="off" class="w-full bg-transparent outline-none text-[13px] py-0.5" on:click|stopPropagation />
</div>
<!-- Grouped by provider, one line per model with its effort inline. The Options panel opens to the
     LEFT and sits OUTSIDE the scroll box — inside it, an absolutely positioned panel would be
     clipped by the scroll container. -->
<div class="relative">
	<div class="max-h-72 overflow-y-auto" bind:this={modelListEl} on:scroll={() => (effortFlyoutModel = null)}>
		{#each modelMenuGroups as g (g.label)}
			<div class="px-2.5 pt-1.5 pb-0.5 text-[10px] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500">
				{$i18n.t(g.label)}
			</div>
			{#each g.models as m}
				<!-- svelte-ignore a11y-no-static-element-interactions -->
				<div
					data-model-row
					class="w-full flex items-center gap-1 group/mrow rounded-md hover:bg-gray-100 dark:hover:bg-gray-800 transition"
					on:mouseenter={(e) => (m?.info?.meta?.supports_effort ? openEffortFlyout(m, e) : closeEffortFlyout())}
					on:mouseleave={closeEffortFlyout}
					on:focusin={(e) => (m?.info?.meta?.supports_effort ? openEffortFlyout(m, e) : closeEffortFlyout())}
					on:focusout={closeEffortFlyout}
				>
					<button
						type="button"
						class="flex-1 min-w-0 flex items-center gap-1.5 px-2.5 py-1 text-left"
						title={[m.id, modelContext(m)].filter(Boolean).join(' · ')}
						on:click={() => dispatch('select', m.id)}
					>
						<span class="flex-1 min-w-0 truncate text-[13px] text-gray-800 dark:text-gray-100">{m.name}</span>
						{#if m?.info?.meta?.supports_effort}
							<!-- The effort rides on the row, so "which model" and "how deep" read as one
							     line. Hovering the row opens the panel that sets it. -->
							<span class="shrink-0 text-[11px] text-gray-400 dark:text-gray-500">{effortLabelOf(m)}</span>
						{/if}
					</button>
					{#if isCloudModel(m)}
						<button type="button" class="shrink-0 text-[11px] text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 px-1 py-1 opacity-0 group-hover/mrow:opacity-100 transition" aria-label={$i18n.t('Edit model profile')} on:click|stopPropagation={() => { editorModel = m; showModelEditor = true; }}>{$i18n.t('Edit')}</button>
					{/if}
					<span class="w-4 shrink-0 mr-1 flex items-center justify-center">
						{#if selectedId === m.id}
							<svg class="size-3.5 text-blue-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
						{/if}
					</span>
				</div>
			{/each}
		{/each}
	</div>

	{#if effortFlyoutModel}
		<!-- svelte-ignore a11y-no-static-element-interactions -->
		<div
			class="absolute right-full mr-1 z-20 w-48 rounded-lg border border-gray-150 dark:border-gray-850 bg-white dark:bg-gray-900 shadow-xl"
			style="top: {Math.max(0, effortFlyoutTop - 8)}px"
			on:mouseenter={holdEffortFlyout}
			on:mouseleave={closeEffortFlyout}
		>
			<EffortSlider model={effortFlyoutModel} on:changed={() => models.update((ms) => [...ms])} />
		</div>
	{/if}
</div>

<!-- Utility actions, fenced off from the model list: the picker is also where the catalogue is
     managed, so neither needs a trip to settings. -->
<div class="my-1 border-t border-gray-150 dark:border-gray-850"></div>
{#if !showAllModels && !modelSearch.trim() && (items ?? []).length > 7}
	<button
		type="button"
		class="w-full flex items-center gap-2 px-2.5 py-1 rounded-md text-left text-[13px] text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition"
		on:click={() => (showAllModels = true)}
	>
		<span class="flex-1">{$i18n.t('Show all models')} ({(items ?? []).length})</span>
		<svg class="size-3 opacity-60 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>
	</button>
{/if}
<button
	type="button"
	class="w-full flex items-center gap-2 px-2.5 py-1 rounded-md text-left text-[13px] text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition disabled:opacity-50"
	disabled={refreshingModels}
	on:click|stopPropagation={refreshModels}
>
	<svg class="size-3.5 shrink-0 opacity-70 {refreshingModels ? 'animate-spin' : ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/></svg>
	<span class="flex-1">{refreshingModels ? $i18n.t('Refreshing…') : $i18n.t('Refresh Models')}</span>
</button>
<!-- NOT /workspace/models: that route is unbacked in the Harvis facade (/api/v1/models/* 404s), so
     it is flag-gated and bounces to /workspace/knowledge — which from the composer reads as
     "nothing happened". The profile editor is the surface that actually edits a model here, and it
     is the same one the row's Edit button opens. -->
<button
	type="button"
	class="w-full flex items-center gap-2 px-2.5 py-1 rounded-md text-left text-[13px] text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition disabled:opacity-40"
	disabled={!editableModel}
	title={editableModel ? '' : $i18n.t('Local models have no editable profile')}
	on:click|stopPropagation={() => { editorModel = editableModel; showModelEditor = true; dispatch('close'); }}
>
	<svg class="size-3.5 shrink-0 opacity-70" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>
	<span class="flex-1">{$i18n.t('Edit Models…')}</span>
</button>

{#if editorModel}
	<!-- Modal portals to document.body, so it is safe inside the dropdown's content. -->
	<ModelProfileEditor bind:show={showModelEditor} model={editorModel} on:saved={() => models.update((ms) => [...ms])} />
{/if}
