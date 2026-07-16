<script lang="ts">
	// Mirrors a running agent review (coder ↔ reviewer) into the main Chat app as a right-side
	// panel. Opened from the "Agent review live" chip in the Navbar. Reuses RunView, which streams
	// the run's events and renders them (including the coder/reviewer agent_message bubbles) — so
	// it's a read-only mirror of what's happening in Build, without leaving Chat.
	import { getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { showReviewMirror } from '$lib/stores';
	import RunView from '$lib/agent-studio/RunView.svelte';

	const i18n: any = getContext('i18n');
	$: runId = $showReviewMirror;
	const close = () => showReviewMirror.set(null);
</script>

{#if runId}
	<!-- Non-modal: NO page-dimming backdrop, so you can keep working (scroll the transcript,
	     type in Build) while following the coder↔reviewer conversation live on the right. -->
	<aside
		class="fixed right-0 top-0 bottom-0 z-50 w-full max-w-md bg-white dark:bg-gray-950 border-l border-gray-100 dark:border-gray-850 shadow-2xl flex flex-col"
	>
		<div class="shrink-0 flex items-center gap-2 px-4 py-3 border-b border-gray-100 dark:border-white/8">
			<span class="relative flex size-2">
				<span
					class="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"
				></span>
				<span class="relative inline-flex rounded-full size-2 bg-amber-500"></span>
			</span>
			<div class="min-w-0">
				<div class="text-sm font-semibold text-gray-800 dark:text-gray-100">
					{$i18n.t('Agent review')}
				</div>
				<div class="text-[11px] text-gray-400">
					{$i18n.t('Coder ↔ reviewer — mirrored from Build')}
				</div>
			</div>
			<button
				class="ml-auto shrink-0 text-[11px] text-gray-400 hover:text-blue-500 transition"
				on:click={() => {
					const id = runId;
					close();
					goto('/harvis/agent-studio/run/' + id);
				}}
				title={$i18n.t('Open the full run')}>⤢ {$i18n.t('Full run')}</button
			>
			<button
				class="shrink-0 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 p-1"
				aria-label={$i18n.t('Close')}
				on:click={close}
			>
				<svg viewBox="0 0 20 20" fill="currentColor" class="size-4"><path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" /></svg>
			</button>
		</div>
		<div class="flex-1 min-h-0 overflow-hidden p-3">
			{#key runId}
				<RunView wsId={runId} mode="stream" />
			{/key}
		</div>
	</aside>
{/if}
