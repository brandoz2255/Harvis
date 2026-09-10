<script lang="ts">
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { workMode } from '$lib/stores';
	import { applyWorkMode, syncWorkModeToSelection } from './workMode';

	const i18n: any = getContext('i18n');

	export let selectedModels: string[] = [];
	/** `compact` is the navbar dressing: same control, smaller target. */
	export let compact = false;

	let busy = false;

	const setMode = async (work: boolean) => {
		if (busy) return;
		busy = true;
		try {
			selectedModels = await applyWorkMode(work, selectedModels, localStorage.token);
		} catch (e) {
			toast.error(`${$i18n.t('Could not start Work mode')}: ${(e as Error).message}`);
			workMode.set(false);
		} finally {
			busy = false;
		}
	};

	// Leaving Work by picking an ordinary model has to keep working wherever this
	// toggle is mounted, not just on the landing screen.
	$: if (!busy) syncWorkModeToSelection(selectedModels);

	// The hit target is the whole segment, not the word. Each button is its own
	// centred flex box with a floor on width and height, so the padding is real
	// clickable area rather than a few pixels either side of the label -- in the
	// navbar the label is `text-xs`, and "Chat" on its own is a ~25px target.
	$: pad = compact ? 'px-4 py-1.5 min-w-[4rem] min-h-[1.9rem]' : 'px-7 py-2 min-w-[5.5rem] min-h-[2.25rem]';
	$: size = compact ? 'text-xs' : 'text-[0.95rem]';
	const box = 'inline-flex items-center justify-center cursor-pointer select-none leading-none';
	const on = 'bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-50 shadow-sm';
	const off = 'text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200';
</script>

<div class="inline-flex items-center gap-2">
<div
	class="inline-flex items-center rounded-full border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900 p-1 {size} font-medium shadow-sm"
	role="tablist"
	aria-label={$i18n.t('Mode')}
>
	<button
		type="button"
		role="tab"
		aria-selected={!$workMode}
		class="rounded-full {box} {pad} transition {$workMode ? off : on}"
		on:click={() => setMode(false)}>{$i18n.t('Chat')}</button
	>
	<button
		type="button"
		role="tab"
		aria-selected={$workMode}
		disabled={busy}
		class="rounded-full {box} {pad} transition {$workMode ? on : off}"
		on:click={() => setMode(true)}>{busy ? $i18n.t('Work…') : $i18n.t('Work')}</button
	>
</div>

</div>
