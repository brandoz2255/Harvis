<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { marked } from 'marked';
	import DOMPurify from 'dompurify';

	import { onMount, getContext, tick, createEventDispatcher } from 'svelte';
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

	import Suggestions from './Suggestions.svelte';
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

	let models = [];
	let selectedModelIdx = 0;

	$: if (selectedModels.length > 0) {
		selectedModelIdx = models.length - 1;
	}

	$: models = selectedModels.map((id) => $_models.find((m) => m.id === id));

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

	// Compact routing pills → real Harvis surfaces (shown alongside model suggestions).
	$: studioEnabled = $config?.features?.enable_harvis_studio ?? true;
	const _iconAttrs =
		'width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';
	const starters = [
		{
			label: 'Build something',
			route: '/harvis/vibecode',
			icon: `<svg xmlns="http://www.w3.org/2000/svg" ${_iconAttrs}><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>`
		},
		{
			label: 'Analyze files',
			route: '/harvis/notebooks',
			icon: `<svg xmlns="http://www.w3.org/2000/svg" ${_iconAttrs}><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>`
		},
		{
			label: 'Research topic',
			route: '/harvis/notebooks',
			icon: `<svg xmlns="http://www.w3.org/2000/svg" ${_iconAttrs}><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>`
		},
		{
			label: 'Plan a project',
			seed: 'Help me plan a project.',
			icon: `<svg xmlns="http://www.w3.org/2000/svg" ${_iconAttrs}><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>`
		}
	];
</script>

<div class="m-auto w-full max-w-6xl px-2 @2xl:px-20 translate-y-6 py-24 text-center">
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

	<div
		class="w-full text-3xl text-gray-800 dark:text-gray-100 text-center flex items-center gap-4 font-primary"
	>
		<div class="home-stage relative w-full flex flex-col justify-center items-center">
			<HarvisMascot size={56} className="mb-3" interactive={true} />
			<div
				class="home-greeting text-3xl font-medium mb-1.5"
				style="background-image:linear-gradient(100deg,#38bdf8 0%,#bae6fd 48%,#38bdf8 100%);background-size:200% auto;-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;color:transparent;"
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

			<div class="text-base font-normal @md:max-w-3xl w-full py-3 {atSelectedModel ? 'mt-2' : ''}">
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
		</div>
	</div>

	{#if $selectedFolder}
		<div
			class="mx-auto px-4 md:max-w-3xl md:px-6 font-primary min-h-62"
			in:fade={{ duration: 200, delay: 200 }}
		>
			<FolderPlaceholder folder={$selectedFolder} />
		</div>
	{:else}
		<div class="mx-auto max-w-2xl font-primary mt-2" in:fade={{ duration: 200, delay: 200 }}>
			<div class="mx-5">
				<Suggestions
					suggestionPrompts={atSelectedModel?.info?.meta?.suggestion_prompts ??
						models[selectedModelIdx]?.info?.meta?.suggestion_prompts ??
						$config?.default_prompt_suggestions ??
						[]}
					inputValue={prompt}
					{onSelect}
				/>
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

	/* Subtle cyan glow behind the home content (bridged from the prototype). */
	.home-stage::before {
		content: '';
		position: absolute;
		top: -8%;
		left: 50%;
		width: 460px;
		max-width: 90%;
		height: 360px;
		transform: translateX(-50%);
		background: radial-gradient(closest-side, rgba(56, 189, 248, 0.1), transparent);
		pointer-events: none;
		z-index: 0;
	}
	.home-stage > * {
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
			color: #38bdf8 !important;
			-webkit-text-fill-color: #38bdf8 !important;
		}
	}
</style>
