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
	 * The developer-mode switch below meets that bar: it persists through the
	 * same admin_config module, is republished in the boot payload as
	 * `features.enable_dev_mode`, and Settings.svelte drops the experimental
	 * tabs from the list, the search index and the URL whitelist when it is
	 * off. Saving refreshes the boot config, so the tabs appear and disappear
	 * without a reload.
	 *
	 * The layout is the shared Pane/Section/Row set from ./ui. It replaced a
	 * `flex flex-col h-full justify-between`, which pinned these two switches to
	 * the top of the viewport and Save to the very bottom with nothing in
	 * between.
	 */
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { getAdminConfig, updateAdminConfig } from '$lib/apis/auths';
	import Switch from '$lib/components/common/Switch.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import { WEBUI_BUILD_HASH, WEBUI_VERSION } from '$lib/constants';
	import { showChangelog } from '$lib/stores';

	import Pane from './ui/Pane.svelte';
	import Row from './ui/Row.svelte';
	import Section from './ui/Section.svelte';

	const i18n = getContext('i18n');

	export let saveHandler: Function;

	let adminConfig: { ENABLE_SIGNUP: boolean; DEV_MODE: boolean } | null = null;
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
	class="text-sm h-full"
	on:submit|preventDefault={async () => {
		updateHandler();
	}}
>
	<Pane
		title={$i18n.t('General')}
		description={$i18n.t('Instance-wide settings. These apply to everyone on this Harvis.')}
	>
		{#if adminConfig !== null}
			<Section title={$i18n.t('Access')}>
				<Row
					label={$i18n.t('Enable New Sign Ups')}
					description={$i18n.t(
						'When off, the sign-in page stops offering to create an account and the server refuses new registrations. Existing accounts are unaffected.'
					)}
				>
					<Switch bind:state={adminConfig.ENABLE_SIGNUP} />
				</Row>

				<Row
					label={$i18n.t('Developer Mode')}
					description={$i18n.t(
						'Shows experimental admin surfaces that are still being built. Currently: Inference Nodes (the FreeToken power switch and MoE model detection). Turn it off on a machine other people use — the panels disappear from this list, from search, and from their own links.'
					)}
				>
					<Switch bind:state={adminConfig.DEV_MODE} />
				</Row>
			</Section>
		{:else if loadError}
			<div
				class="mb-3 rounded-xl border border-red-200 dark:border-red-900/50 bg-red-50/60 dark:bg-red-950/20 px-4 py-3 text-xs text-red-700 dark:text-red-400"
			>
				{$i18n.t('Could not load instance settings')}: {loadError}
			</div>
		{:else}
			<Section>
				<Row label={$i18n.t('Loading...')} />
			</Section>
		{/if}

		<Section title={$i18n.t('About')}>
			<Row label={$i18n.t('Version')}>
				<svelte:fragment slot="detail">
					<div class="mt-1 flex flex-col text-xs text-gray-700 dark:text-gray-200">
						<Tooltip content={WEBUI_BUILD_HASH} placement="right">
							<span class="w-fit">v{WEBUI_VERSION}</span>
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
				</svelte:fragment>
			</Row>
		</Section>

		<svelte:fragment slot="actions">
			<button
				class="px-3.5 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
				type="submit"
				disabled={adminConfig === null}
			>
				{$i18n.t('Save')}
			</button>
		</svelte:fragment>
	</Pane>
</form>
