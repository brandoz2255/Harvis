<script lang="ts">
	// What a workspace run hands back, in the same shape every other lane uses.
	//
	// The studio's RunArtifacts used to render here: a bordered preview panel with its own
	// chevron, a second bordered Changes panel expanded by default, and the file names as
	// 11px monospace chips that did nothing when clicked. Three type sizes, two nested
	// cards, and no way to actually open the file — while the Claude lane a few messages up
	// handed you a file pill that opened in the right-hand panel. Same run, same output,
	// two different products.
	//
	// So: pills, and the panel. The diff still exists, because a run that edits a repo has
	// something to say that a file list cannot, but it is collapsed — you ask for a diff,
	// you do not get shown one.
	import { getContext, onMount } from 'svelte';
	import {
		getRunArtifacts,
		getArtifact,
		artifactRawBlobUrl,
		type ArtifactMeta
	} from '$lib/apis/agent-runs';
	import { openInlineArtifact, sandboxLang } from '$lib/utils/sandbox';
	import FilePill from './FilePill.svelte';

	const i18n: any = getContext('i18n');

	export let wsId = '';
	/** Flips true when the run finishes — artifacts are written at completion. */
	export let done = false;
	/**
	 * Open the primary file in the right-hand panel when the run finishes. Only true for a
	 * run that completes while you are watching it: re-opening yesterday's chat must not
	 * yank the panel onto some old script.
	 */
	export let revealOnFinish = false;

	type Entry = { id: string; name: string; is_binary: boolean; category: string; content: string };

	let files: Entry[] = [];
	let diffs: { id: string; label: string; content: string }[] = [];
	let names: string[] = [];
	let loaded = false;
	let diffOpen = false;
	let opening = '';
	let failed: Record<string, boolean> = {};

	const hasContent = (c: string) => !!c && c.trim() && c.trim() !== '(no changes)';

	const load = async () => {
		if (!wsId) return;
		let artifacts: ArtifactMeta[] = [];
		try {
			artifacts = await getRunArtifacts(wsId);
		} catch (_) {
			return;
		}
		const fileMetas = artifacts.filter((a) => a.artifact_type === 'file');
		files = await Promise.all(
			fileMetas.map(async (a) => ({
				id: a.id,
				name: a.path || 'file',
				is_binary: !!a.is_binary,
				// The backend already classified this file. Guessing again from the
				// extension here would be a second, drifting copy of that table.
				category: a.category || '',
				content: a.is_binary ? '' : (await getArtifact(a.id))?.content || ''
			}))
		);
		const cf = artifacts.find((a) => a.artifact_type === 'changed_files');
		const cfText = cf ? (await getArtifact(cf.id))?.content || '' : '';
		names = cfText
			.split('\n')
			.map((s) => s.trim())
			.filter(Boolean);
		diffs = await Promise.all(
			artifacts
				.filter((a) => a.artifact_type === 'diff')
				.map(async (d) => ({
					id: d.id,
					label: d.path || $i18n.t('Changes'),
					content: (await getArtifact(d.id))?.content || ''
				}))
		);
		loaded = true;
	};

	onMount(load);

	let wasDone = false;
	$: if (wsId && done && !wasDone) {
		wasDone = true;
		load().then(() => {
			if (revealOnFinish && primary) open(primary);
		});
	}

	// Prefer the thing a person would actually want on screen: something you look at, then
	// something you read, then the biggest script.
	const ORDER = [
		'mp4',
		'webm',
		'html',
		'htm',
		'png',
		'jpg',
		'jpeg',
		'gif',
		'webp',
		'pdf',
		'svg',
		'md',
		'csv'
	];
	$: primary = (() => {
		const pool = files.filter((f) => f.is_binary || f.content?.trim());
		if (!pool.length) return null;
		for (const ext of ORDER) {
			const m = pool.filter((f) => f.name.toLowerCase().endsWith('.' + ext));
			if (m.length) return m.reduce((a, b) => ((b.content?.length || 0) > (a.content?.length || 0) ? b : a));
		}
		const txt = pool.filter((f) => !f.is_binary);
		return (txt.length ? txt : pool).reduce((a, b) =>
			(b.content?.length || 0) > (a.content?.length || 0) ? b : a
		);
	})();

	// Names the run reported changing but produced no artifact for — a repo edit rather than
	// a new file. They still belong in the list; they just cannot be opened.
	$: unbacked = names.filter((n) => !files.some((f) => f.name === n || f.name.endsWith('/' + n)));

	const panelType = (name: string) =>
		/\.svg$/i.test(name) ? 'svg' : /\.html?$/i.test(name) ? 'iframe' : 'code';

	const open = async (f: Entry) => {
		if (opening) return;
		opening = f.id;
		try {
			let content = f.content;
			let type = panelType(f.name);
			if (f.is_binary) {
				// The object URL is handed to the panel as-is. It used to be pasted into an
				// HTML document opened as an iframe, which sandboxes to an opaque origin —
				// and a blob URL belongs to the origin that made it, so the image never
				// loaded there.
				content = await artifactRawBlobUrl(f.id);
				// Every binary used to open as an image, so a generated clip rendered as a
				// broken picture. The panel has a player; hand video to it.
				type = f.category === 'video' ? 'video' : 'image';
			}
			openInlineArtifact({
				key: `run:${wsId}/${f.name}`,
				name: f.name.split('/').pop() || f.name,
				lang: sandboxLang(f.name),
				code: content,
				type
			});
			failed[f.id] = false;
		} catch (_) {
			failed[f.id] = true;
		} finally {
			failed = failed;
			opening = '';
		}
	};

	const diffStats = (content: string) => {
		let add = 0;
		let del = 0;
		for (const l of (content || '').split('\n')) {
			if (l.startsWith('+') && !l.startsWith('+++')) add++;
			else if (l.startsWith('-') && !l.startsWith('---')) del++;
		}
		return { add, del };
	};

	const lineClass = (l: string): string => {
		if (l.startsWith('+') && !l.startsWith('+++')) return 'text-green-600 dark:text-green-400';
		if (l.startsWith('-') && !l.startsWith('---')) return 'text-red-500';
		if (l.startsWith('@@')) return 'text-blue-500';
		return 'text-gray-600 dark:text-gray-300';
	};

	$: anyDiff = diffs.some((d) => hasContent(d.content));
	$: total = files.length + unbacked.length;
