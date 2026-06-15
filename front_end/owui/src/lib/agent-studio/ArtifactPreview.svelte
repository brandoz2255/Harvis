<script lang="ts">
	import Markdown from '$lib/components/chat/Messages/Markdown.svelte';

	// File-type router for an agent-produced artifact. v1 handles HTML (live
	// preview), Markdown (rendered), and everything else (code view). It renders
	// ONLY what the agent wrote — no React/Mermaid/PDF generation. Add new cases
	// (PDF / images / SVG) here as the artifact runtime grows.
	export let name = '';
	export let content = '';
	// `fill` makes the preview take its parent's full height (the Artifacts tab
	// renders it full-bleed); otherwise it's a fixed-height card body.
	export let fill = false;

	$: ext = (name.split('.').pop() || '').toLowerCase();
	$: kind = ext === 'html' || ext === 'htm' ? 'html' : ext === 'md' || ext === 'markdown' ? 'markdown' : 'code';
</script>

{#if kind === 'html'}
	<!--
		⚠ SECURITY: sandbox="allow-scripts" ONLY — NEVER add allow-same-origin.
		The HTML is model-generated and UNTRUSTED. Without allow-same-origin the
		iframe runs in a unique opaque origin: scripts execute (so the preview is
		live) but cannot reach the parent page, cookies, localStorage, or the
		user's session. Adding allow-same-origin alongside allow-scripts would let
		the model's code escape the sandbox — do not.
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
{:else}
	<pre
		class="text-[11px] leading-relaxed overflow-auto bg-gray-50 dark:bg-gray-850 rounded-lg p-2.5 {fill
			? 'h-full'
			: 'max-h-96'} font-mono whitespace-pre"><code>{content}</code></pre>
{/if}
