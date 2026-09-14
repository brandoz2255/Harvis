<script lang="ts">
	import Markdown from '$lib/components/chat/Messages/Markdown.svelte';
	import CadViewer from '$lib/cad/CadViewer.svelte';
	import { bundlePreview, type PreviewFile } from './previewBundle';

	// File-type router for an agent-produced artifact. Renders ONLY what the agent wrote.
	//   html  → live sandboxed iframe        markdown → rendered
	//   svg   → safe data-URL <img>          csv      → table        json → pretty-printed
	//   image/video/pdf (binary) → served via `rawUrl` (Slice 2)    else → code view
	export let name = '';
	export let content = '';
	// `rawUrl` points at the backend raw-bytes route for BINARY artifacts (images/pdf/office) —
	// their bytes aren't in `content`. Text types (html/md/svg/csv/json/txt) render from `content`.
	export let rawUrl = '';
	// `fill` makes the preview take its parent's full height (the Artifacts tab renders it
	// full-bleed); otherwise it's a fixed-height card body.
	export let fill = false;
	// The REST of the project. A page split across files (`<link href="styles.css">`,
	// `<script src="js/main.js">`) cannot load a single one of them from inside a srcdoc
	// iframe — see previewBundle.ts. These get folded into the document so a multi-file
	// build previews as the thing it actually is instead of a blank page with a title.
	export let files: PreviewFile[] = [];

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
						: ['mp4', 'm4v', 'webm', 'mov', 'mkv', 'ogv'].includes(ext)
						? 'video'
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

	// ── The preview reports why it is dead ──────────────────────────────────────
	// A generated page whose <script> never closes its IIFE parses to nothing: no
	// handler binds, and the START button only plays its CSS :active animation. The
	// page looked merely unresponsive and the turn had already said "Done." — nothing
	// anywhere told anyone it had failed. This reporter runs FIRST inside the frame and
	// posts what the browser threw back out, so the preview can say it.
	//
	// The frame stays sandbox="allow-scripts" with no allow-same-origin, so it is an
	// opaque origin and postMessage is the only channel it has. Messages are accepted
	// ONLY from this component's own contentWindow and only the two string fields below
	// are ever read — a page cannot use this to reach anything else in the parent.
	let frameEl: HTMLIFrameElement | null = null;
	let pageErrors: string[] = [];
	let errorsDismissed = false;

	const REPORTER = `<script>(function(){
	var sent=0;
	function post(m){ if(sent++>20||!m) return; try{ parent.postMessage({__harvisPreviewError:String(m).slice(0,300)},'*'); }catch(e){} }
	addEventListener('error',function(e){
		// Only genuine SCRIPT errors carry a message. A resource that failed to load
		// (an image, a font) also fires here in the capture phase with e.target set to
		// the element and no message — a working page raised one of those, and reporting
		// it would have flagged a page that runs perfectly well.
		if(!e.message) return;
		post(e.message + (e.lineno ? ' (line '+e.lineno+')' : ''));
	},true);
	addEventListener('unhandledrejection',function(e){
		post('Unhandled promise rejection: ' + ((e.reason && e.reason.message) || e.reason));
	});
	var ce=console.error;
	console.error=function(){ post(Array.prototype.join.call(arguments,' ')); try{ ce.apply(console,arguments); }catch(e){} };
}())<\/script>`;

	/** Put the reporter ahead of the page's own scripts, whatever shape the page is. */
	function withReporter(html: string): string {
		const head = html.match(/<head\b[^>]*>/i);
		if (head) return html.replace(head[0], head[0] + REPORTER);
		const htmlTag = html.match(/<html\b[^>]*>/i);
		if (htmlTag) return html.replace(htmlTag[0], htmlTag[0] + REPORTER);
		return REPORTER + html;
	}
	// Fold the siblings in first, THEN prepend the reporter — the reporter must stay the
	// document's first script, and inlining rewrites tags that come after it.
	$: bundled =
		kind === 'html'
			? bundlePreview(content, files, name || 'index.html')
			: { html: '', missing: [] as string[], inlined: [] as string[] };
	$: previewHtml = kind === 'html' ? withReporter(bundled.html) : '';
	$: missingRefs = kind === 'html' ? bundled.missing : [];
	// A new page starts with a clean slate — otherwise a fixed version still shows the
	// old error and reads as unfixed.
	$: if (previewHtml) {
		pageErrors = [];
		errorsDismissed = false;
	}

	function onPreviewMessage(e: MessageEvent) {
		if (!frameEl || e.source !== frameEl.contentWindow) return;
		const msg = (e.data || {}).__harvisPreviewError;
		if (typeof msg !== 'string' || !msg) return;
		if (pageErrors.includes(msg) || pageErrors.length >= 5) return;
		pageErrors = [...pageErrors, msg];
	}
