<script lang="ts">
	import BlockShell from './BlockShell.svelte';
	import { normalizeStatus } from './registry';
	import MarkdownTokens from '../MarkdownTokens.svelte';

	export let token: any;
	export let id: string = '';
	export let tokenIdx: number = 0;
	export let done: boolean = true;
	export let editCodeBlock: boolean = true;
	export let sourceIds: string[] = [];
	export let onTaskClick: Function = () => {};
	export let onSourceClick: Function = () => {};

	$: attrs = token?.attrs ?? {};
	$: status = normalizeStatus(attrs.status, token?.open ?? false);
	$: label = attrs.title || 'Writing';
</script>

<BlockShell {label} {status} copyText={String(token?.text ?? '')}>
	<div class="px-4 pb-3 prose-sm" dir="auto">
		<MarkdownTokens
			id={`${id}-${tokenIdx}-wb`}
			tokens={token?.tokens ?? []}
			{done}
			{editCodeBlock}
			{sourceIds}
			{onTaskClick}
			{onSourceClick}
		/>
	</div>
</BlockShell>
