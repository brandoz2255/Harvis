<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';

	// The files a Build turn left in the workspace, listed under its reply.
	//
	// The panel that shows this already existed — but the dock defaults elsewhere, so a
	// turn that wrote one index.html said "Done." and named nothing. A user who asked for
	// a game had no way to see what had been created without hunting for it. These chips
	// put the answer under the reply and open the read-only viewer on click.
	//
	// `files` is the workspace's changed set AS OF this turn (cumulative against the
	// session baseline), so the header says "in the workspace" rather than claiming this
	// turn touched every one. `newFiles` — paths absent from the previous turn — IS
	// per-turn accurate, and only those get the "new" mark.
	export let files: string[] = [];
	export let newFiles: string[] = [];
	export let selected = '';

	const i18n: any = getContext('i18n');
	const dispatch = createEventDispatcher<{ open: { path: string } }>();

	const COLLAPSED = 8;
	let expanded = false;
	$: shown = expanded ? files : files.slice(0, COLLAPSED);
	$: hidden = files.length - shown.length;
	$: isNew = new Set(newFiles);

	const base = (p: string) => p.split('/').pop() || p;
</script>

{#if files.length}
	<div class="w-full flex flex-wrap items-center gap-1.5 mt-0.5">
		<span class="text-[11px] text-gray-400 dark:text-gray-500 mr-0.5">
			{files.length === 1
				? $i18n.t('1 file in the workspace')
				: $i18n.t('{{count}} files in the workspace', { count: files.length })}
		</span>
		{#each shown as path (path)}
			<button
				type="button"
				title={path}
				on:click={() => dispatch('open', { path })}
				class="inline-flex items-center gap-1 max-w-[16rem] px-1.5 py-0.5 rounded-md border text-[11px] font-mono truncate transition
					{selected === path
					? 'border-blue-400/60 bg-blue-500/10 text-blue-700 dark:text-blue-300'
					: 'border-gray-200 dark:border-white/10 bg-black/[0.03] dark:bg-white/[0.05] text-gray-600 dark:text-gray-300 hover:border-gray-300 dark:hover:border-white/20'}"
			>
				{#if isNew.has(path)}
					<span
						class="w-1.5 h-1.5 rounded-full bg-emerald-500 shrink-0"
						title={$i18n.t('Created in this turn')}
					></span>
				{/if}
				<span class="truncate">{base(path)}</span>
			</button>
		{/each}
		{#if hidden > 0}
			<button
				type="button"
				on:click={() => (expanded = true)}
				class="text-[11px] text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 underline underline-offset-2"
			>
				{$i18n.t('+{{count}} more', { count: hidden })}
			</button>
		{:else if expanded && files.length > COLLAPSED}
			<button
				type="button"
				on:click={() => (expanded = false)}
				class="text-[11px] text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 underline underline-offset-2"
			>
				{$i18n.t('Show less')}
			</button>
		{/if}
	</div>
{/if}
