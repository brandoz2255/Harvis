<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { createEventDispatcher, onMount, getContext } from 'svelte';
	import { getLanguages, changeLanguage } from '$lib/i18n';
	const dispatch = createEventDispatcher();

	import { config, models, settings, theme, user } from '$lib/stores';
	import { THEMES, applyThemeById } from '$lib/themes';

	const i18n = getContext('i18n');

	import AdvancedParams from './Advanced/AdvancedParams.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import SettingsSection from './SettingsSection.svelte';
	import SettingRow from './SettingRow.svelte';
	export let saveSettings: Function;
	export let getModels: Function;

	// General
	let selectedTheme = 'system';

	let languages: Awaited<ReturnType<typeof getLanguages>> = [];
	let lang = $i18n.language;
	let notificationEnabled = false;
	let system = '';

	let showAdvanced = false;

	const toggleNotification = async () => {
		const permission = await Notification.requestPermission();

		if (permission === 'granted') {
			notificationEnabled = !notificationEnabled;
			saveSettings({ notificationEnabled: notificationEnabled });
		} else {
			toast.error(
				$i18n.t(
					'Response notifications cannot be activated as the website permissions have been denied. Please visit your browser settings to grant the necessary access.'
				)
			);
		}
	};

	let params = {
		// Advanced
		stream_response: null,
		stream_delta_chunk_size: null,
		function_calling: null,
		seed: null,
		temperature: null,
		reasoning_effort: null,
		logit_bias: null,
		frequency_penalty: null,
		presence_penalty: null,
		repeat_penalty: null,
		repeat_last_n: null,
		mirostat: null,
		mirostat_eta: null,
		mirostat_tau: null,
		top_k: null,
		top_p: null,
		min_p: null,
		stop: null,
		tfs_z: null,
		num_ctx: null,
		num_batch: null,
		num_keep: null,
		max_tokens: null,
		num_gpu: null
	};

	const saveHandler = async () => {
		saveSettings({
			system: system !== '' ? system : undefined,
			params: {
				stream_response: params.stream_response !== null ? params.stream_response : undefined,
				stream_delta_chunk_size:
					params.stream_delta_chunk_size !== null ? params.stream_delta_chunk_size : undefined,
				function_calling: params.function_calling !== null ? params.function_calling : undefined,
				seed: (params.seed !== null ? params.seed : undefined) ?? undefined,
				stop: params.stop ? params.stop.split(',').filter((e) => e) : undefined,
				temperature: params.temperature !== null ? params.temperature : undefined,
				reasoning_effort: params.reasoning_effort !== null ? params.reasoning_effort : undefined,
				logit_bias: params.logit_bias !== null ? params.logit_bias : undefined,
				frequency_penalty: params.frequency_penalty !== null ? params.frequency_penalty : undefined,
				presence_penalty: params.presence_penalty !== null ? params.presence_penalty : undefined,
				repeat_penalty: params.repeat_penalty !== null ? params.repeat_penalty : undefined,
				repeat_last_n: params.repeat_last_n !== null ? params.repeat_last_n : undefined,
				mirostat: params.mirostat !== null ? params.mirostat : undefined,
				mirostat_eta: params.mirostat_eta !== null ? params.mirostat_eta : undefined,
				mirostat_tau: params.mirostat_tau !== null ? params.mirostat_tau : undefined,
				top_k: params.top_k !== null ? params.top_k : undefined,
				top_p: params.top_p !== null ? params.top_p : undefined,
				min_p: params.min_p !== null ? params.min_p : undefined,
				tfs_z: params.tfs_z !== null ? params.tfs_z : undefined,
				num_ctx: params.num_ctx !== null ? params.num_ctx : undefined,
				num_batch: params.num_batch !== null ? params.num_batch : undefined,
				num_keep: params.num_keep !== null ? params.num_keep : undefined,
				max_tokens: params.max_tokens !== null ? params.max_tokens : undefined,
				use_mmap: params.use_mmap !== null ? params.use_mmap : undefined,
				use_mlock: params.use_mlock !== null ? params.use_mlock : undefined,
				num_thread: params.num_thread !== null ? params.num_thread : undefined,
				num_gpu: params.num_gpu !== null ? params.num_gpu : undefined,
				think: params.think !== null ? params.think : undefined,
				keep_alive: params.keep_alive !== null ? params.keep_alive : undefined,
				format: params.format !== null ? params.format : undefined
			}
		});
		dispatch('save');
	};

	onMount(async () => {
		selectedTheme = localStorage.theme ?? 'system';

		languages = await getLanguages();

		if (!$config?.features?.enable_easter_eggs) {
			languages = languages.filter((l) => l.code !== 'dg-DG');
		}

		notificationEnabled = $settings.notificationEnabled ?? false;
		system = $settings.system ?? '';

		params = { ...params, ...$settings.params };
		params.stop = $settings?.params?.stop ? ($settings?.params?.stop ?? []).join(',') : null;
	});

	// Theme application is centralised in $lib/themes (applyThemeById) — the registry-driven
	// token-map switcher shared with the desktop theme:update handler and the app.html loader.
	const applyTheme = (_theme: string) => applyThemeById(_theme);

	const themeChangeHandler = (_theme: string) => {
		theme.set(_theme);
		localStorage.setItem('theme', _theme);
		applyTheme(_theme);
	};
