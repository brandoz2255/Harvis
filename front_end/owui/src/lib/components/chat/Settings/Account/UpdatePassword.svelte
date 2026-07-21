<script lang="ts">
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { updateUserPassword } from '$lib/apis/auths';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';

	const i18n = getContext('i18n');

	// HONESTY GATE: the Harvis owui_compat facade does not implement
	// POST /api/v1/auths/update/password (see python_back_end/owui_compat/router.py —
	// only signin/signup/signout and GET /auths/ exist), so every submit would 404.
	// Same pattern as PROFILE_UPDATE_AVAILABLE / API_KEYS_AVAILABLE in Account.svelte;
	// flip this const when the route lands to re-enable the form as-is.
	const PASSWORD_CHANGE_AVAILABLE = false;

	let show = false;
	let currentPassword = '';
	let newPassword = '';
	let newPasswordConfirm = '';

	const updatePasswordHandler = async () => {
		if (!PASSWORD_CHANGE_AVAILABLE) {
			toast.error($i18n.t('Password changes are not available in this deployment yet.'));
			return;
		}
		if (newPassword === newPasswordConfirm) {
			const res = await updateUserPassword(localStorage.token, currentPassword, newPassword).catch(
				(error) => {
					toast.error(`${error}`);
					return null;
				}
			);

			if (res) {
				toast.success($i18n.t('Successfully updated.'));
			}

			currentPassword = '';
			newPassword = '';
			newPasswordConfirm = '';
		} else {
			toast.error(
				$i18n.t("The passwords you entered don't quite match. Please double-check and try again.")
			);
			newPassword = '';
			newPasswordConfirm = '';
		}
	};
</script>

<form
	class="flex flex-col text-sm"
	on:submit|preventDefault={() => {
		updatePasswordHandler();
	}}
>
	<div class="flex justify-between items-center py-2">
		<div class="text-lg font-semibold text-gray-900 dark:text-gray-100">{$i18n.t('Change Password')}</div>
		<button
			class=" text-sm font-medium text-gray-500"
			type="button"
			on:click={() => {
				show = !show;
			}}>{show ? $i18n.t('Hide') : $i18n.t('Show')}</button
		>
	</div>

	{#if show}
		<div class=" py-2.5 space-y-1.5">
			<div class="flex flex-col w-full">
				<div class=" mb-1 text-sm font-medium text-gray-700 dark:text-gray-300">{$i18n.t('Current Password')}</div>

				<div class="flex-1">
					<SensitiveInput
						class="w-full bg-transparent text-sm dark:text-gray-300 outline-hidden placeholder:opacity-30"
						type="password"
						bind:value={currentPassword}
						placeholder={$i18n.t('Enter your current password')}
						autocomplete="current-password"
						required
					/>
				</div>
			</div>

			<div class="flex flex-col w-full">
				<div class=" mb-1 text-sm font-medium text-gray-700 dark:text-gray-300">{$i18n.t('New Password')}</div>

				<div class="flex-1">
					<SensitiveInput
						class="w-full bg-transparent text-sm dark:text-gray-300 outline-hidden placeholder:opacity-30"
						type="password"
						bind:value={newPassword}
						placeholder={$i18n.t('Enter your new password')}
						autocomplete="new-password"
						required
					/>
				</div>
			</div>

			<div class="flex flex-col w-full">
				<div class=" mb-1 text-sm font-medium text-gray-700 dark:text-gray-300">{$i18n.t('Confirm Password')}</div>

				<div class="flex-1">
					<SensitiveInput
						class="w-full bg-transparent text-sm dark:text-gray-300 outline-hidden placeholder:opacity-30"
						type="password"
						bind:value={newPasswordConfirm}
						placeholder={$i18n.t('Confirm your new password')}
						autocomplete="off"
						required
					/>
				</div>
			</div>
		</div>

		<div class="mt-3 flex justify-end items-center gap-3">
			{#if !PASSWORD_CHANGE_AVAILABLE}
				<div class="text-xs text-gray-400 dark:text-gray-500">
					{$i18n.t('Password changes are not available in this deployment yet.')}
				</div>
			{/if}
			<button
				class="px-3.5 py-1.5 text-sm font-medium bg-black text-white dark:bg-white dark:text-black transition rounded-full {PASSWORD_CHANGE_AVAILABLE
					? 'hover:bg-gray-900 dark:hover:bg-gray-100'
					: 'opacity-50 cursor-not-allowed'}"
				disabled={!PASSWORD_CHANGE_AVAILABLE}
			>
				{$i18n.t('Update password')}
			</button>
		</div>
	{/if}
</form>
