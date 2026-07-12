<script lang="ts">
	// Live preview of a file the assistant created in the Claude chat sandbox (inside the sidecar
	// container — never on the user's machine). Fetches the content via /api/owui/chat-file and
	// renders it: HTML/SVG in a sandboxed iframe, images inline, everything else as text.
	import { getContext } from 'svelte';
	import Modal from '$lib/components/common/Modal.svelte';

	const i18n = getContext('i18n');

	export let show = false;
	export let path = '';

	let loading = false;
	let error = '';
	let data: any = null;
	let loadedPath = '';

	$: if (show && path && path !== loadedPath) load(path);
	$: if (!show) loadedPath = ''; // reload next time it opens

	const load = async (p: string) => {
		loadedPath = p;
		loading = true;
		error = '';
		data = null;
		try {
			const res = await fetch(`/api/owui/chat-file?path=${encodeURIComponent(p)}`, {
				headers: { Authorization: `Bearer ${localStorage.token}` }
			});
			if (!res.ok) {
				const j = await res.json().catch(() => ({}));
				throw new Error(j?.detail || `HTTP ${res.status}`);
			}
			data = await res.json();
		} catch (e: any) {
			error = e?.message || 'Failed to load preview';
		} finally {
			loading = false;
		}
	};

	$: isHtml =
		data && (String(data.mime).includes('html') || String(data.mime).includes('svg') ||
			/\.(html?|svg)$/i.test(String(data.name || '')));
</script>

<Modal bind:show size="lg">
	<div class="flex flex-col h-[80vh] max-h-[80vh]">
		<div class="flex items-center justify-between px-4 py-2.5 border-b border-gray-100 dark:border-gray-800 shrink-0">
			<div class="text-sm font-medium truncate text-gray-800 dark:text-gray-100">
				{data?.name || $i18n.t('Preview')}
			</div>
			<button
				class="text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 shrink-0 ml-3"
				aria-label={$i18n.t('Close')}
				on:click={() => (show = false)}
			>
				<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5"><path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z"/></svg>
			</button>
		</div>

		<div class="flex-1 min-h-0 overflow-auto bg-white dark:bg-gray-900">
			{#if loading}
				<div class="p-6 text-sm text-gray-500">{$i18n.t('Loading preview…')}</div>
			{:else if error}
				<div class="p-6 text-sm text-red-500">{error}</div>
			{:else if data?.is_binary}
				<div class="p-4 flex items-center justify-center">
					<img src={data.data_url} alt={data.name} class="max-w-full h-auto rounded" />
				</div>
			{:else if isHtml}
				<iframe
					title={data?.name || 'preview'}
					srcdoc={data?.content}
					sandbox="allow-scripts allow-forms allow-popups"
					class="w-full h-full border-0 bg-white"
				></iframe>
			{:else if data}
				<pre class="p-4 text-xs whitespace-pre-wrap break-words text-gray-800 dark:text-gray-200">{data.content}</pre>
			{/if}
		</div>

		<div class="px-4 py-1.5 border-t border-gray-100 dark:border-gray-800 text-[11px] text-gray-400 truncate shrink-0">
			{data?.path || path} · {$i18n.t('rendered from the sandbox — not saved to your machine')}
		</div>
	</div>
</Modal>
