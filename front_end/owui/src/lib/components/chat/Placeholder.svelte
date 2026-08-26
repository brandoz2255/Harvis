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
		currentChatPage
	} from '$lib/stores';
	import { sanitizeResponseContent, extractCurlyBraceWords } from '$lib/utils';
	import { WEBUI_API_BASE_URL, WEBUI_BASE_URL } from '$lib/constants';
	import { goto } from '$app/navigation';

	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import EyeSlash from '$lib/components/icons/EyeSlash.svelte';
	import MessageInput from './MessageInput.svelte';
	import FolderPlaceholder from './Placeholder/FolderPlaceholder.svelte';
	import FolderTitle from './Placeholder/FolderTitle.svelte';

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
	const greeting = _greetings[Math.floor(Math.random() * _greetings.length)];

	// ── Prototype launcher: connect-tools shadow tray + capability carousel ──
	// Additive, dismissible, local-state only — the send/socket path is untouched.
	let connectDismissed = false;
	const connectBrands = [
		{
			name: 'GitHub',
			svg: `<path fill="currentColor" d="M12 .5C5.73.5.5 5.73.5 12c0 5.08 3.29 9.39 7.86 10.91.58.11.79-.25.79-.56 0-.28-.01-1.02-.02-2-3.2.7-3.88-1.54-3.88-1.54-.52-1.33-1.28-1.68-1.28-1.68-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.68 0-1.25.45-2.28 1.19-3.08-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.18 1.18a11 11 0 0 1 5.8 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.8 1.19 1.83 1.19 3.08 0 4.41-2.69 5.38-5.25 5.67.41.36.78 1.05.78 2.12 0 1.53-.01 2.76-.01 3.14 0 .31.21.68.8.56A11.51 11.51 0 0 0 23.5 12C23.5 5.73 18.27.5 12 .5z"/>`
		},
		{
			name: 'Discord',
			svg: `<path fill="#5865F2" d="M20.32 4.37A19.8 19.8 0 0 0 15.44 2.9c-.24.43-.52 1.01-.71 1.47a18.3 18.3 0 0 0-5.46 0A13 13 0 0 0 8.55 2.9a19.7 19.7 0 0 0-4.88 1.47C.9 8.35.32 12.24.6 16.08a19.9 19.9 0 0 0 6.01 3.04c.49-.66.92-1.36 1.29-2.1-.71-.27-1.39-.6-2.03-.99.17-.12.34-.25.5-.38a14.2 14.2 0 0 0 12.06 0c.16.14.33.26.5.38-.64.39-1.32.72-2.03.99.37.74.8 1.44 1.29 2.1a19.8 19.8 0 0 0 6.01-3.04c.34-4.45-.58-8.3-2.38-11.71zM8.5 13.7c-1.18 0-2.15-1.08-2.15-2.42S7.3 8.86 8.5 8.86s2.17 1.09 2.15 2.42c0 1.34-.96 2.42-2.15 2.42zm7 0c-1.18 0-2.15-1.08-2.15-2.42s.96-2.42 2.15-2.42 2.17 1.09 2.15 2.42c0 1.34-.96 2.42-2.15 2.42z"/>`
		},
		{
			name: 'Notion',
			svg: `<rect x="2.5" y="2.5" width="19" height="19" rx="4" fill="#fff" stroke="#111" stroke-width="1.1"/><path d="M8 16.5V7.5l7 9v-9" stroke="#111" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>`
		},
		{
			name: 'Slack',
			svg: `<rect x="10.5" y="2.5" width="3" height="8" rx="1.5" fill="#36C5F0"/><rect x="13.5" y="10.5" width="8" height="3" rx="1.5" fill="#2EB67D"/><rect x="10.5" y="13.5" width="3" height="8" rx="1.5" fill="#ECB22E"/><rect x="2.5" y="10.5" width="8" height="3" rx="1.5" fill="#E01E5A"/>`
		},
		{
			name: 'Google Drive',
			svg: `<path d="M8.7 3h6.6l6.2 11h-6.6z" fill="#FFCF63"/><path d="M8.7 3 2.5 14l3.3 6L12 9z" fill="#11A861"/><path d="M5.8 20h12.4l3.3-6H9.1z" fill="#5C87F5"/>`
		},
		{
			name: 'Gmail',
			svg: `<rect x="2.5" y="5" width="19" height="14" rx="2" fill="#fff" stroke="#EA4335" stroke-width="1.1"/><path d="M3.2 6.2 12 13l8.8-6.8" fill="none" stroke="#EA4335" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>`
		}
	];

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
			title: 'Use Cookbook',
			desc: 'Find the local models your hardware can actually run, then pull them.',
			icon: `<svg xmlns="http://www.w3.org/2000/svg" ${_capAttrs}><path d="M12 7v14M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/></svg>`
		},
		{
			title: 'Generate Images',
			desc: 'Create images locally with ComfyUI or A1111.',
			icon: `<svg xmlns="http://www.w3.org/2000/svg" ${_capAttrs}><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/></svg>`
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
		const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
		if (!reduce)
			_carTimer = setInterval(() => {
				carousel = (carousel + 1) % capabilities.length;
			}, 4500);
	});
	onDestroy(() => clearInterval(_carTimer));
</script>

<div class="grid grid-rows-[1fr_auto] w-full h-full min-h-full px-5 pt-6 pb-6 text-center">
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
					placeholder={$i18n.t('Ask Harvis anything…')}
					{onChange}
					{onUpload}
					on:submit={(e) => {
						dispatch('submit', e.detail);
					}}
					on:research={(e) => dispatch('research', e.detail)}
				/>
			</div>

			{#if !connectDismissed}
				<div
					class="relative z-0 -mt-[14px] mx-auto w-[calc(100%-34px)] pt-[22px] px-4 pb-[11px] flex items-center justify-between gap-2.5 bg-gray-50 dark:bg-gray-900 border border-t-0 border-gray-200 dark:border-gray-800 rounded-b-[18px] shadow-[0_8px_16px_-10px_rgba(0,0,0,0.25)]"
				>
					<span class="inline-flex items-center gap-1.5 text-[0.8125rem] text-gray-600 dark:text-gray-400">
						<svg
							xmlns="http://www.w3.org/2000/svg"
							width="14"
							height="14"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="1.8"
							stroke-linecap="round"
							stroke-linejoin="round"
						>
							<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
							<path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
						</svg>
						{$i18n.t('Connect your tools to Harvis')}
					</span>
					<div class="flex items-center gap-1.5">
						{#each connectBrands as b}
							<span
								class="inline-flex items-center justify-center size-[26px] rounded-lg text-gray-500 dark:text-gray-400 bg-white dark:bg-gray-850 border border-gray-200 dark:border-gray-800"
								title={b.name}
							>
								<svg width="16" height="16" viewBox="0 0 24 24" role="img" aria-label={b.name}
									>{@html b.svg}</svg
								>
							</span>
						{/each}
						<button
							type="button"
							class="size-6 ml-0.5 inline-flex items-center justify-center rounded-lg text-gray-400 dark:text-gray-500 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-850 transition"
							on:click={() => (connectDismissed = true)}
							aria-label={$i18n.t('Dismiss')}
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								width="14"
								height="14"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="2"
								stroke-linecap="round"
								stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg
							>
						</button>
					</div>
				</div>
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
