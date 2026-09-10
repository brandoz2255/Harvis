<script lang="ts">
	import { getModels, getTaskConfig, updateTaskConfig } from '$lib/apis';
	import { config, settings } from '$lib/stores';
	import { createEventDispatcher, onMount, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { getBaseModels } from '$lib/apis/models';

	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	import Pane from './ui/Pane.svelte';
	import Row from './ui/Row.svelte';
	import Section from './ui/Section.svelte';

	const dispatch = createEventDispatcher();

	const i18n = getContext('i18n');

	let taskConfig = {
		TASK_MODEL: '',
		TASK_MODEL_EXTERNAL: '',
		ENABLE_TITLE_GENERATION: true,
		TITLE_GENERATION_PROMPT_TEMPLATE: '',
		ENABLE_FOLLOW_UP_GENERATION: true,
		FOLLOW_UP_GENERATION_PROMPT_TEMPLATE: '',
		IMAGE_PROMPT_GENERATION_PROMPT_TEMPLATE: '',
		ENABLE_AUTOCOMPLETE_GENERATION: true,
		AUTOCOMPLETE_GENERATION_INPUT_MAX_LENGTH: -1,
		TAGS_GENERATION_PROMPT_TEMPLATE: '',
		ENABLE_TAGS_GENERATION: true,
		ENABLE_SEARCH_QUERY_GENERATION: true,
		ENABLE_RETRIEVAL_QUERY_GENERATION: true,
		QUERY_GENERATION_PROMPT_TEMPLATE: '',
		TOOLS_FUNCTION_CALLING_PROMPT_TEMPLATE: '',
		ENABLE_VOICE_MODE_PROMPT: true,
		VOICE_MODE_PROMPT_TEMPLATE: ''
	};

	const updateInterfaceHandler = async () => {
		taskConfig = await updateTaskConfig(localStorage.token, taskConfig);
	};

	let workspaceModels = null;
	let baseModels = null;

	let models = null;

	const init = async () => {
		try {
			taskConfig = await getTaskConfig(localStorage.token);

			workspaceModels = await getBaseModels(localStorage.token);
			baseModels = await getModels(localStorage.token, null, false);

			models = baseModels.map((m) => {
				const workspaceModel = workspaceModels.find((wm) => wm.id === m.id);

				if (workspaceModel) {
					return {
						...m,
						...workspaceModel
					};
				} else {
					return {
						...m,
						id: m.id,
						name: m.name,

						is_active: true
					};
				}
			});

			console.debug('models', models);
		} catch (err) {
			console.error('Failed to initialize Interface settings:', err);
			toast.error(err?.detail ?? err?.message ?? $i18n.t('Failed to load Interface settings'));
			models = [];
		}
	};

	onMount(async () => {
		await init();
	});
</script>

{#if models !== null && taskConfig}
	<form
		class="text-sm h-full"
		on:submit|preventDefault={() => {
			updateInterfaceHandler();
			dispatch('save');
		}}
	>
		<Pane title={$i18n.t('Interface')}>
			<Section
				title={$i18n.t('Task Model')}
				description={$i18n.t(
					'A task model is used when performing tasks such as generating titles for chats and web search queries'
				)}
			>
				<div class="py-3 flex w-full gap-2">
					<div class="flex-1">
						<div class=" text-xs mb-1">{$i18n.t('Local Task Model')}</div>
						<select
							class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
							bind:value={taskConfig.TASK_MODEL}
							placeholder={$i18n.t('Select a model')}
							on:change={() => {
								if (taskConfig.TASK_MODEL) {
									const model = models.find((m) => m.id === taskConfig.TASK_MODEL);
									if (model) {
										if (
											model?.access_grants &&
											!model.access_grants.some(
												(g) =>
													g.principal_type === 'user' &&
													g.principal_id === '*' &&
													g.permission === 'read'
											)
										) {
											toast.error(
												$i18n.t(
													'This model is not publicly available. Please select another model.'
												)
											);
										}

										taskConfig.TASK_MODEL = model.id;
									} else {
										taskConfig.TASK_MODEL = '';
									}
								}
							}}
						>
							<option value="" selected>{$i18n.t('Current Model')}</option>
							{#each models as model}
								<option value={model.id} class="bg-gray-100 dark:bg-gray-700">
									{model.name}
									{model?.connection_type === 'local' ? `(${$i18n.t('Local')})` : ''}
								</option>
							{/each}
						</select>
					</div>

					<div class="flex-1">
						<div class=" text-xs mb-1">{$i18n.t('External Task Model')}</div>
						<select
							class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
							bind:value={taskConfig.TASK_MODEL_EXTERNAL}
							placeholder={$i18n.t('Select a model')}
							on:change={() => {
								if (taskConfig.TASK_MODEL_EXTERNAL) {
									const model = models.find((m) => m.id === taskConfig.TASK_MODEL_EXTERNAL);
									if (model) {
										if (
											model?.access_grants &&
											!model.access_grants.some(
												(g) =>
													g.principal_type === 'user' &&
													g.principal_id === '*' &&
													g.permission === 'read'
											)
										) {
											toast.error(
												$i18n.t(
													'This model is not publicly available. Please select another model.'
												)
											);
										}

										taskConfig.TASK_MODEL_EXTERNAL = model.id;
									} else {
										taskConfig.TASK_MODEL_EXTERNAL = '';
									}
								}
							}}
						>
							<option value="" selected>{$i18n.t('Current Model')}</option>
							{#each models as model}
								<option value={model.id} class="bg-gray-100 dark:bg-gray-700">
									{model.name}
									{model?.connection_type === 'local' ? `(${$i18n.t('Local')})` : ''}
								</option>
							{/each}
						</select>
					</div>
				</div>
			</Section>

			<Section title={$i18n.t('Tasks')}>
				<Row label={$i18n.t('Title Generation')}>
					<Switch bind:state={taskConfig.ENABLE_TITLE_GENERATION} />
				</Row>

				{#if taskConfig.ENABLE_TITLE_GENERATION}
					<div class="py-3">
						<div class=" mb-1 text-xs font-medium">{$i18n.t('Title Generation Prompt')}</div>

						<Tooltip
							content={$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
							placement="top-start"
						>
							<Textarea
								bind:value={taskConfig.TITLE_GENERATION_PROMPT_TEMPLATE}
								placeholder={$i18n.t(
									'Leave empty to use the default prompt, or enter a custom prompt'
								)}
							/>
						</Tooltip>
					</div>
				{/if}

				<Row label={$i18n.t('Voice Mode Prompt')}>
					<Switch bind:state={taskConfig.ENABLE_VOICE_MODE_PROMPT} />
				</Row>

				{#if taskConfig.ENABLE_VOICE_MODE_PROMPT}
					<div class="py-3">
						<div class=" mb-1 text-xs font-medium">{$i18n.t('Prompt Template')}</div>

						<Tooltip
							content={$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
							placement="top-start"
						>
							<Textarea
								bind:value={taskConfig.VOICE_MODE_PROMPT_TEMPLATE}
								placeholder={$i18n.t(
									'Leave empty to use the default prompt, or enter a custom prompt'
								)}
							/>
						</Tooltip>
					</div>
				{/if}

				<Row label={$i18n.t('Follow Up Generation')}>
					<Switch bind:state={taskConfig.ENABLE_FOLLOW_UP_GENERATION} />
				</Row>

				{#if taskConfig.ENABLE_FOLLOW_UP_GENERATION}
					<div class="py-3">
						<div class=" mb-1 text-xs font-medium">{$i18n.t('Follow Up Generation Prompt')}</div>

						<Tooltip
							content={$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
							placement="top-start"
						>
							<Textarea
								bind:value={taskConfig.FOLLOW_UP_GENERATION_PROMPT_TEMPLATE}
								placeholder={$i18n.t(
									'Leave empty to use the default prompt, or enter a custom prompt'
								)}
							/>
						</Tooltip>
					</div>
				{/if}

				<Row label={$i18n.t('Tags Generation')}>
					<Switch bind:state={taskConfig.ENABLE_TAGS_GENERATION} />
				</Row>

				{#if taskConfig.ENABLE_TAGS_GENERATION}
					<div class="py-3">
						<div class=" mb-1 text-xs font-medium">{$i18n.t('Tags Generation Prompt')}</div>

						<Tooltip
							content={$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
							placement="top-start"
						>
							<Textarea
								bind:value={taskConfig.TAGS_GENERATION_PROMPT_TEMPLATE}
								placeholder={$i18n.t(
									'Leave empty to use the default prompt, or enter a custom prompt'
								)}
							/>
						</Tooltip>
					</div>
				{/if}

				<Row label={$i18n.t('Retrieval Query Generation')}>
					<Switch bind:state={taskConfig.ENABLE_RETRIEVAL_QUERY_GENERATION} />
				</Row>

				<Row label={$i18n.t('Web Search Query Generation')}>
					<Switch bind:state={taskConfig.ENABLE_SEARCH_QUERY_GENERATION} />
				</Row>

				<div class="py-3">
					<div class=" mb-1 text-xs font-medium">{$i18n.t('Query Generation Prompt')}</div>

					<Tooltip
						content={$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
						placement="top-start"
					>
						<Textarea
							bind:value={taskConfig.QUERY_GENERATION_PROMPT_TEMPLATE}
							placeholder={$i18n.t(
								'Leave empty to use the default prompt, or enter a custom prompt'
							)}
						/>
					</Tooltip>
				</div>

				<Row label={$i18n.t('Autocomplete Generation')}>
					<Tooltip content={$i18n.t('Enable autocomplete generation for chat messages')}>
						<Switch bind:state={taskConfig.ENABLE_AUTOCOMPLETE_GENERATION} />
					</Tooltip>
				</Row>

				{#if taskConfig.ENABLE_AUTOCOMPLETE_GENERATION}
					<div class="py-3">
						<div class=" mb-1 text-xs font-medium">
							{$i18n.t('Autocomplete Generation Input Max Length')}
						</div>

						<Tooltip
							content={$i18n.t('Character limit for autocomplete generation input')}
							placement="top-start"
						>
							<input
								class="w-full outline-hidden bg-transparent"
								bind:value={taskConfig.AUTOCOMPLETE_GENERATION_INPUT_MAX_LENGTH}
								placeholder={$i18n.t('-1 for no limit, or a positive integer for a specific limit')}
							/>
						</Tooltip>
					</div>
				{/if}
			</Section>

			<Section title={$i18n.t('Prompts')}>
				<div class="py-3">
					<div class=" mb-1 text-xs font-medium">{$i18n.t('Image Prompt Generation Prompt')}</div>

					<Tooltip
						content={$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
						placement="top-start"
					>
						<Textarea
							bind:value={taskConfig.IMAGE_PROMPT_GENERATION_PROMPT_TEMPLATE}
							placeholder={$i18n.t(
								'Leave empty to use the default prompt, or enter a custom prompt'
							)}
						/>
					</Tooltip>
				</div>

				<div class="py-3">
					<div class=" mb-1 text-xs font-medium">{$i18n.t('Tools Function Calling Prompt')}</div>

					<Tooltip
						content={$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
						placement="top-start"
					>
						<Textarea
							bind:value={taskConfig.TOOLS_FUNCTION_CALLING_PROMPT_TEMPLATE}
							placeholder={$i18n.t(
								'Leave empty to use the default prompt, or enter a custom prompt'
							)}
						/>
					</Tooltip>
				</div>
			</Section>

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
{:else}
	<div class=" h-full w-full flex justify-center items-center">
		<Spinner className="size-5" />
	</div>
{/if}
