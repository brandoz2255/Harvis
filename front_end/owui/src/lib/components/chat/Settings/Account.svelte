<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { onMount, getContext } from 'svelte';

	import { user, config, settings } from '$lib/stores';
	import { updateUserProfile, createAPIKey, getAPIKey, getSessionUser } from '$lib/apis/auths';
	import { WEBUI_BASE_URL } from '$lib/constants';

	import UpdatePassword from './Account/UpdatePassword.svelte';
	import { getGravatarUrl } from '$lib/apis/utils';
	import { generateInitialsImage, canvasPixelTest } from '$lib/utils';
	import { copyToClipboard } from '$lib/utils';
	import Plus from '$lib/components/icons/Plus.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import User from '$lib/components/icons/User.svelte';
	import UserProfileImage from './Account/UserProfileImage.svelte';
	import SettingsSection from './SettingsSection.svelte';
	import SettingRow from './SettingRow.svelte';

	const i18n = getContext('i18n');

	// HONESTY GATES: the Harvis owui_compat facade does not implement
	// POST /api/v1/auths/update/profile or GET|POST /api/v1/auths/api_key
	// (see python_back_end/owui_compat/router.py — only signin/signup/signout,
	// GET /auths/ and the update/timezone stub exist). Rather than letting
	// Save / Create-API-key fail on 404 every time, those controls are
	// disabled with a note until the routes land.
	const PROFILE_UPDATE_AVAILABLE = false;
	const API_KEYS_AVAILABLE = false;

	export let saveHandler: Function;
	export let saveSettings: Function;

	let loaded = false;

	let profileImageUrl = '';
	let name = '';
	let bio = '';

	let _gender = '';
	let gender = '';
	let dateOfBirth = '';

	let webhookUrl = '';
	let showAPIKeys = false;

	let APIKey = '';
	let APIKeyCopied = false;
	let profileImageInputElement: HTMLInputElement;

	const submitHandler = async () => {
		if (name !== $user?.name) {
			if (profileImageUrl === generateInitialsImage($user?.name) || profileImageUrl === '') {
				profileImageUrl = generateInitialsImage(name);
			}
		}

		if (webhookUrl !== $settings?.notifications?.webhook_url) {
			saveSettings({
				notifications: {
					...$settings.notifications,
					webhook_url: webhookUrl
				}
			});
		}

		const updatedUser = await updateUserProfile(localStorage.token, {
			name: name,
			profile_image_url: profileImageUrl,
			bio: bio ? bio : null,
			gender: gender ? gender : null,
			date_of_birth: dateOfBirth ? dateOfBirth : null
		}).catch((error) => {
			toast.error(`${error}`);
		});

		if (updatedUser) {
			// Get Session User Info
			const sessionUser = await getSessionUser(localStorage.token).catch((error) => {
				toast.error(`${error}`);
				return null;
			});

			await user.set(sessionUser);
			return true;
		}
		return false;
	};

	const createAPIKeyHandler = async () => {
		if (!API_KEYS_AVAILABLE) {
			toast.error($i18n.t('API keys are not available in this deployment yet.'));
			return;
		}
		APIKey = await createAPIKey(localStorage.token);
		if (APIKey) {
			toast.success($i18n.t('API Key created.'));
		} else {
			toast.error($i18n.t('Failed to create API Key.'));
		}
	};

	onMount(async () => {
		const user = await getSessionUser(localStorage.token).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (user) {
			name = user?.name ?? '';
			profileImageUrl = user?.profile_image_url ?? '';
			bio = user?.bio ?? '';

			_gender = user?.gender ?? '';
			gender = _gender;

			dateOfBirth = user?.date_of_birth ?? '';
		}

		webhookUrl = $settings?.notifications?.webhook_url ?? '';

		// Only fetch API key if the feature is enabled and user has permission
		if (
			user &&
			($config?.features?.enable_api_keys ?? false) &&
			(user?.role === 'admin' || (user?.permissions?.features?.api_keys ?? false))
		) {
			APIKey = await getAPIKey(localStorage.token).catch((error) => {
				console.log(error);
				return '';
			});
		}

		loaded = true;
	});
</script>

