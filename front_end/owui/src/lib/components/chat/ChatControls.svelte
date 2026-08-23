<script context="module" lang="ts">
	let savedTab:
		| 'controls'
		| 'files'
		| 'overview'
		| 'activity'
		| 'sources'
		| 'view'
		| 'global-map'
		| 'brain'
		| 'run'
		| 'cad'
		| 'research'
		| 'cookbook' = 'overview';
</script>

<script lang="ts">
	import { SvelteFlowProvider } from '@xyflow/svelte';
	import { slide, fly } from 'svelte/transition';
	import { cubicOut } from 'svelte/easing';
	import { Pane, PaneResizer } from 'paneforge';
	import { v4 as uuidv4 } from 'uuid';

	import { onDestroy, onMount, tick, getContext } from 'svelte';
	import {
		config,
		terminalServers,
		mobile,
		showControls,
		workspaceControlsTab,
		dockedRunId,
		dockedResearchId,
		showCallOverlay,
		showArtifacts,
		showEmbeds,
		settings,
		showFileNavPath,
		selectedTerminalId,
		user
	} from '$lib/stores';

	import { uploadFile } from '$lib/apis/files';
	import { toast } from 'svelte-sonner';

	import Controls from './Controls/Controls.svelte';
	import OverviewPanel from './ChatControls/OverviewPanel.svelte';
	import ArtifactsPanel from './ChatControls/ArtifactsPanel.svelte';
	import SourcesPanel from './ChatControls/SourcesPanel.svelte';
	import CallOverlay from './MessageInput/CallOverlay.svelte';
	import Drawer from '../common/Drawer.svelte';
	import Artifacts from './Artifacts.svelte';
	import Embeds from './ChatControls/Embeds.svelte';
	import FileNav from './FileNav.svelte';
	import PyodideFileNav from './PyodideFileNav.svelte';
	import Overview from './Overview.svelte';
	import GlobalMap from '$lib/agent-studio/GlobalMap.svelte';
	import UnderConstruction from '$lib/components/common/UnderConstruction.svelte';
	import Brain from '$lib/agent-studio/Brain.svelte';
	import IncompletePanel from '$lib/agent-studio/IncompletePanel.svelte';
	import Cookbook from '$lib/agent-studio/Cookbook.svelte';
	import RunView from '$lib/agent-studio/RunView.svelte';
	import ResearchPanel from '$lib/agent-studio/ResearchPanel.svelte';
	import CadStudioPanel from '$lib/cad/CadStudioPanel.svelte';
	import CadTabLauncher from '$lib/cad/CadTabLauncher.svelte';
	import { getCadCapability } from '$lib/apis/cad';

	const i18n = getContext('i18n');

	export let history;
	export let models = [];

	export let chatId = null;

	export let chatFiles = [];
	export let params = {};

	export let eventTarget: EventTarget;
	export let submitPrompt: Function;
	export let stopResponse: Function;
	export let showMessage: Function;
	export let files;
	export let modelId;

	export let codeInterpreterEnabled = false;

	export let pane: Pane | null = null;

	let largeScreen = false;
	let dragged = false;
	let minSize = 0;
	// The narrowest the panel may be dragged, and how wide it opens on its own. The floor
	// used to be 460 because code lines did not reflow, so anything narrower cropped them.
	// They wrap now, so the panel can be squeezed down to a genuinely narrow column and
	// still show whole lines.
	const PANE_MIN_PX = 320;
	const PANE_DEFAULT_PCT = 46;
	let paneReady = false;

	// Tab state for Controls+Files panel
	let activeTab = savedTab;
	// svelte-ignore reactive_declaration_module_script_dependency
	$: {
		savedTab = activeTab;
	}

	$: hasMessages = history?.messages && Object.keys(history.messages).length > 0;

	$: showControlsTab = $user?.role === 'admin' || ($user?.permissions?.chat?.controls ?? true);
	$: showFilesTab =
		($selectedTerminalId &&
			(($terminalServers ?? []).some((t) => t.id && t.id === $selectedTerminalId) ||
				$user?.role === 'admin' ||
				($user?.permissions?.features?.direct_tool_servers ?? true))) ||
		(codeInterpreterEnabled && $config?.code?.interpreter_engine !== 'jupyter');
	$: showActivityTab = $user?.role === 'admin' || ($user?.permissions?.chat?.controls ?? true);
	// Harvis Agent Studio surfaces available in the right-rail dock (same gate as Activity).
	// Overview · Artifacts · Sources are one family: they either all belong to this user or
	// none do. They used to be gated three different ways, so Overview could be the active
	// tab on a chat where it was not offered.
	$: showStudioTabs = showActivityTab;
	$: showOverviewTab = showStudioTabs;
	// The dock is now Files · Overview · Artifacts · Sources · CAD. Map / Brain / Global-Map /
	// Controls / Run are no longer tabs — redirect any straggler (module-level savedTab or
	// the dock bridge) to Overview.
	$: if (
		activeTab === 'global-map' ||
		activeTab === 'brain' ||
		activeTab === 'view' ||
		activeTab === 'controls' ||
		activeTab === 'run'
	)
		activeTab = 'overview';

	// The tabs that actually have a button, in the order they are drawn. One list, read by
	// both the guard below and by nothing else — the buttons stay literal so they keep their
	// own labels and tooltips.
	$: visibleTabs = [
		...(showFilesTab ? ['files'] : []),
		...(showStudioTabs ? ['overview', 'activity', 'sources'] : []),
		...(showCadTab ? ['cad'] : [])
	];

	// Tabs opened by something other than a button (the in-chat research card docks one).
	// They have no button, so the guard must not bounce them.
	const BRIDGE_TABS = ['research'];

	// The one redirect. `savedTab` is module-level, so a tab chosen in a chat where it was
	// offered used to survive into a chat where it is not — landing the panel on a tab with
	// no button and, at the bottom of the router, an unrelated fallback panel.
	$: if (
		visibleTabs.length > 0 &&
		!visibleTabs.includes(activeTab) &&
		!BRIDGE_TABS.includes(activeTab)
	)
		activeTab = visibleTabs[0] as typeof activeTab;

	// CAD Studio. The tab appears only when the server says the lane is on — a
	// capability the operator switched off must not leave a tab that 404s on every
	// action. The plan also wanted a project attached before the tab shows; nothing
	// attaches one until Gate 6, and gating on that today would hide the only surface
	// that can create the first project, so the panel offers creation itself.
	//
	// The redirect waits for the probe: bouncing a restored 'cad' tab to Overview
	// before the answer arrives would look like the tab does not exist.
	//
	// Gate 6: the full workspace moved to `/harvis/cad`, and this tab is a launcher
	// pointing at it. Flip this to `false` to put the whole panel back in the rail —
	// the component is unchanged and still mounted below — which is the one-line
	// revert if the route turns out worse. Once the route is verified, delete the
	// 'cad' arm entirely rather than leaving a dead switch.
	const CAD_TAB_IS_LAUNCHER_ONLY = true;

	let showCadTab = false;
	let cadProbed = false;
	if (typeof window !== 'undefined') {
		getCadCapability()
			.then((c) => (showCadTab = !!c?.enabled))
			.catch(() => (showCadTab = false))
			.finally(() => (cadProbed = true));
	}
	$: if (cadProbed && !showCadTab && activeTab === 'cad') activeTab = 'overview';

	// The in-chat WorkspaceRunCard requests the Activity tab via this store.
	$: if ($workspaceControlsTab) {
		activeTab = $workspaceControlsTab as typeof activeTab;
		workspaceControlsTab.set(null);
	}

	// Auto-close only if there's genuinely nothing to show.
	$: if (!showOverviewTab && !showFilesTab && !showStudioTabs && !showCadTab) {
		showControls.set(false);
	}

	// Auto-switch to Files tab when display_file is triggered
	$: if ($showFileNavPath) {
		activeTab = 'files';
		showControls.set(true);
	}

	// Auto-open Files tab when a terminal is selected (suppress panel open when full-screen)
	$: if ($selectedTerminalId && showFilesTab) {
		activeTab = 'files';
		if (largeScreen) {
			showControls.set(true);
		}
	}

	// Clear selected direct terminal if user lost permission
	$: if (
		$selectedTerminalId &&
		!($terminalServers ?? []).some((t) => t.id && t.id === $selectedTerminalId) &&
		!($user?.role === 'admin' || ($user?.permissions?.features?.direct_tool_servers ?? true))
	) {
		selectedTerminalId.set(null);
	}

	// Attach a terminal file to the chat input
	const handleTerminalAttach = async (blob: Blob, name: string, contentType: string) => {
		const tempItemId = uuidv4();
		const fileItem = {
			type: 'file',
			file: '',
			id: null,
			url: '',
			name,
			collection_name: '',
			status: 'uploading',
			error: '',
			itemId: tempItemId,
			size: blob.size
		};

		files = [...files, fileItem];

		try {
			const file = new File([blob], name, { type: contentType || 'application/octet-stream' });
			const uploaded = await uploadFile(localStorage.token, file);
			if (!uploaded) throw new Error('Upload failed');

			const idx = files.findIndex((f) => f.itemId === tempItemId);
			if (idx !== -1) {
				files[idx] = {
					...fileItem,
					status: 'uploaded',
					file: uploaded,
					id: uploaded.id,
					url: `${uploaded.id}`,
					collection_name: uploaded?.meta?.collection_name
				};
				files = files;
			}
			toast.success($i18n.t('File attached to chat'));
		} catch (e) {
			files = files.filter((f) => f.itemId !== tempItemId);
			toast.error($i18n.t('Failed to attach file'));
		}
	};

	// The panel used to appear at full width in a single frame, which reads as a glitch
	// rather than as something opening. This slides it out instead. While it slides, the
	// onResize handler below stands down — otherwise its minimum-width clamp fights every
	// intermediate frame on the way up from zero, and its localStorage write runs 15 times.
	let paneAnimating = false;
	let paneAnimFrame: number | null = null;

	const animatePaneTo = (target: number) => {
		if (!pane) return;
		const start = pane.getSize();
		const reduced =
			typeof window !== 'undefined' &&
			window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;

		if (paneAnimFrame !== null) {
			cancelAnimationFrame(paneAnimFrame);
			paneAnimFrame = null;
		}
		if (reduced || Math.abs(target - start) < 0.75) {
			paneAnimating = false;
			pane.resize(target);
			return;
		}

		paneAnimating = true;
		const startedAt = performance.now();
		const duration = 260;
		// ease-out cubic: quick off the mark, settles rather than stops.
		const ease = (t: number) => 1 - Math.pow(1 - t, 3);

		// Opening from zero, the very first frame is a hair above zero — small enough that
		// paneforge would read it as still collapsed and slam the panel shut again.
		const floor = target > start ? Math.min(target, 3) : 0;

		const step = (now: number) => {
			const t = Math.min(1, (now - startedAt) / duration);
			pane?.resize(Math.max(floor, start + (target - start) * ease(t)));
			if (t < 1) {
				paneAnimFrame = requestAnimationFrame(step);
			} else {
				paneAnimFrame = null;
				paneAnimating = false;
			}
		};
		paneAnimFrame = requestAnimationFrame(step);
	};

	export const openPane = () => {
		if (!pane) return;
		const container = document.getElementById('chat-container');
		let saved = parseInt(localStorage?.chatControlsSize);
		// A width saved back when the floor was 350px reopens the panel too narrow to read
		// code in. Treat anything under the current floor as stale and fall through to the
		// default; the next drag saves a fresh value.
		if (saved && saved < PANE_MIN_PX) {
			delete localStorage.chatControlsSize;
			saved = NaN;
		}
		if (saved && container) {
			animatePaneTo(Math.floor((saved / container.clientWidth) * 100));
		} else {
			// The floor is the narrowest the panel may get, not a sensible width to read a
			// script at. Open at just under half the window so code arrives legible and the
			// handle sits where it can be dragged either way.
			animatePaneTo(Math.min(64, Math.max(minSize, PANE_DEFAULT_PCT)));
		}
	};

	const handleMediaQuery = async (e) => {
		if (e.matches) {
			largeScreen = true;
			if ($showCallOverlay) {
				showCallOverlay.set(false);
				await tick();
				showCallOverlay.set(true);
			}
		} else {
			largeScreen = false;
			if ($showCallOverlay) {
				showCallOverlay.set(false);
				await tick();
				showCallOverlay.set(true);
			}
			pane = null;
		}
	};

	const onMouseDown = () => {
		dragged = true;
	};
	const onMouseUp = () => {
		dragged = false;
	};

	onMount(() => {
		const mediaQuery = window.matchMedia('(min-width: 1024px)');
		mediaQuery.addEventListener('change', handleMediaQuery);
		handleMediaQuery(mediaQuery);

		let resizeObserver: ResizeObserver | null = null;
		let isDestroyed = false;

		// Wait for Svelte to render the Pane after largeScreen changed
		const init = async () => {
			await tick();

			if (isDestroyed) return;

			// If controls were persisted as open, set the pane to the saved size
			if ($showControls && pane) {
				openPane();
			}

			setTimeout(() => {
				paneReady = true;
			}, 0);

			const container = document.getElementById('chat-container') as HTMLElement;
			if (!container) return;

			minSize = Math.floor((PANE_MIN_PX / container.clientWidth) * 100);
			resizeObserver = new ResizeObserver((entries) => {
				for (let entry of entries) {
					const width = entry.contentRect.width;
					minSize = Math.floor((PANE_MIN_PX / width) * 100);
					if ($showControls) {
						if (pane && pane.isExpanded() && pane.getSize() < minSize) {
							pane.resize(minSize);
						} else {
							let size = Math.floor(
								(parseInt(localStorage?.chatControlsSize) / container.clientWidth) * 100
							);
							if (size < minSize && pane) pane.resize(minSize);
						}
					}
				}
			});
			resizeObserver.observe(container);
		};
		init();

		document.addEventListener('mousedown', onMouseDown);
		document.addEventListener('mouseup', onMouseUp);

		return () => {
			isDestroyed = true;
			paneReady = false;
			resizeObserver?.disconnect();
			if (!largeScreen) {
				showControls.set(false);
			}
			mediaQuery.removeEventListener('change', handleMediaQuery);
			document.removeEventListener('mousedown', onMouseDown);
			document.removeEventListener('mouseup', onMouseUp);
		};
	});

	const closeHandler = () => {
		if (!largeScreen) {
			showControls.set(false);
		}
		showArtifacts.set(false);
		showEmbeds.set(false);
		if ($showCallOverlay) showCallOverlay.set(false);
	};

	$: if (paneReady && !chatId) closeHandler();

	// The dock was only ever collapsed by a subscription over in Chat.svelte, and a Svelte
	// store skips its subscribers when the value hasn't actually changed — so `set(false)` on
	// an already-false store (starting a new chat while an artifact is open) collapsed
	// nothing and left an expanded, empty pane behind. Own the collapse here, where `pane`
	// lives, so the width always follows the flag no matter who set it or how.
	const collapsePane = () => {
		if (!pane) return;
		// An open animation still stepping would resize the pane straight back open.
		if (paneAnimFrame !== null) {
			cancelAnimationFrame(paneAnimFrame);
			paneAnimFrame = null;
		}
		paneAnimating = false;
		try {
			pane.collapse();
		} catch (e) {
			// paneforge throws if the group is mid-teardown; nothing left to close then.
		}
	};

	$: if (paneReady && !$showControls && pane?.isExpanded?.()) collapsePane();

	// Helper: is a "special" full-screen panel active?
	$: specialPanel = $showCallOverlay || $showArtifacts || $showEmbeds;
