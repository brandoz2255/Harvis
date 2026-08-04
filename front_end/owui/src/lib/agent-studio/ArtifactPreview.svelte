<script lang="ts">
	import Markdown from '$lib/components/chat/Messages/Markdown.svelte';
	import CadViewer from '$lib/components/chat/ChatControls/CadViewer.svelte';

	// File-type router for an agent-produced artifact. Renders ONLY what the agent wrote.
	//   html  → live sandboxed iframe        markdown → rendered
	//   svg   → safe data-URL <img>          csv      → table        json → pretty-printed
	//   image/pdf (binary) → served via `rawUrl` (Slice 2)          else → code view
	export let name = '';
	export let content = '';
	// `rawUrl` points at the backend raw-bytes route for BINARY artifacts (images/pdf/office) —
	// their bytes aren't in `content`. Text types (html/md/svg/csv/json/txt) render from `content`.
	export let rawUrl = '';
	// `fill` makes the preview take its parent's full height (the Artifacts tab renders it
	// full-bleed); otherwise it's a fixed-height card body.
	export let fill = false;

	$: ext = (name.split('.').pop() || '').toLowerCase();
	$: kind =
		ext === 'html' || ext === 'htm'
			? 'html'
			: ext === 'md' || ext === 'markdown'
				? 'markdown'
				: ext === 'svg'
					? 'svg'
					: ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'ico'].includes(ext)
						? 'image'
						: ext === 'pdf'
							? 'pdf'
							: ext === 'csv' || ext === 'tsv'
								? 'csv'
								: ext === 'json'
									? 'json'
									: ['stl', 'glb', 'gltf', '3mf', 'step', 'stp'].includes(ext)
										? 'mesh'
										: 'code';

	// SVG is model-generated → render via a data-URL <img> (img-loaded SVG never runs scripts).
	$: svgSrc = kind === 'svg' ? `data:image/svg+xml;charset=utf-8,${encodeURIComponent(content)}` : '';

	// Minimal CSV/TSV parse for a preview table (handles quoted fields + embedded commas).
	function parseCsv(text: string, sep: string): string[][] {
		const rows: string[][] = [];
		let row: string[] = [];
		let cur = '';
		let inQ = false;
		for (let i = 0; i < text.length; i++) {
			const c = text[i];
			if (inQ) {
				if (c === '"') {
					if (text[i + 1] === '"') { cur += '"'; i++; } else inQ = false;
				} else cur += c;
			} else if (c === '"') inQ = true;
			else if (c === sep) { row.push(cur); cur = ''; }
			else if (c === '\n') { row.push(cur); rows.push(row); row = []; cur = ''; }
			else if (c === '\r') { /* skip */ }
			else cur += c;
			if (rows.length > 500) break; // cap for preview
		}
		if (cur !== '' || row.length) { row.push(cur); rows.push(row); }
		return rows;
	}
	$: csvRows = kind === 'csv' ? parseCsv(content, ext === 'tsv' ? '\t' : ',') : [];

	// three 0.169 ships GLTF and STL loaders; there is no STEP loader at all, and the
	// 3MF one is not wired into CadViewer. Those two formats say so instead of
	// pretending to preview.
	$: meshFormat = (ext === 'stl' ? 'stl' : ext === 'glb' || ext === 'gltf' ? 'glb' : '') as
		| 'stl'
		| 'glb'
		| '';

	$: prettyJson = (() => {
		if (kind !== 'json') return '';
		try { return JSON.stringify(JSON.parse(content), null, 2); } catch { return content; }
	})();
</script>

