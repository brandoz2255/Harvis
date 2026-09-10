<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { marked } from 'marked';
	import DOMPurify from 'dompurify';

	import { onMount, onDestroy, getContext, tick, createEventDispatcher } from 'svelte';
	import { blur, fade } from 'svelte/transition';

	const dispatch = createEventDispatcher();

	import { getChatList } from '$lib/apis/chats';
	import { updateFolderById } from '$lib/apis/folders';
	import HarvisMascot from '$lib/components/common/HarvisMascot.svelte';

	import {
		config,
		user,
		models as _models,
		temporaryChatEnabled,
		selectedFolder,
		chats,
		currentChatPage,
		showControls,
		workspaceControlsTab,
		workMode
	} from '$lib/stores';
	import { applyWorkMode, readStoredWorkMode, teammatesFrom } from '$lib/agents/workMode';
	import { sanitizeResponseContent, extractCurlyBraceWords } from '$lib/utils';
	import { WEBUI_API_BASE_URL, WEBUI_BASE_URL } from '$lib/constants';
	import { goto } from '$app/navigation';

	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import EyeSlash from '$lib/components/icons/EyeSlash.svelte';
	import MessageInput from './MessageInput.svelte';
	import FolderPlaceholder from './Placeholder/FolderPlaceholder.svelte';
	import FolderTitle from './Placeholder/FolderTitle.svelte';
	import TeammateTray from './Placeholder/TeammateTray.svelte';

	const i18n = getContext('i18n');

	export let createMessagePair: Function;
	export let stopResponse: Function;

	export let autoScroll = false;

	export let atSelectedModel: Model | undefined;
	export let selectedModels: [''];
	export let selectedEffort = 'auto'; // Phase F: reasoning effort for cloud reasoning models

	export let history;

	export let prompt = '';
	export let files = [];
	export let messageInput = null;

	export let selectedToolIds = [];
	export let selectedFilterIds = [];
	export let pendingOAuthTools = [];

	export let showCommands = false;

	export let imageGenerationEnabled = false;
	export let codeInterpreterEnabled = false;
	export let webSearchEnabled = false;

	export let onUpload: Function = (e) => {};
	export let onSelect = (e) => {};
	export let onChange = (e) => {};

	export let toolServers = [];

	export let dragged = false;

	// ── Bridged from the React prototype ──────────────────────────────────────
	// Quirky randomized greeting, wired to the real account name. Picked once per
	// mount (random each load); several lines use the first name when available.
	const _firstName = $user?.name ? $user.name.split(' ')[0] : '';
	const _greetings = [
		'How can I help today?',
		'How can Harvis help?',
		'Welcome, stranger.',
		'What should we make?',
		'Ready when you are.',
		"What's the move?",
		'Back to it?',
		'Welcome back.',
		...(_firstName
			? [
					`Hey ${_firstName}.`,
					`What are we building, ${_firstName}?`,
					`Good to see you, ${_firstName}.`,
					`Yes, ${_firstName}?`
				]
			: [])
	];
	const chatGreeting = _greetings[Math.floor(Math.random() * _greetings.length)];
	$: greeting = $workMode ? 'What should we work on?' : chatGreeting;

	// ── Chat | Work ───────────────────────────────────────────────────────────
	// Work hands the composer to a teammate: the model becomes `agent:<id>`, its
	// run gets the computer, and the screen docks on the right. Chat is the model
	// you had. The switch itself is `WorkModeToggle`, shared with the navbar so
	// the same choice can be made mid-conversation; this file keeps only what the
	// landing screen adds — restoring the remembered mode and the teammate tray.
	let mounted = false;
	let workBusy = false;
	let restoreWork = $workMode || readStoredWorkMode();

	$: teammates = teammatesFrom($_models);
	$: teammate = $workMode ? (teammates.find((m) => selectedModels.includes(m.id)) ?? null) : null;

	const setMode = async (work: boolean) => {
		if (workBusy) return;
		workBusy = true;
		try {
			selectedModels = await applyWorkMode(work, selectedModels, localStorage.token);
		} catch (e) {
			toast.error(`${$i18n.t('Could not start Work mode')}: ${(e as Error).message}`);
			workMode.set(false);
		} finally {
			workBusy = false;
		}
	};

	// Restore runs once the parent has settled its own default model, so the
	// teammate is not overwritten by the new-chat model selection a moment later.
	$: if (restoreWork && mounted && selectedModels.length && selectedModels[0] !== '') {
		restoreWork = false;
		setMode(true);
	}

	const pickTeammate = (id: string) => {
		selectedModels = [id];
	};
	const openComputer = () => {
		workspaceControlsTab.set('computer');
		showControls.set(true);
	};

	// ── Launcher tray + capability carousel ───────────────────────────────────
	// The tray under the composer is the teammate's card: who will do the work,
	// what it has (a computer, skills, memory), and what it always asks about.
	// Dismissible, local-state only — the send/socket path is untouched.
	let connectDismissed = false;
	const _capAttrs =
		'width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"';
	const capabilities = [
		{
			title: 'Create Skills',
			desc: 'Automate repeat work with custom Skills — drafted, reviewed, and saved.',
			icon: `<svg xmlns="http://www.w3.org/2000/svg" ${_capAttrs}><path d="M9.94 14.06A2 2 0 0 0 8.5 12.6l-5.9-1.5 5.9-1.53A2 2 0 0 0 9.94 8.1L11.47 2.2 13 8.1a2 2 0 0 0 1.44 1.44l5.9 1.53-5.9 1.5A2 2 0 0 0 13 15.94L11.47 21.8z"/></svg>`
		},
		{
			title: 'Engines & Connectors',
			desc: 'Wire up GitHub, Discord, ComfyUI, SSH and more — all local-first.',
			icon: `<svg xmlns="http://www.w3.org/2000/svg" ${_capAttrs}><path d="M12 22v-5M9 8V2M15 8V2M18 8v4a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8z"/></svg>`
		},
		{
			title: 'Run Local Models',
			desc: 'Run Ollama models on your own machine. No cloud required.',
			icon: `<svg xmlns="http://www.w3.org/2000/svg" ${_capAttrs}><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>`
		},
		{
			// Named for the job, not the surface. "Use Cookbook" + an open book read as a
			// recipe shelf of ready-made workflows, which is not what this is — it measures
			// your GPU and RAM with llmfit and ranks local models by what will actually run.
			// The surface's own name still appears in the sentence so it stays findable in
			// the sidebar, and the icon is the same cube Cookbook itself uses for a model.
			title: 'Fit Models to Your Hardware',
			desc: 'Cookbook ranks local models against your GPU and RAM, then pulls the ones that fit.',
			icon: `<svg xmlns="http://www.w3.org/2000/svg" ${_capAttrs}><path d="m12 2 9 5v10l-9 5-9-5V7z"/><path d="m3 7 9 5 9-5M12 12v10"/></svg>`
		},
		{
			title: 'Code with Harvis',
			desc: 'Build features, fix bugs, and open PRs from a single prompt.',
			icon: `<svg xmlns="http://www.w3.org/2000/svg" ${_capAttrs}><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>`
		}
	];
	let carousel = 0;
	let _carTimer: any;
	onMount(() => {
		mounted = true;
		const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
		if (!reduce)
			_carTimer = setInterval(() => {
				carousel = (carousel + 1) % capabilities.length;
			}, 4500);
	});
	onDestroy(() => clearInterval(_carTimer));