</script>

<div class="flex flex-col h-full justify-between text-sm" id="tab-general">
	<div class="  overflow-y-scroll max-h-[28rem] md:max-h-full">
		<SettingsSection title={$i18n.t('WebUI Settings')}>
			<SettingRow title={$i18n.t('Theme')} description={$i18n.t('How Harvis looks.')}>
				<select
					class="w-44 sm:w-56 cursor-pointer rounded-[10px] bg-gray-100 dark:bg-gray-850 px-3 py-2 pr-8 text-sm text-gray-800 dark:text-gray-100 {$settings.highContrastMode
						? ''
						: 'outline-hidden'}"
					bind:value={selectedTheme}
					placeholder={$i18n.t('Select a theme')}
					on:change={() => themeChangeHandler(selectedTheme)}
				>
					{#each THEMES as t (t.id)}
						{#if !t.eggOnly || $config?.features?.enable_easter_eggs}
							<option value={t.id}>{t.icon} {$i18n.t(t.label)}</option>
						{/if}
					{/each}
				</select>
			</SettingRow>

			<SettingRow
				title={$i18n.t('Language')}
				description={$i18n.t('The display language of the interface.')}
			>
				<select
					class="w-44 sm:w-56 cursor-pointer rounded-[10px] bg-gray-100 dark:bg-gray-850 px-3 py-2 pr-8 text-sm text-gray-800 dark:text-gray-100 {$settings.highContrastMode
						? ''
						: 'outline-hidden'}"
					bind:value={lang}
					placeholder={$i18n.t('Select a language')}
					on:change={(e) => {
						changeLanguage(lang);
					}}
				>
					{#each languages as language}
						<option value={language['code']}>{language['title']}</option>
					{/each}
				</select>
			</SettingRow>
			{#if $i18n.language === 'en-US' && !($config?.license_metadata ?? false)}
				<div
					class="py-2 text-xs {($settings?.highContrastMode ?? false)
						? 'text-gray-800 dark:text-gray-100'
						: 'text-gray-400 dark:text-gray-500'}"
				>
					Couldn't find your language?
					<a
						class="font-medium underline {($settings?.highContrastMode ?? false)
							? 'text-gray-700 dark:text-gray-200'
							: 'text-gray-300'}"
						href="https://github.com/open-webui/open-webui/blob/main/docs/CONTRIBUTING.md#-translations-and-internationalization"
						target="_blank"
					>
						Help us translate Harvis!
					</a>
				</div>
			{/if}

			<SettingRow
				title={$i18n.t('Notifications')}
				description={$i18n.t('Asks your browser for permission to show notifications.')}
			>
				<button
					class="px-3 py-1.5 text-sm font-medium rounded-[10px] bg-gray-100 hover:bg-gray-200 dark:bg-gray-850 dark:hover:bg-gray-800 text-gray-800 dark:text-gray-100 flex transition"
					on:click={() => {
						toggleNotification();
					}}
					type="button"
					role="switch"
					aria-checked={notificationEnabled}
				>
					{#if notificationEnabled === true}
						<span class="self-center">{$i18n.t('On')}</span>
					{:else}
						<span class="self-center">{$i18n.t('Off')}</span>
					{/if}
				</button>
			</SettingRow>
		</SettingsSection>

		{#if $user?.role === 'admin' || (($user?.permissions.chat?.controls ?? true) && ($user?.permissions.chat?.system_prompt ?? true))}
			<SettingsSection title={$i18n.t('System Prompt')}>
				<Textarea
					bind:value={system}
					className={'w-full text-sm outline-hidden resize-vertical mt-2' +
						($settings.highContrastMode
							? ' p-2.5 border-2 border-gray-300 dark:border-gray-700 rounded-lg bg-transparent text-gray-900 dark:text-gray-100 focus:ring-1 focus:ring-blue-500 focus:border-blue-500 overflow-y-hidden'
							: '  dark:text-gray-300 ')}
					rows="4"
					placeholder={$i18n.t('Enter system prompt here')}
				/>
			</SettingsSection>
		{/if}

		{#if $user?.role === 'admin' || (($user?.permissions.chat?.controls ?? true) && ($user?.permissions.chat?.params ?? true))}
			<div class="mt-2 space-y-3 pr-1.5">
				<SettingRow title={$i18n.t('Advanced Parameters')} border={false}>
					<button
						class=" text-sm font-medium {($settings?.highContrastMode ?? false)
							? 'text-gray-800 dark:text-gray-100'
							: 'text-gray-400 dark:text-gray-500'}"
						type="button"
						aria-expanded={showAdvanced}
						on:click={() => {
							showAdvanced = !showAdvanced;
						}}>{showAdvanced ? $i18n.t('Hide') : $i18n.t('Show')}</button
					>
				</SettingRow>

				{#if showAdvanced}
					<AdvancedParams admin={$user?.role === 'admin'} bind:params />
				{/if}
			</div>
		{/if}
	</div>

	<div class="flex justify-end pt-3 text-sm font-medium">
		<button
			class="px-3.5 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-lg"
			on:click={() => {
				saveHandler();
			}}
		>
			{$i18n.t('Save')}
		</button>
	</div>
</div>