</script>

{#if loaded && total > 0}
	<div class="flex flex-col gap-1.5">
		<div class="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
			{total === 1 ? $i18n.t('Created file') : $i18n.t('Created files')}
		</div>
		<div class="flex flex-col gap-1.5 max-w-[26rem]">
			{#each files as f (f.id)}
				<FilePill
					name={f.name}
					title={failed[f.id] ? $i18n.t('Failed to load preview') : f.name}
					busy={opening === f.id}
					failed={failed[f.id]}
					onClick={() => open(f)}
				/>
			{/each}
			{#each unbacked as n (n)}
				<FilePill name={n} sublabel={$i18n.t('Edited in place')} onClick={null} />
			{/each}
		</div>
	</div>
{/if}

{#if loaded && anyDiff}
	<div>
		<button
			type="button"
			class="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-100 transition"
			on:click={() => (diffOpen = !diffOpen)}
		>
			<svg
				class="size-3.5 transition-transform {diffOpen ? 'rotate-90' : ''}"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2"
				stroke-linecap="round"
				stroke-linejoin="round"><path d="M9 18l6-6-6-6" /></svg
			>
			{diffs.length > 1
				? $i18n.t('{{count}} diffs', { count: diffs.length })
				: $i18n.t('View diff')}
		</button>
		{#if diffOpen}
			<div class="mt-1.5 space-y-2">
				{#each diffs.filter((d) => hasContent(d.content)) as d (d.id)}
					{@const st = diffStats(d.content)}
					<div>
						<div class="flex items-center gap-2 mb-1 text-xs">
							<span class="font-medium text-gray-600 dark:text-gray-300 truncate">{d.label}</span>
							<span class="font-mono shrink-0 whitespace-nowrap"
								><span class="text-green-600 dark:text-green-400">+{st.add}</span>
								<span class="text-red-500">−{st.del}</span></span
							>
						</div>
						<div
							class="text-xs leading-relaxed overflow-auto bg-gray-50 dark:bg-gray-850 rounded-lg p-2.5 max-h-80 font-mono"
						>
							{#each d.content.split('\n') as ln}
								<div class="whitespace-pre {lineClass(ln)}">{ln || ' '}</div>
							{/each}
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</div>
{/if}
