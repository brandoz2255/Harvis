<script lang="ts">
	// Files a run created in the chat sandbox, surfaced as things the user can act on.
	// A path in the prose is not a deliverable — the sandbox lives in a container, so there
	// is no path the user can open.
	//
	// Each file is a card, not a row: it reads as a file you were handed, with a glyph, a
	// name and a type. One click sends it to the right-hand panel, which is where a file is
	// actually read. The full-width treatment stays for content that genuinely needs the
	// width — diagrams, prose, tool output.
	import { decode } from 'html-entities';
	import { getContext } from 'svelte';

	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import FilePill from './FilePill.svelte';
	import { isNoiseSandboxPath, openSandboxFile } from '$lib/utils/sandbox';

	const i18n = getContext('i18n');

	export let id = '';
	export let attributes: { paths?: string } = {};

	$: paths = (() => {
		try {
			const raw = decode(attributes?.paths ?? '');
			const parsed = JSON.parse(raw);
			// Harvis's own seed docs are not the run's output. The backend filters these too;
			// this second fence covers cards written before that filter existed.
			return Array.isArray(parsed)
				? parsed.filter((p) => typeof p === 'string' && !isNoiseSandboxPath(p))
				: [];
		} catch (_) {
			return [];
		}
	})();

	const basename = (p: string) => p.split('/').pop() || p;

	let opening: string | null = null;
	let failed: Record<string, boolean> = {};

	const open = async (p: string) => {
		if (opening) return;
		opening = p;
		try {
			const ok = await openSandboxFile(p);
			failed[p] = !ok;
			failed = failed;
		} finally {
			opening = null;
		}
	};
</script>

{#if paths.length > 0}
	<div {id} class="my-2 flex flex-col gap-1.5">
		<div class="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
			{paths.length === 1 ? $i18n.t('Created file') : $i18n.t('Created files')}
		</div>

		<!-- Matches the width of an in-message artifact card, which gives up 2rem of its
		     max-w-md to the ⋯ menu sitting beside it. -->
		<div class="flex flex-col gap-1.5 max-w-[26rem]">
			{#each paths as p (p)}
				<Tooltip
					content={failed[p] ? $i18n.t('Failed to load preview') : p}
					placement="top"
					className="flex w-full"
				>
					<FilePill
						name={basename(p)}
						title={p}
						busy={opening === p}
						failed={failed[p]}
						onClick={() => open(p)}
					/>
				</Tooltip>
			{/each}
		</div>
	</div>
{/if}