{#if kind === 'html'}
	<!--
		⚠ SECURITY: sandbox="allow-scripts" ONLY — NEVER add allow-same-origin.
		The HTML is model-generated and UNTRUSTED. Without allow-same-origin the iframe runs in a
		unique opaque origin: scripts execute (so the preview is live) but cannot reach the parent
		page, cookies, localStorage, or the user's session. Adding allow-same-origin alongside
		allow-scripts would let the model's code escape the sandbox — do not.
	-->
	<iframe
		title={name || 'preview'}
		srcdoc={content}
		sandbox="allow-scripts"
		referrerpolicy="no-referrer"
		class="w-full {fill ? 'h-full' : 'h-80'} rounded-lg border border-gray-100 dark:border-gray-850 bg-white"
	></iframe>
{:else if kind === 'markdown'}
	<div
		class="text-sm rounded-lg border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-900 p-3 overflow-auto {fill
			? 'h-full'
			: 'max-h-96'}"
	>
		<Markdown id={`artifact-${name}`} {content} />
	</div>
{:else if kind === 'svg'}
	<div
		class="flex items-center justify-center rounded-lg border border-gray-100 dark:border-gray-850 bg-white p-2 overflow-auto {fill
			? 'h-full'
			: 'max-h-96'}"
	>
		<img src={svgSrc} alt={name || 'svg'} class="max-w-full max-h-full object-contain" />
	</div>
{:else if kind === 'image'}
	<div
		class="flex items-center justify-center rounded-lg border border-gray-100 dark:border-gray-850 bg-[#0b1220] p-2 overflow-auto {fill
			? 'h-full'
			: 'max-h-96'}"
	>
		{#if rawUrl}
			<img src={rawUrl} alt={name || 'image'} class="max-w-full max-h-full object-contain" />
		{:else}
			<div class="text-xs text-gray-400 p-4">Image preview unavailable.</div>
		{/if}
	</div>
{:else if kind === 'pdf'}
	{#if rawUrl}
		<iframe
			title={name || 'pdf'}
			src={rawUrl}
			class="w-full {fill ? 'h-full' : 'h-[28rem]'} rounded-lg border border-gray-100 dark:border-gray-850 bg-white"
		></iframe>
	{:else}
		<div class="text-xs text-gray-400 p-4 rounded-lg border border-gray-100 dark:border-gray-850">PDF preview unavailable — download to view.</div>
	{/if}
{:else if kind === 'csv'}
	<div
		class="overflow-auto rounded-lg border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-900 {fill
			? 'h-full'
			: 'max-h-96'}"
	>
		<table class="text-[11px] w-full border-collapse">
			<tbody>
				{#each csvRows as r, ri}
					<tr class={ri === 0 ? 'bg-gray-50 dark:bg-gray-850 font-semibold sticky top-0' : ''}>
						{#each r as cell}
							<td class="border border-gray-100 dark:border-white/10 px-2 py-1 whitespace-nowrap">{cell}</td>
						{/each}
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{:else if kind === 'mesh'}
	{#if rawUrl && meshFormat}
		<div class="rounded-lg border border-gray-100 dark:border-gray-850 overflow-hidden">
			<CadViewer url={rawUrl} format={meshFormat} height={fill ? 480 : 320} />
		</div>
	{:else if rawUrl}
		<div class="text-xs text-gray-400 p-4 rounded-lg border border-gray-100 dark:border-gray-850">
			{ext.toUpperCase()} has no in-browser viewer — download the file to open it in a CAD or slicing
			application.
		</div>
	{:else}
		<div class="text-xs text-gray-400 p-4 rounded-lg border border-gray-100 dark:border-gray-850">
			3D preview unavailable — the artifact bytes are not reachable.
		</div>
	{/if}
{:else if kind === 'json'}
	<pre
		class="text-[11px] leading-relaxed overflow-auto bg-gray-50 dark:bg-gray-850 rounded-lg p-2.5 {fill
			? 'h-full'
			: 'max-h-96'} font-mono whitespace-pre"><code>{prettyJson}</code></pre>
{:else}
	<pre
		class="text-[11px] leading-relaxed overflow-auto bg-gray-50 dark:bg-gray-850 rounded-lg p-2.5 {fill
			? 'h-full'
			: 'max-h-96'} font-mono whitespace-pre"><code>{content}</code></pre>
{/if}
