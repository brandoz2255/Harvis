<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { onMount, getContext } from 'svelte';
	import { getCodeExecutionConfig, setCodeExecutionConfig } from '$lib/apis/configs';

	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';

	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import Switch from '$lib/components/common/Switch.svelte';

	import Pane from './ui/Pane.svelte';
	import Row from './ui/Row.svelte';
	import Section from './ui/Section.svelte';

	const i18n = getContext('i18n');

	export let saveHandler: Function;

	let config = null;

	let engines = ['pyodide', 'jupyter'];

	const submitHandler = async () => {
		const res = await setCodeExecutionConfig(localStorage.token, config);
	};

	onMount(async () => {
		const res = await getCodeExecutionConfig(localStorage.token);

		if (res) {
			config = res;
		}
	});
</script>

<form
	class="text-sm h-full"
	on:submit|preventDefault={async () => {
		await submitHandler();
		saveHandler();
	}}
>
	<Pane title={$i18n.t('Code Execution')}>
		{#if config}
			<Section title={$i18n.t('General')}>
				<Row label={$i18n.t('Enable Code Execution')}>
					<Switch bind:state={config.ENABLE_CODE_EXECUTION} />
				</Row>

				<Row label={$i18n.t('Code Execution Engine')}>
					<svelte:fragment slot="detail">
						{#if config.CODE_EXECUTION_ENGINE === 'jupyter'}
							<div class="mt-1 text-gray-500 text-xs">
								{$i18n.t(
									'Warning: Jupyter execution enables arbitrary code execution, posing severe security risks—proceed with extreme caution.'
								)}
							</div>
						{/if}
					</svelte:fragment>

					<div class="flex items-center relative">
						<select
							class="w-fit pr-8 rounded-sm px-2 p-1 text-xs bg-transparent outline-hidden text-right"
							bind:value={config.CODE_EXECUTION_ENGINE}
							placeholder={$i18n.t('Select a engine')}
							required
						>
							<option disabled selected value="">{$i18n.t('Select a engine')}</option>
							{#each engines as engine}
								<option value={engine}>{engine}{engine === 'jupyter' ? ' (Legacy)' : ''}</option>
							{/each}
						</select>
					</div>
				</Row>

				{#if config.CODE_EXECUTION_ENGINE === 'jupyter'}
					<div class="py-3 flex flex-col gap-1.5 w-full">
						<div class="text-xs font-medium">
							{$i18n.t('Jupyter URL')}
						</div>

						<div class="flex w-full">
							<div class="flex-1">
								<input
									class="w-full text-sm py-0.5 placeholder:text-gray-300 dark:placeholder:text-gray-700 bg-transparent outline-hidden"
									type="text"
									placeholder={$i18n.t('Enter Jupyter URL')}
									bind:value={config.CODE_EXECUTION_JUPYTER_URL}
									autocomplete="off"
								/>
							</div>
						</div>
					</div>

					<div class="py-3 flex flex-col gap-1.5 w-full">
						<div class=" flex gap-2 w-full items-center justify-between">
							<div class="text-xs font-medium">
								{$i18n.t('Jupyter Auth')}
							</div>

							<div>
								<select
									class="w-fit pr-8 rounded-sm px-2 p-1 text-xs bg-transparent outline-hidden text-left"
									bind:value={config.CODE_EXECUTION_JUPYTER_AUTH}
									placeholder={$i18n.t('Select an auth method')}
								>
									<option selected value="">{$i18n.t('None')}</option>
									<option value="token">{$i18n.t('Token')}</option>
									<option value="password">{$i18n.t('Password')}</option>
								</select>
							</div>
						</div>

						{#if config.CODE_EXECUTION_JUPYTER_AUTH}
							<div class="flex w-full gap-2">
								<div class="flex-1">
									{#if config.CODE_EXECUTION_JUPYTER_AUTH === 'password'}
										<SensitiveInput
											type="text"
											placeholder={$i18n.t('Enter Jupyter Password')}
											bind:value={config.CODE_EXECUTION_JUPYTER_AUTH_PASSWORD}
											autocomplete="off"
										/>
									{:else}
										<SensitiveInput
											type="text"
											placeholder={$i18n.t('Enter Jupyter Token')}
											bind:value={config.CODE_EXECUTION_JUPYTER_AUTH_TOKEN}
											autocomplete="off"
										/>
									{/if}
								</div>
							</div>
						{/if}
					</div>

					<Row label={$i18n.t('Code Execution Timeout')}>
						<Tooltip content={$i18n.t('Enter timeout in seconds')}>
							<input
								class="w-fit rounded-sm px-2 p-1 text-xs bg-transparent outline-hidden text-right"
								type="number"
								bind:value={config.CODE_EXECUTION_JUPYTER_TIMEOUT}
								placeholder={$i18n.t('e.g. 60')}
								autocomplete="off"
							/>
						</Tooltip>
					</Row>
				{/if}
			</Section>

			<Section title={$i18n.t('Code Interpreter')}>
				<Row label={$i18n.t('Enable Code Interpreter')}>
					<Switch bind:state={config.ENABLE_CODE_INTERPRETER} />
				</Row>

				{#if config.ENABLE_CODE_INTERPRETER}
					<Row label={$i18n.t('Code Interpreter Engine')}>
						<svelte:fragment slot="detail">
							{#if config.CODE_INTERPRETER_ENGINE === 'jupyter'}
								<div class="mt-1 text-gray-500 text-xs">
									{$i18n.t(
										'Warning: Jupyter execution enables arbitrary code execution, posing severe security risks—proceed with extreme caution.'
									)}
								</div>
							{/if}
						</svelte:fragment>

						<div class="flex items-center relative">
							<select
								class="w-fit pr-8 rounded-sm px-2 p-1 text-xs bg-transparent outline-hidden text-right"
								bind:value={config.CODE_INTERPRETER_ENGINE}
								placeholder={$i18n.t('Select a engine')}
								required
							>
								<option disabled selected value="">{$i18n.t('Select a engine')}</option>
								{#each engines as engine}
									<option value={engine}>{engine}{engine === 'jupyter' ? ' (Legacy)' : ''}</option>
								{/each}
							</select>
						</div>
					</Row>

					{#if config.CODE_INTERPRETER_ENGINE === 'jupyter'}
						<div class="py-3 flex flex-col gap-1.5 w-full">
							<div class="text-xs font-medium">
								{$i18n.t('Jupyter URL')}
							</div>

							<div class="flex w-full">
								<div class="flex-1">
									<input
										class="w-full text-sm py-0.5 placeholder:text-gray-300 dark:placeholder:text-gray-700 bg-transparent outline-hidden"
										type="text"
										placeholder={$i18n.t('Enter Jupyter URL')}
										bind:value={config.CODE_INTERPRETER_JUPYTER_URL}
										autocomplete="off"
									/>
								</div>
							</div>
						</div>

						<div class="py-3 flex flex-col gap-1.5 w-full">
							<div class="flex gap-2 w-full items-center justify-between">
								<div class="text-xs font-medium">
									{$i18n.t('Jupyter Auth')}
								</div>

								<div>
									<select
										class="w-fit pr-8 rounded-sm px-2 p-1 text-xs bg-transparent outline-hidden text-left"
										bind:value={config.CODE_INTERPRETER_JUPYTER_AUTH}
										placeholder={$i18n.t('Select an auth method')}
									>
										<option selected value="">{$i18n.t('None')}</option>
										<option value="token">{$i18n.t('Token')}</option>
										<option value="password">{$i18n.t('Password')}</option>
									</select>
								</div>
							</div>

							{#if config.CODE_INTERPRETER_JUPYTER_AUTH}
								<div class="flex w-full gap-2">
									<div class="flex-1">
										{#if config.CODE_INTERPRETER_JUPYTER_AUTH === 'password'}
											<SensitiveInput
												type="text"
												placeholder={$i18n.t('Enter Jupyter Password')}
												bind:value={config.CODE_INTERPRETER_JUPYTER_AUTH_PASSWORD}
												autocomplete="off"
											/>
										{:else}
											<SensitiveInput
												type="text"
												placeholder={$i18n.t('Enter Jupyter Token')}
												bind:value={config.CODE_INTERPRETER_JUPYTER_AUTH_TOKEN}
												autocomplete="off"
											/>
										{/if}
									</div>
								</div>
							{/if}
						</div>

						<Row label={$i18n.t('Code Execution Timeout')}>
							<Tooltip content={$i18n.t('Enter timeout in seconds')}>
								<input
									class="w-fit rounded-sm px-2 p-1 text-xs bg-transparent outline-hidden text-right"
									type="number"
									bind:value={config.CODE_INTERPRETER_JUPYTER_TIMEOUT}
									placeholder={$i18n.t('e.g. 60')}
									autocomplete="off"
								/>
							</Tooltip>
						</Row>
					{/if}

					<div class="py-3 w-full">
						<div class=" mb-2.5 text-xs font-medium">
							{$i18n.t('Code Interpreter Prompt Template')}
						</div>

						<Tooltip
							content={$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
							placement="top-start"
						>
							<Textarea
								bind:value={config.CODE_INTERPRETER_PROMPT_TEMPLATE}
								placeholder={$i18n.t(
									'Leave empty to use the default prompt, or enter a custom prompt'
								)}
							/>
						</Tooltip>
					</div>
				{/if}
			</Section>
		{/if}

		<svelte:fragment slot="actions">
			<button
				class="px-3.5 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
				type="submit"
			>
				{$i18n.t('Save')}
			</button>
		</svelte:fragment>
	</Pane>
</form>
