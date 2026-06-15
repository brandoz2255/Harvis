<script lang="ts">
	import { getContext } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { WEBUI_NAME, chatId } from '$lib/stores';
	import WorkspaceActivity from '$lib/components/chat/WorkspaceActivity.svelte';
	import IntentPills from '$lib/agent-studio/IntentPills.svelte';
	import Brain from '$lib/agent-studio/Brain.svelte';

	const i18n: any = getContext('i18n');

	// A run id in ?ws= is the OLD deep-link shape — redirect to the dedicated run
	// view. Preserves old links; back button stays clean via replaceState.
	$: wsId = $page.url.searchParams.get('ws');
	$: if (wsId) goto(`/harvis/agent-studio/run/${wsId}`, { replaceState: true });

	const backToChat = () => goto($chatId ? `/c/${$chatId}` : '/');

	// Hub tiles → the Agent Studio sub-surfaces (registered in surfaces.ts). Each
	// renders full-page at /harvis/agent-studio/<key>. Automations leads (the
	// new section); icons are inline so the grid needs no icon imports.
	const hub: { key: string; label: string; desc: string; svg: string; accent?: boolean }[] = [
		{
			key: 'automations',
			label: 'Automations',
			desc: 'Schedule agents, or launch one now from a template.',
			svg: '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/>',
			accent: true
		},
		{
			key: 'global-map',
			label: 'Neural Map',
			desc: 'Every agent run, visualized as a graph.',
			svg: '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="M8.6 13.5l6.8 4M15.4 6.5l-6.8 4"/>'
		},
		{
			key: 'activity',
			label: 'Artifacts',
			desc: 'Browse the files your agents have produced.',
			svg: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>'
		},
		{
			key: 'model-comparison',
			label: 'Model Comparison',
			desc: 'Run models side by side and compare them.',
			svg: '<path d="M3 3v18h18"/><rect x="7" y="9" width="3" height="9" rx="1"/><rect x="13" y="5" width="3" height="13" rx="1"/>'
		},
		{
			key: 'cookbook',
			label: 'Cookbook',
			desc: 'Find the models that fit your hardware.',
			svg: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>'
		}
	];
</script>

<svelte:head>
	<title>{$i18n.t('Agent Studio')} • {$WEBUI_NAME}</title>
</svelte:head>

<div class="w-full h-full overflow-y-auto">
	<div class="max-w-5xl mx-auto px-5 py-6 space-y-8">
		<!-- Header -->
		<header>
			<div class="flex items-center justify-between">
				<button
					class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
					on:click={backToChat}>← {$i18n.t('Back to chat')}</button
				>
				<a
					href="/harvis/agent-studio/tuning"
					class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
					>{$i18n.t('Customize')}</a
				>
			</div>
			<h1 class="text-2xl font-semibold text-gray-800 dark:text-gray-100 mt-2">
				{$i18n.t('Agent Studio')}
			</h1>
			<p class="text-sm text-gray-500 mt-1">
				{$i18n.t('Configure your agent, launch a task, or automate it.')}
			</p>
		</header>

		<!-- Quick start — intent presets -->
		<section>
			<h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
				{$i18n.t('Quick start')}
			</h2>
			<IntentPills />
		</section>

		<!-- Hub — sub-surfaces -->
		<section>
			<h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
				{$i18n.t('Workspaces & tools')}
			</h2>
			<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
				{#each hub as h (h.key)}
					<a
						href={`/harvis/agent-studio/${h.key}`}
						class="group rounded-xl border p-4 transition flex flex-col gap-2 {h.accent
							? 'border-blue-500/30 bg-blue-500/5 hover:bg-blue-500/10'
							: 'border-gray-100 dark:border-gray-850 hover:border-blue-500/40 hover:bg-blue-500/5'}"
					>
						<div
							class="size-9 rounded-lg flex items-center justify-center {h.accent
								? 'bg-blue-500/15 text-blue-600 dark:text-blue-300'
								: 'bg-gray-100 dark:bg-gray-850 text-gray-500 group-hover:text-blue-600 dark:group-hover:text-blue-300'} transition"
						>
							<svg
								class="size-5"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.8"
								stroke-linecap="round"
								stroke-linejoin="round">{@html h.svg}</svg
							>
						</div>
						<div class="text-sm font-medium text-gray-800 dark:text-gray-100">
							{$i18n.t(h.label)}
						</div>
						<div class="text-xs text-gray-500 leading-relaxed">{$i18n.t(h.desc)}</div>
					</a>
				{/each}
			</div>
		</section>

		<!-- Brain — agent config (OpenClaw · Skills · Memory · Tuning) -->
		<section>
			<h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
				{$i18n.t('Brain')}
			</h2>
			<Brain />
		</section>

		<!-- Recent runs -->
		<section>
			<h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
				{$i18n.t('Recent runs')}
			</h2>
			<WorkspaceActivity />
		</section>
	</div>
</div>
