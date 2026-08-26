<script lang="ts">
	// The one way Harvis hands a file to the reader.
	//
	// Every lane produces files — a fenced block the model wrote, a file it saved into the
	// chat sandbox, a file a workspace run left behind — and until now each lane drew its own
	// thing: a full card here, a 11px monospace chip there, a bordered preview panel somewhere
	// else. Same object, three sizes, three shapes. This is that object, once.
	//
	// It is deliberately dumb: a glyph, a name, a type line, an optional trailing slot. Who
	// owns the bytes and what a click does are the caller's business.
	import Spinner from '$lib/components/common/Spinner.svelte';

	export let name = 'file';
	/** Overrides the type line derived from the extension. */
	export let sublabel = '';
	export let lang = '';
	export let busy = false;
	export let failed = false;
	export let title = '';
	export let onClick: (() => void) | null = null;

	$: base = (name || '').split('/').pop() || name || 'file';
	$: ext = ((base.match(/\.([A-Za-z0-9]+)$/) || [])[1] || lang || '').toLowerCase();

	// The glyph only separates the families a reader treats differently: something you run,
	// something you look at, something you read. The type line carries the rest.
	const KIND: Record<string, 'code' | 'image' | 'doc'> = {
		py: 'code', python: 'code', js: 'code', mjs: 'code', ts: 'code', tsx: 'code', jsx: 'code',
		sh: 'code', bash: 'code', shell: 'code', sql: 'code', rb: 'code', go: 'code', rs: 'code',
		c: 'code', cpp: 'code', java: 'code', html: 'code', css: 'code', json: 'code',
		yaml: 'code', yml: 'code', xml: 'code',
		svg: 'image', png: 'image', jpg: 'image', jpeg: 'image', gif: 'image', webp: 'image',
		pdf: 'doc'
	};
	$: kind = KIND[ext] ?? 'doc';

	const LANG_NAME: Record<string, string> = {
		py: 'Python', python: 'Python', js: 'JavaScript', mjs: 'JavaScript', ts: 'TypeScript',
		tsx: 'TypeScript', jsx: 'JavaScript', sh: 'Shell', bash: 'Shell', shell: 'Shell',
		sql: 'SQL', rb: 'Ruby', go: 'Go', rs: 'Rust', c: 'C', cpp: 'C++', java: 'Java',
		html: 'HTML', css: 'CSS', json: 'JSON', yaml: 'YAML', yml: 'YAML', xml: 'XML',
		svg: 'SVG', png: 'PNG', jpg: 'JPEG', jpeg: 'JPEG', gif: 'GIF', webp: 'WebP', pdf: 'PDF',
		md: 'Markdown', markdown: 'Markdown', txt: 'Text', text: 'Text', csv: 'CSV'
	};
	$: typeLabel =
		sublabel || (LANG_NAME[ext] ? `${LANG_NAME[ext]} file` : ext ? `${ext.toUpperCase()} file` : 'File');
</script>

<button
	type="button"
	title={title || name}
	class="w-full flex items-center gap-3 text-left rounded-2xl border px-3 py-2.5 transition {failed
		? 'border-red-300/70 dark:border-red-900/60'
		: 'border-gray-200 dark:border-white/10 hover:bg-gray-100 dark:hover:bg-white/5'}"
	on:click={() => onClick?.()}
>
	<span
		class="shrink-0 size-10 rounded-xl flex items-center justify-center bg-gray-100 dark:bg-white/5 text-gray-500 dark:text-gray-400"
	>
		{#if busy}
			<Spinner className="size-5" />
		{:else if kind === 'image'}
			<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.8" stroke="currentColor" aria-hidden="true" class="size-5">
				<path stroke-linecap="round" stroke-linejoin="round" d="m2.25 15.75 5.159-5.159a2.25 2.25 0 0 1 3.182 0l5.159 5.159m-1.5-1.5 1.409-1.409a2.25 2.25 0 0 1 3.182 0l2.909 2.909M18 6.75h.008v.008H18V6.75Zm2.25 12H3.75a1.5 1.5 0 0 1-1.5-1.5V6.75a1.5 1.5 0 0 1 1.5-1.5h16.5a1.5 1.5 0 0 1 1.5 1.5v10.5a1.5 1.5 0 0 1-1.5 1.5Z" />
			</svg>
		{:else if kind === 'code'}
			<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" aria-hidden="true" class="size-5">
				<path stroke-linecap="round" stroke-linejoin="round" d="m6.75 7.5-3.75 4.5 3.75 4.5m10.5-9 3.75 4.5-3.75 4.5M14.25 4.5l-4.5 15" />
			</svg>
		{:else}
			<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.8" stroke="currentColor" aria-hidden="true" class="size-5">
				<path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25M9 16.5v.75m3-3v3M15 12v5.25m-4.5-15H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
			</svg>
		{/if}
	</span>

	<span class="min-w-0 flex-1">
		<span class="block truncate font-medium text-sm text-gray-800 dark:text-gray-100">{base}</span>
		<span class="block text-xs text-gray-500 dark:text-gray-400">{typeLabel}</span>
	</span>

	<slot name="trailing" />
</button>
