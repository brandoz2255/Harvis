<script lang="ts">
	// Actions row under the Build analysis: View run details · Create PR · Download files.
	// (Commit is intentionally omitted — there's no commit-only endpoint; Create PR commits +
	// pushes + opens the PR.) Self-loads the run's repo + artifacts to gate the buttons.
	import { getContext, onMount } from 'svelte';
	import {
		getRunRepo,
		getRunArtifacts,
		downloadArtifactFile,
		type RunRepo,
		type ArtifactMeta
	} from '$lib/apis/agent-runs';

	const i18n: any = getContext('i18n');
	const t = (s: string) => (i18n && typeof i18n.t === 'function' ? i18n.t(s) : s);

	export let run: any = null; // the turn (needs .id)
	export let sessionId = '';
	export let expanded = false; // is "View run details" open
	export let onOpenRun: () => void = () => {};
	// Phase 4: Create-PR opens the shared PrDrawer (title/body/base + checklist) —
	// this row no longer hosts its own inline title-only form.
	export let onCreatePr: () => void = () => {};

	let repo: RunRepo | null = null;
	let fileArtifacts: ArtifactMeta[] = [];
	let hasDiff = false;
	let loaded = false;

	let downloading = false;

	const load = async () => {
		if (!run?.id) {
			loaded = true;
			return;
		}
		try {
			const [r, arts] = await Promise.all([getRunRepo(run.id), getRunArtifacts(run.id)]);
			repo = r;
			fileArtifacts = (arts || []).filter((a) => a.artifact_type === 'file');
			hasDiff = (arts || []).some((a) => a.artifact_type === 'diff');
		} catch (_) {
			/* fail-soft: the row still shows View run details */
		}
		loaded = true;
	};
	onMount(load);

	$: canPr = !!(repo?.has_github && hasDiff && sessionId);
	$: canDownload = fileArtifacts.length > 0;

	const doDownload = async () => {
		downloading = true;
		try {
			for (const a of fileArtifacts.slice(0, 8)) {
				try {
					await downloadArtifactFile(a.id, (a.path || 'file').split('/').pop());
				} catch (_) {}
			}
		} finally {
			downloading = false;
		}
	};

	const BTN =
		'inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-md border border-gray-200 dark:border-white/10 text-gray-400 hover:text-gray-800 dark:hover:text-gray-100 hover:bg-black/[0.04] dark:hover:bg-white/[0.06] transition';
</script>

<div class="flex items-center gap-1.5 flex-wrap">
	<!-- View run details (Open run · Preview · diff & logs) -->
	<button type="button" class={BTN} on:click={onOpenRun}>
		<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-3 transition-transform {expanded ? 'rotate-90' : ''}"><path fill-rule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clip-rule="evenodd" /></svg>
		{expanded ? t('Hide run details') : t('View run details — diff & logs')}
	</button>

	{#if loaded && canPr}
		<button type="button" class={BTN} on:click={onCreatePr}>
			<svg class="size-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M6 21V9a9 9 0 0 0 9 9"/></svg>
			{t('Create PR')}
		</button>
	{/if}

	{#if loaded && canDownload}
		<button type="button" class={BTN} on:click={doDownload} disabled={downloading}>
			<svg class="size-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/></svg>
			{downloading ? t('Downloading…') : t('Download')}{fileArtifacts.length > 1 ? ` (${fileArtifacts.length})` : ''}
		</button>
	{/if}
</div>

<!-- Phase 4: the inline PR form was replaced by the consolidated PrDrawer (opened via
     the onCreatePr prop → the page's PrDrawer). The old prOpen/prTitle/doPr script was removed. -->
