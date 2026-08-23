<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { onMount, getContext, createEventDispatcher } from 'svelte';
	import { get } from 'svelte/store';
	import { fade } from 'svelte/transition';
	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	import {
		artifactCode,
		chatId,
		config,
		settings,
		showArtifacts,
		showControls,
		artifactContents
	} from '$lib/stores';
	import { copyToClipboard, createMessagesList } from '$lib/utils';
	import { sandboxArtifactsLoading, sandboxSelectPath } from '$lib/utils/sandbox';
	import { injectCsp } from '$lib/utils/csp';

	import XMark from '../icons/XMark.svelte';
	import ArrowsPointingOut from '../icons/ArrowsPointingOut.svelte';
	import Tooltip from '../common/Tooltip.svelte';
	import CodeBlock from '$lib/components/chat/Messages/CodeBlock.svelte';
	import SvgPanZoom from '../common/SVGPanZoom.svelte';
	import ArrowLeft from '../icons/ArrowLeft.svelte';
	import Download from '../icons/Download.svelte';
	import CanvasRenderer from './Canvas/CanvasRenderer.svelte';

	export let overlay = false;

	let contents: Array<{ type: string; content: string; name?: string; lang?: string }> = [];
	let selectedContentIdx = 0;

	let copied = false;
	let pathCopied = false;
	let iframeElement: HTMLIFrameElement;

	// The header says what you are looking at. A sandbox file carries its own name; an
	// HTML or canvas artifact doesn't, so it gets a name that matches what Download hands
	// back rather than a blank space.
	const DEFAULT_NAMES: Record<string, string> = {
		iframe: 'preview.html',
		svg: 'image.svg',
		canvas: 'canvas.json'
	};
	$: selectedContent = contents[selectedContentIdx];
	$: artifactName = selectedContent
		? (selectedContent.name ?? DEFAULT_NAMES[selectedContent.type] ?? 'artifact.txt')
		: '';
	$: artifactPath = artifactName ? `Artifacts/${artifactName}` : '';

	const iframeLoadHandler = () => {
		iframeElement.contentWindow.addEventListener(
			'click',
			function (e) {
				const target = e.target.closest('a');
				if (target && target.href) {
					e.preventDefault();
					const url = new URL(target.href, iframeElement.baseURI);
					if (url.origin === window.location.origin) {
						iframeElement.contentWindow.history.pushState(
							null,
							'',
							url.pathname + url.search + url.hash
						);
					} else {
						console.info('External navigation blocked:', url.href);
					}
				}
			},
			true
		);

		// Cancel drag when hovering over iframe
		iframeElement.contentWindow.addEventListener('mouseenter', function (e) {
			e.preventDefault();
			iframeElement.contentWindow.addEventListener('dragstart', (event) => {
				event.preventDefault();
			});
		});
	};

	const showFullScreen = () => {
		if (iframeElement.requestFullscreen) {
			iframeElement.requestFullscreen();
		} else if (iframeElement.webkitRequestFullscreen) {
			iframeElement.webkitRequestFullscreen();
		} else if (iframeElement.msRequestFullscreen) {
			iframeElement.msRequestFullscreen();
		}
	};

	const downloadArtifact = () => {
		const type = contents[selectedContentIdx].type;
		// An image's or a video's `content` is already an object URL holding the real bytes.
		// Wrapping that string in a fresh Blob would save the URL as text, not the file.
		if (type === 'image' || type === 'video') {
			const a = document.createElement('a');
			a.href = contents[selectedContentIdx].content;
			a.download = artifactName || contents[selectedContentIdx].name || type;
			document.body.appendChild(a);
			a.click();
			document.body.removeChild(a);
			return;
		}
		const mime =
			type === 'canvas'
				? 'application/json'
				: type === 'svg'
					? 'image/svg+xml'
					: type === 'code'
						? 'text/plain'
						: 'text/html';
		const blob = new Blob([contents[selectedContentIdx].content], { type: mime });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		// A file that arrived with a name keeps it — `equations3.py` beats `artifact-3-0.html`.
		a.download = artifactName || `artifact-${$chatId}-${selectedContentIdx}.html`;
		document.body.appendChild(a);
		a.click();
		document.body.removeChild(a);
		URL.revokeObjectURL(url);
	};

	// A selection request can arrive before the artifact it names does — a sandbox file is
	// fetched asynchronously and merged into the list a tick later. So a request is held
	// until the list can satisfy it, instead of silently falling back to index 0.
	let wantedCode: string | null = null;
	let wantedPath: string | null = null;

	const applySelection = () => {
		if (!contents.length) return;
		if (wantedPath) {
			const idx = contents.findIndex((c: any) => c.path === wantedPath);
			if (idx !== -1) {
				selectedContentIdx = idx;
				wantedPath = null;
				wantedCode = null;
				return;
			}
		}
		if (wantedCode) {
			const idx = contents.findIndex((c) => c.content && c.content.includes(wantedCode as string));
			if (idx !== -1) {
				selectedContentIdx = idx;
				wantedCode = null;
			}
		}
	};

	onMount(() => {
		const unsubscribeArtifactCode = artifactCode.subscribe((value) => {
			wantedCode = value ? String(value) : null;
			applySelection();
		});

		const unsubscribeSelectPath = sandboxSelectPath.subscribe((value) => {
			if (!value) return;
			wantedPath = value;
			sandboxSelectPath.set(null);
			applySelection();
		});

		const unsubscribeArtifactContents = artifactContents.subscribe((value) => {
			const newContents = value ?? [];

			if (newContents.length === 0) {
				// Close only on a real transition to empty — switching to a chat with no
				// artifacts. Never on the first render, where contents is still [] because
				// this subscription is what fills it. And never while a sandbox file is in
				// flight; that is what the skeleton exists for.
				if (contents.length > 0 && !get(sandboxArtifactsLoading)) {
					showControls.set(false);
					showArtifacts.set(false);
				}
				selectedContentIdx = 0;
			} else if (newContents.length > contents.length) {
				selectedContentIdx = newContents.length - 1;
			}

			contents = newContents;
			if (selectedContentIdx > contents.length - 1) selectedContentIdx = contents.length - 1;
			applySelection();
		});

		return () => {
			unsubscribeArtifactCode();
			unsubscribeSelectPath();
			unsubscribeArtifactContents();
		};
	});
