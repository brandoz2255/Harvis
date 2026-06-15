<script lang="ts">
	import { getContext } from 'svelte';
	import { dockedRunId } from '$lib/stores';
	import RunArtifacts from '$lib/agent-studio/RunArtifacts.svelte';
	import ArtifactActions from '$lib/agent-studio/ArtifactActions.svelte';
	import SessionArtifacts from '../SessionArtifacts.svelte';

	const i18n: any = getContext('i18n');

	// The current chat (forwarded to SessionArtifacts for session-scoped items).
	export let history: any = null;

	// The run's preview IS the artifact — it fills the whole Artifacts tab. The
	// OWUI session artifacts (research reports etc.) sit behind a small toggle.
	let showSession = false;
	let hasPreview = false;
	let primary: { name: string; content: string } | null = null;
</script>

<div class="h-full flex flex-col min-h-0">
	{#if $dockedRunId && !showSession}
		<div class="flex items-center gap-2 px-3 py-2 shrink-0">
			<span class="text-sm font-medium text-gray-800 dark:text-gray-100">{$i18n.t('Artifact')}</span>
			<div class="ml-auto flex items-center gap-2">
				{#if primary}
					<ArtifactActions name={primary.name} content={primary.content} />
				{/if}
				<button
					class="text-[11px] text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition"
					on:click={() => (showSession = true)}
				>
					{$i18n.t('Session artifacts')}
				</button>
			</div>
		</div>
		<div class="flex-1 min-h-0 px-3 pb-3">
			<RunArtifacts
				wsId={$dockedRunId}
				mode="preview"
				bare
				fill
				on:loaded={(e) => {
					hasPreview = e.detail.hasPreview;
					primary = e.detail.primary;
				}}
			/>
			{#if !hasPreview}
				<div class="text-xs text-gray-400 mt-2">{$i18n.t('No preview available for this run.')}</div>
			{/if}
		</div>
	{:else}
		{#if $dockedRunId}
			<div class="px-3 pt-2 shrink-0">
				<button
					class="text-[11px] text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition"
					on:click={() => (showSession = false)}
				>
					← {$i18n.t('Back to preview')}
				</button>
			</div>
		{/if}
		<div class="flex-1 min-h-0">
			<SessionArtifacts {history} />
		</div>
	{/if}
</div>
