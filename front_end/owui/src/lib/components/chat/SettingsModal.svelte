<script lang="ts">
	import { getContext, onMount, tick } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { config, models, settings, user } from '$lib/stores';
	import { updateUserSettings } from '$lib/apis/users';
	import { getModels as _getModels } from '$lib/apis';
	import { goto } from '$app/navigation';

	import Modal from '../common/Modal.svelte';
	import Tooltip from '../common/Tooltip.svelte';
	import Account from './Settings/Account.svelte';
	import About from './Settings/About.svelte';
	import General from './Settings/General.svelte';
	import Interface from './Settings/Interface.svelte';
	import Audio from './Settings/Audio.svelte';
	import DataControls from './Settings/DataControls.svelte';
	import Search from '../icons/Search.svelte';
	import XMark from '../icons/XMark.svelte';
	import Integrations from './Settings/Integrations.svelte';
	import WorkspaceSettings from './Settings/WorkspaceSettings.svelte';
	import Sparkles from '../icons/Sparkles.svelte';
	import DatabaseSettings from '../icons/DatabaseSettings.svelte';
	import SettingsAlt from '../icons/SettingsAlt.svelte';
	import UserCircle from '../icons/UserCircle.svelte';
	import SoundHigh from '../icons/SoundHigh.svelte';
	import InfoCircle from '../icons/InfoCircle.svelte';
	import WrenchAlt from '../icons/WrenchAlt.svelte';
	import AppNotification from '../icons/AppNotification.svelte';
	import UserBadgeCheck from '../icons/UserBadgeCheck.svelte';
	import Bolt from '../icons/Bolt.svelte';
	import Cube from '../icons/Cube.svelte';
	// Customize group panels. Connectors stays shared with
	// /harvis/agent-studio/customize; Skills gets the desktop-native manager
	// (list → Add dropdown → in-panel detail) — the agent-studio route keeps
	// its own SkillsPanel (governance sync UI) untouched.
	import SkillsManager from './Settings/Skills/SkillsManager.svelte';
	import ConnectorsPanel from '$lib/agent-studio/customize/ConnectorsPanel.svelte';

	const i18n = getContext('i18n');

	export let show: boolean | string = false;

	$: if (show) {
		if (typeof show === 'string') {
			selectedTab = show;
			show = true;
		}
		addScrollListener();
	} else {
		selectedTab = 'general';
		removeScrollListener();
	}

	interface SettingsTab {
		id: string;
		title: string;
		keywords: string[];
	}

	// Grouped left nav (Claude-style settings shell): every tab belongs to one
	// group; groups render as headed sections in the desktop nav column.
	const navGroups = [
		{ id: 'settings', label: 'Settings' },
		{ id: 'integrations', label: 'Integrations' },
		{ id: 'customize', label: 'Customize' }
	];
	const tabGroups: Record<string, string> = {
		general: 'settings',
		interface: 'settings',
		personalization: 'settings',
		audio: 'settings',
		data_controls: 'settings',
		account: 'settings',
		about: 'settings',
		connections: 'integrations',
		tools: 'integrations',
		workspace: 'integrations',
		skills: 'customize',
		connectors: 'customize'
	};
	const tabGroup = (id: string) => tabGroups[id] ?? 'settings';

	const allSettings: SettingsTab[] = [
		{
			id: 'general',
			title: 'General',
			keywords: [
				'advancedparams',
				'advancedparameters',
				'advanced params',
				'advanced parameters',
				'configuration',
				'defaultparameters',
				'default parameters',
				'defaultsettings',
				'default settings',
				'general',
				'keepalive',
				'keep alive',
				'languages',
				'notifications',
				'requestmode',
				'request mode',
				'systemparameters',
				'system parameters',
				'systemprompt',
				'system prompt',
				'systemsettings',
				'system settings',
				'theme',
				'translate',
				'webuisettings',
				'webui settings'
			]
		},
		{
			id: 'interface',
			title: 'Interface',
			keywords: [
				'allow user location',
				'allow voice interruption in call',
				'allowuserlocation',
				'allowvoiceinterruptionincall',
				'always collapse codeblocks',
				'always collapse code blocks',
				'always expand details',
				'always on web search',
				'always play notification sound',
				'alwayscollapsecodeblocks',
				'alwaysexpanddetails',
				'alwaysonwebsearch',
				'alwaysplaynotificationsound',
				'android',
				'auto chat tags',
				'auto copy response to clipboard',
				'auto title',
				'autochattags',
				'autocopyresponsetoclipboard',
				'autotitle',
				'beta',
				'call',
				'chat background image',
				'chat bubble ui',
				'chat direction',
				'chat tags autogen',
				'chat tags autogeneration',
				'chat ui',
				'chatbackgroundimage',
				'chatbubbleui',
				'chatdirection',
				'chat tags autogeneration',
				'chattagsautogeneration',
				'chatui',
				'copy formatted text',
				'copyformattedtext',
				'default model',
				'defaultmodel',
				'design',
				'detect artifacts automatically',
				'detectartifactsautomatically',
				'display emoji in call',
				'display username',
				'displayemojiincall',
				'displayusername',
				'enter key behavior',
				'enterkeybehavior',
				'expand mode',
				'expandmode',
				'file',
				'followup autogeneration',
				'followupautogeneration',
				'fullscreen',
				'fullwidthmode',
				'full width mode',
				'haptic feedback',
				'hapticfeedback',
				'high contrast mode',
				'highcontrastmode',
				'iframe sandbox allow forms',
				'iframe sandbox allow same origin',
				'iframesandboxallowforms',
				'iframesandboxallowsameorigin',
				'imagecompression',
				'image compression',
				'imagemaxcompressionsize',
				'image max compression size',
				'interface customization',
				'interface options',
				'interfacecustomization',
				'interfaceoptions',
				'landing page mode',
				'landingpagemode',
				'layout',
				'left to right',
				'left-to-right',
				'lefttoright',
				'ltr',
				'paste large text as file',
				'pastelargetextasfile',
				'reset background',
				'resetbackground',
				'response auto copy',
				'responseautocopy',
				'rich text input for chat',
				'richtextinputforchat',
				'right to left',
				'right-to-left',
				'righttoleft',
				'rtl',
				'scroll behavior',
				'scroll on branch change',
				'scrollbehavior',
				'scrollonbranchchange',
				'select model',
				'selectmodel',
				'settings',
				'show username',
				'showusername',
				'stream large chunks',
				'streamlargechunks',
				'stylized pdf export',
				'stylizedpdfexport',
				'title autogeneration',
				'titleautogeneration',
				'toast notifications for new updates',
				'toastnotificationsfornewupdates',
				'upload background',
				'uploadbackground',
				'user interface',
				'user location access',
				'userinterface',
				'userlocationaccess',
				'vibration',
				'voice control',
				'voicecontrol',
				'widescreen mode',
				'widescreenmode',
				'whatsnew',
				'whats new',
				'websearchinchat',
				'web search in chat'
			]
		},
		{
			id: 'tools',
			title: 'Integrations',
			keywords: [
				'addconnection',
				'add connection',
				'integrations',
				'managetools',
				'manage tools',
				'manage tool servers',
				'managetoolservers',
				'open terminal',
				'openterminal',
				'terminal',
				'settings'
			]
		},

		{
			id: 'workspace',
			title: 'Workspace',
			keywords: ['workspace', 'openclaw', 'agent', 'provider', 'model', 'byo', 'usage', 'claw']
		},

		{
			id: 'audio',
			title: 'Audio',
			keywords: [
				'audio config',
				'audio control',
				'audio features',
				'audio input',
				'audio output',
				'audio playback',
				'audio voice',
				'audioconfig',
				'audiocontrol',
				'audiofeatures',
				'audioinput',
				'audiooutput',
				'audioplayback',
				'audiovoice',
				'auto playback response',
				'autoplaybackresponse',
				'auto transcribe',
				'autotranscribe',
				'instant auto send after voice transcription',
				'instantautosendaftervoicetranscription',
				'language',
				'non local voices',
				'nonlocalvoices',
				'save settings',
				'savesettings',
				'set voice',
				'setvoice',
				'sound settings',
				'soundsettings',
				'speech config',
				'speech mode',
				'speech playback speed',
				'speech rate',
				'speech recognition',
				'speech settings',
				'speech speed',
				'speech synthesis',
				'speech to text engine',
				'speechconfig',
				'speechmode',
				'speechplaybackspeed',
				'speechrate',
				'speechrecognition',
				'speechsettings',
				'speechspeed',
				'speechsynthesis',
				'speechtotextengine',
				'speedch playback rate',
				'speedchplaybackrate',
				'stt settings',
				'sttsettings',
				'text to speech engine',
				'text to speech',
				'textospeechengine',
				'texttospeech',
				'texttospeechvoice',
				'text to speech voice',
				'voice control',
				'voice modes',
				'voice options',
				'voice playback',
				'voice recognition',
				'voice speed',
				'voicecontrol',
				'voicemodes',
				'voiceoptions',
				'voiceplayback',
				'voicerecognition',
				'voicespeed',
				'volume'
			]
		},
		{
			id: 'data_controls',
			title: 'Data Controls',
			keywords: [
				'archive all chats',
				'archive chats',
				'archiveallchats',
				'archivechats',
				'archived chats',
				'archivedchats',
				'chat activity',
				'chat history',
				'chat settings',
				'chatactivity',
				'chathistory',
				'chatsettings',
				'conversation activity',
				'conversation history',
				'conversationactivity',
				'conversationhistory',
				'conversations',
				'convos',
				'delete all chats',
				'delete chats',
				'deleteallchats',
				'deletechats',
				'export chats',
				'exportchats',
				'import chats',
				'importchats',
				'message activity',
				'message archive',
				'message history',
				'messagearchive',
				'messagehistory'
			]
		},
		{
			id: 'account',
			title: 'Account',
			keywords: [
				'account preferences',
				'account settings',
				'accountpreferences',
				'accountsettings',
				'api keys',
				'apikeys',
				'change password',
				'changepassword',
				'jwt token',
				'jwttoken',
				'login',
				'new password',
				'newpassword',
				'notification webhook url',
				'notificationwebhookurl',
				'personal settings',
				'personalsettings',
				'privacy settings',
				'privacysettings',
				'profileavatar',
				'profile avatar',
				'profile details',
				'profile image',
				'profile picture',
				'profiledetails',
				'profileimage',
				'profilepicture',
				'security settings',
				'securitysettings',
				'update account',
				'update password',
				'updateaccount',
				'updatepassword',
				'user account',
				'user data',
				'user preferences',
				'user profile',
				'useraccount',
				'userdata',
				'username',
				'userpreferences',
				'userprofile',
				'webhook url',
				'webhookurl'
			]
		},
		{
			id: 'about',
			title: 'About',
			keywords: [
				'about app',
				'about me',
				'about open webui',
				'about page',
				'about us',
				'aboutapp',
				'aboutme',
				'aboutopenwebui',
				'aboutpage',
				'aboutus',
				'check for updates',
				'checkforupdates',
				'contact',
				'copyright',
				'details',
				'discord',
				'documentation',
				'github',
				'help',
				'information',
				'license',
				'redistributions',
				'release',
				'see whats new',
				'seewhatsnew',
				'settings',
				'software info',
				'softwareinfo',
				'support',
				'terms and conditions',
				'terms of use',
				'termsandconditions',
				'termsofuse',
				'timothy jae ryang baek',
				'timothy j baek',
				'timothyjaeryangbaek',
				'timothyjbaek',
				'twitter',
				'update info',
				'updateinfo',
				'version info',
				'versioninfo'
			]
		},
		// ── Customize group (shared panels with /harvis/agent-studio/customize) ──
		{
			id: 'skills',
			title: 'Skills',
			keywords: [
				'skill',
				'skills',
				'audit',
				'verdict',
				'governance',
				'openclaw sync',
				'instructions',
				'capability',
				'customize'
			]
		},
		{
			id: 'connectors',
			title: 'Connectors',
			keywords: [
				'connector',
				'connectors',
				'connect',
				'mcp',
				'mcp servers',
				'model context protocol',
				'marketplace',
				'directory',
				'attach',
				'tools',
				'plugins',
				'built-in tools',
				'capabilities',
				'customize'
			]
		}
	];

	let availableSettings = [];
	let filteredSettings = [];

	let search = '';
	let searchDebounceTimeout;

	const getAvailableSettings = () => {
		return allSettings.filter((tab) => {
			if (tab.id === 'tools') {
				return (
					$user?.role === 'admin' ||
					($user?.role === 'user' && $user?.permissions?.features?.direct_tool_servers)
				);
			}

			if (tab.id === 'interface') {
				return $user?.role === 'admin' || ($user?.permissions?.settings?.interface ?? true);
			}

			return true;
		});
	};

	const setFilteredSettings = () => {
		filteredSettings = availableSettings
			.filter((tab) => {
				return (
					search === '' ||
					tab.title.toLowerCase().includes(search.toLowerCase().trim()) ||
					tab.keywords.some((keyword) => keyword.includes(search.toLowerCase().trim()))
				);
			})
			.map((tab) => tab.id);

		if (filteredSettings.length > 0 && !filteredSettings.includes(selectedTab)) {
			selectedTab = filteredSettings[0];
		}
	};

	const searchDebounceHandler = () => {
		if (searchDebounceTimeout) {
			clearTimeout(searchDebounceTimeout);
		}

		searchDebounceTimeout = setTimeout(() => {
			setFilteredSettings();
		}, 100);
	};

	const saveSettings = async (updated) => {
		console.log(updated);
		await settings.set({ ...$settings, ...updated });
		await models.set(await getModels());
		await updateUserSettings(localStorage.token, { ui: $settings });
	};

	const getModels = async () => {
		return await _getModels(
			localStorage.token,
			$config?.features?.enable_direct_connections && ($settings?.directConnections ?? null)
		);
	};

	let selectedTab = 'general';

	// Shared nav-row chrome: rail rows on desktop, strip pills on mobile.
	// Reactive assignment so class strings recompute when the active tab or
	// high-contrast mode changes.
	$: tabClass = (id: string) =>
		`px-0.5 md:px-2.5 py-1 md:py-0 md:h-10 min-w-fit rounded-lg flex-1 md:flex-none flex items-center text-left transition ${
			selectedTab === id
				? ($settings?.highContrastMode ?? false)
					? 'bg-gray-200 dark:bg-gray-800 text-gray-900 dark:text-gray-100'
					: 'bg-gray-200/70 dark:bg-gray-800 text-gray-900 dark:text-gray-100'
				: ($settings?.highContrastMode ?? false)
					? 'hover:bg-gray-200 dark:hover:bg-gray-800'
					: 'text-gray-500 dark:text-gray-400 hover:bg-gray-200/60 dark:hover:bg-gray-800/60 hover:text-gray-800 dark:hover:text-gray-100'
		}`;

	// Function to handle sideways scrolling
	const scrollHandler = (event) => {
		const settingsTabsContainer = document.getElementById('settings-tabs-container');
		if (settingsTabsContainer) {
			event.preventDefault(); // Prevent default vertical scrolling
			settingsTabsContainer.scrollLeft += event.deltaY; // Scroll sideways
		}
	};

	const addScrollListener = async () => {
		await tick();
		const settingsTabsContainer = document.getElementById('settings-tabs-container');
		if (settingsTabsContainer) {
			settingsTabsContainer.addEventListener('wheel', scrollHandler);
		}
	};

	const removeScrollListener = async () => {
		await tick();
		const settingsTabsContainer = document.getElementById('settings-tabs-container');
		if (settingsTabsContainer) {
			settingsTabsContainer.removeEventListener('wheel', scrollHandler);
		}
	};

	onMount(() => {
		availableSettings = getAvailableSettings();
		setFilteredSettings();

		config.subscribe((configData) => {
			availableSettings = getAvailableSettings();
			setFilteredSettings();
		});
	});
