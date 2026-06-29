<script lang="ts">
	import { getContext } from 'svelte';
	import { downloadArtifactFile } from '$lib/apis/agent-runs';

	const i18n: any = getContext('i18n');

	// Actions on a loaded artifact (name + content already fetched for the preview).
	export let name = '';
	export let content = '';
	// For BINARY artifacts (image/pdf/office) the bytes aren't in `content` — pass the artifact id
	// so Download fetches them from /download. Copy is disabled for binary (nothing text to copy).
	export let artifactId = '';
	export let isBinary = false;

	const mimeFor = (n: string): string => {
		const ext = (n.split('.').pop() || '').toLowerCase();
		if (ext === 'html' || ext === 'htm') return 'text/html';
		if (ext === 'md' || ext === 'markdown') return 'text/markdown';
		if (ext === 'json') return 'application/json';
		if (ext === 'css') return 'text/css';
		if (ext === 'js' || ext === 'mjs') return 'text/javascript';
		if (ext === 'svg') return 'image/svg+xml';
		if (ext === 'xml') return 'application/xml';
		return 'text/plain';
	};

	// Save the file to disk. Safe for untrusted model HTML: a downloaded .html runs
	// from a file:// origin if the user later opens it — never Harvis's origin.
	// (We deliberately do NOT "open in a new tab" via a blob: URL — that would
	// inherit Harvis's origin and let the model's scripts escape the iframe sandbox.)
	const download = async () => {
		// Binary: fetch the real bytes from /download (content is empty for binary artifacts).
		if (isBinary && artifactId) {
			try {
				await downloadArtifactFile(artifactId, name || 'artifact');
			} catch (_) {
				/* best-effort */
			}
			return;
		}
		if (!content) return;
		const blob = new Blob([content], { type: mimeFor(name) });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = name || 'artifact.txt';
		document.body.appendChild(a);
		a.click();
		a.remove();
		setTimeout(() => URL.revokeObjectURL(url), 1000);
	};

	let copied = false;
	const copy = async () => {
		try {
			await navigator.clipboard.writeText(content || '');
			copied = true;
			setTimeout(() => (copied = false), 1500);
		} catch (_) {
			/* clipboard unavailable — no-op */
		}
	};

	const btn =
		'text-[11px] px-2 py-1 rounded-lg border border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:border-gray-300 dark:hover:border-gray-600 transition shrink-0';
</script>

<div class="flex items-center gap-1.5">
	<button type="button" class={btn} on:click={copy} disabled={!content}>
		{copied ? $i18n.t('Copied') : $i18n.t('Copy')}
	</button>
	<button type="button" class={btn} on:click={download} disabled={!content && !(isBinary && artifactId)}>
		{$i18n.t('Download')}
	</button>
</div>