</script>

{#if !largeScreen}
	{#if $showControls}
		<Drawer
			show={$showControls}
			onClose={() => showControls.set(false)}
			className="min-h-[100dvh] !bg-white dark:!bg-gray-850"
		>
			<div class="h-[100dvh] flex flex-col">
				{#if $showCallOverlay}
					<div
						class="h-full max-h-[100dvh] bg-white text-gray-700 dark:bg-black dark:text-gray-300 flex justify-center"
					>
						<CallOverlay
							bind:files
							{submitPrompt}
							{stopResponse}
							{modelId}
							{chatId}
							{eventTarget}
							on:close={() => showControls.set(false)}
						/>
					</div>
				{:else if $showEmbeds}
					<Embeds />
				{:else if $showArtifacts}
					<Artifacts {history} />
				{:else}
					<!-- Controls + Files tabs -->
					<div class="flex flex-col h-full min-h-0">
						<!-- Tab bar -->
						<div class="flex items-center justify-between px-2 pt-2 pb-2 shrink-0">
							<div class="flex gap-1 min-w-0 overflow-x-auto scrollbar-hidden">
								{#if showFilesTab}
									<button
										class="px-2.5 py-1 text-sm rounded-lg transition whitespace-nowrap {activeTab ===
										'files'
											? 'bg-gray-100 dark:bg-gray-800 font-medium text-gray-900 dark:text-white'
											: 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'}"
										on:click={() => (activeTab = 'files')}
									>
										{$i18n.t('Files')}
									</button>
								{/if}
								{#if showStudioTabs}
									<button
										class="px-2.5 py-1 text-sm rounded-lg transition whitespace-nowrap {activeTab ===
										'overview'
											? 'bg-gray-100 dark:bg-gray-800 font-medium text-gray-900 dark:text-white'
											: 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'}"
										on:click={() => (activeTab = 'overview')}
									>
										{$i18n.t('Overview')}
									</button>
								{/if}
								{#if showActivityTab}
									<button
										class="px-2.5 py-1 text-sm rounded-lg transition whitespace-nowrap {activeTab ===
										'activity'
											? 'bg-gray-100 dark:bg-gray-800 font-medium text-gray-900 dark:text-white'
											: 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'}"
										on:click={() => (activeTab = 'activity')}
									>
										{$i18n.t('Artifacts')}
									</button>
								{/if}
								{#if showStudioTabs}
									<button
										class="px-2.5 py-1 text-sm rounded-lg transition whitespace-nowrap {activeTab ===
										'sources'
											? 'bg-gray-100 dark:bg-gray-800 font-medium text-gray-900 dark:text-white'
											: 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'}"
										on:click={() => (activeTab = 'sources')}
									>
										{$i18n.t('Sources')}
									</button>
								{/if}
								{#if showCadTab}
									<button
										class="px-2.5 py-1 text-sm rounded-lg transition whitespace-nowrap {activeTab ===
										'cad'
											? 'bg-gray-100 dark:bg-gray-800 font-medium text-gray-900 dark:text-white'
											: 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'}"
										on:click={() => (activeTab = 'cad')}
									>
										{$i18n.t('CAD')}
									</button>
								{/if}
							</div>
							<button
								class="p-1 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition text-gray-500 dark:text-gray-400"
								on:click={() => showControls.set(false)}
								aria-label={$i18n.t('Close')}
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="1.5"
									class="size-4"
								>
									<path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
								</svg>
							</button>
						</div>

						<div
							class="flex-1 min-h-0 {activeTab === 'view' || activeTab === 'cad'
								? 'h-full'
								: activeTab === 'overview'
									? 'overflow-y-auto px-3 pt-1'
									: ''}"
						>
							{#if activeTab === 'overview'}
								<OverviewPanel />
							{:else if activeTab === 'activity'}
								<ArtifactsPanel {history} />
							{:else if activeTab === 'sources'}
								<SourcesPanel {history} />
							{:else if activeTab === 'cad'}
								{#if CAD_TAB_IS_LAUNCHER_ONLY}
									<CadTabLauncher />
								{:else}
									<CadStudioPanel />
								{/if}
							{:else if activeTab === 'view'}
								<Overview
									{history}
									onNodeClick={(e) => {
										const node = e.node;
										showMessage(node.data.message, true);
									}}
									onClose={() => showControls.set(false)}
								/>
							{:else if activeTab === 'global-map'}
								<!-- Neural Map is flagged under construction in agent-studio/surfaces.ts;
								     mark the docked view too so it doesn't read as finished. -->
								<div class="px-3 pt-3"><UnderConstruction /></div>
								<GlobalMap mode="dock" />
							{:else if activeTab === 'brain'}
								<Brain mode="dock" />
							{:else if activeTab === 'research'}
								<ResearchPanel researchId={$dockedResearchId ?? ''} mode="dock" />
							{:else if activeTab === 'files' && $selectedTerminalId}
								<FileNav onAttach={handleTerminalAttach} {chatId} />
							{:else if activeTab === 'files' && codeInterpreterEnabled}
								<PyodideFileNav />
							{:else if activeTab === 'controls'}
								<Controls embed={true} {models} bind:chatFiles bind:params />
							{:else if activeTab === 'cookbook'}
								<Cookbook mode="dock" />
							{:else}
								<OverviewPanel />
							{/if}
						</div>
					</div>
				{/if}
			</div>
		</Drawer>
	{/if}
{:else}
	{#if $showControls}
		<PaneResizer
			class="relative w-2.5 shrink-0 flex items-center justify-center group cursor-col-resize border-l border-gray-100 dark:border-gray-850 hover:border-gray-200 dark:hover:border-gray-800 transition z-20"
			id="controls-resizer"
		>
			<div
				class="absolute -left-1.5 -right-1.5 -top-0 -bottom-0 z-20 cursor-col-resize bg-transparent"
			/>
			<!-- A drag handle nobody can see is a drag handle nobody uses. -->
			<div
				class="pointer-events-none h-8 w-[3px] rounded-full bg-gray-300/70 dark:bg-gray-700 opacity-0 group-hover:opacity-100 transition-opacity"
			/>
		</PaneResizer>
	{/if}

	<!-- The Pane element renders whether or not the dock is open, so a background painted
	     unconditionally turns any width the pane is left holding into a solid black bar in
	     dark mode. Its `class` below paints only when there is content inside to paint behind. -->
	<Pane
		bind:pane
		defaultSize={0}
		onResize={(size) => {
			if (paneAnimating) return;
			if ($showControls && pane.isExpanded()) {
				if (size < minSize) pane.resize(minSize);
				if (size < minSize) {
					localStorage.chatControlsSize = 0;
				} else {
					const container = document.getElementById('chat-container');
					localStorage.chatControlsSize = Math.floor((size / 100) * container.clientWidth);
				}
			}
		}}
		onCollapse={() => {
			if (paneAnimating) return;
			if (paneReady) showControls.set(false);
		}}
		collapsible={true}
		class="z-10 {$showControls ? 'bg-white dark:bg-gray-850' : ''}"
	>
		{#if $showControls}
			<div
				class="flex max-h-full min-h-full"
				in:fly|global={{ x: 28, duration: 300, easing: cubicOut, opacity: 0 }}
			>
				<div
					class="w-full {specialPanel && !$showCallOverlay
						? ' '
						: 'bg-white dark:shadow-lg dark:bg-gray-850'} z-40 pointer-events-auto {activeTab ===
					'files'
						? ''
						: 'overflow-y-auto'} scrollbar-hidden"
					id="controls-container"
				>
					{#if $showCallOverlay}
						<div class="w-full h-full flex justify-center">
							<CallOverlay
								bind:files
								{submitPrompt}
								{stopResponse}
								{modelId}
								{chatId}
								{eventTarget}
								on:close={() => showControls.set(false)}
							/>
						</div>
					{:else if $showEmbeds}
						<Embeds overlay={dragged} />
					{:else if $showArtifacts}
						<Artifacts {history} overlay={dragged} />
					{:else}
						<!-- Controls + Files tabs -->
						<div class="flex flex-col h-full min-h-0">
							<!-- Tab bar -->
							<div class="flex items-center justify-between px-2 pt-2 pb-2 shrink-0">
								<div class="flex gap-1 min-w-0 overflow-x-auto scrollbar-hidden">
									{#if showFilesTab}
										<button
											class="px-2.5 py-1 text-sm rounded-lg transition whitespace-nowrap {activeTab ===
											'files'
												? 'bg-gray-100 dark:bg-gray-800 font-medium text-gray-900 dark:text-white'
												: 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'}"
											on:click={() => (activeTab = 'files')}
										>
											{$i18n.t('Files')}
										</button>
									{/if}
									{#if showStudioTabs}
										<button
											class="px-2.5 py-1 text-sm rounded-lg transition whitespace-nowrap {activeTab ===
											'overview'
												? 'bg-gray-100 dark:bg-gray-800 font-medium text-gray-900 dark:text-white'
												: 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'}"
											on:click={() => (activeTab = 'overview')}
										>
											{$i18n.t('Overview')}
										</button>
									{/if}
									{#if showActivityTab}
										<button
											class="px-2.5 py-1 text-sm rounded-lg transition whitespace-nowrap {activeTab ===
											'activity'
												? 'bg-gray-100 dark:bg-gray-800 font-medium text-gray-900 dark:text-white'
												: 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'}"
											on:click={() => (activeTab = 'activity')}
										>
											{$i18n.t('Artifacts')}
										</button>
									{/if}
									{#if showStudioTabs}
										<button
											class="px-2.5 py-1 text-sm rounded-lg transition whitespace-nowrap {activeTab ===
											'sources'
												? 'bg-gray-100 dark:bg-gray-800 font-medium text-gray-900 dark:text-white'
												: 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'}"
											on:click={() => (activeTab = 'sources')}
										>
											{$i18n.t('Sources')}
										</button>
									{/if}
									{#if showCadTab}
										<button
											class="px-2.5 py-1 text-sm rounded-lg transition whitespace-nowrap {activeTab ===
											'cad'
												? 'bg-gray-100 dark:bg-gray-800 font-medium text-gray-900 dark:text-white'
												: 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'}"
											on:click={() => (activeTab = 'cad')}
										>
											{$i18n.t('CAD')}
										</button>
									{/if}
								</div>
								<button
									class="p-1 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition text-gray-500 dark:text-gray-400"
									on:click={() => showControls.set(false)}
									aria-label={$i18n.t('Close')}
								>
									<svg
										xmlns="http://www.w3.org/2000/svg"
										viewBox="0 0 24 24"
										fill="none"
										stroke="currentColor"
										stroke-width="1.5"
										class="size-4"
									>
										<path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
									</svg>
								</button>
							</div>

							<div
								class="flex-1 min-h-0 {activeTab === 'view' || activeTab === 'cad'
									? 'h-full'
									: activeTab === 'overview'
										? 'overflow-y-auto px-3 pt-1'
										: ''}"
							>
								{#if activeTab === 'overview'}
									<OverviewPanel />
								{:else if activeTab === 'activity'}
									<ArtifactsPanel {history} />
								{:else if activeTab === 'sources'}
									<SourcesPanel {history} />
								{:else if activeTab === 'cad'}
									{#if CAD_TAB_IS_LAUNCHER_ONLY}
										<CadTabLauncher />
									{:else}
										<CadStudioPanel />
									{/if}
								{:else if activeTab === 'view'}
									<Overview
										{history}
										onNodeClick={(e) => {
											const node = e.node;
											if (node?.data?.message?.favorite) {
												history.messages[node.data.message.id].favorite = true;
											} else {
												history.messages[node.data.message.id].favorite = null;
											}
											showMessage(node.data.message, true);
										}}
										onClose={() => showControls.set(false)}
									/>
								{:else if activeTab === 'global-map'}
									<div class="px-3 pt-3"><UnderConstruction /></div>
									<GlobalMap mode="dock" />
								{:else if activeTab === 'brain'}
									<Brain mode="dock" />
								{:else if activeTab === 'research'}
									<ResearchPanel researchId={$dockedResearchId ?? ''} mode="dock" />
								{:else if activeTab === 'files' && $selectedTerminalId}
									<FileNav onAttach={handleTerminalAttach} overlay={dragged} {chatId} />
								{:else if activeTab === 'files' && codeInterpreterEnabled}
									<PyodideFileNav overlay={dragged} />
								{:else if activeTab === 'controls'}
									<Controls embed={true} {models} bind:chatFiles bind:params />
								{:else if activeTab === 'cookbook'}
									<Cookbook mode="dock" />
								{:else}
									<OverviewPanel />
								{/if}
							</div>
						</div>
					{/if}
				</div>
			</div>
		{/if}
	</Pane>
{/if}