</script>

<svelte:window on:message={onPreviewMessage} />

{#if kind === 'html'}
	<!--
		⚠ SECURITY: sandbox="allow-scripts" ONLY — NEVER add allow-same-origin.
		The HTML is model-generated and UNTRUSTED. Without allow-same-origin the iframe runs in a
		unique opaque origin: scripts execute (so the preview is live) but cannot reach the parent
		page, cookies, localStorage, or the user's session. Adding allow-same-origin alongside
		allow-scripts would let the model's code escape the sandbox — do not.
	-->
	<div class="relative w-full {fill ? 'h-full' : 'h-80'}">
		<iframe
			bind:this={frameEl}
			title={name || 'preview'}
			srcdoc={previewHtml}
			sandbox="allow-scripts"
			referrerpolicy="no-referrer"
			class="w-full h-full rounded-lg border border-gray-100 dark:border-gray-850 bg-white"
		></iframe>
		{#if missingRefs.length && !errorsDismissed}
			<!-- The page asks for files the run never wrote. Saying so beats a blank frame. -->
			<div
				class="absolute inset-x-1.5 top-1.5 rounded-lg border border-amber-300 dark:border-amber-500/40 bg-amber-50/95 dark:bg-amber-950/90 backdrop-blur px-2.5 py-1.5 text-[11px] text-amber-900 dark:text-amber-200 shadow-sm"
			>
				<div class="font-medium">
					{missingRefs.length === 1
						? 'This page references a file the preview could not load:'
						: `This page references ${missingRefs.length} files the preview could not load:`}
				</div>
				<div class="font-mono break-words opacity-90">{missingRefs.join('  ·  ')}</div>
			</div>
		{/if}
		{#if pageErrors.length && !errorsDismissed}
			<div
				class="absolute inset-x-1.5 bottom-1.5 rounded-lg border border-red-300 dark:border-red-500/40 bg-red-50/95 dark:bg-red-950/90 backdrop-blur px-2.5 py-1.5 text-[11px] text-red-800 dark:text-red-200 shadow-sm"
			>
				<div class="flex items-start gap-2">
					<div class="flex-1 min-w-0">
						<div class="font-medium">
							{pageErrors.length === 1
								? 'This page threw an error — that is why it does not respond.'
								: `This page threw ${pageErrors.length} errors — that is why it does not respond.`}
						</div>
						{#each pageErrors as err}
							<div class="font-mono break-words opacity-90">{err}</div>
						{/each}
					</div>
					<button
						type="button"
						aria-label="Dismiss"
						class="shrink-0 opacity-60 hover:opacity-100"
						on:click={() => (errorsDismissed = true)}>✕</button
					>
				</div>
			</div>
		{/if}
	</div>
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
		class="dark-surface flex items-center justify-center rounded-lg border border-gray-100 dark:border-gray-850 bg-[#0b1220] p-2 overflow-auto {fill
			? 'h-full'
			: 'max-h-96'}"
	>
		{#if rawUrl}
			<!-- The cap is in rem, not `max-h-full`: a percentage max-height resolves
			     against a parent that has a definite HEIGHT, and this parent only has a
			     max-height. `max-h-full` computed to none, so a 1024px render drew at
			     full size and the box scrolled instead of fitting it. -->
			<img
				src={rawUrl}
				alt={name || 'image'}
				decoding="async"
				class="max-w-full object-contain {fill ? 'max-h-full' : 'max-h-96'}"
			/>
		{:else}
			<div class="text-xs text-gray-400 p-4">Image preview unavailable.</div>
		{/if}
	</div>
{:else if kind === 'video'}
	<div
		class="flex items-center justify-center rounded-lg border border-gray-100 dark:border-gray-850 bg-black p-2 overflow-hidden {fill
			? 'h-full'
			: 'max-h-96'}"
	>
		{#if rawUrl}
			<!-- svelte-ignore a11y-media-has-caption -->
			<video
				src={rawUrl}
				controls
				loop
				playsinline
				class="max-w-full object-contain {fill ? 'max-h-full' : 'max-h-96'}"
			></video>
		{:else}
			<div class="text-xs text-gray-400 p-4">Video preview unavailable.</div>
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
