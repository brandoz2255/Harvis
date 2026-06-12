<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';
	const dispatch = createEventDispatcher();
	const i18n = getContext('i18n');

	import XMark from '$lib/components/icons/XMark.svelte';
	import AdvancedParams from '../Settings/Advanced/AdvancedParams.svelte';
	import Valves from '$lib/components/chat/Controls/Valves.svelte';
	import FileItem from '$lib/components/common/FileItem.svelte';
	import RailCard from '$lib/components/common/RailCard.svelte';
	import AdjustmentsHorizontal from '$lib/components/icons/AdjustmentsHorizontal.svelte';
	import Wrench from '$lib/components/icons/Wrench.svelte';

	import { user, settings } from '$lib/stores';
	export let models = [];
	export let chatFiles = [];
	export let params = {};
	export let embed = false;

	// Card open/close state — persisted per card by RailCard via the same
	// chatControls.* localStorage keys the old Collapsible layout used.
	let showFiles = false;
	let showValves = false;
	let showAdvancedParams = false;
</script>

<div class=" dark:text-white">
	{#if !embed}
		<div class=" flex items-center justify-between dark:text-gray-100 mb-2">
			<div class=" text-md self-center font-primary">{$i18n.t('Controls')}</div>
			<button
				class="self-center"
				aria-label={$i18n.t('Close chat controls')}
				on:click={() => {
					dispatch('close');
				}}
			>
				<XMark className="size-3.5" />
			</button>
		</div>
	{/if}

	{#if $user?.role === 'admin' || ($user?.permissions.chat?.controls ?? true)}
		<div class="space-y-2 dark:text-gray-200 text-sm py-0.5">
			<!-- Quick settings — the common knobs, always visible -->
			<RailCard
				title={$i18n.t('Quick settings')}
				icon={AdjustmentsHorizontal}
				collapsible={false}
			>
				{#if $user?.role === 'admin' || ($user?.permissions.chat?.system_prompt ?? true)}
					<div class="text-xs font-medium text-gray-500 dark:text-gray-400">
						{$i18n.t('System Prompt')}
					</div>
					<textarea
						bind:value={params.system}
						class="w-full text-xs outline-hidden resize-vertical {$settings.highContrastMode
							? 'border-2 border-gray-300 dark:border-gray-700 rounded-lg bg-gray-50 dark:bg-gray-800 p-2.5'
							: 'py-1.5 bg-transparent'}"
						rows="4"
						placeholder={$i18n.t('Enter system prompt')}
					/>
				{/if}

				{#if $user?.role === 'admin' || ($user?.permissions.chat?.params ?? true)}
					<!-- Temperature pulled up from Advanced — same params key + null
					     semantics as AdvancedParams (which stays the source of truth) -->
					<div class=" py-0.5 w-full justify-between">
						<div class="flex w-full justify-between">
							<div class=" self-center text-xs font-medium">
								{$i18n.t('Temperature')}
							</div>
							<button
								class="p-1 px-3 text-xs flex rounded-sm transition shrink-0 outline-hidden"
								type="button"
								on:click={() => {
									params.temperature = (params?.temperature ?? null) === null ? 0.8 : null;
								}}
							>
								{#if (params?.temperature ?? null) === null}
									<span class="ml-2 self-center"> {$i18n.t('Default')} </span>
								{:else}
									<span class="ml-2 self-center"> {$i18n.t('Custom')} </span>
								{/if}
							</button>
						</div>
						{#if (params?.temperature ?? null) !== null}
							<div class="flex mt-0.5 space-x-2">
								<div class=" flex-1">
									<input
										aria-label={$i18n.t('Temperature')}
										type="range"
										min="0"
										max="2"
										step="0.05"
										bind:value={params.temperature}
										class="w-full h-2 rounded-lg appearance-none cursor-pointer dark:bg-gray-700"
									/>
								</div>
								<div>
									<input
										bind:value={params.temperature}
										type="number"
										class=" bg-transparent text-center w-14"
										min="0"
										max="2"
										step="any"
									/>
								</div>
							</div>
						{/if}
					</div>
				{/if}
			</RailCard>

			{#if $user?.role === 'admin' || ($user?.permissions.chat?.params ?? true)}
				<RailCard
					title={$i18n.t('Advanced Params')}
					icon={AdjustmentsHorizontal}
					bind:open={showAdvancedParams}
					persistKey="chatControls.advancedParams"
				>
					<div class="text-sm">
						<AdvancedParams admin={$user?.role === 'admin'} custom={true} bind:params />
					</div>
				</RailCard>
			{/if}

			{#if $user?.role === 'admin' || ($user?.permissions.chat?.valves ?? true)}
				<RailCard
					title={$i18n.t('Valves')}
					icon={Wrench}
					bind:open={showValves}
					persistKey="chatControls.valves"
				>
					<div class="text-sm">
						<Valves show={showValves} />
					</div>
				</RailCard>
			{/if}

			{#if chatFiles.length > 0}
				<RailCard
					title={$i18n.t('Files')}
					count={chatFiles.length}
					bind:open={showFiles}
					persistKey="chatControls.files"
				>
					<div class="flex flex-col gap-1">
						{#each chatFiles as file, fileIdx}
							<FileItem
								className="w-full"
								item={file}
								edit={true}
								url={file?.url ? file.url : null}
								name={file.name}
								type={file.type}
								size={file?.size}
								dismissible={true}
								small={true}
								on:dismiss={() => {
									// Remove the file from the chatFiles array

									chatFiles.splice(fileIdx, 1);
									chatFiles = chatFiles;
								}}
								on:click={() => {
									console.log(file);
								}}
							/>
						{/each}
					</div>
				</RailCard>
			{/if}
		</div>
	{/if}
</div>
