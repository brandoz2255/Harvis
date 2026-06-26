<script lang="ts">
	// Sources dock tab — aggregates every message's citations/sources across the whole
	// conversation into one deduped list (web-search results + attached-knowledge docs).
	// Same reduction as Messages/Citations.svelte, run over all assistant messages.
	import { getContext } from 'svelte';

	const i18n: any = getContext('i18n');

	export let history: any = null;

	const decodeStr = (s: string) => {
		try {
			return decodeURIComponent(s);
		} catch (_) {
			return s;
		}
	};

	$: messages = history?.messages ? Object.values(history.messages) : [];
	$: allSources = messages
		.filter((m: any) => m?.role === 'assistant')
		.flatMap((m: any) => m?.sources ?? m?.citations ?? []);

	$: citations = allSources.reduce((acc: any[], source: any) => {
		if (!source || Object.keys(source).length === 0) return acc;
		const docs = source?.document ?? [];
		if (docs.length === 0) {
			const sid = source?.source?.id ?? source?.source?.name ?? 'N/A';
			let _src = source?.source ?? { name: String(sid) };
			if (typeof sid === 'string' && /^https?:\/\//.test(sid)) _src = { ..._src, name: sid, url: sid };
			if (_src && !acc.find((i) => i.id === sid)) acc.push({ id: sid, source: _src, document: [] });
			return acc;
		}
		docs.forEach((document: string, index: number) => {
			const metadata = source?.metadata?.[index];
			const id = metadata?.source ?? source?.source?.id ?? 'N/A';
			let _source = source?.source ?? {};
			if (metadata?.name) _source = { ..._source, name: metadata.name };
			if (typeof id === 'string' && /^https?:\/\//.test(id)) _source = { ..._source, name: id, url: id };
			const existing = acc.find((i: any) => i.id === id);
			if (existing) existing.document.push(document);
			else acc.push({ id, source: _source, document: [document] });
		});
		return acc;
	}, []);

	const urlOf = (c: any): string =>
		c?.source?.url ?? (typeof c?.id === 'string' && /^https?:\/\//.test(c.id) ? c.id : '');
	const open = (c: any) => {
		const u = urlOf(c);
		if (u) window.open(u, '_blank', 'noopener,noreferrer');
	};
</script>

<div class="h-full flex flex-col min-h-0">
	<div class="flex items-center gap-2 px-3 py-2 shrink-0">
		<span class="text-sm font-medium text-gray-800 dark:text-gray-100">{$i18n.t('Sources')}</span>
		{#if citations.length}
			<span class="ml-auto text-[11px] text-gray-400">{citations.length}</span>
		{/if}
	</div>

	<div class="flex-1 min-h-0 overflow-y-auto px-3 pb-3">
		{#if !citations.length}
			<div class="text-xs text-gray-400 leading-relaxed py-8 px-2 text-center">
				{$i18n.t('No sources yet.')}
				<br />
				{$i18n.t('Sources from web search and attached knowledge will appear here.')}
			</div>
		{:else}
			<div class="flex flex-col gap-1.5">
				{#each citations as c, i (c.id)}
					{@const url = urlOf(c)}
					<button
						type="button"
						on:click={() => open(c)}
						class="group flex items-start gap-2.5 rounded-xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-2.5 text-left transition hover:bg-gray-100 dark:hover:bg-gray-850 {url
							? 'cursor-pointer'
							: 'cursor-default'}"
					>
						<div
							class="shrink-0 mt-0.5 size-5 flex items-center justify-center rounded-md bg-gray-100 dark:bg-gray-850 text-[11px] font-semibold text-gray-500 dark:text-gray-400"
						>
							{i + 1}
						</div>
						{#if url}
							<img
								src="https://www.google.com/s2/favicons?sz=32&domain={c.source.name}"
								alt=""
								class="shrink-0 mt-0.5 size-4 rounded"
								on:error={(e) => ((e.target as HTMLImageElement).src = '/favicon.png')}
							/>
						{/if}
						<div class="min-w-0 flex-1">
							<div class="text-xs font-medium text-gray-800 dark:text-gray-100 truncate">
								{decodeStr(c?.source?.name ?? c.id ?? 'Source')}
							</div>
							{#if url}
								<div class="text-[11px] text-gray-400 truncate">{url}</div>
							{/if}
							{#if c.document?.[0]}
								<div class="text-[11px] text-gray-500 dark:text-gray-400 line-clamp-2 mt-0.5 leading-snug">
									{c.document[0]}
								</div>
							{/if}
						</div>
					</button>
				{/each}
			</div>
		{/if}
	</div>
</div>
