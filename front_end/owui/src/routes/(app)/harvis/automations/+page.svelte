<script lang="ts">
	// Automations = the operations surface: active/background runs, approvals,
	// scheduled jobs, and history. (Capabilities + customization live on the
	// Agent Studio page; this is "what is running / scheduled".)
	import { getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { WEBUI_NAME, chatId } from '$lib/stores';
	import Automations from '$lib/agent-studio/Automations.svelte';
	import WorkspaceActivity from '$lib/components/chat/WorkspaceActivity.svelte';

	const i18n: any = getContext('i18n');
	const backToChat = () => goto($chatId ? `/c/${$chatId}` : '/');
</script>

<svelte:head>
	<title>{$i18n.t('Automations')} • {$WEBUI_NAME}</title>
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
				<button
					class="text-xs px-3 py-1.5 rounded-full bg-blue-600 hover:bg-blue-500 text-white transition"
					on:click={() => goto('/')}>{$i18n.t('Run task')}</button
				>
			</div>
			<h1 class="text-2xl font-semibold text-gray-800 dark:text-gray-100 mt-2">
				{$i18n.t('Automations')}
			</h1>
			<p class="text-sm text-gray-500 mt-1">
				{$i18n.t('Runs, schedules, approvals, and background tasks.')}
			</p>
		</header>

		<!-- Active -->
		<section>
			<h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
				{$i18n.t('Active')}
			</h2>
			<WorkspaceActivity embed statuses={['running']} emptyText={$i18n.t('No active runs.')} />
		</section>

		<!-- Waiting for review (approvals) -->
		<section>
			<h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
				{$i18n.t('Waiting for review')}
			</h2>
			<div
				class="rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 px-4 py-3 text-xs text-gray-500"
			>
				{$i18n.t('No approvals pending. Enable approvals in agent settings to gate risky steps.')}
			</div>
		</section>

		<!-- Scheduled · recent runs · templates — the rich automations surface (header-less). -->
		<Automations embed />
	</div>
</div>
