<script lang="ts">
	import { parseAnsiSegments } from '../../terminalText';
	import BlockShell from './BlockShell.svelte';
	import { normalizeStatus, unwrapCodeFence } from './registry';

	export let token: any;

	$: attrs = token?.attrs ?? {};
	$: status = normalizeStatus(attrs.status, token?.open ?? false);
	$: label = attrs.title || 'Terminal';
	// Model text only. parseAnsiSegments strips control characters and maps the
	// colour codes to a fixed class list, so nothing here can inject markup —
	// each segment is rendered as escaped text inside a span.
	$: body = unwrapCodeFence(String(token?.text ?? ''));
	$: lines = parseAnsiSegments(body);
</script>

<BlockShell {label} {status} dark copyText={body}>
	<div class="px-4 py-3 overflow-x-auto">
		<pre
			class="text-xs leading-relaxed font-mono text-gray-200 whitespace-pre">{#each lines as seg}<span
					class={seg.className}>{seg.text}</span
				>{/each}{#if status === 'running'}<span
					class="inline-block w-2 h-3.5 align-text-bottom bg-gray-300 animate-pulse"
				/>{/if}</pre>
	</div>
</BlockShell>
