<script lang="ts">
	/*
	 * Admin → Settings → General.
	 *
	 * This was OpenWebUI's stock 900-line panel: ~25 switches bound to an
	 * `adminConfig` object it fetched from `GET /api/v1/auths/admin/config`,
	 * plus LDAP, a webhook URL, banners and a version-update check. Harvis
	 * implements none of those routes except the admin config itself (added
	 * alongside this rewrite), so `getAdminConfig` threw inside the onMount
	 * `Promise.all`, every later assignment was skipped, and `adminConfig`
	 * stayed null — which the markup gated on. The result was a tab that
	 * rendered as an empty box with a Save button under it.
	 *
	 * What replaced it is the set of controls the backend actually enforces.
	 * The signup switch below is real: it persists through
	 * owui_compat/admin_config.py and both the enforcement gate in
	 * main._signup_with_connection and the `features.enable_signup` flag that
	 * draws the auth page's "Sign up" link resolve through the same function.
	 * Anything OWUI offered that Harvis does not honor is gone rather than
	 * shown-and-ignored — the rule setup_flow.setup_preferences already states:
	 * a control that cannot change the thing it names is worse than no control.
	 *
	 * Adding a switch here means wiring its enforcement in the same commit.
	 */
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { getAdminConfig, updateAdminConfig } from '$lib/apis/auths';
	import Switch from '$lib/components/common/Switch.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import { WEBUI_BUILD_HASH, WEBUI_VERSION } from '$lib/constants';
	import { showChangelog } from '$lib/stores';

	const i18n = getContext('i18n');

	export let saveHandler: Function;

	let adminConfig: { ENABLE_SIGNUP: boolean } | null = null;
	let loadError = '';

	const updateHandler = async () => {
		if (!adminConfig) return;
		const res = await updateAdminConfig(localStorage.token, adminConfig).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		if (res) {
			adminConfig = res;
			saveHandler();
		}
	};

	onMount(async () => {
		// Caught, not thrown: a failure here used to take the whole panel down
		// with it. Now it shows why, and the rest of the admin area keeps working.
		try {
			adminConfig = await getAdminConfig(localStorage.token);
		} catch (error) {
			loadError = `${error}`;
		}
	});
</script>

<form
	class="flex flex-col h-full justify-between space-y-3 text-sm"
	on:submit|preventDefault={async () => {
		updateHandler();
	}}
>
	<div class="space-y-3 overflow-y-scroll scrollbar-hidden h-full">
		<div class="mb-3.5">
			<div class="mt-0.5 mb-2.5 text-base font-medium">{$i18n.t('General')}</div>

			<hr class="border-gray-100/30 dark:border-gray-850/30 my-2" />

			<div class="mb-2.5">
				<div class="mb-1 text-xs font-medium">{$i18n.t('Version')}</div>
				<div class="flex flex-col text-xs text-gray-700 dark:text-gray-200">
					<Tooltip content={WEBUI_BUILD_HASH}>
						<span>v{WEBUI_VERSION}</span>
					</Tooltip>
					<button
						class="underline flex items-center space-x-1 text-xs text-gray-500 dark:text-gray-500 w-fit"
						type="button"
						on:click={() => {
							showChangelog.set(true);
						}}
					>
						<div>{$i18n.t("See what's new")}</div>
					</button>
				</div>
			</div>

			<hr class="border-gray-100/30 dark:border-gray-850/30 my-2" />

			{#if adminConfig !== null}
				<div class="mb-2.5 flex w-full justify-between pr-2">
					<div class="self-center text-xs font-medium">{$i18n.t('Enable New Sign Ups')}</div>
					<Switch bind:state={adminConfig.ENABLE_SIGNUP} />
				</div>
				<div class="text-xs text-gray-600 dark:text-gray-400 pr-2">
					{$i18n.t(
						'When off, the sign-in page stops offering to create an account and the server refuses new registrations. Existing accounts are unaffected.'
					)}
				</div>
			{:else if loadError}
				<div class="text-xs text-red-700 dark:text-red-400 pr-2">
					{$i18n.t('Could not load instance settings')}: {loadError}
				</div>
			{:else}
				<div class="text-xs text-gray-600 dark:text-gray-400 pr-2">{$i18n.t('Loading...')}</div>
			{/if}
		</div>
	</div>

	<div class="flex justify-end pt-3 text-sm font-medium">
		<button
			class="px-3.5 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-lg"
			type="submit"
			disabled={adminConfig === null}
		>
			{$i18n.t('Save')}
		</button>
	</div>
</form>
