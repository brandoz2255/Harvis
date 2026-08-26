<script lang="ts">
	import Switch from '$lib/components/common/Switch.svelte';
	import { config, models, settings, user } from '$lib/stores';
	import { createEventDispatcher, onMount, getContext, tick } from 'svelte';
	import { toast } from 'svelte-sonner';
	import ManageModal from './Personalization/ManageModal.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import SettingRow from './SettingRow.svelte';
	const dispatch = createEventDispatcher();

	const i18n = getContext('i18n');

	export let saveSettings: Function;

	let showManageModal = false;

	// Addons
	let enableMemory = false;

	onMount(async () => {
		enableMemory = $settings?.memory ?? false;
	});
</script>

<ManageModal bind:show={showManageModal} />

<form
	id="tab-personalization"
	class="flex flex-col h-full justify-between space-y-3 text-sm"
	on:submit|preventDefault={() => {
		dispatch('save');
	}}
>
	<div class="py-1 overflow-y-scroll max-h-[28rem] md:max-h-full">
		<SettingRow>
			<svelte:fragment slot="title">
				<Tooltip
					content={$i18n.t(
						'This is an experimental feature, it may not function as expected and is subject to change at any time.'
					)}
				>
					<div class="flex items-center gap-2">
						{$i18n.t('Memory')}
						<span
							class="text-[0.65rem] font-medium uppercase px-1.5 py-0.5 rounded-md bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400"
							>{$i18n.t('Experimental')}</span
						>
					</div>
				</Tooltip>
			</svelte:fragment>
			<svelte:fragment slot="description">
				{$i18n.t(
					"You can personalize your interactions with LLMs by adding memories through the 'Manage' button below, making them more helpful and tailored to you."
				)}
			</svelte:fragment>
			<Switch
				bind:state={enableMemory}
				on:change={async () => {
					saveSettings({ memory: enableMemory });
				}}
			/>
		</SettingRow>

		<div class="mt-4 mb-1">
			<button
				type="button"
				class="px-3 py-1.5 text-sm font-medium rounded-[10px] bg-gray-100 hover:bg-gray-200 dark:bg-gray-850 dark:hover:bg-gray-800 text-gray-800 dark:text-gray-100 transition"
				on:click={() => {
					showManageModal = true;
				}}
			>
				{$i18n.t('Manage')}
			</button>
		</div>
	</div>

	<div class="flex justify-end text-sm font-medium">
		<button
			class="px-3.5 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-lg"
			type="submit"
		>
			{$i18n.t('Save')}
		</button>
	</div>
</form>
