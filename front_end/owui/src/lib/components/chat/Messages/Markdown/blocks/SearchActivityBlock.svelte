<script lang="ts">
	import BlockShell from './BlockShell.svelte';
	import { normalizeStatus, safeHref } from './registry';

	export let token: any;

	$: attrs = token?.attrs ?? {};
	$: status = normalizeStatus(attrs.status, token?.open ?? false);
	$: label = attrs.title || 'Search';

	// One line per result. A line may be "Title — /path" or plain prose; the
	// href half is honoured only when it is a same-origin path (safeHref), so a
	// model cannot turn a search summary into an outbound link.
	$: rows = String(token?.text ?? '')
		.split('\n')
		.map((l) => l.replace(/^[-*+]\s+/, '').trim())
		.filter(Boolean)
		.map((line) => {
			const m = /^(.*?)\s+[—–|]\s+(\S+)$/.exec(line);
			return m ? { text: m[1], href: safeHref(m[2]) } : { text: line, href: null };
		});
</script>

<BlockShell {label} {status} copyText={String(token?.text ?? '')}>
	<div class="px-4 pb-3 flex flex-col gap-1">
		{#each rows as row}
			<div class="flex items-start gap-2 text-sm text-gray-600 dark:text-gray-300">
				<span class="text-green-500 mt-0.5 shrink-0">✓</span>
				{#if row.href}
					<a class="underline underline-offset-2 hover:no-underline" href={row.href}>{row.text}</a>
				{:else}
					<span>{row.text}</span>
				{/if}
			</div>
		{/each}
	</div>
</BlockShell>