</script>

<div class="grid grid-rows-[auto_1fr_auto] w-full h-full min-h-full px-5 pt-3 pb-6 text-center">
	<!-- ROW 0: intentionally empty — the Chat | Work switch lives in the navbar
	     now, so it is reachable here and mid-conversation from one component. -->
	<div></div>
	<!-- ROW 1: hero + composer (+ attached connect tray), centered. -->
	<div class="launch-main flex flex-col items-center justify-center gap-[22px] w-full max-w-[780px] mx-auto">
		{#if $temporaryChatEnabled}
			<Tooltip
				content={$i18n.t("This chat won't appear in history and your messages will not be saved.")}
				className="w-full flex justify-center mb-0.5"
				placement="top"
			>
				<div class="flex items-center gap-2 text-gray-500 text-base my-2 w-fit">
					<EyeSlash strokeWidth="2.5" className="size-4" />{$i18n.t('Temporary Chat')}
				</div>
			</Tooltip>
		{/if}

		<div class="launch-hero flex flex-col items-center w-full font-primary">
			<HarvisMascot size={56} className="mb-3" interactive={true} />
			<div
				class="home-greeting text-3xl font-medium mb-1.5"
				style="background-image:linear-gradient(100deg,var(--color-blue-500) 0%,var(--color-blue-400) 48%,var(--color-blue-500) 100%);background-size:200% auto;-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;color:transparent;"
				in:fade={{ duration: 150 }}
			>
				{greeting}
			</div>
			{#if $selectedFolder}
				<FolderTitle
					folder={$selectedFolder}
					onUpdate={async (folder) => {
						await chats.set(await getChatList(localStorage.token, $currentChatPage));
						currentChatPage.set(1);
					}}
					onDelete={async () => {
						await chats.set(await getChatList(localStorage.token, $currentChatPage));
						currentChatPage.set(1);

						selectedFolder.set(null);
					}}
				/>
			{/if}
		</div>

		<!-- Launch composer: card on top (z-10), connect tray tucked under it (z-0). -->
		<div class="relative w-full max-w-[780px] {atSelectedModel ? 'mt-2' : ''}">
			<div class="relative z-10 w-full text-base font-normal">
				<MessageInput
					bind:this={messageInput}
					{history}
					bind:selectedModels
					bind:selectedEffort
					bind:files
					bind:prompt
					bind:autoScroll
					bind:selectedToolIds
					bind:selectedFilterIds
					bind:imageGenerationEnabled
					bind:codeInterpreterEnabled
					bind:webSearchEnabled
					bind:atSelectedModel
					bind:showCommands
					bind:dragged
					{pendingOAuthTools}
					{toolServers}
					{stopResponse}
					{createMessagePair}
					placeholder={$workMode
						? $i18n.t('Give {{name}} something to do…', { name: teammate?.name || 'your teammate' })
						: $i18n.t('Ask Harvis anything…')}
					{onChange}
					{onUpload}
					on:submit={(e) => {
						dispatch('submit', e.detail);
					}}
					on:research={(e) => dispatch('research', e.detail)}
				/>
			</div>

			{#if !connectDismissed}
				<TeammateTray
					workMode={$workMode}
					{workBusy}
					{teammate}
					{teammates}
					{selectedModels}
					on:pick={(e) => pickTeammate(e.detail)}
					on:computer={openComputer}
					on:work={() => setMode(true)}
					on:dismiss={() => (connectDismissed = true)}
				/>
			{/if}
		</div>

		{#if $selectedFolder}
			<div
				class="w-full px-4 md:max-w-3xl md:px-6 font-primary"
				in:fade={{ duration: 200, delay: 200 }}
			>
				<FolderPlaceholder folder={$selectedFolder} />
			</div>
		{/if}
	</div>

	<!-- ROW 2: capability carousel pinned to the bottom of the page. -->
	{#if !$selectedFolder}
		<div
			class="w-full max-w-[620px] mx-auto self-end font-primary"
			in:fade={{ duration: 200, delay: 300 }}
		>
			<div class="flex items-stretch gap-2">
				<button
					type="button"
					class="flex-none w-[34px] inline-flex items-center justify-center rounded-xl border border-gray-200 dark:border-gray-800 text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-850 transition"
					aria-label={$i18n.t('Previous')}
					on:click={() => (carousel = (carousel - 1 + capabilities.length) % capabilities.length)}
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						width="16"
						height="16"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"><path d="m15 18-6-6 6-6" /></svg
					>
				</button>
				<div
					class="flex-1 flex items-center gap-3.5 min-h-[88px] px-4 py-4 rounded-2xl border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900 text-left"
				>
					<span
						class="flex-none size-[38px] inline-flex items-center justify-center rounded-xl bg-blue-500/10 text-blue-600 dark:text-blue-400"
						>{@html capabilities[carousel].icon}</span
					>
					<div class="min-w-0">
						<div class="text-[0.9rem] font-semibold text-gray-900 dark:text-gray-50">
							{capabilities[carousel].title}
						</div>
						<div class="text-[0.8125rem] leading-relaxed text-gray-600 dark:text-gray-400">
							{capabilities[carousel].desc}
						</div>
					</div>
				</div>
				<button
					type="button"
					class="flex-none w-[34px] inline-flex items-center justify-center rounded-xl border border-gray-200 dark:border-gray-800 text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-850 transition"
					aria-label={$i18n.t('Next')}
					on:click={() => (carousel = (carousel + 1) % capabilities.length)}
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						width="16"
						height="16"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"><path d="m9 18 6-6-6-6" /></svg
					>
				</button>
			</div>
			<div class="mt-2.5 flex items-center justify-center gap-1.5">
				{#each capabilities as _, i}
					<button
						type="button"
						class="h-1.5 rounded-full transition-all {i === carousel
							? 'w-[18px] bg-blue-500'
							: 'w-1.5 bg-gray-300 dark:bg-gray-700'}"
						aria-label={`${$i18n.t('Capability')} ${i + 1}`}
						on:click={() => (carousel = i)}
					></button>
				{/each}
			</div>
		</div>
	{/if}
</div>

<style>
	/* The gradient + background-clip:text live INLINE on the element — a
	   `background-clip: text` in a CSS file gets stripped by the production
	   minifier. Here we only animate the sheen; keyframe + animation stay
	   together so Svelte's scoped-keyframe rename keeps matching. */
	.home-greeting {
		animation: home-sheen 7s ease-in-out 0.4s infinite;
	}

	/* Subtle theme-accent glow centered behind the hero (mascot + greeting). */
	.launch-hero {
		position: relative;
	}
	.launch-hero::before {
		content: '';
		position: absolute;
		top: 50%;
		left: 50%;
		width: 460px;
		max-width: 120%;
		height: 340px;
		transform: translate(-50%, -50%);
		background: radial-gradient(closest-side, color-mix(in oklab, var(--color-blue-500) 12%, transparent), transparent);
		pointer-events: none;
		z-index: 0;
	}
	.launch-hero > * {
		position: relative;
		z-index: 1;
	}

	@keyframes home-sheen {
		0% {
			background-position: 150% center;
		}
		100% {
			background-position: -50% center;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.home-greeting {
			animation: none;
			background-image: none !important;
			color: var(--color-blue-500) !important;
			-webkit-text-fill-color: var(--color-blue-500) !important;
		}
	}
</style>
