<script lang="ts">
	import { getContext } from 'svelte';
	const i18n: any = getContext('i18n');

	// Content-shaped skeleton for the Recents chat list on cold load — mirrors a
	// ChatItem row exactly (rounded-xl · px-[11px] py-[6px] · h-[20px] title line) so
	// the placeholder reserves the same space and real rows swap in with no layout
	// shift. A gentle staggered pulse (opacity only, GPU-cheap) replaces the bare
	// centered spinner. Decorative → aria-hidden, with one sr-only status line.
	export let rows = 7;

	// Varied "title" widths so it reads like a list of chat titles, not identical bars.
	const widths = ['82%', '56%', '90%', '46%', '72%', '64%', '86%', '52%', '76%', '60%'];
</script>

<div class="pt-0.5" aria-hidden="true">
	{#each Array.from({ length: rows }) as _, i}
		<div class="w-full rounded-xl px-[11px] py-[6px]">
			<div class="h-[20px] flex items-center">
				<div
					class="h-[13px] rounded-md bg-black/5 dark:bg-white/5 animate-pulse motion-reduce:animate-none"
					style="width: {widths[i % widths.length]}; animation-delay: {i * 90}ms;"
				></div>
			</div>
		</div>
	{/each}
</div>
<span class="sr-only" role="status">{$i18n.t('Loading recent chats…')}</span>
