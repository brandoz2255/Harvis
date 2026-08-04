<script lang="ts">
	// The temporary CAD tab in the chat controls rail.
	//
	// The full workspace moved to `/harvis/cad` (Gate 6) because a 300px rail is the
	// wrong shape for a viewport, a parameter list, a version history and an export
	// row all at once. This tab stays only so the route is discoverable from chat
	// while it is being verified; once it is, delete the `'cad'` arm in
	// ChatControls.svelte and this file with it.
	//
	// It shows nothing the route does not — no viewport, no parameters. What it does
	// show is real: the project list comes from `/api/cad/projects`, so an empty list
	// here means the user genuinely has no parts, not that the tab is a stub.
	import { getContext, onMount } from 'svelte';
	import { goto } from '$app/navigation';

	import {
		getCadCapability,
		listCadProjects,
		type CadCapability,
		type CadProject
	} from '$lib/apis/cad';

	const i18n: any = getContext('i18n');

	let capability: CadCapability | null = null;
	let projects: CadProject[] = [];
	let loading = true;

	onMount(async () => {
		try {
			capability = await getCadCapability();
			if (capability?.enabled) {
				projects = await listCadProjects().catch(() => []);
			}
		} catch {
			capability = null;
		}
		loading = false;
	});
</script>

<div class="flex flex-col w-full h-full text-sm">
	{#if loading}
		<div class="p-4 text-xs text-gray-500 dark:text-gray-400">{$i18n.t('Loading…')}</div>
	{:else if !capability?.enabled}
		<div class="p-4 text-xs text-gray-500 dark:text-gray-400">
			{$i18n.t('Local CAD is not enabled on this server.')}
		</div>
	{:else}
		<div class="flex flex-col gap-3 px-3 py-3">
			<div class="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
				{$i18n.t(
					'CAD Studio has its own workspace now — the viewport, parameters, versions and exports all live there.'
				)}
			</div>

			<button
				class="self-start text-xs px-3 py-1.5 rounded-lg bg-gray-900 text-white dark:bg-white dark:text-gray-900"
				on:click={() => goto('/harvis/cad')}>{$i18n.t('Open CAD Studio')}</button
			>

			{#if projects.length}
				<div class="flex flex-col gap-0.5 pt-1">
					<div class="text-[11px] text-gray-500 dark:text-gray-400">
						{$i18n.t('Recent parts')}
					</div>
					{#each projects.slice(0, 6) as p}
						<button
							class="text-left text-xs px-2 py-1.5 rounded-lg truncate text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-900"
							on:click={() => goto(`/harvis/cad/${p.id}`)}>{p.title}</button
						>
					{/each}
				</div>
			{/if}

			{#if !capability.engine_reachable}
				<span class="text-[11px] text-amber-600 dark:text-amber-400"
					>{$i18n.t('engine unreachable')}</span
				>
			{/if}
		</div>
	{/if}
</div>
