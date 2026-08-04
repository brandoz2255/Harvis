<script lang="ts">
	// CAD Studio — the dedicated workspace (Gate 6).
	//
	// The studio used to live in the chat controls rail, which is ~300px wide. A
	// viewport, a parameter list, a version history and an export row do not fit
	// there, so the rail keeps only a launcher and the workspace lives here.
	//
	// This page is a shell: the header, the width, and the honest note about where
	// geometry runs. Everything below it is CadStudioPanel, unchanged from Gate 4 —
	// moving a working surface is not the moment to also rewrite it.
	import { getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { WEBUI_NAME, chatId, showSidebar } from '$lib/stores';

	import CadStudioPanel from '$lib/cad/CadStudioPanel.svelte';

	const i18n: any = getContext('i18n');
	const backToChat = () => goto($chatId ? `/c/${$chatId}` : '/');

	/** Set by the `[id]` route so a deep link opens that part. */
	export let projectId = '';
</script>

<svelte:head>
	<title>{$i18n.t('CAD Studio')} • {$WEBUI_NAME}</title>
</svelte:head>

<div
	class="w-full h-full overflow-y-auto {$showSidebar
		? 'md:max-w-[calc(100%-var(--sidebar-width))]'
		: ''}"
>
	<div class="max-w-5xl mx-auto px-5 py-6 space-y-4">
		<header>
			<button
				class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
				on:click={backToChat}
			>
				← {$i18n.t('Back to chat')}
			</button>
			<div class="mt-2">
				<h1 class="text-2xl font-semibold text-gray-800 dark:text-gray-100">
					{$i18n.t('CAD Studio')}
				</h1>
				<p class="text-sm text-gray-500 mt-0.5">
					{$i18n.t(
						'Exact parametric geometry, built locally. Every dimension is editable and every build is a revision you can return to.'
					)}
				</p>
			</div>
		</header>

		<div
			class="rounded-2xl border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-900 overflow-hidden"
		>
			<CadStudioPanel initialProjectId={projectId} viewerHeight={420} />
		</div>
	</div>
</div>
