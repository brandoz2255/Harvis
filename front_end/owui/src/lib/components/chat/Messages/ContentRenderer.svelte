<script>
	import { onDestroy, onMount, tick, getContext } from 'svelte';
	const i18n = getContext('i18n');

	import Markdown from './Markdown.svelte';
	import { SANDBOX_PATH_RE, openSandboxFile } from '$lib/utils/sandbox';
	import SandboxPreview from './SandboxPreview.svelte';
	import {
		artifactCode,
		artifactContents,
		chatId,
		mobile,
		settings,
		showArtifacts,
		showControls,
		showEmbeds
	} from '$lib/stores';
	import FloatingButtons from '../ContentRenderer/FloatingButtons.svelte';
	import { createMessagesList } from '$lib/utils';

	/**
	 * Extracts all top-level <details>...</details> blocks from content,
	 * handling nested <details> via depth tracking.
	 * Returns { detailsContent, plainContent }.
	 */
	const extractDetailsBlocks = (text) => {
		const blocks = [];
		let remaining = text;
		let result = '';
		const openTag = '<details';
		const closeTag = '</details>';

		while (true) {
			const start = remaining.indexOf(openTag);
			if (start === -1) {
				result += remaining;
				break;
			}

			result += remaining.slice(0, start);

			// Find matching closing tag with depth tracking
			let depth = 1;
			let idx = start + openTag.length;
			while (depth > 0 && idx < remaining.length) {
				if (remaining.startsWith(openTag, idx)) {
					depth++;
				} else if (remaining.startsWith(closeTag, idx)) {
					depth--;
				}
				if (depth > 0) idx++;
			}

			if (depth === 0) {
				const end = idx + closeTag.length;
				blocks.push(remaining.slice(start, end));
				remaining = remaining.slice(end);
			} else {
				// Unmatched opening tag, treat as plain text
				result += remaining.slice(start);
				remaining = '';
				break;
			}
		}

		return {
			detailsContent: blocks.join('\n'),
			plainContent: result.trim()
		};
	};

	export let id;
	export let content;

	export let history;
	export let messageId;

	export let selectedModels = [];

	export let done = true;
	export let model = null;
	export let sources = null;

	export let save = false;
	export let preview = false;
	export let floatingButtons = true;

	export let editCodeBlock = true;
	export let topPadding = false;

	export let onSave = (e) => {};
	export let onSourceClick = (e) => {};
	export let onTaskClick = (e) => {};
	export let onSetInputText = (text) => {};

	let contentContainerElement;
	let floatingButtonsElement;

	let sourceIds = [];
	$: getSourceIds(sources);

	const getSourceIds = (sources) => {
		const result = [];
		for (const source of sources ?? []) {
			for (let index = 0; index < (source.document ?? []).length; index++) {
				if (model?.info?.meta?.capabilities?.citations == false) {
					result.push('N/A');
					continue;
				}
				const metadata = source.metadata?.[index];
				const id = metadata?.source ?? 'N/A';
				if (metadata?.name) {
					result.push(metadata.name);
				} else if (id.startsWith('http://') || id.startsWith('https://')) {
					result.push(id);
				} else {
					result.push(source?.source?.name ?? id);
				}
			}
		}
		sourceIds = [...new Set(result)];
	};

	const updateButtonPosition = (event) => {
		const buttonsContainerElement = document.getElementById(`floating-buttons-${id}`);
		if (
			!contentContainerElement?.contains(event.target) &&
			!buttonsContainerElement?.contains(event.target)
		) {
			closeFloatingButtons();
			return;
		}

		setTimeout(async () => {
			await tick();

			if (!contentContainerElement?.contains(event.target)) return;

			let selection = window.getSelection();

			if (selection.toString().trim().length > 0) {
				const range = selection.getRangeAt(0);
				const rect = range.getBoundingClientRect();

				const parentRect = contentContainerElement.getBoundingClientRect();

				// Adjust based on parent rect
				const top = rect.bottom - parentRect.top;
				const left = rect.left - parentRect.left;

				if (buttonsContainerElement) {
					buttonsContainerElement.style.display = 'block';

					// Calculate space available on the right
					const spaceOnRight = parentRect.width - left;
					let halfScreenWidth = $mobile ? window.innerWidth / 2 : window.innerWidth / 3;

					if (spaceOnRight < halfScreenWidth) {
						const right = parentRect.right - rect.right;
						buttonsContainerElement.style.right = `${right}px`;
						buttonsContainerElement.style.left = 'auto'; // Reset left
					} else {
						// Enough space, position using 'left'
						buttonsContainerElement.style.left = `${left}px`;
						buttonsContainerElement.style.right = 'auto'; // Reset right
					}
					buttonsContainerElement.style.top = `${top + 5}px`; // +5 to add some spacing
				}
			} else {
				closeFloatingButtons();
			}
		}, 0);
	};

	const closeFloatingButtons = () => {
		const buttonsContainerElement = document.getElementById(`floating-buttons-${id}`);
		if (buttonsContainerElement) {
			buttonsContainerElement.style.display = 'none';
		}

		if (floatingButtonsElement) {
			// check if closeHandler is defined

			if (typeof floatingButtonsElement?.closeHandler === 'function') {
				// call the closeHandler function
				floatingButtonsElement?.closeHandler();
			}
		}
	};

	const keydownHandler = (e) => {
		if (e.key === 'Escape') {
			closeFloatingButtons();
		}
	};

	// Reactive listener attachment: re-attaches when floatingButtons
	// transitions from false → true (e.g. when message.done flips).
	let listenersAttached = false;

	function attachListeners() {
		if (!listenersAttached && contentContainerElement) {
			contentContainerElement.addEventListener('mouseup', updateButtonPosition);
			document.addEventListener('mouseup', updateButtonPosition);
			document.addEventListener('keydown', keydownHandler);
			listenersAttached = true;
		}
	}

	function detachListeners() {
		if (listenersAttached) {
			contentContainerElement?.removeEventListener('mouseup', updateButtonPosition);
			document.removeEventListener('mouseup', updateButtonPosition);
			document.removeEventListener('keydown', keydownHandler);
			listenersAttached = false;
		}
	}

	$: if (floatingButtons && contentContainerElement) {
		attachListeners();
	} else {
		detachListeners();
	}

	onDestroy(() => {
		detachListeners();
	});

	// Sandbox-file preview: paths the assistant wrote inside the Claude sandbox
	// (/tmp/harvis-chat/u<id>/…) become clickable → open a live preview fetched from the container.
	let sandboxPreviewPath = '';
	let showSandboxPreview = false;
	const SANDBOX_RE = SANDBOX_PATH_RE;

	const linkifySandboxPaths = (container) => {
		if (!container) return;
		if (!(container.textContent || '').includes('/harvis-chat/')) return; // fast path
		try {
			container.querySelectorAll('code:not([data-hp])').forEach((c) => {
				const t = (c.textContent || '').trim();
				SANDBOX_RE.lastIndex = 0;
				if (SANDBOX_RE.test(t)) {
					c.setAttribute('data-hp', '1');
					c.setAttribute('data-path', t);
					c.classList.add('harvis-sandbox-path');
				}
			});
			const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, null);
			const targets = [];
			let node;
			while ((node = walker.nextNode())) {
				if (node.parentElement?.closest('.harvis-sandbox-path, a, button, pre')) continue;
				SANDBOX_RE.lastIndex = 0;
				if (SANDBOX_RE.test(node.nodeValue || '')) targets.push(node);
			}
			targets.forEach((n) => {
				const s = n.nodeValue;
				const frag = document.createDocumentFragment();
				let last = 0;
				let m;
				SANDBOX_RE.lastIndex = 0;
				while ((m = SANDBOX_RE.exec(s))) {
					if (m.index > last) frag.appendChild(document.createTextNode(s.slice(last, m.index)));
					const b = document.createElement('button');
					b.className = 'harvis-sandbox-path';
					b.setAttribute('data-path', m[0]);
					b.textContent = m[0];
					frag.appendChild(b);
					last = m.index + m[0].length;
				}
				if (last < s.length) frag.appendChild(document.createTextNode(s.slice(last)));
				n.parentNode?.replaceChild(frag, n);
			});
		} catch (_) {
			/* linkify is best-effort */
		}
	};


	// Click a sandbox path → open its live preview in the RIGHT-SIDE Artifacts rail (same panel as
	// inline HTML previews). Falls back to the centered modal on mobile (no rail) or on error.
	const onSandboxClick = async (e) => {
		const t = e.target?.closest?.('.harvis-sandbox-path');
		const p = t?.getAttribute?.('data-path');
		if (!p) return;
		e.preventDefault();
		e.stopPropagation();
		if ($mobile) {
			sandboxPreviewPath = p;
			showSandboxPreview = true;
			return;
		}
		if (!(await openSandboxFile(p))) {
			sandboxPreviewPath = p;
			showSandboxPreview = true;
		}
	};

	// The codespan is rendered by a child (Markdown) component AFTER this component's own update,
	// so a plain afterUpdate misses it. A MutationObserver reliably re-linkifies on any DOM change.
	let sandboxObserver;
	onMount(() => {
		if (!contentContainerElement) return;
		let raf;
		const run = () => {
			cancelAnimationFrame(raf);
			raf = requestAnimationFrame(() => linkifySandboxPaths(contentContainerElement));
		};
		run();
		sandboxObserver = new MutationObserver(run);
		sandboxObserver.observe(contentContainerElement, {
			childList: true,
			subtree: true,
			characterData: true
		});
	});
	onDestroy(() => sandboxObserver?.disconnect());
