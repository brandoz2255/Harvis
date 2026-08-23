<script lang="ts">
	// A fenced block the model wrote, lifted out of the prose. It reads as a file you were
	// handed — a card with a glyph, a name and a type — because that is what it is. Clicking
	// it sends the code to the right-hand panel, which is where code is actually read; the
	// inline view stays available under the menu for editing and for watching a block stream.
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { copyToClipboard } from '$lib/utils';
	import { openInlineArtifact } from '$lib/utils/sandbox';
	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import EllipsisHorizontal from '$lib/components/icons/EllipsisHorizontal.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import CodeBlock from './CodeBlock.svelte';
	import FilePill from './FilePill.svelte';

	const i18n = getContext('i18n');

	export let id = '';
	export let lang = 'text';
	export let filename = 'artifact';
	export let code = '';
	export let streaming = false;
	export let done = true;
	export let save = false;
	export let preview = false;
	export let edit = false;
	export let onSave: (value: string) => void = () => {};

	let expanded = false;
	let menu = false;

	// Stable across re-renders, so re-opening the same block re-selects its panel entry
	// rather than stacking another copy of it.
	$: artifactKey = `chat-artifact:${id}/${filename}`;

	const openInPanel = () => {
		if (streaming) return;
		openInlineArtifact({ key: artifactKey, name: filename, lang, code });
	};

	const downloadFile = () => {
		menu = false;
		const blob = new Blob([code || ''], { type: 'text/plain;charset=utf-8' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = filename || 'artifact';
		a.click();
		URL.revokeObjectURL(url);
	};

	const copyFile = async () => {
		menu = false;
		const ok = await copyToClipboard(code || '');
		if (ok === false) toast.error($i18n.t('Failed to copy'));
		else toast.success($i18n.t('Copied'));
	};
</script>

<div class="w-full">
	<div class="flex items-center gap-1 max-w-md">
		<Tooltip
			content={streaming ? $i18n.t('Writing…') : $i18n.t('Open in panel')}
			placement="top"
			className="flex flex-1 min-w-0"
		>
			<FilePill
				name={filename}
				lang={lang}
				sublabel={streaming ? $i18n.t('Writing…') : ''}
				title={filename}
				onClick={openInPanel}
			>
				<span slot="trailing" class="contents">
					{#if streaming}
						<span class="shrink-0 inline-block w-1.5 h-4 bg-current animate-pulse"></span>
					{/if}
				</span>
			</FilePill>
		</Tooltip>

		<Dropdown bind:show={menu} align="start">
			<button
				type="button"
				class="p-1.5 rounded-lg text-gray-400 hover:text-gray-800 dark:hover:text-gray-100 hover:bg-black/5 dark:hover:bg-white/5"
				aria-label={$i18n.t('More')}
			>
				<EllipsisHorizontal className="size-4" />
			</button>
			<div slot="content">
				<div
					class="min-w-[150px] rounded-xl p-1 border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-850 dark:text-white shadow-lg text-sm"
				>
					<button
						type="button"
						class="w-full text-left px-3 py-1.5 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800"
						on:click={copyFile}
					>
						{$i18n.t('Copy')}
					</button>
					<button
						type="button"
						class="w-full text-left px-3 py-1.5 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800"
						on:click={downloadFile}
					>
						{$i18n.t('Download')}
					</button>
					<button
						type="button"
						class="w-full text-left px-3 py-1.5 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800"
						on:click={() => {
							menu = false;
							expanded = !expanded;
						}}
					>
						{expanded ? $i18n.t('Hide code') : $i18n.t('Show code here')}
					</button>
				</div>
			</div>
		</Dropdown>
	</div>

	<!-- Inline code stays reachable — it is where in-place editing lives, and it is the only
	     way to watch a block arrive while it is still streaming. -->
	{#if expanded || streaming}
		<div class="mt-1.5">
			<CodeBlock {id} {lang} {filename} {code} {done} {save} {preview} {edit} {onSave} />
		</div>
	{/if}
</div>