<div id="tab-account" class="flex flex-col h-full justify-between text-sm">
	<div class=" overflow-y-scroll max-h-[28rem] md:max-h-full">
		<SettingsSection title={$i18n.t('Your Account')}>
			<svelte:fragment slot="description">{$i18n.t('Manage your account information.')}</svelte:fragment>

			<SettingRow stack={true}>
				<UserProfileImage bind:profileImageUrl user={$user} />
			</SettingRow>

			<SettingRow title={$i18n.t('Name')}>
				<input
					class="w-full sm:w-72 rounded-[10px] bg-gray-100 dark:bg-gray-850 px-3 py-2 text-sm text-gray-800 dark:text-gray-100 outline-hidden"
					type="text"
					bind:value={name}
					aria-label={$i18n.t('Name')}
					required
					placeholder={$i18n.t('Enter your name')}
				/>
			</SettingRow>

			<SettingRow title={$i18n.t('Bio')} stack={true}>
				<Textarea
					className="w-full rounded-[10px] bg-gray-100 dark:bg-gray-850 px-3 py-2 text-sm text-gray-800 dark:text-gray-100 outline-hidden"
					minSize={60}
					bind:value={bio}
					ariaLabel={$i18n.t('Bio')}
					placeholder={$i18n.t('Share your background and interests')}
				/>
			</SettingRow>

			<SettingRow title={$i18n.t('Gender')}>
				<div class="flex w-full flex-col gap-1.5 sm:w-72">
					<select
						class="w-full cursor-pointer rounded-[10px] bg-gray-100 dark:bg-gray-850 px-3 py-2 pr-8 text-sm text-gray-800 dark:text-gray-100 outline-hidden"
						bind:value={_gender}
						aria-label={$i18n.t('Gender')}
						on:change={(e) => {
							console.log(_gender);

							if (_gender === 'custom') {
								// Handle custom gender input
								gender = '';
							} else {
								gender = _gender;
							}
						}}
					>
						<option value="" selected>{$i18n.t('Prefer not to say')}</option>
						<option value="male">{$i18n.t('Male')}</option>
						<option value="female">{$i18n.t('Female')}</option>
						<option value="custom">{$i18n.t('Custom')}</option>
					</select>

					{#if _gender === 'custom'}
						<input
							class="w-full rounded-[10px] bg-gray-100 dark:bg-gray-850 px-3 py-2 text-sm text-gray-800 dark:text-gray-100 outline-hidden"
							type="text"
							required
							aria-label={$i18n.t('Custom Gender')}
							placeholder={$i18n.t('Enter your gender')}
							bind:value={gender}
						/>
					{/if}
				</div>
			</SettingRow>

			<SettingRow title={$i18n.t('Birth Date')}>
				<input
					class="w-full sm:w-72 rounded-[10px] bg-gray-100 dark:bg-gray-850 px-3 py-2 text-sm text-gray-800 dark:text-gray-100 dark:placeholder:text-gray-300 outline-hidden"
					type="date"
					aria-label={$i18n.t('Birth Date')}
					bind:value={dateOfBirth}
					required
				/>
			</SettingRow>

			{#if $config?.features?.enable_user_webhooks}
				<SettingRow title={$i18n.t('Notification Webhook')}>
					<input
						class="w-full sm:w-72 rounded-[10px] bg-gray-100 dark:bg-gray-850 px-3 py-2 text-sm text-gray-800 dark:text-gray-100 outline-hidden"
						type="url"
						placeholder={$i18n.t('Enter your webhook URL')}
						aria-label={$i18n.t('Notification Webhook')}
						bind:value={webhookUrl}
						required
					/>
				</SettingRow>
			{/if}
		</SettingsSection>

		{#if $config?.features.enable_login_form && $config?.features.enable_password_change_form}
			<UpdatePassword />
		{/if}

		{#if ($config?.features?.enable_api_keys ?? false) && ($user?.role === 'admin' || ($user?.permissions?.features?.api_keys ?? false))}
			<SettingsSection>
				<SettingRow border={false}>
					<svelte:fragment slot="title">
						<div class="text-lg">{$i18n.t('API keys')}</div>
					</svelte:fragment>
					<button
						class=" text-sm font-medium text-gray-500"
						type="button"
						on:click={() => {
							showAPIKeys = !showAPIKeys;
						}}>{showAPIKeys ? $i18n.t('Hide') : $i18n.t('Show')}</button
					>
				</SettingRow>

				{#if showAPIKeys}
					<div class="flex flex-col">
						{#if ($config?.features?.enable_api_keys ?? false) && ($user?.role === 'admin' || ($user?.permissions?.features?.api_keys ?? false))}
							<div class="justify-between w-full mt-2">
								{#if $user?.role === 'admin'}
									<div class="flex justify-between w-full">
										<div class="self-center text-xs font-medium mb-1">{$i18n.t('API Key')}</div>
									</div>
								{/if}
								<div class="flex">
									{#if APIKey}
										<SensitiveInput value={APIKey} readOnly={true} />

										<button
											class="ml-1.5 px-1.5 py-1 dark:hover:bg-gray-850 transition rounded-lg"
											aria-label={$i18n.t('Copy API Key')}
											on:click={() => {
												copyToClipboard(APIKey);
												APIKeyCopied = true;
												setTimeout(() => {
													APIKeyCopied = false;
												}, 2000);
											}}
										>
											{#if APIKeyCopied}
												<svg
													xmlns="http://www.w3.org/2000/svg"
													viewBox="0 0 20 20"
													fill="currentColor"
													class="w-4 h-4"
												>
													<path
														fill-rule="evenodd"
														d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z"
														clip-rule="evenodd"
													/>
												</svg>
											{:else}
												<svg
													xmlns="http://www.w3.org/2000/svg"
													viewBox="0 0 16 16"
													fill="currentColor"
													class="w-4 h-4"
												>
													<path
														fill-rule="evenodd"
														d="M11.986 3H12a2 2 0 0 1 2 2v6a2 2 0 0 1-1.5 1.937V7A2.5 2.5 0 0 0 10 4.5H4.063A2 2 0 0 1 6 3h.014A2.25 2.25 0 0 1 8.25 1h1.5a2.25 2.25 0 0 1 2.236 2ZM10.5 4v-.75a.75.75 0 0 0-.75-.75h-1.5a.75.75 0 0 0-.75.75V4h3Z"
														clip-rule="evenodd"
													/>
													<path
														fill-rule="evenodd"
														d="M3 6a1 1 0 0 0-1 1v7a1 1 0 0 0 1 1h7a1 1 0 0 0 1-1V7a1 1 0 0 0-1-1H3Zm1.75 2.5a.75.75 0 0 0 0 1.5h3.5a.75.75 0 0 0 0-1.5h-3.5ZM4 11.75a.75.75 0 0 1 .75-.75h3.5a.75.75 0 0 1 0 1.5h-3.5a.75.75 0 0 1-.75-.75Z"
														clip-rule="evenodd"
													/>
												</svg>
											{/if}
										</button>

										<Tooltip
											content={API_KEYS_AVAILABLE
												? $i18n.t('Create new key')
												: $i18n.t('Not available in this deployment')}
										>
											<button
												class=" px-1.5 py-1 rounded-lg {API_KEYS_AVAILABLE
													? 'dark:hover:bg-gray-850 transition'
													: 'opacity-50 cursor-not-allowed'}"
												aria-label={$i18n.t('Create new key')}
												disabled={!API_KEYS_AVAILABLE}
												on:click={() => {
													createAPIKeyHandler();
												}}
											>
												<svg
													xmlns="http://www.w3.org/2000/svg"
													fill="none"
													viewBox="0 0 24 24"
													stroke-width="2"
													stroke="currentColor"
													class="size-4"
												>
													<path
														stroke-linecap="round"
														stroke-linejoin="round"
														d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99"
													/>
												</svg>
											</button>
										</Tooltip>
									{:else}
										<Tooltip
											content={API_KEYS_AVAILABLE ? '' : $i18n.t('Not available in this deployment')}
										>
											<button
												class="flex gap-1.5 items-center font-medium px-3.5 py-1.5 rounded-lg bg-gray-100/70 dark:bg-gray-850 {API_KEYS_AVAILABLE
													? 'hover:bg-gray-100 dark:hover:bg-gray-850 transition'
													: 'opacity-50 cursor-not-allowed'}"
												disabled={!API_KEYS_AVAILABLE}
												on:click={() => {
													createAPIKeyHandler();
												}}
											>
												<Plus strokeWidth="2" className=" size-3.5" />

												{$i18n.t('Create new secret key')}</button
											>
										</Tooltip>
									{/if}
								</div>
							</div>
						{/if}
					</div>
				{/if}
			</SettingsSection>
		{/if}
	</div>

	<div class="flex justify-end items-center gap-3 pt-3 text-sm font-medium">
		{#if !PROFILE_UPDATE_AVAILABLE}
			<div class="text-xs text-gray-400 dark:text-gray-500">
				{$i18n.t('Profile editing is not available in this deployment yet.')}
			</div>
		{/if}
		<button
			class="px-3.5 py-1.5 text-sm font-medium bg-black text-white dark:bg-white dark:text-black transition rounded-lg {PROFILE_UPDATE_AVAILABLE
				? 'hover:bg-gray-900 dark:hover:bg-gray-100'
				: 'opacity-50 cursor-not-allowed'}"
			disabled={!PROFILE_UPDATE_AVAILABLE}
			on:click={async () => {
				if (!PROFILE_UPDATE_AVAILABLE) {
					return;
				}
				const res = await submitHandler();

				if (res) {
					saveHandler();
				}
			}}
		>
			{$i18n.t('Save')}
		</button>
	</div>
</div>
