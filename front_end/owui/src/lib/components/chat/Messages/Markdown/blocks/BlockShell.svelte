<script lang="ts">
	import { getContext } from 'svelte';
	import { copyToClipboard } from '$lib/utils';
	import { settings } from '$lib/stores';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import DocumentDuplicate from '$lib/components/icons/DocumentDuplicate.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import type { BlockStatus } from './registry';

	const i18n = getContext('i18n');

	export let label: string = '';
	export let status: BlockStatus = null;
	/** Text handed to the copy button. Empty string hides the button. */
	export let copyText: string = '';
	/** Terminal-style dark chrome vs. the light card used for prose. */
	export let dark: boolean = false;

	let copied = false;

	const doCopy = async () => {
		copied = true;
		await copyToClipboard(copyText, null, $settings?.copyFormatted ?? false);
		setTimeout(() => (copied = false), 1000);
	};
</script>

<div
	class="relative group my-2 rounded-2xl border overflow-hidden {dark
		? 'border-gray-800 bg-gray-950'
		: 'border-gray-100 dark:border-gray-800'}"
>
	<div
		class="flex items-center justify-between gap-2 px-4 py-2 {dark
			? 'bg-gray-900/60 text-gray-400'
			: 'text-gray-500 dark:text-gray-400'}"
	>
		<div class="flex items-center gap-2 min-w-0">
			<span class="text-xs font-medium truncate">{label}</span>
			{#if status === 'running'}
				<Spinner className="size-3" />
			{:else if status === 'complete'}
				<svg
					xmlns="http://www.w3.org/2000/svg"
					fill="none"
					viewBox="0 0 24 24"
					stroke-width="2"
					stroke="currentColor"
					class="size-3.5 text-green-500 shrink-0"
					aria-label={$i18n.t('Complete')}
				>
					<path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
				</svg>
			{:else if status === 'error'}
				<svg
					xmlns="http://www.w3.org/2000/svg"
					fill="none"
					viewBox="0 0 24 24"
					stroke-width="2"
					stroke="currentColor"
					class="size-3.5 text-red-500 shrink-0"
					aria-label={$i18n.t('Error')}
				>
					<path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
				</svg>
			{/if}
		</div>

		{#if copyText}
			<div class="invisible group-hover:visible flex gap-0.5 shrink-0">
				<Tooltip content={copied ? $i18n.t('Copied') : $i18n.t('Copy')}>
					<button
						class="p-1 rounded-lg bg-transparent hover:bg-black/5 dark:hover:bg-white/5 transition"
						type="button"
						on:click|stopPropagation={doCopy}
					>
						{#if copied}
							<svg
								xmlns="http://www.w3.org/2000/svg"
								fill="none"
								viewBox="0 0 24 24"
								stroke-width="1.5"
								stroke="currentColor"
								class="size-3.5 text-green-500"
							>
								<path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
							</svg>
						{:else}
							<DocumentDuplicate className="size-3.5" strokeWidth="1.5" />
						{/if}
					</button>
				</Tooltip>
			</div>
		{/if}
	</div>

	<slot />
</div>