</script>

<Modal
	size="2xl"
	className="bg-white dark:bg-gray-900 rounded-2xl overflow-hidden md:w-[min(1150px,96vw)] md:h-[min(88vh,900px)]"
	bind:show
>
	<div class="relative h-full max-h-full text-gray-700 dark:text-gray-100">
		<!-- Mobile top bar — on desktop the close button is pinned over the content pane instead. -->
		<div class="flex md:hidden justify-between dark:text-gray-300 px-4 pt-4.5 pb-0.5">
			<div class=" text-lg font-medium self-center">{$i18n.t('Settings')}</div>
			<button
				aria-label={$i18n.t('Close settings modal')}
				class="self-center"
				on:click={() => {
					show = false;
				}}
			>
				<XMark className="w-5 h-5"></XMark>
			</button>
		</div>

		<Tooltip
			className="hidden md:flex absolute top-3.5 right-3.5 z-10"
			content={$i18n.t('Close')}
			placement="bottom"
		>
			<button
				aria-label={$i18n.t('Close settings modal')}
				class="flex size-8 items-center justify-center rounded-lg text-gray-400 hover:text-gray-700 dark:text-gray-500 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition"
				on:click={() => {
					show = false;
				}}
			>
				<XMark className="size-4.5"></XMark>
			</button>
		</Tooltip>

		<div class="flex flex-col md:flex-row w-full h-full max-h-full pt-1 md:pt-0 pb-4 md:pb-0">
			<div
				role="tablist"
				id="settings-tabs-container"
				class="tabs flex flex-row overflow-x-auto gap-2.5 mx-3 md:mx-0 md:gap-0.5 md:flex-col flex-1 md:flex-none md:w-[220px] md:shrink-0 md:h-full md:overflow-y-auto md:overflow-x-hidden md:px-3 md:pt-3.5 md:pb-3 md:bg-gray-100 md:dark:bg-gray-950 md:border-r md:border-gray-200 md:dark:border-gray-800 dark:text-gray-200 text-sm md:text-[15px] text-left mb-1 md:mb-0"
			>
				<div
					class="hidden md:flex w-full h-10 shrink-0 items-center rounded-lg px-3 gap-2 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 mb-1"
					id="settings-search"
				>
					<div class="shrink-0 text-gray-400 dark:text-gray-500">
						<Search
							className="size-4"
							strokeWidth={($settings?.highContrastMode ?? false) ? '3' : '1.5'}
						/>
					</div>
					<label class="sr-only" for="search-input-settings-modal">{$i18n.t('Search')}</label>
					<input
						class={`w-full text-sm bg-transparent dark:text-gray-300 outline-hidden
								${($settings?.highContrastMode ?? false) ? 'placeholder-gray-800' : 'placeholder-gray-400 dark:placeholder-gray-500'}`}
						bind:value={search}
						id="search-input-settings-modal"
						on:input={searchDebounceHandler}
						placeholder={$i18n.t('Search')}
					/>
				</div>
				{#if filteredSettings.length > 0}
					{#each navGroups as group (group.id)}
					{@const groupTabs = filteredSettings.filter((id) => tabGroup(id) === group.id)}
					{#if groupTabs.length > 0}
					<!-- Group header — desktop only (mobile keeps the flat horizontal strip). -->
					<div
						class="hidden md:block px-2.5 pt-5 pb-1.5 text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-500 select-none"
					>
						{$i18n.t(group.label)}
					</div>
					{#each groupTabs as tabId (tabId)}
						{#if tabId === 'general'}
							<button
								role="tab"
								aria-controls="tab-general"
								aria-selected={selectedTab === 'general'}
								class={tabClass('general')}
								on:click={() => {
									selectedTab = 'general';
								}}
							>
								<div class=" self-center mr-2">
									<SettingsAlt strokeWidth="1.75" className="size-[18px]" />
								</div>
								<div class=" self-center">{$i18n.t('General')}</div>
							</button>
						{:else if tabId === 'interface'}
							<button
								role="tab"
								aria-controls="tab-interface"
								aria-selected={selectedTab === 'interface'}
								class={tabClass('interface')}
								on:click={() => {
									selectedTab = 'interface';
								}}
							>
								<div class=" self-center mr-2">
									<AppNotification strokeWidth="1.75" className="size-[18px]" />
								</div>
								<div class=" self-center">{$i18n.t('Interface')}</div>
							</button>
						{:else if tabId === 'tools'}
							{#if $user?.role === 'admin' || ($user?.role === 'user' && $user?.permissions?.features?.direct_tool_servers)}
								<button
									role="tab"
									aria-controls="tab-tools"
									aria-selected={selectedTab === 'tools'}
									class={tabClass('tools')}
									on:click={() => {
										selectedTab = 'tools';
									}}
								>
									<div class=" self-center mr-2">
										<WrenchAlt strokeWidth="1.75" className="size-[18px]" />
									</div>
									<div class=" self-center">{$i18n.t('Integrations')}</div>
								</button>
							{/if}
						{:else if tabId === 'workspace'}
							{#if $config?.features?.enable_harvis_studio ?? true}
								<button
									role="tab"
									aria-controls="tab-workspace"
									aria-selected={selectedTab === 'workspace'}
									class={tabClass('workspace')}
									on:click={() => {
										selectedTab = 'workspace';
									}}
								>
									<div class=" self-center mr-2">
										<Sparkles strokeWidth="1.75" className="size-[18px]" />
									</div>
									<div class=" self-center">{$i18n.t('Workspace')}</div>
								</button>
							{/if}
						{:else if tabId === 'audio'}
							<button
								role="tab"
								aria-controls="tab-audio"
								aria-selected={selectedTab === 'audio'}
								class={tabClass('audio')}
								on:click={() => {
									selectedTab = 'audio';
								}}
							>
								<div class=" self-center mr-2">
									<SoundHigh strokeWidth="1.75" className="size-[18px]" />
								</div>
								<div class=" self-center">{$i18n.t('Audio')}</div>
							</button>
						{:else if tabId === 'data_controls'}
							<button
								role="tab"
								aria-controls="tab-data-controls"
								aria-selected={selectedTab === 'data_controls'}
								class={tabClass('data_controls')}
								on:click={() => {
									selectedTab = 'data_controls';
								}}
							>
								<div class=" self-center mr-2">
									<DatabaseSettings strokeWidth="1.75" className="size-[18px]" />
								</div>
								<div class=" self-center">{$i18n.t('Data Controls')}</div>
							</button>
						{:else if tabId === 'account'}
							<button
								role="tab"
								aria-controls="tab-account"
								aria-selected={selectedTab === 'account'}
								class={tabClass('account')}
								on:click={() => {
									selectedTab = 'account';
								}}
							>
								<div class=" self-center mr-2">
									<UserCircle strokeWidth="1.75" className="size-[18px]" />
								</div>
								<div class=" self-center">{$i18n.t('Account')}</div>
							</button>
						{:else if tabId === 'about'}
							<button
								role="tab"
								aria-controls="tab-about"
								aria-selected={selectedTab === 'about'}
								class={tabClass('about')}
								on:click={() => {
									selectedTab = 'about';
								}}
							>
								<div class=" self-center mr-2">
									<InfoCircle strokeWidth="1.75" className="size-[18px]" />
								</div>
								<div class=" self-center">{$i18n.t('About')}</div>
							</button>
						{:else if tabId === 'skills'}
							<button
								role="tab"
								aria-controls="tab-skills"
								aria-selected={selectedTab === 'skills'}
								class={tabClass('skills')}
								on:click={() => {
									selectedTab = 'skills';
								}}
							>
								<div class=" self-center mr-2">
									<Bolt strokeWidth="1.75" className="size-[18px]" />
								</div>
								<div class=" self-center">{$i18n.t('Skills')}</div>
							</button>
						{:else if tabId === 'connectors'}
							<button
								role="tab"
								aria-controls="tab-connectors"
								aria-selected={selectedTab === 'connectors'}
								class={tabClass('connectors')}
								on:click={() => {
									selectedTab = 'connectors';
								}}
							>
								<div class=" self-center mr-2">
									<Cube strokeWidth="1.75" className="size-[18px]" />
								</div>
								<div class=" self-center">{$i18n.t('Connectors')}</div>
							</button>
						{/if}
					{/each}
					{/if}
				{/each}
				{:else}
					<div class="text-center text-gray-500 mt-4">
						{$i18n.t('No results found')}
					</div>
				{/if}
				{#if $user?.role === 'admin'}
					<a
						href="/admin/settings"
						draggable="false"
						class="px-0.5 md:px-2.5 py-1 md:py-0 md:h-10 min-w-fit rounded-lg flex-1 md:flex-none md:mt-auto md:shrink-0 flex items-center select-none text-left transition {$settings?.highContrastMode
							? 'hover:bg-gray-200 dark:hover:bg-gray-800'
							: 'text-gray-500 dark:text-gray-400 hover:bg-gray-200/60 dark:hover:bg-gray-800/60 hover:text-gray-800 dark:hover:text-gray-100'}"
						on:click={async (e) => {
							e.preventDefault();
							await goto('/admin/settings');
							show = false;
						}}
					>
						<div class=" self-center mr-2">
							<UserBadgeCheck strokeWidth="1.75" className="size-[18px]" />
						</div>
						<div class=" self-center">{$i18n.t('Admin Settings')}</div>
					</a>
				{/if}
			</div>
			<div
				class="settings-pane flex-1 min-w-0 md:h-full px-3.5 md:px-7 md:py-6 max-h-[min(42rem,calc(100dvh-10rem))] md:max-h-full overflow-y-auto"
			>
				{#if selectedTab === 'general'}
					<General
						{getModels}
						{saveSettings}
						on:save={() => {
							toast.success($i18n.t('Settings saved successfully!'));
						}}
					/>
				{:else if selectedTab === 'interface'}
					<Interface
						{saveSettings}
						on:save={() => {
							toast.success($i18n.t('Settings saved successfully!'));
						}}
					/>
				{:else if selectedTab === 'tools'}
					<Integrations
						saveSettings={async (updated) => {
							await saveSettings(updated);
							toast.success($i18n.t('Settings saved successfully!'));
						}}
					/>
				{:else if selectedTab === 'workspace'}
					<WorkspaceSettings {saveSettings} />
				{:else if selectedTab === 'audio'}
					<Audio
						{saveSettings}
						on:save={() => {
							toast.success($i18n.t('Settings saved successfully!'));
						}}
					/>
				{:else if selectedTab === 'data_controls'}
					<DataControls {saveSettings} />
				{:else if selectedTab === 'account'}
					<Account
						{saveSettings}
						saveHandler={() => {
							toast.success($i18n.t('Settings saved successfully!'));
						}}
					/>
				{:else if selectedTab === 'skills'}
					<SkillsManager token={localStorage.token} />
				{:else if selectedTab === 'connectors'}
					<ConnectorsPanel token={localStorage.token} />
				{:else if selectedTab === 'about'}
					<About />
				{/if}
			</div>
		</div>
	</div>
</Modal>

<style>
	input::-webkit-outer-spin-button,
	input::-webkit-inner-spin-button {
		/* display: none; <- Crashes Chrome on hover */
		-webkit-appearance: none;
		margin: 0; /* <-- Apparently some margin are still there even though it's hidden */
	}

	.tabs::-webkit-scrollbar {
		display: none; /* for Chrome, Safari and Opera */
	}

	.tabs {
		-ms-overflow-style: none; /* IE and Edge */
		scrollbar-width: none; /* Firefox */
	}

	input[type='number'] {
		appearance: textfield;
		-moz-appearance: textfield; /* Firefox */
	}

	/* Slim scrollbar for the content pane (desktop shell) — gray tokens so all
	   themes remap it. */
	.settings-pane {
		scrollbar-width: thin;
		scrollbar-color: var(--color-gray-300) transparent;
	}

	:global(.dark) .settings-pane {
		scrollbar-color: var(--color-gray-700) transparent;
	}

	.settings-pane::-webkit-scrollbar {
		width: 6px;
	}

	.settings-pane::-webkit-scrollbar-thumb {
		border-radius: 9999px;
		background-color: var(--color-gray-300);
	}

	:global(.dark) .settings-pane::-webkit-scrollbar-thumb {
		background-color: var(--color-gray-700);
	}
</style>