</script>

<SandboxPreview bind:show={showSandboxPreview} path={sandboxPreviewPath} />

<!-- capture phase: intercept a path click BEFORE the codespan's copy-on-click handler -->
<div bind:this={contentContainerElement} on:click|capture={onSandboxClick}>
	{#if $settings?.renderMarkdownInAssistantMessages ?? true}
		<Markdown
			{id}
			content={model?.info?.meta?.capabilities?.citations == false
				? content.replace(/\s*(\[(?:\d+(?:#[^,\]\s]+)?(?:,\s*\d+(?:#[^,\]\s]+)?)*)\])+/g, '')
				: content}
			{model}
			{save}
			{preview}
			{done}
			{editCodeBlock}
			{topPadding}
			{sourceIds}
			{onSourceClick}
			{onTaskClick}
			{onSave}
			onUpdate={async (token) => {
				const { lang, text: code } = token;

				if (
					($settings?.detectArtifacts ?? true) &&
					(['html', 'svg'].includes(lang) || (lang === 'xml' && code.includes('svg'))) &&
					!$mobile &&
					$chatId
				) {
					await tick();
					showArtifacts.set(true);
					showControls.set(true);
				}
			}}
			onPreview={async (value) => {
				console.log('Preview', value);
				await artifactCode.set(value);
				await showControls.set(true);
				await showArtifacts.set(true);
				await showEmbeds.set(false);
			}}
		/>
	{:else}
		{@const extracted = extractDetailsBlocks(content)}

		{#if extracted.detailsContent}
			<!-- Render structural blocks (tool calls, reasoning, etc.) through Markdown -->
			<Markdown {id} content={extracted.detailsContent} {done} />
		{/if}
		{#if extracted.plainContent}
			<div class="whitespace-pre-wrap">{extracted.plainContent}</div>
		{/if}
	{/if}
</div>

{#if floatingButtons}
	<FloatingButtons
		bind:this={floatingButtonsElement}
		{id}
		actions={$settings?.floatingActionButtons ?? []}
		onSetInputText={(text) => {
			onSetInputText(text);
			closeFloatingButtons();
		}}
	/>
{/if}

<style>
	/* The chip's look lives in app.css, so the card and the prose share one definition.
	   These paths are injected as raw DOM nodes, so the rule has to be global either way. */
</style>
