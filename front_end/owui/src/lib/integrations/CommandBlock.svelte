<script lang="ts">
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { copyToClipboard } from '$lib/utils';
	import Clipboard from '$lib/components/icons/Clipboard.svelte';
	import Check from '$lib/components/icons/Check.svelte';

	const i18n: any = getContext('i18n');

	export let command = '';
	export let label = '';

	let copied = false;
	const copy = async () => {
		const ok = await copyToClipboard(command);
		if (ok) {
			copied = true;
			toast.success($i18n.t('Copied to clipboard'));
			setTimeout(() => (copied = false), 1500);
		}
	};
</script>

{#if command}
	<div class="space-y-1">
		{#if label}<div class="text-[11px] font-medium text-gray-500 dark:text-gray-400">{label}</div>{/if}
		<div
			class="flex items-center gap-2 rounded-lg border border-gray-100 dark:border-white/8 bg-gray-50 dark:bg-[#0a0e18] px-2.5 py-1.5"
		>
			<code class="flex-1 min-w-0 truncate text-[11px] font-mono text-gray-700 dark:text-gray-300">{command}</code>
			<button
				type="button"
				class="shrink-0 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition"
				on:click={copy}
				title={$i18n.t('Copy')}
				aria-label={$i18n.t('Copy')}
			>
				{#if copied}<Check className="size-3.5" />{:else}<Clipboard className="size-3.5" />{/if}
			</button>
		</div>
	</div>
{/if}
