<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';
	import HarvisMascot from '$lib/components/common/HarvisMascot.svelte';

	// The card tucked under the launch composer. In Work it says who will do the
	// work, what they have (a computer, skills, memory) and what they always ask
	// about; in Chat it is the one-line invitation to hand the task to a teammate.
	// Events only — the parent owns the mode and the model selection.
	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let workMode = false;
	export let workBusy = false;
	export let teammate: any = null;
	export let teammates: any[] = [];
	export let selectedModels: string[] = [];

	const trayChips = ['Computer', 'Skills', 'Memory'];
</script>

<div
	class="relative z-0 -mt-[14px] mx-auto w-[calc(100%-34px)] pt-[22px] px-4 pb-[11px] flex items-center justify-between gap-3 bg-gray-50 dark:bg-gray-900 border border-t-0 border-gray-200 dark:border-gray-800 rounded-b-2xl text-left"
>
		{#if workMode}
			<div class="flex min-w-0 items-center gap-2.5">
				{#if teammate?.info?.meta?.profile_image_url}
					<img
						class="size-7 shrink-0 rounded-lg"
						src={teammate.info.meta.profile_image_url}
						alt=""
					/>
				{:else}
					<HarvisMascot size={28} />
				{/if}
				<div class="min-w-0">
					<div class="truncate text-[0.8125rem] font-medium text-gray-900 dark:text-gray-50">
						{teammate?.name || $i18n.t('Your teammate')}
						<span class="ml-1 font-normal text-gray-500 dark:text-gray-400"
							>{$i18n.t('does the work; you watch or take over')}</span
						>
					</div>
					<div class="mt-0.5 flex flex-wrap items-center gap-1 text-[11px] text-gray-500 dark:text-gray-400">
						{#each trayChips as chip}
							<span class="rounded-md border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-850 px-1.5 py-px"
								>{chip}</span
							>
						{/each}
						<span class="ml-0.5">{$i18n.t('asks before sign in, pay, send, delete')}</span>
					</div>
				</div>
			</div>
			<div class="flex shrink-0 items-center gap-1.5">
				{#if teammates.length > 1}
					{#each teammates as m (m.id)}
						<button
							type="button"
							class="max-w-[110px] truncate rounded-lg border px-2 py-0.5 text-[11px] transition {selectedModels.includes(
								m.id
							)
								? 'border-blue-500/50 bg-blue-500/10 text-blue-700 dark:text-blue-300'
								: 'border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-850 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'}"
							title={m.info?.meta?.description || m.name}
							on:click={() => dispatch('pick', m.id)}>{m.name}</button
						>
					{/each}
				{/if}
				<button
					type="button"
					class="inline-flex items-center gap-1 rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-850 px-2 py-0.5 text-[11px] text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition"
					title={$i18n.t("Open the teammate's screen")}
					on:click={() => dispatch('computer')}
				>
					<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
						><rect x="2" y="3" width="20" height="14" rx="2" /><path d="M8 21h8M12 17v4" /></svg
					>
					{$i18n.t('Computer')}
				</button>
				<button
					type="button"
					class="size-6 ml-0.5 inline-flex items-center justify-center rounded-lg text-gray-400 dark:text-gray-500 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-850 transition"
					on:click={() => dispatch('dismiss')}
					aria-label={$i18n.t('Dismiss')}
				>
					<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
				</button>
			</div>
		{:else}
			<span class="inline-flex min-w-0 items-center gap-1.5 text-[0.8125rem] text-gray-600 dark:text-gray-400">
				<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"
					><rect x="2" y="3" width="20" height="14" rx="2" /><path d="M8 21h8M12 17v4" /></svg
				>
				<span class="truncate"
					>{$i18n.t('Switch to Work to hand this to a teammate with its own computer.')}</span
				>
			</span>
			<div class="flex shrink-0 items-center gap-1.5">
				<button
					type="button"
					class="rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-850 px-2.5 py-0.5 text-[11px] text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition"
					disabled={workBusy}
					on:click={() => dispatch('work')}>{$i18n.t('Work')}</button
				>
				<button
					type="button"
					class="size-6 ml-0.5 inline-flex items-center justify-center rounded-lg text-gray-400 dark:text-gray-500 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-850 transition"
					on:click={() => dispatch('dismiss')}
					aria-label={$i18n.t('Dismiss')}
				>
					<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
				</button>
			</div>
		{/if}
</div>