</script>

<div
	class=" w-full h-full relative flex flex-col bg-white dark:bg-gray-850"
	id="artifacts-container"
>
	<div class="w-full h-full flex flex-col flex-1 relative">
		{#if contents.length > 0}
			<!-- The header names the file, then offers the three things you can do with it:
			     copy, download, close. Version stepping used to live here; the user asked
			     for the filename instead. -->
			<div
				class="pointer-events-auto z-20 flex justify-between items-center gap-2 px-3 py-1 font-primary text-[11px] text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-[#1a1a1a] border-b border-gray-200/80 dark:border-white/10"
			>
				<Tooltip content={artifactPath} placement="bottom-start" className="min-w-0 flex-1">
					<button
						type="button"
						class="w-full text-left truncate font-mono tracking-wide hover:text-gray-800 dark:hover:text-gray-100 transition"
						on:click={() => {
							copyToClipboard(artifactPath);
							pathCopied = true;
							setTimeout(() => {
								pathCopied = false;
							}, 2000);
						}}
					>
						{pathCopied ? $i18n.t('Copied') : artifactPath}
					</button>
				</Tooltip>

				<div class="flex items-center gap-1 shrink-0">
					<button
						class="copy-code-button bg-none border-none transition rounded px-1.5 py-0.5 hover:text-gray-800 dark:hover:text-gray-100"
						on:click={() => {
							copyToClipboard(contents[selectedContentIdx].content);
							copied = true;

							setTimeout(() => {
								copied = false;
							}, 2000);
						}}>{copied ? $i18n.t('Copied') : $i18n.t('Copy')}</button
					>

					<Tooltip content={$i18n.t('Download')}>
						<button
							class=" bg-none border-none transition rounded p-1 hover:text-gray-800 dark:hover:text-gray-100"
							on:click={downloadArtifact}
						>
							<Download className="size-3.5" />
						</button>
					</Tooltip>

					{#if contents[selectedContentIdx].type === 'iframe'}
						<Tooltip content={$i18n.t('Open in full screen')}>
							<button
								class=" bg-none border-none transition rounded p-1 hover:text-gray-800 dark:hover:text-gray-100"
								on:click={showFullScreen}
							>
								<ArrowsPointingOut className="size-3.5" />
							</button>
						</Tooltip>
					{/if}

					<Tooltip content={$i18n.t('Close')}>
						<button
							class=" bg-none border-none transition rounded p-1 hover:text-gray-800 dark:hover:text-gray-100"
							on:click={() => {
								dispatch('close');
								showControls.set(false);
								showArtifacts.set(false);
							}}
						>
							<XMark className="size-3.5" />
						</button>
					</Tooltip>
				</div>
			</div>
		{/if}

		{#if overlay}
			<div class=" absolute top-0 left-0 right-0 bottom-0 z-10"></div>
		{/if}

		<div class="flex-1 w-full h-full">
			<div class=" h-full flex flex-col">
				{#if contents.length > 0}
					<!-- Keyed on the selection so switching files fades too. Without the key the
					     fade fires once, on first open, and every later artifact — the one a run
					     just finished writing — is swapped in on a single frame. -->
					{#key selectedContentIdx}
						<div class="max-w-full w-full h-full" in:fade={{ duration: 180 }}>
						{#if contents[selectedContentIdx].type === 'iframe'}
							<iframe
								bind:this={iframeElement}
								title="Content"
								srcdoc={injectCsp(
									contents[selectedContentIdx].content,
									$config?.ui?.iframe_csp ?? ''
								)}
								class="w-full border-0 h-full rounded-none"
								sandbox="allow-scripts allow-downloads{($settings?.iframeSandboxAllowForms ?? false)
									? ' allow-forms'
									: ''}{($settings?.iframeSandboxAllowSameOrigin ?? false)
									? ' allow-same-origin'
									: ''}"
								on:load={iframeLoadHandler}
							></iframe>
						{:else if contents[selectedContentIdx].type === 'image'}
							<!-- Rendered in THIS document, never in the sandboxed iframe below.
							     The src is an object URL owned by this origin, and the iframe runs
							     in an opaque one — it could not load the blob, so the picture came
							     up empty. An image needs no script sandbox anyway. -->
							<div class="w-full h-full overflow-auto flex items-center justify-center bg-white dark:bg-gray-900">
								<img
									src={contents[selectedContentIdx].content}
									alt={contents[selectedContentIdx].name ?? 'image'}
									decoding="async"
									class="max-w-full max-h-full object-contain"
								/>
							</div>
						{:else if contents[selectedContentIdx].type === 'video'}
							<!-- Same reasoning as the image above: the src is an object URL owned by
							     this origin, so it has to play in THIS document and not in the
							     opaque-origin sandbox iframe. `controls` because a clip nobody can
							     pause or scrub is barely a result. -->
							<div class="w-full h-full overflow-auto flex items-center justify-center bg-black">
								<!-- svelte-ignore a11y-media-has-caption -->
								<video
									src={contents[selectedContentIdx].content}
									controls
									loop
									playsinline
									class="max-w-full max-h-full object-contain"
								></video>
							</div>
						{:else if contents[selectedContentIdx].type === 'svg'}
							<SvgPanZoom
								className=" w-full h-full max-h-full overflow-hidden"
								svg={contents[selectedContentIdx].content}
							/>
						{:else if contents[selectedContentIdx].type === 'code'}
							<!-- A sandbox script, shown as a script: highlighted, in the app's own theme.
							     It used to be escaped into a white plaintext iframe, which read worse than
							     the chat bubble it came from. -->
							<div
								class="lms-artifact-code w-full h-full overflow-auto bg-gray-50 dark:bg-[#1e1e1e]"
							>
								<CodeBlock
									id={`artifact-code-${selectedContentIdx}`}
									lang={contents[selectedContentIdx].lang ?? ''}
									code={contents[selectedContentIdx].content}
									filename={contents[selectedContentIdx].name ?? ''}
									edit={false}
									run={false}
									save={false}
									preview={false}
									header={false}
									flush={true}
								/>
							</div>
						{:else if contents[selectedContentIdx].type === 'canvas'}
							<div class="w-full h-full overflow-y-auto">
								<CanvasRenderer spec={contents[selectedContentIdx].content} mode="panel" />
							</div>
							{/if}
						</div>
					{/key}
				{:else if $sandboxArtifactsLoading}
					<!-- The panel opens before the file has arrived. Showing its shape rather than
					     an empty box is the difference between "loading" and "broken". -->
					<div class="w-full h-full flex flex-col" aria-busy="true">
						<div
							class="flex items-center justify-between gap-2 px-3 py-1 bg-gray-50 dark:bg-[#1a1a1a] border-b border-gray-200/80 dark:border-white/10"
						>
							<div class="lms-skeleton h-3 w-40 rounded"></div>
							<div class="lms-skeleton h-3 w-16 rounded"></div>
						</div>
						<div class="flex-1 px-4 py-4 space-y-2.5 bg-gray-50 dark:bg-[#1e1e1e]">
							{#each ['70%', '46%', '88%', '34%', '62%', '78%', '52%', '40%', '84%', '58%'] as w}
								<div class="lms-skeleton h-3 rounded" style="width: {w}"></div>
							{/each}
						</div>
					</div>
				{:else}
					<div class="m-auto flex flex-col items-center gap-3 px-6 text-center">
						<div class="font-medium text-xs text-gray-500 dark:text-gray-400">
							{$i18n.t('Nothing to preview yet.')}
						</div>
						<button
							class="rounded-lg border border-gray-200 dark:border-gray-800 px-2.5 py-1 text-xs text-gray-600 dark:text-gray-300 transition hover:bg-gray-100 dark:hover:bg-white/5"
							on:click={() => {
								dispatch('close');
								showControls.set(false);
								showArtifacts.set(false);
							}}
						>
							{$i18n.t('Close')}
						</button>
					</div>
				{/if}
			</div>
		</div>
	</div>
</div>

<style>
	/* The code view breathes with the pane, not the window. A container query is the only
	   thing that can know how wide THIS panel is — the viewport is 2000px wide whether the
	   panel is a third of it or a sliver. Padding tops out just under half an inch (44px). */
	:global(.lms-artifact-code) {
		container-type: inline-size;
	}
	/* In the panel the code is being read, not scanned sideways. A long line wraps rather
	   than running off the edge, so squeezing the pane narrows the column instead of hiding
	   the end of every line behind a horizontal scrollbar. Chat code blocks are untouched —
	   this only applies inside the panel. */
	:global(.lms-artifact-code .lms-code-pre) {
		padding: 0.5rem 0.625rem;
		overflow-x: hidden;
	}
	:global(.lms-artifact-code .lms-code-pre code) {
		font-size: 11px;
		line-height: 1.5;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	@container (min-width: 340px) {
		:global(.lms-artifact-code .lms-code-pre) {
			padding: 0.625rem 0.75rem;
		}
		:global(.lms-artifact-code .lms-code-pre code) {
			font-size: 11.5px;
			line-height: 1.55;
		}
	}
	@container (min-width: 420px) {
		:global(.lms-artifact-code .lms-code-pre) {
			padding: 0.875rem 1.125rem;
		}
		:global(.lms-artifact-code .lms-code-pre code) {
			font-size: 12px;
			line-height: 1.6;
		}
	}
	@container (min-width: 620px) {
		:global(.lms-artifact-code .lms-code-pre) {
			padding: 1.125rem 1.75rem;
		}
		:global(.lms-artifact-code .lms-code-pre code) {
			font-size: 12.5px;
			line-height: 1.65;
		}
	}
	@container (min-width: 860px) {
		:global(.lms-artifact-code .lms-code-pre) {
			padding: 1.375rem 2.5rem;
		}
		:global(.lms-artifact-code .lms-code-pre code) {
			font-size: 13px;
			line-height: 1.7;
		}
	}
	@container (min-width: 1140px) {
		:global(.lms-artifact-code .lms-code-pre) {
			padding: 1.5rem 2.75rem;
		}
		:global(.lms-artifact-code .lms-code-pre code) {
			font-size: 13.5px;
			line-height: 1.75;
		}
	}

	.lms-skeleton {
		background: linear-gradient(
			90deg,
			rgba(0, 0, 0, 0.06) 25%,
			rgba(0, 0, 0, 0.11) 37%,
			rgba(0, 0, 0, 0.06) 63%
		);
		background-size: 400% 100%;
		animation: lms-skeleton-sheen 1.4s ease-in-out infinite;
	}
	:global(.dark) .lms-skeleton {
		background: linear-gradient(
			90deg,
			rgba(255, 255, 255, 0.06) 25%,
			rgba(255, 255, 255, 0.12) 37%,
			rgba(255, 255, 255, 0.06) 63%
		);
		background-size: 400% 100%;
	}
	@keyframes lms-skeleton-sheen {
		0% {
			background-position: 100% 50%;
		}
		100% {
			background-position: 0 50%;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.lms-skeleton {
			animation: none;
		}
	}
</style>
