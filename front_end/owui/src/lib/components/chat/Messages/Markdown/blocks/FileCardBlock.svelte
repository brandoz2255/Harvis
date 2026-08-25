<script lang="ts">
	import { getContext } from 'svelte';
	import BlockShell from './BlockShell.svelte';
	import { normalizeStatus, safeHref } from './registry';
	import Document from '$lib/components/icons/Document.svelte';

	const i18n = getContext('i18n');

	export let token: any;

	$: attrs = token?.attrs ?? {};
	$: status = normalizeStatus(attrs.status, token?.open ?? false);
	// The fence body is a description, not the file — the name always comes
	// from the attribute so a long body can never masquerade as a filename.
	$: name = attrs.name || attrs.path || 'File';
	$: size = attrs.size || '';
	$: href = safeHref(attrs.href);
	$: note = String(token?.text ?? '').trim();
</script>

<BlockShell label={$i18n.t('File')} {status} copyText={name}>
	<div class="px-4 pb-3 flex items-center gap-3">
		<Document className="size-5 shrink-0 text-gray-400" strokeWidth="1.5" />

		<div class="min-w-0 flex-1">
			<div class="text-sm font-medium truncate text-gray-800 dark:text-gray-100">{name}</div>
			{#if size || note}
				<div class="text-xs text-gray-500 dark:text-gray-400 truncate">
					{[size, note].filter(Boolean).join(' · ')}
				</div>
			{/if}
		</div>

		{#if href}
			<div class="flex gap-1 shrink-0">
				<a
					class="text-xs px-2.5 py-1 rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-black/5 dark:hover:bg-white/5 transition"
					href={href}
				>
					{$i18n.t('Open')}
				</a>
				<a
					class="text-xs px-2.5 py-1 rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-black/5 dark:hover:bg-white/5 transition"
					href={href}
					download={name}
				>
					{$i18n.t('Download')}
				</a>
			</div>
		{/if}
	</div>
</BlockShell>
